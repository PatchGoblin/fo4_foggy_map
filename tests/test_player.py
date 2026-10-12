"""Turning the plugin's raw player.json into what the published page shows.

The fixture mirrors what the player probe found on a real save: perk ranks as chained
forms, magazines and bobbleheads mixed in with perks, item names tagged by a sorting
mod, items split across stacks, and quests the player never saw.
"""

import copy
import json

import pytest

from foggymap.player import load_player, public_profile, xp_progress

COMPLETED, SHOWN, FAILED, RUNNING = 0x2, 0x20, 0x40, 0x1


def _perk(form_id, name, ranks=1, level=0, playable=True, hidden=False, rank=1, next_id=0):
    return {"id": form_id, "name": name, "rank": rank, "ranks": ranks, "level": level,
            "playable": playable, "hidden": hidden, "next": next_id}


RAW = {
    "version": 1,
    "character": {
        "name": "Nora", "sex": 1, "level": 37, "xp": 56183.89, "perk_points": 0, "caps": 29224,
        "special": {"strength": [10, 10], "perception": [10, 10], "endurance": [10, 10],
                    "charisma": [10, 11], "intelligence": [10, 11], "agility": [10, 10],
                    "luck": [10, 10]},
        "stats": {"health": [400, 242.99], "action_points": [160, 160], "rads": [0, 36.3],
                  "carry_weight": [300, 100305]},
    },
    "time": {"playtime_ms": 176625356,
             "game": {"year": 287, "month": 12, "day": 4, "hour": 18.87, "days_passed": 42.79}},
    "location": "Thicket Excavations",
    "perks": [
        # Each rank of a perk is its own form with the same name.
        _perk(0x1D2479, "Rad Resistant", ranks=4, next_id=0x1D247A),
        _perk(0x1D247A, "Rad Resistant", ranks=4, level=13, next_id=0x1D247B),
        _perk(0x1D247B, "Rad Resistant", ranks=4, level=26),
        _perk(0x0523FF, "Locksmith", ranks=4),
        # SPECIAL points bought at level-up are perks too; SPECIAL already shows them.
        _perk(0x0D9784, "Strength Training", ranks=9),
        # Magazines: real ranks on one form, or numbered issues each their own form.
        _perk(0x08E3A4, "Covert Operations", ranks=10, playable=False, rank=5),
        _perk(0x1C63E3, "Wasteland Survival 2", playable=False),
        _perk(0x1C63EB, "Wasteland Survival 8", playable=False),
        # Bobbleheads are hidden perks.
        _perk(0x061686, "Sneak Bobblehead", playable=False, hidden=True),
        # Engine bookkeeping: hidden, or unnamed.
        _perk(0x2458BA, "AddictionManager", playable=False, hidden=True),
        _perk(0x00084B, "", hidden=True),
        # A perk from a mod: kept, under Other.
        _perk(0xFE001234, "Modded Perk", ranks=2),
    ],
    "inventory": [
        {"id": 0x23736, "type": "ALCH", "name": "[Stimpak] Stimpak", "count": 215, "equipped": False},
        {"id": 0x23736, "type": "ALCH", "name": "[Stimpak] Stimpak", "count": 3, "equipped": False},
        {"id": 0x21B3B, "type": "ARMO", "name": "Pipboy", "count": 1, "equipped": True},
        {"id": 0x1EED7, "type": "ARMO", "name": "[VaultSuit] Vault 111 Jumpsuit | Insulated",
         "count": 1, "equipped": False},
        {"id": 0xE5881, "type": "WEAP", "name": "[Flamethrower] Maximum Capacity Huge Napalmer",
         "count": 1, "equipped": False},
        {"id": 0x18ABE2, "type": "AMMO", "name": "[AmmoEnergy] Cryo Cell", "count": 200, "equipped": False},
        {"id": 0xF, "type": "MISC", "name": "[Currency] Bottle Cap", "count": 29220, "equipped": False},
        {"id": 0x4F629, "type": "NOTE", "name": "[HolotapeV] Hi Honey!", "count": 1, "equipped": False},
        {"id": 0x194374, "type": "KEYM", "name": "[Key] Margaret's Safe Key", "count": 1, "equipped": False},
        {"id": 0x140AF0, "type": "MISC", "name": "[Trash] Folder", "count": 393, "equipped": False},
    ],
    "quests": [
        {"id": 1, "editor_id": "MQ102", "name": "[MainQuest] Out of Time",
         "flags": COMPLETED | SHOWN, "type": 1, "stage": 1000},
        {"id": 2, "editor_id": "DN143", "name": "[VaultTec] Vault 75",
         "flags": COMPLETED | SHOWN | RUNNING, "type": 0, "stage": 800},
        {"id": 3, "editor_id": "Pyro", "name": "[Quest] Pyromaniac",
         "flags": SHOWN | RUNNING, "type": 7, "stage": 50},
        # The same name from a CC add-on the player never saw: hidden.
        {"id": 4, "editor_id": "ccPyro", "name": "[Quest] Pyromaniac",
         "flags": RUNNING, "type": 7, "stage": 10},
        {"id": 5, "editor_id": "MQ203", "name": "[MainQuest] Jewel of the Commonwealth",
         "flags": SHOWN | RUNNING, "type": 1, "stage": 10},
        {"id": 6, "editor_id": "Hook", "name": "Quest Hook - Automatron - Defending Rust Devils",
         "flags": COMPLETED, "type": 6, "stage": 1000},
        {"id": 7, "editor_id": "Fail", "name": "[Quest] The Lost Cause",
         "flags": FAILED | SHOWN, "type": 7, "stage": 50},
        {"id": 8, "editor_id": "MinRadiant", "name": "[Minutemen] *<Alias=ActualLocation>: Greenskins",
         "flags": RUNNING, "type": 4, "stage": 40},
    ],
    "objectives": [
        {"quest": 3, "instance": 1, "index": 40, "state": 2, "quest_name": "[Quest] Pyromaniac",
         "text": "Track down the arsonists"},
        {"quest": 3, "instance": 1, "index": 50, "state": 1, "quest_name": "[Quest] Pyromaniac",
         "text": "Kill the arsonists"},
        {"quest": 2, "instance": 1, "index": 700, "state": 3, "quest_name": "[VaultTec] Vault 75",
         "text": "Explore Admin Area"},
        # Two instances of one radiant quest, each with its own place.
        {"quest": 8, "instance": 5, "index": 40, "state": 1,
         "quest_name": "[Minutemen] *Abernathy Farm: Greenskins", "text": "Kill the super mutants"},
        {"quest": 8, "instance": 9, "index": 40, "state": 1,
         "quest_name": "[Minutemen] *The Slog: Greenskins", "text": "Kill the super mutants"},
        # A finished old instance: not active.
        {"quest": 8, "instance": 2, "index": 40, "state": 2,
         "quest_name": "[Minutemen] *Finch Farm: Greenskins", "text": "Kill the super mutants"},
    ],
    "companions": ["Dogmeat"],
    "mods": {
        "plugins": [
            {"name": "Fallout4.esm", "index": 0, "light": False},
            {"name": "DLCRobot.esm", "index": 1, "light": False},
            {"name": "unofficial fallout 4 patch.esp", "index": 7, "light": False},
            {"name": "ccBGSFO4044-HellfirePowerArmor.esl", "index": 2, "light": True},
            {"name": "prp.esp", "index": 60, "light": True},
        ],
        "f4se": ["FoggyMap.dll", "Buffout4.dll"],
    },
}


