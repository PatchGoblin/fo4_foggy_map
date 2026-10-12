"""Our own relief map, drawn from the game's terrain heights.

The published site needs a recognisable map without shipping Bethesda's map art. The
terrain itself does the job: hill shading, height tint and the water line give the
coast, rivers and lakes their real shapes, so the Commonwealth reads as itself.
"""

from __future__ import annotations

import struct

import numpy as np

# The page's palette: sage lowland lifting to pale upland, slate water darkening with depth.
LOWLAND = np.array([0x76, 0x83, 0x6A], dtype=np.float32)
UPLAND = np.array([0xB4, 0xB3, 0x98], dtype=np.float32)
SHALLOWS = np.array([0x2C, 0x3E, 0x4A], dtype=np.float32)
DEEP = np.array([0x1F, 0x2B, 0x33], dtype=np.float32)

# How far below the surface water reaches its darkest, in world units.
FULL_DEPTH_UNITS = 2500.0

# Exaggerates slopes for shading; the game's hills are gentle at map scale.
RELIEF_EXAGGERATION = 2.0


def decode_vhgt(body: bytes) -> np.ndarray:
    """A LAND record's VHGT as 33x33 heights in world units, north row first.

    The game stores a base offset and then one signed delta per vertex: the first
    column steps from row to row, and the rest step along each row. Units are eighths.
    Rows run south to north in the record, so they are flipped to read like an image.
    """
    (offset,) = struct.unpack_from("<f", body)
    deltas = np.frombuffer(body, dtype=np.int8, count=33 * 33, offset=4)
    grid = deltas.reshape(33, 33).astype(np.float32)
    grid[:, 0] = np.cumsum(grid[:, 0])
    heights = (np.cumsum(grid, axis=1) + offset) * 8.0
    return heights[::-1]


def render_relief(heights: np.ndarray, water: np.ndarray, units_per_sample: float) -> np.ndarray:
    """RGB relief for a height grid and the water surface over each sample."""
    heights = heights.astype(np.float32)
    shade = _hillshade(heights, units_per_sample)
    under = heights < water

    land_heights = heights[~under]
    if land_heights.size:
        low, high = np.percentile(land_heights, [2, 98])
    else:
        low, high = 0.0, 1.0
    lift = np.clip((heights - low) / max(high - low, 1.0), 0.0, 1.0)[..., None]
    land = (LOWLAND * (1 - lift) + UPLAND * lift) * (0.45 + 0.75 * shade[..., None])

    depth = np.clip((water - heights) / FULL_DEPTH_UNITS, 0.0, 1.0)[..., None]
    sea = SHALLOWS * (1 - depth) + DEEP * depth

    return np.clip(np.where(under[..., None], sea, land), 0, 255).astype(np.uint8)


def _hillshade(heights: np.ndarray, units_per_sample: float) -> np.ndarray:
    """Brightness 0..1 from a mainly north-west light, softened by two others so no
    slope falls to black."""
    rise_south, rise_east = np.gradient(heights, units_per_sample)
    slope = np.arctan(RELIEF_EXAGGERATION * np.hypot(rise_east, rise_south))
    # Aspect as the compass direction the slope faces; rows run south, so north is -rows.
    aspect = np.arctan2(-rise_east, rise_south)

    def lit(azimuth_deg: float, altitude_deg: float = 40.0) -> np.ndarray:
        azimuth, altitude = np.radians(azimuth_deg), np.radians(altitude_deg)
        return np.clip(np.sin(altitude) * np.cos(slope)
                       + np.cos(altitude) * np.sin(slope) * np.cos(azimuth - aspect), 0.0, 1.0)

    return 0.6 * lit(315) + 0.25 * lit(270) + 0.15 * lit(0)
