"""The player's character as the published page shows it.

The plugin's player.json records raw facts. This decides what is public and makes it
readable: perk ranks rebuilt from their chained forms, magazines and bobbleheads set
apart, sorting-mod tags stripped from names, split stacks merged, and only the quests
the player has actually seen.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict

PLAYER_FILE = "player.json"
ANONYMOUS = "The Sole Survivor"
REDACTED = "[name]"

# Quest flags, from the game's QuestFlag.
QUEST_COMPLETED = 0x2
QUEST_SHOWN = 0x20  # displayed to the player: it is in their Pip-Boy
QUEST_FAILED = 0x40

# Objective states, from QUEST_OBJECTIVE_STATE.
OBJECTIVE_DISPLAYED = 1

MISC_QUEST_TYPE = 6

QUEST_TYPES = {
    1: "Main", 2: "Brotherhood of Steel", 3: "Institute", 4: "Minutemen",
    5: "Railroad", 7: "Side", 8: "DLC", 9: "DLC", 10: "DLC",
}

SPECIAL = ("strength", "perception", "endurance", "charisma", "intelligence", "agility", "luck")

# The perk chart. Perks from mods and DLC fall under Other.
PERK_TREES: dict[str, tuple[str, ...]] = {
    "Strength": ("Iron Fist", "Big Leagues", "Armorer", "Blacksmith", "Heavy Gunner",
                 "Strong Back", "Steady Aim", "Basher", "Rooted", "Pain Train"),
    "Perception": ("Pickpocket", "Rifleman", "Awareness", "Locksmith", "Demolition Expert",
                   "Night Person", "Refractor", "Sniper", "Penetrator", "Concentrated Fire"),
    "Endurance": ("Toughness", "Lead Belly", "Lifegiver", "Chem Resistant", "Aquaboy",
                  "Aquagirl", "Rad Resistant", "Adamantium Skeleton", "Cannibal", "Ghoulish",
                  "Solar Powered"),
    "Charisma": ("Cap Collector", "Lady Killer", "Black Widow", "Lone Wanderer", "Attack Dog",
                 "Animal Friend", "Local Leader", "Party Boy", "Party Girl", "Inspirational",
                 "Wasteland Whisperer", "Intimidation"),
    "Intelligence": ("V.A.N.S.", "Medic", "Gun Nut", "Hacker", "Scrapper", "Science!",
                     "Chemist", "Robotics Expert", "Nuclear Physicist", "Nerd Rage!"),
    "Agility": ("Gunslinger", "Commando", "Sneak", "Mister Sandman", "Action Boy",
                "Action Girl", "Moving Target", "Ninja", "Quick Hands", "Blitz", "Gun Fu"),
    "Luck": ("Fortune Finder", "Scrounger", "Bloody Mess", "Mysterious Stranger",
             "Idiot Savant", "Better Criticals", "Critical Banker", "Grim Reaper's Sprint",
             "Four Leaf Clover", "Ricochet"),
}
_TREE_OF = {name: tree for tree, names in PERK_TREES.items() for name in names}

# Inventory sections in page order, by the game's form type.
INVENTORY_SECTIONS = (
    ("Weapons", ("WEAP",)),
    ("Apparel", ("ARMO",)),
    ("Aid", ("ALCH",)),
    ("Ammo", ("AMMO",)),
    ("Mods", ("OMOD",)),
    ("Notes & Holotapes", ("BOOK", "NOTE")),
    ("Keys", ("KEYM",)),
    ("Misc", ("MISC",)),
)
_SECTION_OF = {form_type: label for label, types in INVENTORY_SECTIONS for form_type in types}
CAPS_FORM_ID = 0xF

BASE_GAME_FILES = {
    "fallout4.esm", "dlcrobot.esm", "dlcworkshop01.esm", "dlccoast.esm",
    "dlcworkshop02.esm", "dlcworkshop03.esm", "dlcnukaworld.esm",
    "dlcultrahighresolution.esm",
}

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")

# A sorting mod's "[Stimpak] " prefix, and the "*" the game puts on radiant quests.
_TAG = re.compile(r"^\s*\[[^\]]*\]\s*")


def load_player(data_dir) -> dict | None:
    """The plugin's player.json, or None if it is absent or unreadable.

    Read as bytes: game text is usually UTF-8, but some strings come through in the
    Windows code page, and one of those must not cost the whole profile.
    """
    path = os.path.join(str(data_dir), PLAYER_FILE)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    try:
        player = json.loads(text)
    except ValueError:
        return None
    return player if isinstance(player, dict) else None


def clean_name(name: str) -> str:
    """A display name without a sorting mod's tag or the radiant-quest asterisk."""
    return _TAG.sub("", name or "").lstrip("*").strip()


def xp_progress(level: int, xp: float) -> dict:
    """Where ``xp`` sits within ``level``. Level 2 needs 200 XP and each level after
    needs 75 more than the one before -- the vanilla curve, checked against a real
    save, since the game exposes no setting for it."""
    def start(of: int) -> int:
        steps = max(of - 1, 0)
        return 200 * steps + 75 * steps * (steps - 1) // 2

    level_start, next_level = start(level), start(level + 1)
    span = max(next_level - level_start, 1)
    return {
        "level_start": level_start,
        "next_level": next_level,
        "progress": min(max((xp - level_start) / span, 0.0), 1.0),
    }