@pytest.fixture
def profile():
    return public_profile(RAW, show_name=False)


# --- loading -----------------------------------------------------------------------


def test_load_reads_the_plugins_file(tmp_path):
    (tmp_path / "player.json").write_text(json.dumps(RAW), encoding="utf-8")

    assert load_player(tmp_path)["character"]["level"] == 37


def test_load_returns_none_when_absent_or_cut_short(tmp_path):
    assert load_player(tmp_path) is None
    (tmp_path / "player.json").write_text('{"version": 1, "charac', encoding="utf-8")
    assert load_player(tmp_path) is None


def test_load_survives_text_that_is_not_utf8(tmp_path):
    """Game strings can be in the old Windows code page."""
    raw = json.dumps(RAW).replace("Thicket Excavations", "Café").encode("cp1252")
    (tmp_path / "player.json").write_bytes(raw)

    assert load_player(tmp_path)["location"].startswith("Caf")


# --- character ---------------------------------------------------------------------


def test_the_name_is_hidden_unless_asked_for(profile):
    assert profile["name"] == "The Sole Survivor"
    assert "Nora" not in json.dumps(profile)
    assert public_profile(RAW, show_name=True)["name"] == "Nora"


def test_xp_progress_uses_the_games_level_curve():
    """Level 2 needs 200 XP, and each level after needs 75 more than the last.
    Verified against a real save: 56,184 XP sits inside level 37."""
    progress = xp_progress(level=37, xp=56183.89)

    assert progress["level_start"] == 54450
    assert progress["next_level"] == 57350
    assert progress["progress"] == pytest.approx((56183.89 - 54450) / (57350 - 54450))


