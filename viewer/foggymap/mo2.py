"""The mod list as Mod Organizer 2 shows it: every enabled mod, grouped by separator.

The game itself only knows the plugins it loaded. Texture packs, UI mods and loose
scripts have no plugin, so only MO2's own profile can list everything. Read only when
publish.ini points at a profile; otherwise the page lists the load order alone.
"""

from __future__ import annotations

import configparser
import os

PLUGIN_EXTENSIONS = (".esp", ".esm", ".esl")
SEPARATOR_SUFFIX = "_separator"
UNSORTED = "Unsorted"


def read_profile(profile_dir) -> dict:
    """Enabled mods from ``profile_dir``'s modlist.txt, in MO2's left-pane order.

    modlist.txt lists the highest priority first, so it is read backwards. A separator
    heads the mods below it in MO2; mods above the first separator are Unsorted. Lines
    starting ``*`` are game content MO2 does not manage (DLC, Creation Club).
    """
    profile_dir = str(profile_dir)
    with open(os.path.join(profile_dir, "modlist.txt"), "r", encoding="utf-8-sig") as handle:
        lines = [line.rstrip("\r\n") for line in handle]

    mods_dir = _mods_directory(profile_dir)
    groups: list[dict] = [{"label": UNSORTED, "mods": []}]
    unmanaged: list[str] = []
    for line in reversed(lines):
        if not line or line.startswith("#"):
            continue
        flag, name = line[0], line[1:].strip()
        if flag == "*":
            unmanaged.append(name)
        elif name.endswith(SEPARATOR_SUFFIX):
            groups.append({"label": name[: -len(SEPARATOR_SUFFIX)], "mods": []})
        elif flag == "+":
            groups[-1]["mods"].append(_mod(mods_dir, name))

    unmanaged.reverse()  # back to the order MO2 lists them in
    groups = [group for group in groups if group["mods"]]
    return {
        "groups": groups,
        "unmanaged": unmanaged,
        "enabled": sum(len(group["mods"]) for group in groups),
    }


def _mod(mods_dir: str, name: str) -> dict:
    """A mod with the plugins in its root and the F4SE DLLs it ships."""
    folder = os.path.join(mods_dir, name)
    plugins: list[str] = []
    dlls: list[str] = []
    try:
        for entry in os.scandir(folder):
            if entry.is_file() and entry.name.lower().endswith(PLUGIN_EXTENSIONS):
                plugins.append(entry.name)
            elif entry.is_dir() and entry.name.lower() == "f4se":
                dlls = _dlls(entry.path)
    except OSError:
        pass  # listed in the profile but missing on disk: still a mod the player chose
    return {"name": name, "plugins": sorted(plugins, key=str.lower),
            "dlls": sorted(dlls, key=str.lower)}


def _dlls(f4se_dir: str) -> list[str]:
    for entry in os.scandir(f4se_dir):
        if entry.is_dir() and entry.name.lower() == "plugins":
            return [file.name for file in os.scandir(entry.path)
                    if file.is_file() and file.name.lower().endswith(".dll")]
    return []


def _mods_directory(profile_dir: str) -> str:
    """The instance's mods folder: <instance>/mods, unless ModOrganizer.ini moves it."""
    instance = os.path.dirname(os.path.dirname(os.path.abspath(profile_dir)))
    default = os.path.join(instance, "mods")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(os.path.join(instance, "ModOrganizer.ini"), encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        return default
    value = parser.get("Settings", "mod_directory", fallback="").strip().strip('"')
    if not value:
        return default
    base = parser.get("Settings", "base_directory", fallback="").strip().strip('"') or instance
    return os.path.normpath(value.replace("%BASE_DIR%", base))
