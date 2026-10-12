"""The playthrough timeline: what the character gained, and when."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from foggymap.history import Timeline, load_events, record_changes
from foggymap.markers import Poi

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
SHOWN, COMPLETED, FAILED = 0x20, 0x2, 0x40


def _raw(level=10, perks=(), quests=(), objectives=(), name="Nora", bobbleheads=()):
    return {
        "version": 1,
        "character": {"name": name, "sex": 1, "level": level, "xp": 0},
        "time": {"playtime_ms": 3_600_000 * 5,
                 "game": {"year": 287, "month": 10, "day": 30, "hour": 9, "days_passed": 7}},
        "perks": [{"id": i, "name": n, "rank": 1, "ranks": 4, "level": 0, "playable": True,
                   "hidden": False, "next": 0} for i, n in enumerate(perks)]
                 + [{"id": 900 + i, "name": f"{b} Bobblehead", "rank": 1, "ranks": 1, "level": 0,
                     "playable": False, "hidden": True, "next": 0} for i, b in enumerate(bobbleheads)],
        "quests": list(quests),
        "objectives": list(objectives),
    }


def _quest(quest_id, name, flags):
    return {"id": quest_id, "editor_id": f"Q{quest_id}", "name": name, "flags": flags,
            "type": 7, "stage": 10}


def _poi(form_id, name, discovered=True, marker_type=15):
    return Poi("Commonwealth", form_id, name, 0.0, 0.0, None, marker_type, discovered)


def _kinds(events):
    return [(e["kind"], e["text"]) for e in events]


def test_the_first_snapshot_is_a_baseline_not_a_flood_of_events():
    """Everything before tracking began did not all happen just now."""
    state, events = record_changes(None, _raw(level=37, perks=["Locksmith"]), [_poi(1, "Vault 81")], NOW)

    assert _kinds(events) == [("tracking_began", "Started tracking at level 37")]
    assert state["level"] == 37


def test_levels_gained_each_get_an_event():
    state, _ = record_changes(None, _raw(level=10), [], NOW)

    _, events = record_changes(state, _raw(level=12), [], NOW)

    assert _kinds(events) == [("level", "Reached level 11"), ("level", "Reached level 12")]


def test_perks_and_ranks_taken():
    state, _ = record_changes(None, _raw(perks=["Locksmith"]), [], NOW)

    _, events = record_changes(state, _raw(perks=["Locksmith", "Locksmith", "Hacker"]), [], NOW)

    assert _kinds(events) == [("perk", "Took Hacker"), ("perk", "Locksmith rank 2")]
    assert all(e["icon"] == "star" for e in events)


def test_quests_started_completed_and_failed():
    active = _quest(1, "[Quest] Pyromaniac", SHOWN | 0x1)
    objective = {"quest": 1, "instance": 1, "index": 10, "state": 1,
                 "quest_name": "[Quest] Pyromaniac", "text": "Kill the arsonists"}
    state, _ = record_changes(None, _raw(), [], NOW)

    state, started = record_changes(state, _raw(quests=[active], objectives=[objective]), [], NOW)
    done = _quest(1, "[Quest] Pyromaniac", SHOWN | COMPLETED)
    lost = _quest(2, "[Quest] Lost Cause", SHOWN | FAILED)
    _, finished = record_changes(state, _raw(quests=[done, lost]), [], NOW)

    assert _kinds(started) == [("quest_started", "Started Pyromaniac")]
    assert _kinds(finished) == [("quest_completed", "Completed Pyromaniac"),
                                ("quest_failed", "Failed Lost Cause")]


def test_discoveries_carry_the_locations_icon():
    state, _ = record_changes(None, _raw(), [_poi(1, "Vault 81", discovered=False)], NOW)

    _, events = record_changes(state, _raw(), [_poi(1, "Vault 81")], NOW)

    assert _kinds(events) == [("discovery", "Discovered Vault 81")]
    assert events[0]["icon"] == "cog"


def test_bobbleheads_found():
    state, _ = record_changes(None, _raw(), [], NOW)

    _, events = record_changes(state, _raw(bobbleheads=["Sneak"]), [], NOW)

    assert _kinds(events) == [("bobblehead", "Found the Sneak bobblehead")]


def test_loading_an_older_save_records_nothing_and_regaining_records_nothing_twice():
    """Reloading never claims progress the player already made once."""
    state, _ = record_changes(None, _raw(level=10), [], NOW)
    state, _ = record_changes(state, _raw(level=12, perks=["Hacker"]), [], NOW)

    state, back = record_changes(state, _raw(level=10), [], NOW)
    _, again = record_changes(state, _raw(level=12, perks=["Hacker"]), [], NOW)

    assert back == [] and again == []


def test_a_different_character_starts_a_new_chapter():
    state, _ = record_changes(None, _raw(level=37, name="Nora"), [], NOW)

    state, events = record_changes(state, _raw(level=2, name="Nate"), [], NOW)
    _, later = record_changes(state, _raw(level=3, name="Nate"), [], NOW)

    assert _kinds(events) == [("new_character", "Started tracking a new character at level 2")]
    assert _kinds(later) == [("level", "Reached level 3")]


def test_the_character_name_never_reaches_the_timeline():
    state, events = record_changes(None, _raw(name="Nora"), [], NOW)
    state, more = record_changes(state, _raw(name="Nate"), [], NOW)

    assert "Nora" not in json.dumps([state, events, more])
    assert "Nate" not in json.dumps([state, events, more])


def test_events_carry_real_time_playtime_and_game_date():
    state, _ = record_changes(None, _raw(level=1), [], NOW)

    _, (event,) = record_changes(state, _raw(level=2), [], NOW)

    assert event["at"] == "2026-10-12T20:00:00+00:00"
    assert event["playtime_hours"] == 5.0
    assert event["game_date"] == "30 October 2287"


# --- the persisted timeline ----------------------------------------------------------


def _write_player(data, raw):
    (data / "player.json").write_text(json.dumps(raw), encoding="utf-8")


def test_timeline_appends_events_and_remembers_its_state(tmp_path):
    _write_player(tmp_path, _raw(level=10))
    timeline = Timeline(tmp_path)
    timeline.update(NOW)

    _write_player(tmp_path, _raw(level=11))
    timeline.update(NOW + timedelta(minutes=1))
    Timeline(tmp_path).update(NOW + timedelta(minutes=2))  # a new session, nothing changed

    events = load_events(tmp_path)
    assert _kinds(events) == [("level", "Reached level 11"),
                              ("tracking_began", "Started tracking at level 10")]


def test_timeline_does_nothing_without_a_player_file(tmp_path):
    Timeline(tmp_path).update(NOW)

    assert load_events(tmp_path) == []


def test_load_events_skips_a_line_cut_short(tmp_path):
    _write_player(tmp_path, _raw(level=10))
    Timeline(tmp_path).update(NOW)
    with open(tmp_path / "timeline.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"kind": "lev')

    assert len(load_events(tmp_path)) == 1


def test_an_unexpected_error_is_reported_not_raised(tmp_path, capsys):
    """The timeline rides the watch loop that keeps the Pip-Boy fog current."""
    (tmp_path / "player.json").write_text(json.dumps({"character": "not a dict"}))

    Timeline(tmp_path).update(NOW)

    assert "timeline" in capsys.readouterr().out


def test_misc_objectives_are_not_a_quest_on_the_timeline():
    misc = {"quest": 10, "instance": 1, "index": 20, "state": 1, "quest_name": "",
            "text": "Read the note"}
    state, _ = record_changes(None, _raw(), [], NOW)

    _, events = record_changes(state, _raw(objectives=[misc]), [], NOW)

    assert events == []
