"""Building the base map images and worldspace manifest from installed game files."""

import json
import os

import numpy
import pytest
from PIL import Image

from foggymap.assets import build_assets
from foggymap.grid import Grid

from game_paths import data_dir

DATA = data_dir()

needs_game = pytest.mark.skipif(
    not os.path.exists(os.path.join(DATA, "Fallout4.esm")),
    reason="Fallout 4 not installed at the expected path",
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("assets")
    return build_assets(DATA, out), out


@needs_game
def test_covers_the_commonwealth_and_both_dlc_worldspaces(built):
    manifest, _ = built

    assert set(manifest) == {"Commonwealth", "DLC03FarHarbor", "NukaWorld"}


@needs_game
def test_records_commonwealth_map_bounds_and_writes_its_image(built):
    manifest, out = built

    commonwealth = manifest["Commonwealth"]

    assert commonwealth["nw_cell"] == [-33, 25]
    assert commonwealth["se_cell"] == [28, -36]
    assert commonwealth["width_px"] == 2048
    assert (out / commonwealth["image"]).exists()


@needs_game
def test_manifest_feeds_the_viewer_grid_directly(built):
    """The manifest is the contract between asset prep and the viewer."""
    manifest, _ = built
    entry = manifest["Commonwealth"]

    grid = Grid.from_cells(
        nw_cell_x=entry["nw_cell"][0],
        nw_cell_y=entry["nw_cell"][1],
        se_cell_x=entry["se_cell"][0],
        se_cell_y=entry["se_cell"][1],
        width_px=entry["width_px"],
        height_px=entry["height_px"],
    )

    assert grid.units_per_px_x == 124.0


@needs_game
@pytest.mark.parametrize("editor_id", ["Commonwealth", "DLC03FarHarbor", "NukaWorld"])
def test_every_base_map_is_greyscale_with_real_detail(built, editor_id):
    """Nuka-World keeps its map in the alpha channel and leaves RGB black, so a naive
    RGB conversion silently produces a blank image."""
    manifest, out = built

    image = Image.open(out / manifest[editor_id]["image"])
    pixels = numpy.array(image)

    assert image.mode == "L", "base maps are tinted by the viewer, so store intensity only"
    assert pixels.max() > 0, "image is entirely black"
    assert pixels.std() > 10, "image has no detail, just a flat fill"


@needs_game
def test_manifest_is_written_to_disk_as_json(built):
    _, out = built

    on_disk = json.loads((out / "worldspaces.json").read_text())

    assert "Commonwealth" in on_disk
