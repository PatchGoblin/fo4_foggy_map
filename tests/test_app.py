"""The window's wiring, exercised with Qt's offscreen platform (no display needed)."""

import json
import os

import numpy as np
import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from foggymap.app import Window  # noqa: E402

CELL = 4096
MARKER_HEADER = "worldspace,form_id,name,x,y,radius,marker_type,discovered"


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def assets(tmp_path):
    intensity = np.zeros((64, 64), dtype=np.uint8)
    intensity[:, ::4] = 180
    for editor_id in ("Alpha", "Beta"):
        Image.fromarray(intensity, mode="L").save(tmp_path / f"worldmap_{editor_id}.png")
    (tmp_path / "worldspaces.json").write_text(
        json.dumps({
            editor_id: {
                "editor_id": editor_id, "nw_cell": [0, 1], "se_cell": [1, 0],
                "width_px": 64, "height_px": 64, "image": f"worldmap_{editor_id}.png",
            }
            for editor_id in ("Alpha", "Beta")
        })
    )
    return tmp_path


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "markers.csv").write_text(
        f"{MARKER_HEADER}\n"
        f"Alpha,0x1,Red Rocket,{0.5 * CELL},{0.5 * CELL},,1,1\n"
        f"Alpha,0x2,Gorski Cabin,{1.5 * CELL},{1.5 * CELL},,1,0\n"
    )
    (directory / "path_Alpha.csv").write_text("t_ms,x,y,z\n0,2000,2000,0\n1000,2200,2100,0\n")
    return directory


@pytest.fixture
def window(qt_app, assets, data):
    window = Window(str(assets), str(data), ["Alpha", "Beta"])
    _drain(qt_app, window)
    return window


def _drain(qt_app, window, seconds=15.0):
    """Renders happen on a worker thread; spin the event loop until one lands."""
    import time

    window.fog = None
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if window.fog is not None:
            return
        if window.last_error:
            raise AssertionError(f"render failed: {window.last_error}")
        time.sleep(0.01)
    raise AssertionError("no render completed within the deadline")


def test_the_map_renders_into_the_scene(window):
    assert not window.map_item.pixmap().isNull()
    assert window.scene.sceneRect().width() == 64


def test_only_discovered_pois_get_markers(window):
    """Marking undiscovered POIs would give away places the player has not found."""
    labels = [item.text() for item in window.label_items]

    assert "Red Rocket" in labels
    assert "Gorski Cabin" not in labels


def test_the_player_gets_a_marker_at_the_latest_sample(window):
    assert window.player_item is not None

    grid = window.worldspace().grid
    expected_col, expected_row = grid.to_px(2200.0, 2100.0)
    assert window.player_item.pos().x() == pytest.approx(expected_col)
    assert window.player_item.pos().y() == pytest.approx(expected_row)


def test_no_spoilers_hides_the_undiscovered_poi_readout(window, qt_app):
    window.spoiler_free.setChecked(True)
    _drain(qt_app, window)

    assert window.settings.show_missed_pois is False


def test_names_are_hidden_when_zoomed_out(window):
    window.view.resetTransform()
    window.view.scale(0.2, 0.2)
    window.update_label_visibility()

    assert all(not item.isVisible() for item in window.label_items)


def test_names_appear_when_zoomed_in(window):
    window.view.resetTransform()
    window.view.scale(4.0, 4.0)
    window.update_label_visibility()

    assert all(item.isVisible() for item in window.label_items)


def test_polling_does_not_re_render_when_nothing_changed(window):
    before = window.fingerprint

    window.poll()

    assert window.fingerprint == before, "an unchanged directory must not trigger work"


def test_polling_re_renders_after_new_samples(window, qt_app):
    with (window.data_dir and open(os.path.join(window.data_dir, "path_Alpha.csv"), "a")) as f:
        f.write("2000,2400,2200,0\n")

    window.poll()
    _drain(qt_app, window)

    assert window.fog.sample_count == 3


def test_switching_worldspace_reloads(window, qt_app):
    window.chooser.setCurrentText("Beta")
    _drain(qt_app, window)

    assert window.editor_id == "Beta"
    assert window.fog is not None
