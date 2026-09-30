"""How the fog layers combine into a single alpha mask."""

import numpy as np
import pytest

from foggymap.config import FOG_ALPHA_PARTIAL, FOG_ALPHA_UNVISITED
from foggymap.coverage import PARTIAL, SWEPT, UNVISITED
from foggymap.grid import Grid
from foggymap.markers import disc_mask
from foggymap.render import fog_alpha, tint_map

CELL = 4096
SYNTHETIC = Grid(min_x=0.0, min_y=0.0, max_x=10 * CELL, max_y=10 * CELL,
                 width_px=320, height_px=320)
TILES = (10, 10)


def alpha_at(alpha, world_x, world_y):
    """Alpha at a world position, as an approximate value (the mask is float32)."""
    col, row = SYNTHETIC.to_px(world_x, world_y)
    return pytest.approx(float(alpha[int(row), int(col)]), abs=1e-6)


def layers(tile_class=None, coverage=None, cleared=None, fogged=None):
    empty = np.zeros((SYNTHETIC.height_px, SYNTHETIC.width_px), dtype=bool)
    return fog_alpha(
        grid=SYNTHETIC,
        coverage=empty if coverage is None else coverage,
        tile_class=np.full(TILES, UNVISITED, dtype=np.int8) if tile_class is None else tile_class,
        poi_cleared=empty if cleared is None else cleared,
        poi_fogged=empty if fogged is None else fogged,
        tile_units=CELL,
    )


def test_tinting_produces_an_rgb_image_the_size_of_the_map():
    intensity = np.full((4, 6), 200, dtype=np.uint8)
    alpha = np.zeros((4, 6), dtype=np.float32)

    rgb = tint_map(intensity, alpha)

    assert rgb.shape == (4, 6, 3)
    assert rgb.dtype == np.uint8


def test_fog_lifts_the_black_background_so_it_reads_at_a_glance():
    """The Pip-Boy map is line art on black, so dimming alone is invisible: most of an
    unexplored region is background, not lines."""
    intensity = np.zeros((1, 2), dtype=np.uint8)  # a blank patch of map
    alpha = np.array([[0.0, FOG_ALPHA_UNVISITED]], dtype=np.float32)

    rgb = tint_map(intensity, alpha)

    assert rgb[0, 0].astype(int).sum() == 0, "explored blank map stays black"
    assert rgb[0, 1].astype(int).sum() >= 30, "fogged blank map must show a visible wash"


def test_fogged_ground_is_dimmer_than_clear_ground_but_still_visible():
    intensity = np.full((1, 2), 220, dtype=np.uint8)
    alpha = np.array([[0.0, FOG_ALPHA_UNVISITED]], dtype=np.float32)

    rgb = tint_map(intensity, alpha)

    clear, fogged = rgb[0, 0].astype(int).sum(), rgb[0, 1].astype(int).sum()
    assert fogged < clear, "fog must dim the map"
    assert fogged > 0, "fog must never hide the map completely"


def test_never_visited_ground_is_fogged_but_not_opaque():
    alpha = layers()

    assert alpha_at(alpha, 5 * CELL, 5 * CELL) == FOG_ALPHA_UNVISITED
    assert FOG_ALPHA_UNVISITED < 1.0, "fog must never fully hide the map"


def test_a_swept_tile_is_clear():
    tile_class = np.full(TILES, UNVISITED, dtype=np.int8)
    tile_class[4, 5] = SWEPT

    alpha = layers(tile_class=tile_class)

    assert alpha_at(alpha, 5.5 * CELL, 5.5 * CELL) == 0.0


def test_a_partial_tile_gets_a_middle_tint():
    tile_class = np.full(TILES, UNVISITED, dtype=np.int8)
    tile_class[4, 5] = PARTIAL

    alpha = layers(tile_class=tile_class)

    assert alpha_at(alpha, 5.5 * CELL, 5.5 * CELL) == FOG_ALPHA_PARTIAL


def test_the_coverage_blob_shows_through_a_partial_tile():
    """Inside a partial tile you still see the honest shape of what was walked."""
    tile_class = np.full(TILES, PARTIAL, dtype=np.int8)
    coverage = disc_mask(SYNTHETIC, [(5 * CELL, 5 * CELL)], radius_units=1000.0)

    alpha = layers(tile_class=tile_class, coverage=coverage)

    assert alpha_at(alpha, 5 * CELL, 5 * CELL) == 0.0, "inside the blob"
    assert alpha_at(alpha, 5.8 * CELL, 5 * CELL) == FOG_ALPHA_PARTIAL, "outside the blob"


def test_an_undiscovered_poi_stays_dark_inside_fully_swept_ground():
    """The whole point of the POI layer: a location you walked past but never found."""
    tile_class = np.full(TILES, SWEPT, dtype=np.int8)
    coverage = np.ones((SYNTHETIC.height_px, SYNTHETIC.width_px), dtype=bool)
    fogged = disc_mask(SYNTHETIC, [(5 * CELL, 5 * CELL)], radius_units=2048.0)

    alpha = layers(tile_class=tile_class, coverage=coverage, fogged=fogged)

    assert alpha_at(alpha, 5 * CELL, 5 * CELL) == FOG_ALPHA_UNVISITED, "missed POI"
    assert alpha_at(alpha, 8 * CELL, 8 * CELL) == 0.0, "swept ground around it"


def test_a_discovered_poi_is_clear_inside_never_visited_ground():
    """Progress made before FoggyMap existed: found the place, swept nothing around it."""
    cleared = disc_mask(SYNTHETIC, [(5 * CELL, 5 * CELL)], radius_units=2048.0)

    alpha = layers(cleared=cleared)

    assert alpha_at(alpha, 5 * CELL, 5 * CELL) == 0.0, "the POI itself"
    assert alpha_at(alpha, 8 * CELL, 8 * CELL) == FOG_ALPHA_UNVISITED, "ground around it"

