"""Turning a walked path into revealed area."""

import numpy as np
import pytest
from scipy import ndimage

from foggymap.config import area_fog_radius_units
from foggymap.coverage import (
    PARTIAL,
    SWEPT,
    UNVISITED,
    _disc,
    classify_tiles,
    coverage_mask,
    land_tile_mask,
    rasterize_path,
    tile_scores,
)
from foggymap.grid import Grid
from foggymap.paths import Sample, build_segments

CELL = 4096

# A synthetic 10x10 cell worldspace at 128 units/px -- small enough to stay fast.
SYNTHETIC = Grid(min_x=0.0, min_y=0.0, max_x=10 * CELL, max_y=10 * CELL,
                 width_px=320, height_px=320)


def walk_north(x, y_start, y_end, step=200.0):
    """Samples marching north in a straight line at constant x."""
    ys = np.arange(y_start, y_end, step)
    return [Sample(int(i * 1000), x, float(y), 0.0) for i, y in enumerate(ys)]


def test_a_straight_walk_reveals_a_band_two_radii_wide():
    radius = 4915.2
    samples = walk_north(x=5 * CELL, y_start=2 * CELL, y_end=8 * CELL)

    revealed = coverage_mask(
        rasterize_path(SYNTHETIC, samples, build_segments(samples)),
        SYNTHETIC,
        radius_units=radius,
    )

    middle_row = revealed[revealed.shape[0] // 2]
    width_units = middle_row.sum() * SYNTHETIC.units_per_px_x
    assert width_units == pytest.approx(2 * radius, abs=2 * SYNTHETIC.units_per_px_x)


def walk_east(y, x_start, x_end, step=200.0):
    """Samples marching east in a straight line at constant y."""
    xs = np.arange(x_start, x_end, step)
    return [Sample(int(i * 1000), float(x), y, 0.0) for i, x in enumerate(xs)]


def scores_for(samples, tile_units=CELL):
    revealed = coverage_mask(
        rasterize_path(SYNTHETIC, samples, build_segments(samples)),
        SYNTHETIC,
        radius_units=area_fog_radius_units(),
    )
    return tile_scores(revealed, SYNTHETIC, tile_units=tile_units)


def test_a_single_pass_clears_every_tile_it_crosses():
    """The point of a generous sight radius: reaching 100% must not need grid-walking."""
    samples = walk_east(y=5.5 * CELL, x_start=1 * CELL, x_end=9 * CELL)

    scores = scores_for(samples)

    crossed = scores[_tile_row(5.5 * CELL), 2:8]
    assert crossed.min() >= 0.85, f"a single pass left partial tiles: {crossed}"


def test_a_pass_along_a_tile_boundary_clears_both_adjoining_rows():
    """Worst case: the road follows a tile edge instead of a tile centre."""
    samples = walk_east(y=5 * CELL, x_start=1 * CELL, x_end=9 * CELL)

    scores = scores_for(samples)

    north_of_line = scores[_tile_row(5 * CELL + 1), 2:8]
    south_of_line = scores[_tile_row(5 * CELL - 1), 2:8]
    assert north_of_line.min() >= 0.85, f"north row left partial: {north_of_line}"
    assert south_of_line.min() >= 0.85, f"south row left partial: {south_of_line}"


def test_fast_travel_reveals_both_ends_but_nothing_between():
    samples = [
        Sample(0, 2 * CELL, 5 * CELL, 0.0),
        Sample(1000, 8 * CELL, 5 * CELL, 0.0),  # arrived by fast travel
        Sample(2000, 8 * CELL + 300, 5 * CELL, 0.0),
    ]

    revealed = coverage_mask(
        rasterize_path(SYNTHETIC, samples, build_segments(samples)),
        SYNTHETIC,
        radius_units=area_fog_radius_units(),
    )

    assert _revealed_at(revealed, 2 * CELL, 5 * CELL), "departure point"
    assert _revealed_at(revealed, 8 * CELL, 5 * CELL), "arrival point"
    assert not _revealed_at(revealed, 5 * CELL, 5 * CELL), "ground never travelled"


def test_closing_fills_a_narrow_stripe_missed_between_two_parallel_passes():
    """Two passes just too far apart leave a sliver; that should not read as unexplored."""
    radius = area_fog_radius_units()
    gap = 600.0
    south, north = 5 * CELL, 5 * CELL + 2 * radius + gap
    samples = walk_east(south, 1 * CELL, 9 * CELL) + walk_east(north, 1 * CELL, 9 * CELL)
    path = rasterize_path(SYNTHETIC, samples, build_segments(samples))
    middle = (south + north) / 2

    unsmoothed = coverage_mask(path, SYNTHETIC, radius_units=radius)
    smoothed = coverage_mask(path, SYNTHETIC, radius_units=radius, close_units=gap)

    assert not _revealed_at(unsmoothed, 5 * CELL, middle), "sliver should exist untreated"
    assert _revealed_at(smoothed, 5 * CELL, middle), "closing should bridge the sliver"


def test_land_tiles_exclude_the_blank_ocean():
    """Open water is drawn as flat black, and must not count as forever unexplored."""
    intensity = np.zeros((SYNTHETIC.height_px, SYNTHETIC.width_px), dtype=np.uint8)
    intensity[:, : SYNTHETIC.width_px // 2 : 7] = 200  # contour lines over the west half

    land = land_tile_mask(intensity, SYNTHETIC, tile_units=CELL)

    assert land[:, 0].all(), "west half is drawn land"
    assert not land[:, -1].any(), "east half is blank water"


def test_tiles_are_classified_into_swept_partial_and_unvisited():
    scores = np.array([[0.99, 0.85], [0.60, 0.34]])

    classes = classify_tiles(scores)

    assert classes.tolist() == [[SWEPT, SWEPT], [PARTIAL, UNVISITED]]


def _revealed_at(mask, world_x, world_y):
    col, row = SYNTHETIC.to_px(world_x, world_y)
    return bool(mask[int(row), int(col)])


def _tile_row(world_y, tile_units=CELL):
    """Row index of the tile containing ``world_y``, counting south from the north edge."""
    return int((SYNTHETIC.max_y - world_y) // tile_units)


def test_unvisited_ground_stays_hidden():
    samples = walk_north(x=5 * CELL, y_start=2 * CELL, y_end=8 * CELL)

    revealed = coverage_mask(
        rasterize_path(SYNTHETIC, samples, build_segments(samples)),
        SYNTHETIC,
        radius_units=4915.2,
    )

    far_col, far_row = SYNTHETIC.to_px(9.5 * CELL, 5 * CELL)
    assert not revealed[int(far_row), int(far_col)]


def _random_walk(seed, count=400):
    """A wandering path with fast-travel jumps, some of it beyond the map edge."""
    rng = np.random.default_rng(seed)
    position = np.array([5 * CELL, 5 * CELL])
    samples = []
    for index in range(count):
        if rng.random() < 0.02:
            position = rng.uniform(-CELL, 11 * CELL, size=2)
        else:
            position = position + rng.normal(0, 600, size=2)
        samples.append(Sample(index * 1000, float(position[0]), float(position[1]), 0.0))
    return samples


def _rasterize_reference(grid, samples, segments):
    """The original point-by-point rasterizer, kept as the oracle for the fast one."""
    raster = np.zeros((grid.height_px, grid.width_px), dtype=bool)

    def mark(col, row):
        col, row = int(col), int(row)
        if 0 <= row < raster.shape[0] and 0 <= col < raster.shape[1]:
            raster[row, col] = True

    for sample in samples:
        mark(*grid.to_px(sample.x, sample.y))
    for start, end in segments:
        col0, row0 = grid.to_px(start.x, start.y)
        col1, row1 = grid.to_px(end.x, end.y)
        steps = int(max(abs(col1 - col0), abs(row1 - row0))) + 1
        for col, row in zip(np.linspace(col0, col1, steps + 1), np.linspace(row0, row1, steps + 1)):
            mark(col, row)
    return raster


@pytest.mark.parametrize("seed", range(5))
def test_rasterize_marks_exactly_the_pixels_of_the_point_by_point_walk(seed):
    samples = _random_walk(seed)
    segments = build_segments(samples)

    np.testing.assert_array_equal(
        rasterize_path(SYNTHETIC, samples, segments),
        _rasterize_reference(SYNTHETIC, samples, segments),
    )


def test_rasterize_handles_no_samples():
    assert not rasterize_path(SYNTHETIC, [], []).any()


@pytest.mark.parametrize("seed", range(5))
def test_closing_matches_closing_the_whole_image(seed):
    """Closing is confined to the explored area for speed; it must not change the result,
    including where the explored area meets the map edge."""
    samples = _random_walk(seed)
    raster = rasterize_path(SYNTHETIC, samples, build_segments(samples))
    radius, close = 1500.0, CELL / 4

    distance = ndimage.distance_transform_edt(
        ~raster, sampling=(SYNTHETIC.units_per_px_y, SYNTHETIC.units_per_px_x)
    )
    expected = ndimage.binary_closing(distance <= radius, _disc(SYNTHETIC, close))

    np.testing.assert_array_equal(
        coverage_mask(raster, SYNTHETIC, radius_units=radius, close_units=close), expected
    )
