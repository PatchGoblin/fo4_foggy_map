"""The playthrough timeline: levels, perks, quests, bobbleheads and discoveries, as they
happen.

The plugin only ever writes the present, so the timeline is built here by comparing
each new snapshot with what has been seen before. "Seen" is a high-water mark rather
than the last snapshot: reloading an older save then neither records losses nor
records the same progress twice when it is made again.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

from foggymap.markers import Poi, load_pois, marker_kind
from foggymap.player import journal, load_player, public_profile, sort_perks

STATE_FILE = "timeline_state.json"
EVENTS_FILE = "timeline.jsonl"

ICONS = {
    "tracking_began": "flag",
    "new_character": "flag",
    "level": "trending-up",
    "perk": "star",
    "bobblehead": "trophy",
    "quest_started": "scroll",
    "quest_completed": "circle-check",
    "quest_failed": "circle-x",
}


def record_changes(state: dict | None, raw: dict, pois: list[Poi], now: datetime):
    """The new high-water state and the events between ``state`` and ``raw``.

    With no state, or a different character, the current snapshot becomes the
    baseline and a single marker event says so.
    """
    current = _snapshot(raw, pois)
    stamp = _stamp(raw, now)

    if state is None or state.get("character") != current["character"]:
        kind = "tracking_began" if state is None else "new_character"
        text = ("Started tracking" if state is None else "Started tracking a new character")
        return current, [_event(kind, f"{text} at level {current['level']}", stamp)]

    events = []
    for level in range(state["level"] + 1, current["level"] + 1):
        events.append(_event("level", f"Reached level {level}", stamp))

    for name in sorted(current["perks"]):
        seen = state["perks"].get(name, 0)
        for rank in range(seen + 1, current["perks"][name] + 1):
            text = f"Took {name}" if rank == 1 else f"{name} rank {rank}"
            events.append(_event("perk", text, stamp))

    for name in current["bobbleheads"]:
        if name not in state["bobbleheads"]:
            events.append(_event("bobblehead", f"Found the {name} bobblehead", stamp))

    for name, status in current["quests"].items():
        before = state["quests"].get(name)
        if before == status or before in ("completed", "failed"):
            continue
        if status == "active":
            if before is None:
                events.append(_event("quest_started", f"Started {name}", stamp))
        else:
            events.append(_event(f"quest_{status}", f"{status.capitalize()} {name}", stamp))

    discovered = set(state["discovered"])
    for poi in pois:
        if poi.discovered and poi.form_id not in discovered:
            event = _event("discovery", f"Discovered {poi.name}", stamp)
            event["icon"] = marker_kind(poi.marker_type)[0]
            event["worldspace"] = poi.worldspace
            events.append(event)

    merged = {
        "character": current["character"],
        "level": max(state["level"], current["level"]),
        "perks": {name: max(state["perks"].get(name, 0), rank)
                  for name, rank in {**state["perks"], **current["perks"]}.items()},
        "bobbleheads": sorted(set(state["bobbleheads"]) | set(current["bobbleheads"])),
        "quests": {**state["quests"], **{name: status for name, status in current["quests"].items()
                                         if state["quests"].get(name) not in ("completed", "failed")}},
        "discovered": sorted(discovered | set(current["discovered"])),
    }
    return merged, events


def _snapshot(raw: dict, pois: list[Poi]) -> dict:
    character = raw.get("character") or {}
    if not isinstance(character, dict):
        raise ValueError("player.json has no character")
    groups, _, bobbleheads = sort_perks(raw.get("perks") or [])
    quests = journal(raw.get("quests") or [], raw.get("objectives") or [])
    statuses = {quest["name"]: "active" for quest in quests["active"] if not quest.get("misc")}
    for quest in quests["finished"]:
        statuses[quest["name"]] = "failed" if quest["failed"] else "completed"
    # The name identifies the character but is never stored, even locally.
    identity = f"{character.get('name', '')}|{character.get('sex', '')}"
    return {
        "character": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "level": int(character.get("level") or 0),
        "perks": {perk["name"]: perk["rank"] for group in groups for perk in group["perks"]},
        "bobbleheads": bobbleheads,
        "quests": statuses,
        "discovered": sorted(poi.form_id for poi in pois if poi.discovered),
    }


def _stamp(raw: dict, now: datetime) -> dict:
    profile = public_profile({"time": raw.get("time") or {}}, show_name=False)
    return {"at": now.isoformat(), "playtime_hours": profile["playtime_hours"],
            "game_date": profile["game_date"]}


def _event(kind: str, text: str, stamp: dict) -> dict:
    return {"kind": kind, "text": text, "icon": ICONS.get(kind, "flag"), **stamp}


class Timeline:
    """Keeps timeline.jsonl current as the plugin rewrites player.json and markers.csv.

    ``update`` is called from the watch loop every second, so it is cheap when nothing
    changed, and never raises: the same loop keeps the in-game fog current.
    """

    def __init__(self, data_dir):
        self._data_dir = str(data_dir)
        self._seen_stamp: tuple | None = None

    def update(self, now: datetime) -> list[dict]:
        try:
            return self._update(now)
        except Exception as error:  # noqa: BLE001 - reported; the fog must keep going
            print(f"timeline update failed: {type(error).__name__}: {error}", flush=True)
            return []

    def _update(self, now: datetime) -> list[dict]:
        player_path = os.path.join(self._data_dir, "player.json")
        markers_path = os.path.join(self._data_dir, "markers.csv")
        stamp = tuple(_file_stamp(path) for path in (player_path, markers_path))
        if stamp == self._seen_stamp:
            return []
        self._seen_stamp = stamp

        raw = load_player(self._data_dir)
        if raw is None:
            return []
        content = _hash_files(player_path, markers_path)
        saved = self._load_state()
        if saved and saved.get("content") == content:
            return []

        state, events = record_changes(saved.get("state") if saved else None,
                                       raw, load_pois(markers_path), now)
        if events:
            with open(os.path.join(self._data_dir, EVENTS_FILE), "a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._save_state({"content": content, "state": state})
        return events

    def _load_state(self) -> dict | None:
        try:
            with open(os.path.join(self._data_dir, STATE_FILE), "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def _save_state(self, saved: dict) -> None:
        path = os.path.join(self._data_dir, STATE_FILE)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(saved, handle)
        os.replace(path + ".tmp", path)


def load_events(data_dir, limit: int | None = None) -> list[dict]:
    """Timeline events, newest first. A line cut short by a kill is skipped."""
    events = []
    try:
        with open(os.path.join(str(data_dir), EVENTS_FILE), "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    events.reverse()
    return events[:limit] if limit else events


def _file_stamp(path: str) -> tuple:
    try:
        info = os.stat(path)
    except OSError:
        return (0, 0.0)
    return (info.st_size, info.st_mtime)


def _hash_files(*paths: str) -> str:
    digest = hashlib.sha256()
    for path in paths:
        try:
            with open(path, "rb") as handle:
                digest.update(handle.read())
        except OSError:
            digest.update(b"absent")
    return digest.hexdigest()
