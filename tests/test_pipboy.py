"""Exporting the fog for the in-game Pip-Boy overlay."""

import numpy as np
import pytest

from foggymap.config import FOG_ALPHA_PARTIAL, FOG_ALPHA_UNVISITED
from foggymap.pipboy import export_for_pipboy, read_fog_file, write_fog_file


def strip(*alphas):
    return np.array([list(alphas)], dtype=np.float32)


def test_explored_ground_exports_as_zero():
    """Zero means the overlay draws nothing there, leaving the map art untouched."""
    opacity = fog_opacity(strip(0.0))

    assert opacity[0, 0] == 0


def test_unexplored_ground_exports_proportional_to_its_opacity():
    opacity = fog_opacity(strip(FOG_ALPHA_UNVISITED))

    assert opacity[0, 0] == round(FOG_ALPHA_UNVISITED * 255)


def test_partial_ground_sits_between_explored_and_unexplored():
    opacity = fog_opacity(strip(0.0, FOG_ALPHA_PARTIAL, FOG_ALPHA_UNVISITED))

    assert opacity[0, 0] < opacity[0, 1] < opacity[0, 2]


def test_the_map_art_is_not_baked_in():
    """The overlay sits on top of the real map, so mixing the art in would double it up
    and, worse, make explored ground non-zero wherever a road happens to run."""
    alpha = strip(0.0, 0.0)
    bright_map = np.array([[250, 250]], dtype=np.uint8)

    opacity = fog_opacity(alpha, intensity=bright_map)

    assert (opacity == 0).all(), "a road through explored ground must still export as clear"


def test_opacity_spans_the_full_byte_range_for_quantising():
    """The plugin quantises into levels across 0-255, so a full-opacity cell must reach
    the top of the range rather than being squashed into the lowest level."""
    opacity = fog_opacity(strip(1.0))

    assert opacity[0, 0] == 255


def fog_opacity(alpha, intensity=None):
    """Runs the export and reads back what the plugin would load."""
    from types import SimpleNamespace
    import tempfile
    from pathlib import Path

    shape = alpha.shape
    worldspace = SimpleNamespace(
        editor_id="Test",
        grid=None,
        intensity=np.zeros(shape, dtype=np.uint8) if intensity is None else intensity,
    )
    fog = SimpleNamespace(alpha=alpha)
    with tempfile.TemporaryDirectory() as directory:
        export_for_pipboy(worldspace, fog, directory)
        _, _, pixels = read_fog_file(Path(directory) / "pipboy_Test.fog")
    return pixels


def test_export_names_the_file_for_the_worldspace(tmp_path):
    """Far Harbor and Nuka-World have their own maps, so fog is per worldspace."""
    from types import SimpleNamespace

    worldspace = SimpleNamespace(
        editor_id="NukaWorld", grid=None, intensity=np.zeros((8, 8), dtype=np.uint8)
    )
    fog = SimpleNamespace(alpha=np.zeros((8, 8), dtype=np.float32))

    export_for_pipboy(worldspace, fog, tmp_path)

    width, height, _ = read_fog_file(tmp_path / "pipboy_NukaWorld.fog")
    assert (width, height) == (8, 8)


def test_fog_file_round_trips(tmp_path):
    image = np.arange(6, dtype=np.uint8).reshape(2, 3)
    path = tmp_path / "pipboy_Test.fog"

    write_fog_file(path, image)

    width, height, pixels = read_fog_file(path)
    assert (width, height) == (3, 2)
    assert np.array_equal(pixels, image)


def test_writing_is_atomic_so_the_plugin_never_sees_half_a_frame(tmp_path):
    path = tmp_path / "pipboy_Test.fog"
    write_fog_file(path, np.zeros((4, 4), dtype=np.uint8))

    write_fog_file(path, np.full((4, 4), 9, dtype=np.uint8))

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name]
    assert leftovers == [], f"temporary files left behind: {leftovers}"
    assert read_fog_file(path)[2][0, 0] == 9


def test_reading_a_foreign_file_is_rejected(tmp_path):
    path = tmp_path / "pipboy_Test.fog"
    path.write_bytes(b"NOPE" + b"\x00" * 16)

    with pytest.raises(ValueError):
        read_fog_file(path)
