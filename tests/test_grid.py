"""World-unit to map-pixel transform for a single worldspace."""

import pytest

from foggymap.grid import Grid

CELL = 4096

# Commonwealth, from WRLD 0x0000003C MNAM: NW cell (-33, 25), SE cell (28, -36),
# drawn onto the 2048x2048 WorldMap_d texture.
COMMONWEALTH = dict(
    nw_cell_x=-33, nw_cell_y=25, se_cell_x=28, se_cell_y=-36, width_px=2048, height_px=2048
)


def test_bounds_cover_whole_cells_inclusive():
    grid = Grid.from_cells(**COMMONWEALTH)

    assert grid.min_x == -33 * CELL
    assert grid.max_x == 29 * CELL, "east edge is the far side of cell 28"
    assert grid.min_y == -36 * CELL
    assert grid.max_y == 26 * CELL, "north edge is the far side of cell 25"


def test_commonwealth_is_62_cells_square_at_124_units_per_pixel():
    grid = Grid.from_cells(**COMMONWEALTH)

    assert grid.width_units == 62 * CELL
    assert grid.height_units == 62 * CELL
    assert grid.units_per_px_x == 124.0
    assert grid.units_per_px_y == 124.0


def test_north_west_corner_maps_to_the_top_left_pixel():
    grid = Grid.from_cells(**COMMONWEALTH)

    assert grid.to_px(grid.min_x, grid.max_y) == (0.0, 0.0)


def test_south_east_corner_maps_to_the_bottom_right_pixel():
    grid = Grid.from_cells(**COMMONWEALTH)

    assert grid.to_px(grid.max_x, grid.min_y) == (2048.0, 2048.0)


def test_moving_north_moves_up_the_image():
    """World Y is north-positive but image rows count downward from the north edge."""
    grid = Grid.from_cells(**COMMONWEALTH)

    col_south, row_south = grid.to_px(0.0, 0.0)
    col_north, row_north = grid.to_px(0.0, 10 * CELL)

    assert row_north < row_south
    assert col_north == col_south


def test_pixel_to_world_round_trips():
    grid = Grid.from_cells(**COMMONWEALTH)
    world = (-12345.0, 54321.0)

    assert grid.from_px(*grid.to_px(*world)) == pytest.approx(world)
