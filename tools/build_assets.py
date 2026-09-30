"""One-off asset preparation: base map images plus the worldspace manifest.

Reads only installed game files. The extracted images are not redistributable, which
is why assets/ is gitignored.

    python tools/build_assets.py [--data <Fallout 4 Data dir>] [--out assets]
"""

from __future__ import annotations

import argparse
import io
import json
import os
from dataclasses import dataclass

from PIL import Image

from ba2 import extract_texture
from fo4_esm import read_worldspace_map_data

from game_paths import data_dir
MANIFEST_NAME = "worldspaces.json"


@dataclass(frozen=True)
class MapSource:
    """Where one worldspace's map bounds and map image live inside the game files."""

    editor_id: str
    esm: str
    archive: str
    texture: str


MAP_SOURCES = (
    MapSource(
        editor_id="Commonwealth",
        esm="Fallout4.esm",
        archive="Fallout4 - Textures6.ba2",
        texture=r"Textures\Interface\Pip-Boy\WorldMap_d.DDS",
    ),
    MapSource(
        editor_id="DLC03FarHarbor",
        esm="DLCCoast.esm",
        archive="DLCCoast - Textures.ba2",
        texture=r"Textures\DLC03\Interface\Map\MapFarHarbor.DDS",
    ),
    MapSource(
        editor_id="NukaWorld",
        esm="DLCNukaWorld.esm",
        archive="DLCNukaWorld - Textures.ba2",
        texture=r"Textures\DLC04\Interface\Map\NukaWorldMap.DDS",
    ),
)


def _base_intensity(image: Image.Image) -> Image.Image:
    """Reduce a map texture to a single intensity channel for the viewer to tint.

    The Commonwealth and Far Harbor maps carry their artwork in RGB. The Nuka-World
    map leaves RGB entirely black and stores the map as an alpha mask, so converting
    it to RGB yields a blank image.
    """
    rgba = image.convert("RGBA")
    red, green, blue, alpha = rgba.split()
    luminance = rgba.convert("L")
    if max(red.getextrema()[1], green.getextrema()[1], blue.getextrema()[1]) == 0:
        return alpha
    return luminance


def build_assets(data_dir: str, out_dir) -> dict:
    """Extract each map image to ``out_dir`` and return (and write) the manifest."""
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    manifest: dict[str, dict] = {}
    for source in MAP_SOURCES:
        bounds = read_worldspace_map_data(os.path.join(data_dir, source.esm))
        if source.editor_id not in bounds:
            raise KeyError(f"{source.editor_id} has no map data in {source.esm}")
        map_data = bounds[source.editor_id]

        dds = extract_texture(os.path.join(data_dir, source.archive), source.texture)
        image = _base_intensity(Image.open(io.BytesIO(dds)))

        image_name = f"worldmap_{source.editor_id}.png"
        image.save(os.path.join(out_dir, image_name), optimize=True)

        manifest[source.editor_id] = {
            "editor_id": source.editor_id,
            "form_id": f"0x{map_data.form_id:08X}",
            "nw_cell": [map_data.nw_cell_x, map_data.nw_cell_y],
            "se_cell": [map_data.se_cell_x, map_data.se_cell_y],
            "width_px": image.width,
            "height_px": image.height,
            "image": image_name,
        }

    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=data_dir(), help="Fallout 4 Data directory")
    parser.add_argument("--out", default="assets", help="where to write images and manifest")
    args = parser.parse_args()

    manifest = build_assets(args.data, args.out)
    for editor_id, entry in manifest.items():
        nw, se = entry["nw_cell"], entry["se_cell"]
        cells_x = se[0] - nw[0] + 1
        cells_y = nw[1] - se[1] + 1
        print(
            f"{editor_id:16s} {entry['width_px']}x{entry['height_px']} px  "
            f"{cells_x}x{cells_y} cells  -> {entry['image']}"
        )


if __name__ == "__main__":
    main()
