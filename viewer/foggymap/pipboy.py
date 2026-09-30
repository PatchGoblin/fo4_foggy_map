"""Exporting the fog mask for the in-game Pip-Boy overlay.

The plugin draws this as a translucent layer attached to the map page's own texture
holder, whose coordinate space is exactly the map image -- the same space the fog is
rendered in, since both derive from the worldspace's MNAM bounds. So no coordinate
conversion is needed on either side.

Only the fog's opacity is exported, never the map art: the real map is already on
screen underneath. Colour is absent too, because the Pip-Boy re-tints its content
(``fPipboyEffectColorR/G/B``) and would discard it.
"""

from __future__ import annotations

import os
import struct

import numpy as np

MAGIC = b"FOGM"
VERSION = 1
HEADER = struct.Struct("<4sIII")


def fog_opacity(alpha: np.ndarray) -> np.ndarray:
    """The fog mask as a full-range byte image: 0 clear, 255 fully fogged.

    Deliberately excludes the map art. The plugin draws this *over* the real Pip-Boy
    map, so baking the art in would double it up -- and would make explored ground
    non-zero wherever a road runs, fogging places that should read as clear.

    Scaled across the whole byte range because the plugin quantises into levels to
    merge neighbouring cells into single rectangles; a compressed range would collapse
    every level into the faintest one.
    """
    return np.rint(np.clip(alpha, 0.0, 1.0) * 255.0).astype(np.uint8)


def export_for_pipboy(worldspace, fog, data_dir) -> str:
    """Write the current fog for one worldspace where the plugin will look for it.

    Named per worldspace because Far Harbor and Nuka-World each have their own map, and
    the plugin draws the one matching where the player is.
    """
    path = os.path.join(str(data_dir), f"pipboy_{worldspace.editor_id}.fog")
    write_fog_file(path, fog_opacity(fog.alpha))
    return path


def write_fog_file(path, image: np.ndarray) -> None:
    """Write an intensity image as a headed raw bitmap, atomically.

    The plugin reads this while the game is running, so the file is built under a
    temporary name and renamed into place -- a half-written frame is never visible.
    """
    path = str(path)
    height, width = image.shape
    temporary = f"{path}.tmp"

    with open(temporary, "wb") as handle:
        handle.write(HEADER.pack(MAGIC, VERSION, width, height))
        handle.write(np.ascontiguousarray(image, dtype=np.uint8).tobytes())
    os.replace(temporary, path)


def read_fog_file(path) -> tuple[int, int, np.ndarray]:
    """Read back a fog file as (width, height, pixels). Mirrors what the plugin does."""
    with open(str(path), "rb") as handle:
        magic, version, width, height = HEADER.unpack(handle.read(HEADER.size))
        if magic != MAGIC:
            raise ValueError(f"not a fog file: magic {magic!r}")
        if version != VERSION:
            raise ValueError(f"unsupported fog file version {version}")
        data = handle.read(width * height)

    if len(data) != width * height:
        raise ValueError(f"truncated fog file: {len(data)} of {width * height} bytes")
    return width, height, np.frombuffer(data, dtype=np.uint8).reshape(height, width)
