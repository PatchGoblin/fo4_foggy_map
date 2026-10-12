"""Reading a worldspace's terrain heights and water levels out of a plugin file."""

import os
import struct
import zlib

import numpy as np
import pytest

from foggymap.fo4_esm import WorldspaceMapData, read_terrain

from game_paths import data_dir

COMPRESSED = 0x00040000


def _sub(sig: bytes, body: bytes) -> bytes:
    return sig + struct.pack("<H", len(body)) + body


def _record(sig: bytes, form_id: int, body: bytes, compress=False) -> bytes:
    flags = 0
    if compress:
        body = struct.pack("<I", len(body)) + zlib.compress(body)
        flags = COMPRESSED
    return sig + struct.pack("<IIIIHH", len(body), flags, form_id, 0, 131, 0) + body


def _group(label: bytes, group_type: int, *children: bytes) -> bytes:
    content = b"".join(children)
    return b"GRUP" + struct.pack("<I", 24 + len(content)) + label + struct.pack("<iII", group_type, 0, 0) + content


def _id(form_id: int) -> bytes:
    return struct.pack("<I", form_id)


def _flat_land(height_eighths: int) -> bytes:
    deltas = np.zeros((33, 33), dtype=np.int8)
    deltas[0, 0] = height_eighths
    return _sub(b"VHGT", struct.pack("<f", 0.0) + deltas.tobytes() + b"\x00" * 3)


def _cell(form_id, x, y, land_eighths=None, water=None, compress_land=True):
    body = _sub(b"XCLC", struct.pack("<iiI", x, y, 0))
    if water is not None:
        body += _sub(b"XCLW", struct.pack("<f", water))
    parts = [_record(b"CELL", form_id, body)]
    if land_eighths is not None:
        land = _record(b"LAND", form_id + 0x1000, _flat_land(land_eighths), compress=compress_land)
        parts.append(_group(_id(form_id), 6, _group(_id(form_id), 9, land)))
    return b"".join(parts)


def _world(form_id, editor_id, *cells, default_land=-500.0, default_water=0.0):
    record = _record(b"WRLD", form_id, _sub(b"EDID", editor_id.encode() + b"\x00")
                     + _sub(b"DNAM", struct.pack("<ff", default_land, default_water)))
    block = _group(b"\x00\x00\x00\x00", 4, _group(b"\x00\x00\x00\x00", 5, *cells))
    return record + _group(_id(form_id), 1, block)


@pytest.fixture
def esm(tmp_path):
    header = _record(b"TES4", 0, _sub(b"HEDR", b"\x00" * 12))
    other_group = _group(b"WEAP", 0, _record(b"WEAP", 0x99, b""))
    worlds = _group(
        b"WRLD", 0,
        _world(0x3C, "Commonwealth",
               _cell(0x100, 0, 0, land_eighths=50, water=100.0),       # land, above water
               _cell(0x101, 1, 0, land_eighths=5, water=100.0),        # under water
               _cell(0x102, 0, -1, land_eighths=20),                   # default water level
               # (1, -1) has a cell but no terrain: default land height
               _cell(0x103, 1, -1),
               _cell(0x104, 5, 5, land_eighths=99, water=0.0),         # outside the map
               default_land=-500.0, default_water=60.0),
        _world(0x50, "Elsewhere", _cell(0x200, 0, 0, land_eighths=120, water=0.0)),
    )
    path = tmp_path / "Test.esm"
    path.write_bytes(header + other_group + worlds)
    return str(path)


BOUNDS = WorldspaceMapData("Commonwealth", 0x3C, nw_cell_x=0, nw_cell_y=0, se_cell_x=1, se_cell_y=-1)


def test_reads_one_sample_grid_covering_the_map(esm):
    terrain = read_terrain(esm, BOUNDS)

    assert terrain.heights.shape == (2 * 32 + 1, 2 * 32 + 1)
    assert terrain.water.shape == terrain.heights.shape


def test_each_cell_lands_in_its_place_north_up(esm):
    terrain = read_terrain(esm, BOUNDS)

    assert terrain.heights[10, 10] == 50 * 8, "(0, 0) is the north-west cell"
    assert terrain.heights[10, 50] == 5 * 8, "(1, 0) is north-east"
    assert terrain.heights[50, 10] == 20 * 8, "(0, -1) is south-west"


def test_a_cell_without_terrain_uses_the_worldspace_default(esm):
    terrain = read_terrain(esm, BOUNDS)

    assert terrain.heights[50, 50] == -500.0


def test_water_comes_from_the_cell_or_the_worldspace_default(esm):
    terrain = read_terrain(esm, BOUNDS)

    assert terrain.water[10, 10] == 100.0
    assert terrain.water[50, 10] == 60.0


def test_other_worldspaces_and_cells_off_the_map_are_ignored(esm):
    terrain = read_terrain(esm, BOUNDS)

    assert terrain.heights.max() == 50 * 8


def test_uncompressed_terrain_reads_the_same(tmp_path):
    header = _record(b"TES4", 0, _sub(b"HEDR", b"\x00" * 12))
    worlds = _group(b"WRLD", 0, _world(0x3C, "Commonwealth",
                                       _cell(0x100, 0, 0, land_eighths=7, compress_land=False)))
    path = tmp_path / "Plain.esm"
    path.write_bytes(header + worlds)

    terrain = read_terrain(str(path), BOUNDS)

    assert terrain.heights[10, 10] == 7 * 8


def test_an_unknown_worldspace_is_an_error(esm):
    with pytest.raises(KeyError):
        read_terrain(esm, WorldspaceMapData("Nowhere", 1, 0, 0, 0, 0))


FALLOUT4_ESM = os.path.join(data_dir(), "Fallout4.esm")


@pytest.mark.skipif(not os.path.exists(FALLOUT4_ESM), reason="Fallout 4 not installed")
def test_the_real_commonwealth_has_its_coast():
    bounds = WorldspaceMapData("Commonwealth", 0x3C, -33, 25, 28, -36)

    terrain = read_terrain(FALLOUT4_ESM, bounds)

    under = terrain.heights < terrain.water
    assert terrain.heights.shape == (62 * 32 + 1, 62 * 32 + 1)
    assert 0.15 < under.mean() < 0.4
    assert under[len(under) // 2, -1], "the open sea lies east of Boston"
