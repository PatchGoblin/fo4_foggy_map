"""Points of interest, and the fog discs each one owns.

A POI's disc is cleared only by the game reporting the marker as discovered -- never
by walking nearby. That is what makes a missed POI show as a dark circle inside
ground the player otherwise swept, and a POI found before FoggyMap existed show as a
small clear circle in terrain that is still fogged.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from foggymap.grid import Grid


@dataclass(frozen=True)
class Poi:
    """One map marker as the game currently sees it."""

    worldspace: str
    form_id: int
    name: str
    x: float
    y: float
    radius: float | None
    marker_type: int
    discovered: bool


# What each map marker type is, as an icon (a Lucide name; see tools/fetch_icons.py)
# and a word for the hover label. Grouped from the names the game gives each type.
MARKER_KINDS: dict[int, tuple[str, str]] = {
    0: ("mountain", "Cave"),
    1: ("building-2", "Apartments"),
    2: ("star", "City"),
    3: ("house", "House"),
    4: ("warehouse", "Workshop"),
    5: ("landmark", "Landmark"),
    6: ("train-front", "Metro station"),
    7: ("shield", "Military base"),
    8: ("flag", "Landmark"),
    9: ("store", "Shop"),
    10: ("house", "Neighbourhood"),
    11: ("building", "Ruins"),
    12: ("house", "Settlement"),
    13: ("map-pin", "Settlement"),
    14: ("construction", "Tunnel"),
    15: ("cog", "Vault"),
    16: ("plane", "Aircraft"),
    17: ("landmark", "Monument"),
    18: ("caravan", "Trailer park"),
    19: ("construction", "Bridge"),
    20: ("church", "Church"),
    22: ("clock", "Tower"),
    23: ("clapperboard", "Entertainment"),
    24: ("construction", "Overpass"),
    25: ("landmark", "Landmark"),
    26: ("wheat", "Farm"),
    27: ("fuel", "Filling station"),
    28: ("trees", "Park"),
    29: ("hotel", "Hotel"),
    30: ("cross", "Cemetery"),
    31: ("hospital", "Hospital"),
    32: ("zap", "Power plant"),
    33: ("factory", "Factory"),
    35: ("fish", "Fishery"),
    36: ("trash-2", "Junkyard"),
    37: ("telescope", "Lookout"),
    38: ("anchor", "Harbour"),
    39: ("droplets", "Lake"),
    40: ("pickaxe", "Quarry"),
    41: ("radiation", "Crater"),
    42: ("radio-tower", "Radio tower"),
    43: ("skull", "Museum"),
    44: ("school", "School"),
    45: ("ship", "Shipwreck"),
    47: ("bird", "Pond"),
    49: ("ferris-wheel", "Amusement park"),
    51: ("shirt", "Shop"),
    52: ("package", "Bunker"),
    53: ("castle", "Fort"),
    54: ("building-2", "Office tower"),
    55: ("sailboat", "Raider fleet"),
    56: ("building", "Roadside stop"),
    58: ("siren", "Police station"),
    61: ("train-front", "Station"),
    62: ("satellite-dish", "Satellite array"),
    63: ("rocket", "Missile silo"),
    64: ("ship", "Ship"),
    66: ("utensils", "Restaurant"),
    70: ("rocket", "Arcade"),
    73: ("train-front", "Station"),
    74: ("ferris-wheel", "Ride"),
    75: ("paw-print", "Safari"),
    78: ("mountain", "Mountain"),
    79: ("building", "Parlour"),
    80: ("music", "Amphitheatre"),
}
UNKNOWN_KIND = ("map-pin", "Location")


def marker_kind(marker_type: int) -> tuple[str, str]:
    """(icon, label) for a map marker type, or a plain pin for one we have not named."""
    return MARKER_KINDS.get(marker_type, UNKNOWN_KIND)


def load_pois(csv_path, worldspace: str | None = None) -> list[Poi]:
    """Read ``markers.csv`` written by the plugin, optionally for one worldspace."""
    if not os.path.exists(csv_path):
        return []

    pois: list[Poi] = []
    with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                poi = Poi(
                    worldspace=row["worldspace"],
                    form_id=int(row["form_id"], 16),
                    name=row["name"],
                    x=float(row["x"]),
                    y=float(row["y"]),
                    radius=float(row["radius"]) if row["radius"] else None,
                    marker_type=int(row["marker_type"] or 0),
                    discovered=row["discovered"].strip() in ("1", "true", "True"),
                )
            except (KeyError, TypeError, ValueError):
                continue  # a partially flushed final row
            # A disabled marker is not on the game's map and can never be discovered.
            if (row.get("disabled") or "").strip() in ("1", "true", "True"):
                continue
            if worldspace is None or poi.worldspace == worldspace:
                pois.append(poi)
    return pois


def disc_mask(
    grid: Grid,
    points: Iterable[tuple[float, float]],
    radius_units: float,
    min_px: int = 0,
) -> np.ndarray:
    """Mark a disc around each world position.

    ``min_px`` keeps discs visible when the world radius is small relative to the
    map's pixel size.
    """
    mask = np.zeros((grid.height_px, grid.width_px), dtype=bool)

    radius_x = max(radius_units / grid.units_per_px_x, min_px)
    radius_y = max(radius_units / grid.units_per_px_y, min_px)
    if radius_x <= 0 or radius_y <= 0:
        return mask  # the layer is switched off
    reach_x, reach_y = int(np.ceil(radius_x)), int(np.ceil(radius_y))

    for x, y in points:
        col, row = grid.to_px(x, y)
        col_lo, col_hi = int(np.floor(col)) - reach_x, int(np.ceil(col)) + reach_x + 1
        row_lo, row_hi = int(np.floor(row)) - reach_y, int(np.ceil(row)) + reach_y + 1

        col_lo, col_hi = max(col_lo, 0), min(col_hi, grid.width_px)
        row_lo, row_hi = max(row_lo, 0), min(row_hi, grid.height_px)
        if col_lo >= col_hi or row_lo >= row_hi:
            continue

        cols = np.arange(col_lo, col_hi) + 0.5
        rows = np.arange(row_lo, row_hi) + 0.5
        inside = (((cols - col) / radius_x) ** 2)[None, :] + (
            ((rows - row) / radius_y) ** 2
        )[:, None] <= 1.0
        mask[row_lo:row_hi, col_lo:col_hi] |= inside

    return mask
