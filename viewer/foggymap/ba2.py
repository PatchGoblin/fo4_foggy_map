"""Minimal reader for Fallout 4 BA2 archives, enough to pull out map textures.

Only DX10 (texture) archives are supported, and only the full-resolution mip is
returned. BA2 stores texture payloads without a DDS header, so one is rebuilt from
the archive's own dimension and format fields.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass

ARCHIVE_HEADER = "<4sI4sIQ"
ARCHIVE_HEADER_SIZE = 24
TEXTURE_RECORD_SIZE = 24
CHUNK_SIZE = 24

# DXGI_FORMAT values seen on the map textures, mapped to the legacy FourCC that
# Pillow's DDS decoder understands.
DXGI_TO_FOURCC = {
    71: b"DXT1",  # BC1_UNORM
    72: b"DXT1",  # BC1_UNORM_SRGB
    74: b"DXT3",  # BC2_UNORM
    77: b"DXT5",  # BC3_UNORM
    78: b"DXT5",  # BC3_UNORM_SRGB
}


@dataclass(frozen=True)
class TextureEntry:
    name: str
    width: int
    height: int
    dxgi_format: int
    chunks: list[tuple[int, int, int]]  # (offset, packed_size, unpacked_size)


def _read_index(path: str) -> list[TextureEntry]:
    with open(path, "rb") as handle:
        magic, _version, archive_type, count, name_table_offset = struct.unpack(
            ARCHIVE_HEADER, handle.read(ARCHIVE_HEADER_SIZE)
        )
        if magic != b"BTDX":
            raise ValueError(f"{path} is not a BA2 archive")
        if archive_type != b"DX10":
            raise ValueError(f"{path} is a {archive_type.decode()} archive, not DX10")

        records = []
        for _ in range(count):
            (_name_hash, _ext, _dir_hash, _unknown, chunk_count, _chunk_header_size,
             height, width, _mips, dxgi_format, _cubemap, _tile_mode) = struct.unpack(
                "<I4sIBBHHHBBBB", handle.read(TEXTURE_RECORD_SIZE)
            )
            chunks = []
            for _ in range(chunk_count):
                offset, packed, unpacked, _start_mip, _end_mip, _align = struct.unpack(
                    "<QIIHHI", handle.read(CHUNK_SIZE)
                )
                chunks.append((offset, packed, unpacked))
            records.append((width, height, dxgi_format, chunks))

        handle.seek(name_table_offset)
        entries = []
        for width, height, dxgi_format, chunks in records:
            (length,) = struct.unpack("<H", handle.read(2))
            name = handle.read(length).decode("utf-8", "replace")
            entries.append(TextureEntry(name, width, height, dxgi_format, chunks))
        return entries


def list_files(path: str) -> list[str]:
    """Internal paths of every texture in the archive."""
    return [entry.name for entry in _read_index(path)]


def extract_texture(path: str, internal_path: str) -> bytes:
    """Return a complete, decodable DDS file for one texture in the archive.

    Only the top mip level is included, which is all the map images need.
    """
    wanted = _normalise(internal_path)
    entries = {_normalise(entry.name): entry for entry in _read_index(path)}
    if wanted not in entries:
        raise KeyError(f"{internal_path} is not in {os.path.basename(path)}")
    entry = entries[wanted]

    offset, packed, unpacked = entry.chunks[0]
    with open(path, "rb") as handle:
        handle.seek(offset)
        raw = handle.read(packed if packed else unpacked)
    payload = zlib.decompress(raw) if packed else raw

    return _dds_header(entry, len(payload)) + payload


def _normalise(internal_path: str) -> str:
    return internal_path.lower().replace("/", "\\")


def _dds_header(entry: TextureEntry, payload_size: int) -> bytes:
    fourcc = DXGI_TO_FOURCC.get(entry.dxgi_format)
    if fourcc is None:
        raise ValueError(f"unsupported DXGI format {entry.dxgi_format} for {entry.name}")

    DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PIXELFORMAT, DDSD_LINEARSIZE = (
        0x1, 0x2, 0x4, 0x1000, 0x80000
    )
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE

    header = struct.pack(
        "<4sIIIIIII44s",
        b"DDS ",
        124,               # header size
        flags,
        entry.height,
        entry.width,
        payload_size,      # linear size of the top mip
        0,                 # depth
        1,                 # mip count
        b"\x00" * 44,      # reserved
    )
    pixel_format = struct.pack("<II4sIIIIII", 32, 0x4, fourcc, 0, 0, 0, 0, 0, 0)
    caps = struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)  # DDSCAPS_TEXTURE
    return header + pixel_format + caps
