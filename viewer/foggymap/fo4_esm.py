"""Minimal reader for the bits of Bethesda plugin files that FoggyMap needs.

Only worldspace map bounds are extracted. Top-level groups other than WRLD are
skipped without being read, so this stays fast even on the 900 MB Fallout4.esm.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

RECORD_HEADER_SIZE = 24
COMPRESSED_FLAG = 0x00040000


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
