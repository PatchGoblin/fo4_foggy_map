"""Text the window shows: the status bar and the hover readout.

Kept apart from the window itself so it can be tested without a display.
"""

from __future__ import annotations

from foggymap import config
from foggymap.coverage import PARTIAL, SWEPT
from foggymap.pipeline import FogMap, Settings, Worldspace

_VERDICTS = {SWEPT: "swept", PARTIAL: "partial"}


def status_line(editor_id: str, fog: FogMap, settings: Settings) -> str:
    """One-line summary of progress in the worldspace on screen."""
    return (
        f"{editor_id}   "
        f"area {fog.percent_area_explored:4.1f}%   "
        f"tiles {fog.land_tiles_swept}/{fog.land_tile_count}   "
        f"POIs {fog.pois_discovered}/{len(fog.pois)}   "
        f"sight {settings.area_radius / config.UNITS_PER_METRE:.0f} m   "
        f"{fog.sample_count} samples"
    )


def point_description(
    fog: FogMap,
    worldspace: Worldspace,
    settings: Settings,
    col: float,
    row: float,
    spoilers: bool = True,
) -> str:
    """What is known about the pixel under the cursor.

    With ``spoilers`` off, nothing is said about places the player has not found yet.
    """
    grid = worldspace.grid
    x, y = grid.from_px(col, row)
    cell_x, cell_y = int(x // config.CELL_UNITS), int(y // config.CELL_UNITS)

    parts = [f"world ({x:.0f}, {y:.0f})", f"cell ({cell_x}, {cell_y})"]

    tile = _tile_verdict(fog, worldspace, settings, x, y)
    if tile:
        parts.append(tile)

    if spoilers:
        nearest = _nearest_undiscovered(fog, x, y)
        if nearest:
            parts.append(nearest)

    return "   ".join(parts)


def _tile_verdict(
    fog: FogMap, worldspace: Worldspace, settings: Settings, x: float, y: float
) -> str:
    grid = worldspace.grid
    tile_col = int((x - grid.min_x) // settings.tile_units)
    tile_row = int((grid.max_y - y) // settings.tile_units)

    rows, cols = fog.tile_coverage.shape
    if not (0 <= tile_row < rows and 0 <= tile_col < cols):
        return ""

    fraction = fog.tile_coverage[tile_row, tile_col] * 100.0
    verdict = _VERDICTS.get(int(fog.tile_class[tile_row, tile_col]), "unvisited")
    suffix = "" if fog.land_tiles[tile_row, tile_col] else " (no map here)"
    return f"tile {fraction:3.0f}% {verdict}{suffix}"


def _nearest_undiscovered(fog: FogMap, x: float, y: float) -> str:
    missed = [poi for poi in fog.pois if not poi.discovered]
    if not missed:
        return ""
    poi = min(missed, key=lambda p: (p.x - x) ** 2 + (p.y - y) ** 2)
    metres = ((poi.x - x) ** 2 + (poi.y - y) ** 2) ** 0.5 / config.UNITS_PER_METRE
    name = poi.name or f"0x{poi.form_id:08X}"
    return f"nearest undiscovered: {name} ({metres:.0f} m)"
