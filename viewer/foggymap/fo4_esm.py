"""Minimal reader for the bits of Bethesda plugin files that FoggyMap needs.

Worldspace map bounds, and the terrain heights and water levels the published relief
map is drawn from. Top-level groups other than WRLD are skipped without being read,
so this stays fast even on the 900 MB Fallout4.esm.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

from foggymap.relief import decode_vhgt

RECORD_HEADER_SIZE = 24
COMPRESSED_FLAG = 0x00040000

# Group types, from the record format.
WORLD_CHILDREN = 1
CELL_CHILDREN = 6

# Terrain vertices along one side of a cell, less the edge shared with its neighbour.
SAMPLES_PER_CELL = 32

# XCLW holds a huge float where a cell means "use the worldspace's water level".
NO_WATER_OVERRIDE = 1e7


@dataclass(frozen=True)
class WorldspaceMapData:
    """A worldspace's Pip-Boy map extent, in exterior cell coordinates.

    The map image covers whole cells: the north-west corner of ``nw_cell`` through
    the south-east corner of ``se_cell``. Note the Y axis runs north-positive, so
    ``nw_cell_y`` is the *larger* Y value.
    """

    editor_id: str
    form_id: int
    nw_cell_x: int
    nw_cell_y: int
    se_cell_x: int
    se_cell_y: int


def _iter_subrecords(data: bytes):
    offset = 0
    while offset + 6 <= len(data):
        signature = data[offset : offset + 4]
        (size,) = struct.unpack_from("<H", data, offset + 4)
        yield signature, data[offset + 6 : offset + 6 + size]
        offset += 6 + size


def _iter_records(handle, end: int):
    """Yield (signature, form_id, payload) for direct child records between here and ``end``.

    Nested groups are skipped rather than descended into. Worldspace records sit
    directly inside the top-level WRLD group; their child groups hold the tens of
    thousands of cell and landscape records we have no use for.
    """
    while handle.tell() < end:
        start = handle.tell()
        header = handle.read(RECORD_HEADER_SIZE)
        if len(header) < RECORD_HEADER_SIZE:
            return
        signature, size, flags, form_id = struct.unpack_from("<4sIII", header)
        if signature == b"GRUP":
            handle.seek(start + size)
            continue
        payload = handle.read(size)
        if flags & COMPRESSED_FLAG:
            payload = zlib.decompress(payload[4:])
        yield signature, form_id, payload


def read_worldspace_map_data(esm_path: str) -> dict[str, WorldspaceMapData]:
    """Map editor ID to map bounds for every worldspace in ``esm_path`` that has them."""
    worldspaces: dict[str, WorldspaceMapData] = {}
    with open(esm_path, "rb") as handle:
        _, header_size = struct.unpack_from("<4sI", handle.read(8))
        handle.seek(RECORD_HEADER_SIZE + header_size)  # past the TES4 header record

        file_end = handle.seek(0, 2)
        handle.seek(RECORD_HEADER_SIZE + header_size)

        while handle.tell() < file_end:
            start = handle.tell()
            group_header = handle.read(RECORD_HEADER_SIZE)
            if len(group_header) < RECORD_HEADER_SIZE:
                break
            signature, size, label = struct.unpack_from("<4sI4s", group_header)
            if signature != b"GRUP":
                break
            if label != b"WRLD":
                handle.seek(start + size)
                continue
            for record_sig, form_id, payload in _iter_records(handle, start + size):
                if record_sig != b"WRLD":
                    continue
                editor_id = None
                map_data = None
                for sub_sig, sub_data in _iter_subrecords(payload):
                    if sub_sig == b"EDID":
                        editor_id = sub_data.rstrip(b"\x00").decode("utf-8", "replace")
                    elif sub_sig == b"MNAM" and len(sub_data) >= 16:
                        map_data = struct.unpack_from("<hhhh", sub_data, 8)
                if editor_id and map_data:
                    nw_x, nw_y, se_x, se_y = map_data
                    worldspaces[editor_id] = WorldspaceMapData(
                        editor_id=editor_id,
                        form_id=form_id,
                        nw_cell_x=nw_x,
                        nw_cell_y=nw_y,
                        se_cell_x=se_x,
                        se_cell_y=se_y,
                    )
            handle.seek(start + size)
    return worldspaces


@dataclass(frozen=True)
class Terrain:
    """Heights and the water surface over each sample, in world units, north row first.

    Covers exactly the map's cells, ``SAMPLES_PER_CELL`` samples per cell plus the
    closing edge, so it lines up with the map image without any alignment.
    """

    heights: np.ndarray
    water: np.ndarray


def read_terrain(esm_path: str, map_data: WorldspaceMapData) -> Terrain:
    """Read the terrain under ``map_data``'s map from the plugin that defines it.

    A cell with no terrain takes the worldspace's default land height, and one with no
    water level of its own takes the worldspace's default water.
    """
    cols = map_data.se_cell_x - map_data.nw_cell_x + 1
    rows = map_data.nw_cell_y - map_data.se_cell_y + 1
    shape = (rows * SAMPLES_PER_CELL + 1, cols * SAMPLES_PER_CELL + 1)

    with open(esm_path, "rb") as handle:
        world = _find_worldspace(handle, map_data.editor_id)
        if world is None:
            raise KeyError(f"no worldspace {map_data.editor_id} in {esm_path}")
        world_id, default_land, default_water, children_start, children_end = world

        heights = np.full(shape, default_land, dtype=np.float32)
        water = np.full(shape, default_water, dtype=np.float32)
        cells: dict[int, tuple[int, int]] = {}

        def place(x: int, y: int) -> tuple[slice, slice] | None:
            if not (map_data.nw_cell_x <= x <= map_data.se_cell_x
                    and map_data.se_cell_y <= y <= map_data.nw_cell_y):
                return None
            row = (map_data.nw_cell_y - y) * SAMPLES_PER_CELL
            col = (x - map_data.nw_cell_x) * SAMPLES_PER_CELL
            return slice(row, row + 33), slice(col, col + 33)

        def visit(end: int, cell_id: int | None) -> None:
            while handle.tell() < end:
                start = handle.tell()
                header = handle.read(RECORD_HEADER_SIZE)
                # A group's third field is its label; a record's is its flags.
                signature, size, label_or_flags = struct.unpack_from("<4sII", header)
                if signature == b"GRUP":
                    group_type = struct.unpack_from("<i", header, 12)[0]
                    visit(start + size, label_or_flags if group_type == CELL_CHILDREN else cell_id)
                    handle.seek(start + size)
                    continue
                if signature not in (b"CELL", b"LAND"):
                    handle.seek(start + RECORD_HEADER_SIZE + size)
                    continue
                payload = handle.read(size)
                if label_or_flags & COMPRESSED_FLAG:
                    payload = zlib.decompress(payload[4:])
                fields = dict(_iter_subrecords(payload))
                form_id = struct.unpack_from("<I", header, 12)[0]
                if signature == b"CELL" and b"XCLC" in fields:
                    x, y = struct.unpack_from("<ii", fields[b"XCLC"])
                    cells[form_id] = (x, y)
                    where = place(x, y)
                    if where and b"XCLW" in fields:
                        (level,) = struct.unpack_from("<f", fields[b"XCLW"])
                        if abs(level) < NO_WATER_OVERRIDE:
                            water[where] = level
                elif signature == b"LAND" and b"VHGT" in fields and cell_id in cells:
                    where = place(*cells[cell_id])
                    if where:
                        heights[where] = decode_vhgt(fields[b"VHGT"])

        handle.seek(children_start)
        visit(children_end, None)
    return Terrain(heights=heights, water=water)


def _find_worldspace(handle, editor_id: str):
    """(form id, default land, default water, children start, children end) or None."""
    _, header_size = struct.unpack_from("<4sI", handle.read(8))
    file_end = handle.seek(0, 2)
    handle.seek(RECORD_HEADER_SIZE + header_size)

    while handle.tell() < file_end:
        start = handle.tell()
        signature, size, label = struct.unpack_from("<4sI4s", handle.read(RECORD_HEADER_SIZE))
        if signature != b"GRUP":
            return None
        if label != b"WRLD":
            handle.seek(start + size)
            continue
        found = None
        while handle.tell() < start + size:
            item = handle.tell()
            header = handle.read(RECORD_HEADER_SIZE)
            item_sig, item_size, item_label, flags = struct.unpack_from("<4sIII", header)
            if item_sig == b"GRUP":
                group_type = struct.unpack_from("<i", header, 12)[0]
                if found and group_type == WORLD_CHILDREN and item_label == found[0]:
                    return found + (item + RECORD_HEADER_SIZE, item + item_size)
                handle.seek(item + item_size)
                continue
            payload = handle.read(item_size)
            if flags & COMPRESSED_FLAG:
                payload = zlib.decompress(payload[4:])
            if item_sig != b"WRLD":
                continue
            fields = dict(_iter_subrecords(payload))
            if fields.get(b"EDID", b"").rstrip(bytes(1)).decode("utf-8", "replace") == editor_id:
                form_id = struct.unpack_from("<I", header, 12)[0]
                land, sea = struct.unpack_from("<ff", fields[b"DNAM"]) if b"DNAM" in fields else (0.0, 0.0)
                found = (form_id, land, sea)
        return None
    return None
