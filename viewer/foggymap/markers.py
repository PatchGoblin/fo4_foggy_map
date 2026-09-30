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