def test_character_basics(profile):
    assert profile["level"] == 37
    assert profile["caps"] == 29224
    assert profile["location"] == "Thicket Excavations"
    assert profile["companions"] == ["Dogmeat"]
    assert profile["playtime_hours"] == pytest.approx(49.06, abs=0.01)
    assert profile["game_date"] == "4 December 2287"


def test_special_keeps_base_and_current(profile):
    charisma = next(s for s in profile["special"] if s["label"] == "Charisma")
    assert (charisma["base"], charisma["current"]) == (10, 11)
    assert [s["label"][0] for s in profile["special"]] == list("SPECIAL")


# --- perks -------------------------------------------------------------------------


def test_perk_rank_is_the_number_of_rank_forms_owned(profile):
    perks = {p["name"]: p for group in profile["perks"] for p in group["perks"]}
    assert (perks["Rad Resistant"]["rank"], perks["Rad Resistant"]["ranks"]) == (3, 4)
    assert perks["Locksmith"]["rank"] == 1


def test_perks_are_grouped_by_special(profile):
    groups = {g["special"]: [p["name"] for p in g["perks"]] for g in profile["perks"]}
    assert groups["Endurance"] == ["Rad Resistant"]
    assert groups["Perception"] == ["Locksmith"]
    assert groups["Other"] == ["Modded Perk"]


def test_special_training_and_engine_perks_are_not_listed(profile):
    names = json.dumps(profile["perks"])
    for hidden in ("Strength Training", "AddictionManager", "Bobblehead", "Covert", "Wasteland"):
        assert hidden not in names


def test_magazines_are_collected_with_ranks_or_issues(profile):
    magazines = {m["name"]: m for m in profile["magazines"]}
    assert (magazines["Covert Operations"]["rank"], magazines["Covert Operations"]["ranks"]) == (5, 10)
    assert magazines["Wasteland Survival"]["issues"] == [2, 8]


def test_bobbleheads_are_collected(profile):
    assert profile["bobbleheads"] == ["Sneak"]


# --- inventory ---------------------------------------------------------------------


def _category(profile, label):
    return next(c for c in profile["inventory"] if c["category"] == label)["items"]


def test_inventory_is_grouped_and_tags_are_stripped(profile):
    labels = [c["category"] for c in profile["inventory"]]
    assert labels == ["Weapons", "Apparel", "Aid", "Ammo", "Notes & Holotapes", "Keys", "Misc"]
    assert _category(profile, "Weapons")[0]["name"] == "Maximum Capacity Huge Napalmer"


def test_split_stacks_are_merged(profile):
    (stimpak,) = _category(profile, "Aid")
    assert (stimpak["name"], stimpak["count"]) == ("Stimpak", 218)


def test_equipped_items_come_first(profile):
    apparel = _category(profile, "Apparel")
    assert apparel[0] == {"name": "Pipboy", "count": 1, "equipped": True}


def test_caps_are_a_stat_not_an_item(profile):
    assert "Bottle Cap" not in json.dumps(profile["inventory"])


# --- quests ------------------------------------------------------------------------


def test_only_quests_the_player_has_seen_are_listed(profile):
    names = json.dumps(profile["quests"])
    assert "Quest Hook" not in names
    assert names.count("Pyromaniac") == 1


def test_active_quests_show_their_current_objectives(profile):
    active = {q["name"]: q for q in profile["quests"]["active"]}
    assert active["Pyromaniac"]["objectives"] == ["Kill the arsonists"]
    assert active["Pyromaniac"]["type"] == "Side"
    assert active["Jewel of the Commonwealth"]["objectives"] == []


def test_each_radiant_instance_is_its_own_quest_named_for_its_place(profile):
    active = [q["name"] for q in profile["quests"]["active"]]
    assert "Abernathy Farm: Greenskins" in active
    assert "The Slog: Greenskins" in active
    assert not any("Finch Farm" in name for name in active)


def test_finished_quests_say_whether_they_failed(profile):
    finished = {q["name"]: q for q in profile["quests"]["finished"]}
    assert finished["Out of Time"] == {"name": "Out of Time", "type": "Main", "failed": False}
    assert finished["Vault 75"]["type"] == "Miscellaneous"
    assert finished["The Lost Cause"]["failed"] is True


# --- mods --------------------------------------------------------------------------