def public_profile(raw: dict, show_name: bool) -> dict:
    """Everything the page shows about the character, and nothing it should not."""
    character = raw.get("character") or {}
    level = int(character.get("level") or 0)
    profile = {
        "name": (character.get("name") or ANONYMOUS) if show_name else ANONYMOUS,
        "level": level,
        "xp": xp_progress(level, float(character.get("xp") or 0)),
        "caps": int(character.get("caps") or 0),
        "perk_points": int(character.get("perk_points") or 0),
        "special": _special(character.get("special") or {}),
        "stats": _stats(character.get("stats") or {}),
        "location": raw.get("location") or "",
        "companions": list(raw.get("companions") or []),
        "playtime_hours": round((raw.get("time") or {}).get("playtime_ms", 0) / 3_600_000, 2),
        "game_date": _game_date((raw.get("time") or {}).get("game")),
    }
    perks, magazines, bobbleheads = sort_perks(raw.get("perks") or [])
    profile.update(perks=perks, magazines=magazines, bobbleheads=bobbleheads)
    profile["inventory"] = _inventory(raw.get("inventory") or [])
    profile["quests"] = journal(raw.get("quests") or [], raw.get("objectives") or [])
    profile["mods"] = _mods(raw.get("mods") or {})
    if not show_name:
        profile = redact(profile, character.get("name") or "")
    return profile


def redact(value, name: str):
    """``value`` with every whole-word mention of ``name`` replaced, at any depth.

    The game writes the player's name into some text -- a note titled with it, an
    objective that addresses them -- so hiding the name means hiding it everywhere.
    Whole words only, so a short name never mangles a longer word that contains it.
    """
    name = name.strip()
    if not name:
        return value
    pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)

    def scrub(node):
        if isinstance(node, str):
            return pattern.sub(REDACTED, node)
        if isinstance(node, list):
            return [scrub(item) for item in node]
        if isinstance(node, dict):
            return {key: scrub(item) for key, item in node.items()}
        return node

    return scrub(value)


def _number(value):
    """Whole numbers as ints, so the page shows 10 rather than 10.0."""
    value = round(float(value), 1)
    return int(value) if value == int(value) else value


def _special(values: dict) -> list[dict]:
    out = []
    for key in SPECIAL:
        pair = values.get(key)
        if pair:
            out.append({"key": key, "label": key.capitalize(),
                        "base": _number(pair[0]), "current": _number(pair[1])})
    return out


def _stats(values: dict) -> dict:
    out = {}
    for key, pair in values.items():
        if pair:
            out[key] = {"max": _number(pair[0]), "current": _number(pair[1])}
    return out


def _game_date(game: dict | None) -> str:
    if not game or not game.get("month"):
        return ""
    month = MONTHS[(int(game["month"]) - 1) % 12]
    return f"{int(game['day'])} {month} {2000 + int(game['year'])}"


def sort_perks(raw: list[dict]):
    """Perks by SPECIAL tree, plus magazines and bobbleheads.

    Every rank of a perk is its own form sharing the perk's name, so a perk's rank is
    how many of those forms the player owns. "X Training" forms are SPECIAL points
    bought at level-up, already shown as SPECIAL. Hidden or unnamed perks are the
    engine's own bookkeeping -- except bobbleheads, which are hidden perks too.
    """
    owned: dict[str, list[int]] = {}  # name -> each owned rank form's rank count
    magazines: dict[str, dict] = {}
    bobbleheads: list[str] = []

    for perk in raw:
        name = (perk.get("name") or "").strip()
        if not name:
            continue
        if perk.get("hidden"):
            if name.endswith(" Bobblehead"):
                bobbleheads.append(name[: -len(" Bobblehead")])
            continue
        if perk.get("playable"):
            if name.endswith(" Training"):
                continue
            owned.setdefault(name, []).append(int(perk.get("ranks") or 1))
            continue
        issue = re.match(r"^(.*\S) (\d+)$", name)
        if issue and int(perk.get("ranks") or 1) == 1:
            magazine = magazines.setdefault(issue.group(1), {"name": issue.group(1), "issues": []})
            magazine.setdefault("issues", []).append(int(issue.group(2)))
        else:
            magazines[name] = {"name": name, "rank": int(perk.get("rank") or 1),
                               "ranks": int(perk.get("ranks") or 1)}

    trees: dict[str, list[dict]] = defaultdict(list)
    for name, counts in owned.items():
        # The forms should agree on the rank count, but a mod can edit one of them;
        # the majority wins, and a tie goes to the larger.
        ranks = max(set(counts), key=lambda count: (counts.count(count), count))
        entry = {"name": name, "rank": len(counts), "ranks": max(ranks, len(counts))}
        trees[_TREE_OF.get(name, "Other")].append(entry)
    order = list(PERK_TREES) + ["Other"]
    chart_position = {name: i for names in PERK_TREES.values() for i, name in enumerate(names)}
    groups = [
        {"special": tree,
         "perks": sorted(trees[tree], key=lambda p: (chart_position.get(p["name"], 99), p["name"]))}
        for tree in order if trees.get(tree)
    ]
    for magazine in magazines.values():
        if "issues" in magazine:
            magazine["issues"].sort()
    return groups, sorted(magazines.values(), key=lambda m: m["name"]), bobbleheads


