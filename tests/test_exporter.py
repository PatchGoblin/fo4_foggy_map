"""The headless exporter that keeps the in-game Pip-Boy fog current."""

import inspect
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from foggymap.exporter import export_changed, export_once, watch
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


def _walk(data, editor_id):
    (data / f"path_{editor_id}.csv").write_text(
        "t_ms,x,y,z\n" + "".join(
            f"{i * 1000},{0.5 * CELL},{0.2 * CELL + i * 150.0},0\n" for i in range(40)
        )
    )


def test_export_changed_exports_everything_the_first_time(assets, data):
    seen = {}

    written = export_changed(assets, data, seen)

    assert sorted(Path(p).name for p in written) == [
        "pipboy_Commonwealth.fog",
        "pipboy_NukaWorld.fog",
    ]


def test_export_changed_does_nothing_when_nothing_changed(assets, data):
    seen = {}
    export_changed(assets, data, seen)

    assert export_changed(assets, data, seen) == []


def test_a_new_path_sample_re_exports_only_its_own_worldspace(assets, data):
    """Re-rendering every map on every step is what made the fog slow to catch up."""
    seen = {}
    export_changed(assets, data, seen)

    _walk(data, "Commonwealth")
    written = export_changed(assets, data, seen)

    assert [Path(p).name for p in written] == ["pipboy_Commonwealth.fog"]


def test_new_markers_re_export_every_worldspace(assets, data):
    """markers.csv holds every worldspace's markers, so any of them may have changed."""
    seen = {}
    export_changed(assets, data, seen)

    (data / "markers.csv").write_text(
        MARKER_HEADER + "\nNukaWorld,0x00000001,\"Somewhere\",100.0,100.0,,1,1\n"
    )
    written = export_changed(assets, data, seen)

    assert len(written) == 2


def test_the_companion_polls_at_least_every_second():
    """Polling is a few stat calls; a slow poll only adds latency to the in-game fog."""
    default = inspect.signature(watch).parameters["interval"].default
    assert default <= 1.0


class _Stop(Exception):
    pass


def test_watch_runs_the_tick_hook_on_every_pass_after_exporting(assets, data):
    """The publisher rides the watch loop, after the fog files are current."""
    events = []

    def on_tick():
        events.append(("tick", (data / "pipboy_Commonwealth.fog").exists()))

    def sleep(_):
        if len(events) == 3:
            raise _Stop
        events.append(("sleep", None))

    with pytest.raises(_Stop):
        watch(assets, data, on_tick=on_tick, sleep=sleep)

    assert events[:3] == [("tick", True), ("sleep", None), ("tick", True)]
