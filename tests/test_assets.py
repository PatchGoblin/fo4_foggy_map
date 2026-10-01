"""Building assets from whatever game files the player actually has.

The real readers are swapped for fakes so these run without the game installed;
test_build_assets.py covers the real files.
"""

import io
import json

import numpy as np
import pytest
from PIL import Image

from foggymap import assets
from foggymap.assets import AssetsUnavailable, MapSource, build_assets
from foggymap.fo4_esm import WorldspaceMapData

SOURCES = (
    MapSource("Commonwealth", "Fallout4.esm", "Fallout4 - Textures6.ba2", "cw.dds"),
    MapSource("NukaWorld", "DLCNukaWorld.esm", "DLCNukaWorld - Textures.ba2", "nw.dds"),
)


def _png_bytes() -> bytes:
    pixels = np.zeros((8, 8, 3), dtype=np.uint8)
    pixels[:, ::2] = 200
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def fake_readers(monkeypatch):
    """Map data and textures for any file that exists; failures injectable by name."""
    failing: set[str] = set()

    def read_map_data(esm_path):
        editor_id = {"Fallout4.esm": "Commonwealth", "DLCNukaWorld.esm": "NukaWorld"}[
            esm_path.replace("\\", "/").rsplit("/", 1)[-1]
        ]
        return {editor_id: WorldspaceMapData(editor_id, 0x3C, -1, 1, 1, -1)}

    def extract(archive_path, texture):
        if texture in failing:
            raise ValueError(f"corrupt {texture}")
        return _png_bytes()

    monkeypatch.setattr(assets, "read_worldspace_map_data", read_map_data)
    monkeypatch.setattr(assets, "extract_texture", extract)
    return failing


def _install(data_dir, *names):
    data_dir.mkdir(exist_ok=True)
    for name in names:
        (data_dir / name).write_bytes(b"")


def test_builds_every_worldspace_the_game_has(tmp_path, fake_readers):
    game = tmp_path / "Data"
    _install(game, "Fallout4.esm", "Fallout4 - Textures6.ba2",
             "DLCNukaWorld.esm", "DLCNukaWorld - Textures.ba2")

    manifest = build_assets(str(game), tmp_path / "assets", SOURCES)

    assert set(manifest) == {"Commonwealth", "NukaWorld"}


def test_a_missing_dlc_is_skipped_and_named(tmp_path, fake_readers, capsys):
    """A player without Nuka-World still gets the Commonwealth."""
    game = tmp_path / "Data"
    _install(game, "Fallout4.esm", "Fallout4 - Textures6.ba2")
    out = tmp_path / "assets"

    manifest = build_assets(str(game), out, SOURCES)

    assert set(manifest) == {"Commonwealth"}
    assert set(json.loads((out / "worldspaces.json").read_text())) == {"Commonwealth"}
    assert "skipped NukaWorld" in capsys.readouterr().out


def test_an_esm_without_its_archive_counts_as_missing(tmp_path, fake_readers):
    game = tmp_path / "Data"
    _install(game, "Fallout4.esm", "Fallout4 - Textures6.ba2", "DLCNukaWorld.esm")

    manifest = build_assets(str(game), tmp_path / "assets", SOURCES)

    assert set(manifest) == {"Commonwealth"}


def test_nothing_to_build_is_an_error_naming_the_folder(tmp_path, fake_readers):
    game = tmp_path / "Data"
    game.mkdir()
    out = tmp_path / "assets"

    with pytest.raises(AssetsUnavailable, match="Fallout4.esm"):
        build_assets(str(game), out, SOURCES)

    assert not (out / "worldspaces.json").exists()


def test_a_failure_part_way_leaves_no_manifest(tmp_path, fake_readers):
    """The manifest marks the assets complete, so an interrupted or failed build must
    not write one -- otherwise the next launch would trust half-built assets."""
    game = tmp_path / "Data"
    _install(game, "Fallout4.esm", "Fallout4 - Textures6.ba2",
             "DLCNukaWorld.esm", "DLCNukaWorld - Textures.ba2")
    fake_readers.add("nw.dds")
    out = tmp_path / "assets"

    with pytest.raises(ValueError):
        build_assets(str(game), out, SOURCES)

    assert not (out / "worldspaces.json").exists()
    assert not out.exists() or not any(out.iterdir())