def test_mods_are_grouped_in_load_order(profile):
    groups = {g["label"]: g["plugins"] for g in profile["mods"]["groups"]}
    assert [p["name"] for p in groups["Base game"]] == ["Fallout4.esm", "DLCRobot.esm"]
    assert [p["name"] for p in groups["Creation Club"]] == ["ccBGSFO4044-HellfirePowerArmor.esl"]
    assert [p["name"] for p in groups["Mods"]] == ["unofficial fallout 4 patch.esp", "prp.esp"]
    assert profile["mods"]["f4se"] == ["Buffout4.dll", "FoggyMap.dll"]


def test_a_partial_file_from_an_older_plugin_still_profiles():
    profile = public_profile({"version": 1, "character": {"level": 3}}, show_name=False)

    assert profile["level"] == 3
    assert profile["perks"] == [] and profile["inventory"] == []
    assert profile["quests"] == {"active": [], "finished": []}


def test_when_rank_forms_disagree_on_the_rank_count_the_majority_wins():
    """Seen on a real save: one of four Toughness forms says 10 ranks, the rest say 5."""
    raw = {"perks": [_perk(1, "Toughness", ranks=5), _perk(2, "Toughness", ranks=5),
                     _perk(3, "Toughness", ranks=10), _perk(4, "Toughness", ranks=5)]}

    (group,) = public_profile(raw, show_name=False)["perks"]

    assert (group["perks"][0]["rank"], group["perks"][0]["ranks"]) == (4, 5)


def _journal(quests, objectives):
    return public_profile({"quests": quests, "objectives": objectives}, show_name=False)["quests"]


def test_misc_objectives_are_listed_like_the_pipboys_misc_section():
    """Seen on a real save: misc quests are never shown by name, and some are unnamed,
    but their current objectives are on the Pip-Boy under Misc."""
    quests = [
        {"id": 10, "name": "[Quest] [DN070 - Jamaica Plain]", "flags": 0x6901, "type": 6},
        {"id": 11, "name": "", "flags": 0x1, "type": 0},
    ]
    objectives = [
        {"quest": 10, "instance": 1, "index": 20, "state": 1,
         "quest_name": "[Quest] [DN070 - Jamaica Plain]", "text": "Find the treasure of Jamaica Plain"},
        {"quest": 11, "instance": 0, "index": 0, "state": 1, "quest_name": "",
         "text": "Read the note"},
        {"quest": 11, "instance": 0, "index": 5, "state": 3, "quest_name": "",
         "text": "Something already done"},
    ]

    journal = _journal(quests, objectives)

    assert journal["active"] == [{"name": "Miscellaneous", "type": "Miscellaneous",
                                  "objectives": ["Find the treasure of Jamaica Plain", "Read the note"],
                                  "misc": True}]


def test_no_misc_entry_without_misc_objectives(profile):
    assert "Miscellaneous" not in [q["name"] for q in profile["quests"]["active"]]


def test_a_hidden_name_is_redacted_from_every_published_text():
    """Seen on a real save: a note titled with the character's name. The game writes
    the player's name into some text, so hiding it means hiding it everywhere."""
    raw = copy.deepcopy(RAW)
    raw["inventory"].append({"id": 1, "type": "NOTE", "name": "Orders: Eliminate NORA",
                             "count": 1, "equipped": False})
    raw["objectives"].append({"quest": 3, "instance": 1, "index": 60, "state": 1,
                              "quest_name": "[Quest] Pyromaniac", "text": "Tell Nora's friends"})

    profile = public_profile(raw, show_name=False)

    assert "nora" not in json.dumps(profile).lower()
    notes = next(c for c in profile["inventory"] if c["category"] == "Notes & Holotapes")["items"]
    assert "Orders: Eliminate [name]" in [i["name"] for i in notes]


def test_redaction_matches_whole_words_only():
    raw = copy.deepcopy(RAW)
    raw["character"]["name"] = "Al"
    raw["inventory"].append({"id": 1, "type": "ALCH", "name": "Alcohol", "count": 1, "equipped": False})

    profile = public_profile(raw, show_name=False)

    aid = next(c for c in profile["inventory"] if c["category"] == "Aid")["items"]
    assert "Alcohol" in [i["name"] for i in aid]


def test_a_shown_name_is_left_everywhere():
    raw = copy.deepcopy(RAW)
    raw["inventory"].append({"id": 1, "type": "NOTE", "name": "Orders: Eliminate Nora",
                             "count": 1, "equipped": False})

    assert "Orders: Eliminate Nora" in json.dumps(public_profile(raw, show_name=True))
