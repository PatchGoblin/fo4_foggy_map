"""The text the window puts on screen."""

import json

import numpy as np
import pytest
from PIL import Image

from foggymap.pipeline import Settings, load_worldspace, render
from foggymap.readout import point_description, status_line

CELL = 4096
MARKER_HEADER = "worldspace,form_id,name,x,y,radius,marker_type,discovered"


@pytest.fixture
def worldspace(tmp_path):
    intensity = np.zeros((128, 128), dtype=np.uint8)
    intensity[:, ::4] = 180
    Image.fromarray(intensity, mode="L").save(tmp_path / "worldmap_Test.png")
    (tmp_path / "worldspaces.json").write_text(
        json.dumps({
            "Test": {
                "editor_id": "Test", "nw_cell": [0, 3], "se_cell": [3, 0],
                "width_px": 128, "height_px": 128, "image": "worldmap_Test.png",
            }
        })
    )
    return load_worldspace(tmp_path, "Test")


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "markers.csv").write_text(
        f"{MARKER_HEADER}\n"
        f"Test,0x1,Red Rocket,{0.5 * CELL},{0.5 * CELL},,1,1\n"
        f"Test,0x2,Gorski Cabin,{3.5 * CELL},{3.5 * CELL},,1,0\n"
    )
    return directory


def test_status_line_reports_both_progress_measures(worldspace, data):
    fog = render(worldspace, str(data))

    line = status_line("Commonwealth", fog, Settings())

    assert "Commonwealth" in line
    assert "POIs 1/2" in line
    assert "%" in line, "area progress is shown as a percentage"
    assert "70 m" in line, "the sight radius is shown in metres, not game units"


def test_point_description_gives_world_position_and_cell(worldspace, data):
    fog = render(worldspace, str(data))
    col, row = worldspace.grid.to_px(1.5 * CELL, 2.5 * CELL)

    text = point_description(fog, worldspace, Settings(), col, row)

    assert "6144" in text, "world x"
    assert "cell (1, 2)" in text


def test_point_description_names_the_nearest_undiscovered_poi(worldspace, data):
    fog = render(worldspace, str(data))
    col, row = worldspace.grid.to_px(3.0 * CELL, 3.0 * CELL)

    text = point_description(fog, worldspace, Settings(), col, row)

    assert "Gorski Cabin" in text
    assert "Red Rocket" not in text, "only undiscovered POIs are worth pointing at"


def test_point_description_hides_undiscovered_pois_without_spoilers(worldspace, data):
    """No-spoilers mode must not name a place the player has not found yet."""
    fog = render(worldspace, str(data))
    col, row = worldspace.grid.to_px(3.0 * CELL, 3.0 * CELL)

    text = point_description(fog, worldspace, Settings(), col, row, spoilers=False)

    assert "Gorski Cabin" not in text
    assert "nearest" not in text
    assert "cell" in text, "the rest of the readout still works"


def test_point_description_reports_the_tile_verdict(worldspace, data):
    fog = render(worldspace, str(data))
    col, row = worldspace.grid.to_px(1.5 * CELL, 2.5 * CELL)

    text = point_description(fog, worldspace, Settings(), col, row)

    assert "unvisited" in text


def test_point_description_outside_the_map_does_not_raise(worldspace, data):
    fog = render(worldspace, str(data))

    text = point_description(fog, worldspace, Settings(), -500.0, -500.0)

    assert isinstance(text, str)
