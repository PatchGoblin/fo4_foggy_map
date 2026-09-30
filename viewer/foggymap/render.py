"""Combining the fog layers into one alpha mask, and tinting the base map with it."""

from __future__ import annotations

import numpy as np

from foggymap.config import FOG_ALPHA_PARTIAL, FOG_ALPHA_UNVISITED
from foggymap.coverage import PARTIAL, SWEPT, expand_tiles
from foggymap.grid import Grid

# The map is drawn Pip-Boy green on black. Fog therefore has to *lift* the background
# towards a cool slate rather than merely dim the line art -- most of an unexplored
# region is empty background, so dimming alone would be invisible. The map stays fully
# legible underneath either way.
PIPBOY_GREEN = (0.16, 1.0, 0.44)
FOG_HAZE = (0.10, 0.15, 0.17)


def tint_map(
    intensity: np.ndarray,
    alpha: np.ndarray,
    map_colour: tuple[float, float, float] = PIPBOY_GREEN,
    fog_haze: tuple[float, float, float] = FOG_HAZE,
) -> np.ndarray:
    """Colour the greyscale base map, then wash fog over it."""
    normalised = intensity.astype(np.float32) / 255.0
    coloured = normalised[..., None] * np.asarray(map_colour, dtype=np.float32)

    weight = alpha[..., None]
    washed = coloured * (1.0 - weight) + np.asarray(fog_haze, dtype=np.float32) * weight
    return (np.clip(washed, 0.0, 1.0) * 255.0).astype(np.uint8)


def fog_alpha(
    grid: Grid,
    coverage: np.ndarray,
    tile_class: np.ndarray,
    poi_cleared: np.ndarray,
    poi_fogged: np.ndarray,
    tile_units: float,
    unvisited_alpha: float = FOG_ALPHA_UNVISITED,
    partial_alpha: float = FOG_ALPHA_PARTIAL,
) -> np.ndarray:
    """Per-pixel fog opacity, applied in order of increasing authority.

    The coarse tile verdict is the backdrop; the true coverage blob shows through it;
    a discovered POI clears its own disc; and an undiscovered POI re-fogs its disc over
    everything, so a location missed inside swept ground cannot hide.
    """
    tile_alpha = np.full(tile_class.shape, unvisited_alpha, dtype=np.float32)
    tile_alpha[tile_class == PARTIAL] = partial_alpha
    tile_alpha[tile_class == SWEPT] = 0.0

    alpha = expand_tiles(tile_alpha, grid, tile_units)
    alpha[coverage] = 0.0
    alpha[poi_cleared] = 0.0
    alpha[poi_fogged] = unvisited_alpha
    return alpha
