"""Pulling texture files out of the game's BA2 archives."""

import io
import os

import pytest
from PIL import Image

from ba2 import extract_texture, list_files

from game_paths import data_dir

DATA = data_dir()
TEXTURES6 = os.path.join(DATA, "Fallout4 - Textures6.ba2")
NUKAWORLD = os.path.join(DATA, "DLCNukaWorld - Textures.ba2")
WORLD_MAP = r"Textures\Interface\Pip-Boy\WorldMap_d.DDS"
NUKA_MAP = r"Textures\DLC04\Interface\Map\NukaWorldMap.DDS"

needs_game = pytest.mark.skipif(
    not os.path.exists(TEXTURES6), reason="Fallout 4 not installed at the expected path"
)


@needs_game
def test_lists_archive_contents():
    assert WORLD_MAP in list_files(TEXTURES6)


@needs_game
def test_extracts_the_commonwealth_map_as_a_decodable_bc1_texture():
    data = extract_texture(TEXTURES6, WORLD_MAP)

    assert data[:4] == b"DDS "
    assert Image.open(io.BytesIO(data)).size == (2048, 2048)


@needs_game
def test_extracts_the_nuka_world_map_which_is_bc3_not_bc1():
    """Nuka-World uses a different compression format from the other two maps."""
    data = extract_texture(NUKAWORLD, NUKA_MAP)

    assert Image.open(io.BytesIO(data)).size == (2048, 2048)


@needs_game
def test_internal_paths_are_matched_case_insensitively():
    assert extract_texture(TEXTURES6, WORLD_MAP.lower()) == extract_texture(
        TEXTURES6, WORLD_MAP
    )


@needs_game
def test_a_missing_internal_path_raises():
    with pytest.raises(KeyError):
        extract_texture(TEXTURES6, r"Textures\Nope\Missing.dds")
