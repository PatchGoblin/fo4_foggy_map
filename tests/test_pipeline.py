"""End-to-end rendering of one worldspace from recorded data files."""

import json

import numpy as np
import pytest
from PIL import Image

from foggymap.pipeline import Settings, load_worldspace, render

CELL = 4096
MARKER_HEADER = "worldspace,form_id,name,x,y,radius,marker_type,discovered"


def make_assets(directory, cells=4, px=128):
    """A square worldspace whose west half is drawn land and east half is blank water."""
    intensity = np.zeros((px, px), dtype=np.uint8)
    intensity[:, : px // 2 : 4] = 180
    Image.fromarray(intensity, mode="L").save(directory / "worldmap_Test.png")
    (directory / "worldspaces.json").write_text(
        json.dumps({
            "Test": {
                "editor_id": "Test",
                "nw_cell": [0, cells - 1],
                "se_cell": [cells - 1, 0],
                "width_px": px,
                "height_px": px,
                "image": "worldmap_Test.png",
            }
        })
    )
    return directory


@pytest.fixture
def assets(tmp_path):
    """A tiny 4x4 cell worldspace, smaller than one sight radius across."""
    return make_assets(tmp_path)


@pytest.fixture
def wide_assets(tmp_path):
    """A 16x16 cell worldspace, big enough for coverage not to saturate."""
    return make_assets(tmp_path, cells=16, px=512)


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    return directory


def write_path(data, samples):
    rows = "\n".join(f"{t},{x},{y},0.0" for t, x, y in samples)
    (data / "path_Test.csv").write_text(f"t_ms,x,y,z\n{rows}\n")


def test_an_empty_data_directory_renders_a_fully_fogged_map(assets, data):
    worldspace = load_worldspace(assets, "Test")

    fog = render(worldspace, str(data))

    assert fog.rgb.shape == (128, 128, 3)
    assert fog.sample_count == 0
    assert fog.percent_area_explored == 0.0
    assert fog.land_tiles_swept == 0


def test_walking_raises_the_explored_percentage(assets, data):
    worldspace = load_worldspace(assets, "Test")
    before = render(worldspace, str(data)).percent_area_explored

    write_path(data, [(i * 1000, 0.5 * CELL, 0.2 * CELL + i * 200.0) for i in range(60)])
    after = render(worldspace, str(data)).percent_area_explored

    assert after > before
    assert 0.0 < after < 100.0


def test_water_tiles_are_left_out_of_the_land_count(assets, data):
    """Half the test map is blank water, so only half the tiles should be countable."""
    worldspace = load_worldspace(assets, "Test")

    fog = render(worldspace, str(data))

    assert fog.land_tile_count == 8, "4x4 tiles, west half drawn"


def test_an_undiscovered_poi_darkens_swept_ground_in_the_final_image(assets, data):
    """Proves the POI layer actually reaches the pixels, not just the counts."""
    write_path(data, [(i * 1000, 0.5 * CELL + i * 150.0, 1.5 * CELL) for i in range(60)])
    (data / "markers.csv").write_text(
        f"{MARKER_HEADER}\nTest,0x2,Missed,{1.5 * CELL},{1.5 * CELL},,1,0\n"
    )
    worldspace = load_worldspace(assets, "Test")

    with_poi = render(worldspace, str(data))
    without_poi = render(worldspace, str(data), Settings(poi_fog_radius=0.0, poi_min_px=0))

    col, row = worldspace.grid.to_px(1.5 * CELL, 1.5 * CELL)
    at_poi = with_poi.rgb[int(row), int(col)].astype(int).sum()
    same_spot_without = without_poi.rgb[int(row), int(col)].astype(int).sum()
    assert at_poi < same_spot_without, "the missed POI should re-fog its own disc"


def test_no_poi_is_outlined_in_the_rendered_fog(assets, data):
    """Outlines on undiscovered POIs gave away locations the player had not found yet.
    POIs are drawn as scene markers by the viewer instead, so the fog carries no rings."""
    (data / "markers.csv").write_text(
        f"{MARKER_HEADER}\n"
        f"Test,0x1,Found,{1.0 * CELL},{3.0 * CELL},,1,1\n"
        f"Test,0x2,Missed,{1.0 * CELL},{1.0 * CELL},,1,0\n"
    )
    worldspace = load_worldspace(assets, "Test")

    rgb = render(worldspace, str(data)).rgb
    colours = {tuple(int(v) for v in c) for c in rgb.reshape(-1, 3)}

    assert not any(max(c) > 200 and c[2] < 120 for c in colours), (
        f"found a warm highlight colour in the fog: {colours}"
    )


def test_hiding_missed_pois_stops_them_darkening_the_map(assets, data):
    """No-spoilers mode: an undiscovered POI must leave no trace of where it is."""
    write_path(data, [(i * 1000, 0.5 * CELL + i * 150.0, 1.5 * CELL) for i in range(60)])
    (data / "markers.csv").write_text(
        f"{MARKER_HEADER}\nTest,0x2,Missed,{1.5 * CELL},{1.5 * CELL},,1,0\n"
    )
    worldspace = load_worldspace(assets, "Test")
    col, row = worldspace.grid.to_px(1.5 * CELL, 1.5 * CELL)

    shown = render(worldspace, str(data), Settings(show_missed_pois=True))
    hidden = render(worldspace, str(data), Settings(show_missed_pois=False))

    at_shown = shown.rgb[int(row), int(col)].astype(int).sum()
    at_hidden = hidden.rgb[int(row), int(col)].astype(int).sum()
    assert at_hidden > at_shown, "hiding the POI should leave the swept ground clear"


def test_the_fog_alpha_mask_is_exposed_for_other_renderers(assets, data):
    """The Pip-Boy exporter needs the raw opacity, not the tinted RGB."""
    worldspace = load_worldspace(assets, "Test")

    fog = render(worldspace, str(data))

    assert fog.alpha.shape == worldspace.intensity.shape
    assert fog.alpha.max() > 0.0, "an unexplored map should be fogged"
    assert fog.alpha.max() <= 1.0


def test_the_latest_sample_is_the_player_position(assets, data):
    write_path(data, [(0, 1000.0, 2000.0), (1000, 1100.0, 2100.0)])
    worldspace = load_worldspace(assets, "Test")

    fog = render(worldspace, str(data))

    assert fog.player_position == (1100.0, 2100.0)


def test_player_position_is_unknown_without_samples(assets, data):
    worldspace = load_worldspace(assets, "Test")

    assert render(worldspace, str(data)).player_position is None


def test_smoothing_is_applied_so_parallel_passes_read_as_one_blob(wide_assets, data):
    """Two passes just too far apart must not leave a permanent pinstripe."""
    radius = Settings().area_radius
    gap = 400.0
    south = 3 * CELL
    north = south + 2 * radius + gap
    samples = [(i * 1000, 2 * CELL + i * 150.0, south) for i in range(60)]
    samples += [(60_000 + i * 1000, 2 * CELL + i * 150.0, north) for i in range(60)]
    write_path(data, samples)
    worldspace = load_worldspace(wide_assets, "Test")

    smoothed = render(worldspace, str(data), Settings(close_units=gap))
    unsmoothed = render(worldspace, str(data), Settings(close_units=0.0))

    assert smoothed.percent_area_explored > unsmoothed.percent_area_explored


def test_poi_counts_come_from_the_marker_file(assets, data):
    (data / "markers.csv").write_text(
        f"{MARKER_HEADER}\n"
        "Test,0x1,Found,2048,2048,,1,1\n"
        "Test,0x2,Missed,6144,6144,,1,0\n"
        "Other,0x3,Elsewhere,0,0,,1,1\n"
    )
    worldspace = load_worldspace(assets, "Test")

    fog = render(worldspace, str(data))

    assert len(fog.pois) == 2, "the other worldspace's marker is excluded"
    assert fog.pois_discovered == 1
