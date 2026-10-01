"""Reading worldspace map bounds out of the shipped ESM files."""

import os

import pytest

from foggymap.fo4_esm import read_worldspace_map_data

from game_paths import data_dir

DATA = data_dir()
FALLOUT4_ESM = os.path.join(DATA, "Fallout4.esm")

needs_game = pytest.mark.skipif(
    not os.path.exists(FALLOUT4_ESM), reason="Fallout 4 not installed at the expected path"
)


@needs_game
def test_reads_commonwealth_map_bounds():
    """Ground truth read independently from the MNAM subrecord of WRLD 0x0000003C."""
    worldspaces = read_worldspace_map_data(FALLOUT4_ESM)

    commonwealth = worldspaces["Commonwealth"]

    assert (commonwealth.nw_cell_x, commonwealth.nw_cell_y) == (-33, 25)
    assert (commonwealth.se_cell_x, commonwealth.se_cell_y) == (28, -36)
