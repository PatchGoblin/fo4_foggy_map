"""Locating the installed Fallout 4 data directory.

Kept in one place so no test or tool hardcodes a single machine's install. Set
``FALLOUT4_DATA`` to override; otherwise the usual Steam locations are tried.
"""

from __future__ import annotations

import os

CANDIDATES = [
    r"D:\SteamLibrary\steamapps\common\Fallout 4\Data",
    r"C:\Program Files (x86)\Steam\steamapps\common\Fallout 4\Data",
    r"C:\SteamLibrary\steamapps\common\Fallout 4\Data",
    r"E:\SteamLibrary\steamapps\common\Fallout 4\Data",
    r"D:\Program Files (x86)\Steam\steamapps\common\Fallout 4\Data",
]


def data_dir() -> str:
    """The game's Data directory.

    Returns the first candidate that exists, or the first candidate regardless so the
    caller has a concrete path to report or skip on. Never returns None -- callers should
    not have to distinguish "not configured" from "not installed".
    """
    override = os.environ.get("FALLOUT4_DATA")
    if override:
        return override
    for candidate in CANDIDATES:
        if os.path.isdir(candidate):
            return candidate
    return CANDIDATES[0]
