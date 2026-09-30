"""The headless exporter that keeps the in-game Pip-Boy fog current."""

import json

import numpy as np
import pytest
from PIL import Image

from foggymap.exporter import export_once
from foggymap.pipboy import read_fog_file

CELL = 4096
MARKER_HEADER = "worldspace,form_id,name,x,y,radius,marker_type,discovered"


@pytest.fixture
def assets(tmp_path):
    directory = tmp_path / "assets"
    directory.mkdir()
    intensity = np.zeros((64, 64), dtype=np.uint8)
    intensity[:, ::4] = 180
    manifest = {}
    for editor_id in ("Commonwealth", "NukaWorld"):
        Image.fromarray(intensity, mode="L").save(directory / f"worldmap_{editor_id}.png")
        manifest[editor_id] = {
            "editor_id": editor_id, "nw_cell": [0, 1], "se_cell": [1, 0],
            "width_px": 64, "height_px": 64, "image": f"worldmap_{editor_id}.png",
        }
    (directory / "worldspaces.json").write_text(json.dumps(manifest))
    return directory


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    return directory


def test_exports_a_fog_file_for_every_worldspace(assets, data):
    written = export_once(assets, data)

    assert sorted(p.name for p in data.glob("pipboy_*.fog")) == [
        "pipboy_Commonwealth.fog",
        "pipboy_NukaWorld.fog",
    ]
    assert len(written) == 2


def test_exported_fog_reflects_walked_ground(assets, data):
    (data / "path_Commonwealth.csv").write_text(
        "t_ms,x,y,z\n" + "".join(
            f"{i * 1000},{0.5 * CELL},{0.2 * CELL + i * 150.0},0\n" for i in range(40)
        )
    )

    export_once(assets, data)

    _, _, pixels = read_fog_file(data / "pipboy_Commonwealth.fog")
    assert pixels.min() == 0, "walked ground must export as clear"
    assert pixels.max() > 0, "unwalked ground must export as fogged"


def test_a_worldspace_with_no_data_is_still_exported_as_fully_fogged(assets, data):
    """Otherwise the Pip-Boy would show no fog at all somewhere you have never been."""
    export_once(assets, data)

    _, _, pixels = read_fog_file(data / "pipboy_NukaWorld.fog")
    assert (pixels > 0).all()


def test_export_survives_a_missing_asset(assets, data):
    """One broken worldspace must not stop the others being exported."""
    (assets / "worldmap_NukaWorld.png").unlink()

    written = export_once(assets, data)

    assert any("Commonwealth" in str(p) for p in written)
    assert (data / "pipboy_Commonwealth.fog").exists()