def _inventory(raw: list[dict]) -> list[dict]:
    """Items by section, stacks merged, equipped first, caps left to their own stat."""
    merged: dict[tuple, dict] = {}
    for item in raw:
        if item.get("id") == CAPS_FORM_ID:
            continue
        section = _SECTION_OF.get(item.get("type"), "Other")
        name = clean_name(item.get("name") or "")
        if not name:
            continue
        equipped = bool(item.get("equipped"))
        key = (section, name, equipped)
        entry = merged.setdefault(key, {"name": name, "count": 0, "equipped": equipped})
        entry["count"] += int(item.get("count") or 0)

    sections = []
    for label in [label for label, _ in INVENTORY_SECTIONS] + ["Other"]:
        items = [entry for (section, _, _), entry in merged.items() if section == label]
        if items:
            items.sort(key=lambda i: (not i["equipped"], i["name"].lower()))
            sections.append({"category": label, "items": items})
    return sections


def journal(quests: list[dict], objectives: list[dict]) -> dict:
    """Active quests with their showing objectives, and finished ones, as the Pip-Boy
    lists them.

    A quest is listed by name only once it has been shown to the player: the game
    also runs hundreds of internal quests, some marked completed, that nobody sees.
    Active quests come from the player's objective list, one per instance, because
    radiant quests run several at once, each named for its own place. Objectives of
    misc quests -- never shown by name, sometimes unnamed -- are gathered under
    Miscellaneous, which is how the Pip-Boy shows them.
    """
    by_id = {quest.get("id"): quest for quest in quests}

    def flags(quest: dict | None) -> int:
        return (quest or {}).get("flags", 0)

    def type_of(quest: dict | None) -> str:
        return QUEST_TYPES.get((quest or {}).get("type"), "Miscellaneous")

    instances: dict[tuple, dict] = {}
    misc: list[str] = []
    for objective in objectives:
        quest = by_id.get(objective.get("quest"))
        if flags(quest) & (QUEST_COMPLETED | QUEST_FAILED):
            continue
        name = clean_name(objective.get("quest_name") or (quest or {}).get("name", ""))
        text = (objective.get("text") or "").strip()
        live = objective.get("state") == OBJECTIVE_DISPLAYED
        if not flags(quest) & QUEST_SHOWN and (not name or (quest or {}).get("type") == MISC_QUEST_TYPE):
            if live and text:
                misc.append(text)
            continue
        entry = instances.setdefault((objective.get("quest"), objective.get("instance")),
                                     {"name": name, "type": type_of(quest), "live": []})
        if live and text:
            entry["live"].append((objective.get("index", 0), text))

    active = []
    shown_in_progress = set()
    for (quest_id, _), entry in instances.items():
        if entry["live"]:
            active.append({"name": entry["name"], "type": entry["type"],
                           "objectives": [text for _, text in sorted(entry["live"])]})
            shown_in_progress.add(quest_id)

    finished = []
    for quest in quests:
        if not flags(quest) & QUEST_SHOWN:
            continue
        name = clean_name(quest.get("name", ""))
        if flags(quest) & (QUEST_COMPLETED | QUEST_FAILED):
            finished.append({"name": name, "type": type_of(quest),
                             "failed": bool(flags(quest) & QUEST_FAILED)})
        elif quest.get("id") not in shown_in_progress:
            active.append({"name": name, "type": type_of(quest), "objectives": []})

    if misc:
        # Marked, so the timeline does not treat the Misc list as a quest of its own.
        active.append({"name": "Miscellaneous", "type": "Miscellaneous", "objectives": misc,
                       "misc": True})
    return {"active": active, "finished": finished}


def _mods(raw: dict) -> dict:
    """Plugins in load order, grouped into the base game, Creation Club and mods."""
    plugins = sorted(raw.get("plugins") or [],
                     key=lambda p: (bool(p.get("light")), int(p.get("index") or 0)))
    groups: dict[str, list[dict]] = {"Base game": [], "Creation Club": [], "Mods": []}
    for plugin in plugins:
        name = plugin.get("name") or ""
        if name.lower() in BASE_GAME_FILES:
            group = "Base game"
        elif name.lower().startswith("cc"):
            group = "Creation Club"
        else:
            group = "Mods"
        groups[group].append({"name": name, "index": plugin.get("index"),
                              "light": bool(plugin.get("light"))})
    return {
        "groups": [{"label": label, "plugins": items} for label, items in groups.items() if items],
        "f4se": sorted(raw.get("f4se") or [], key=str.lower),
    }
