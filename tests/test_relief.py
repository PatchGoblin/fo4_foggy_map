"""Decoding the game's terrain heights and drawing our own relief map from them."""

import struct

import numpy as np

from foggymap.relief import decode_vhgt, render_relief


def _vhgt(offset: float, deltas: np.ndarray) -> bytes:
    """A VHGT subrecord body: base offset, 33x33 signed deltas, three unused bytes."""
    return struct.pack("<f", offset) + deltas.astype(np.int8).tobytes() + b"\x00" * 3


def test_a_flat_cell_is_its_offset_times_eight():
    deltas = np.zeros((33, 33))
    deltas[0, 0] = 1

    heights = decode_vhgt(_vhgt(10.0, deltas))

    assert heights.shape == (33, 33)
    assert np.all(heights == (10 + 1) * 8)


def test_the_first_column_steps_between_rows_and_the_rest_along_them():
    deltas = np.zeros((33, 33))
    deltas[:, 0] = 1  # each row starts one higher than the last
    deltas[0, 1:] = 2  # and the southern row climbs eastward

    heights = decode_vhgt(_vhgt(0.0, deltas))

    south = heights[-1]
    assert list(south[:4]) == [8, 24, 40, 56]
    assert heights[0, 0] == 33 * 8


def test_rows_come_out_north_first_like_an_image():
    """The game stores rows south to north; images run north to south."""
    deltas = np.zeros((33, 33))
    deltas[:, 0] = 1

    heights = decode_vhgt(_vhgt(0.0, deltas))

    assert heights[0, 0] > heights[-1, 0]


def _slope(rows=40, cols=40, rise_east=0.0, rise_south=0.0, base=1000.0):
    r, c = np.mgrid[0:rows, 0:cols].astype(np.float32)
    return base + c * rise_east + r * rise_south


def test_water_and_land_are_coloured_differently():
    heights = _slope()
    water = np.full_like(heights, 500.0)
    water[:, 20:] = 2000.0  # east half is under water

    rgb = render_relief(heights, water, units_per_sample=128.0)

    assert rgb.shape == (40, 40, 3) and rgb.dtype == np.uint8
    land, sea = rgb[20, 5].astype(int), rgb[20, 35].astype(int)
    assert sea[2] > sea[0], "water is blue-leaning"
    assert land[1] > land[2], "land is green-leaning"
    assert land.sum() > sea.sum(), "land reads lighter than water"


def test_slopes_facing_the_north_west_light_are_brighter():
    flat = np.full((40, 40), -1e6, dtype=np.float32)
    facing_light = render_relief(_slope(rise_east=60, rise_south=60), flat, 128.0)
    facing_away = render_relief(_slope(rise_east=-60, rise_south=-60), flat, 128.0)

    assert facing_light[20, 20].sum() > facing_away[20, 20].sum()


def test_deep_water_is_darker_than_shallows():
    heights = np.full((40, 40), 0.0, dtype=np.float32)
    heights[:, 20:] = -3000.0
    water = np.full_like(heights, 100.0)

    rgb = render_relief(heights, water, 128.0)

    assert rgb[20, 5].sum() > rgb[20, 35].sum()
