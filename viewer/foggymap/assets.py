"""Building the base map images and worldspace manifest from installed game files.

Runs on the player's machine, on the companion's first launch: the images are
Bethesda's, so they can be extracted but never shipped. Alongside each it renders a
relief map of our own from the terrain, which is what the published site shows.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass

from PIL import Image

from foggymap.ba2 import extract_texture
from foggymap.config import CELL_UNITS
from foggymap.fo4_esm import SAMPLES_PER_CELL, read_terrain, read_worldspace_map_data
from foggymap.pipeline import MANIFEST_NAME
from foggymap.relief import render_relief


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


class AssetsUnavailable(Exception):
    """None of the worldspaces could be built: the game files are not where we looked."""


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


def _relief(esm_path: str, map_data) -> Image.Image | None:
    """Our own relief map of the worldspace, or None if its terrain cannot be read.

    Only the published site uses it, so a failure here must never cost the fog.
    """
    try:
        terrain = read_terrain(esm_path, map_data)
    except Exception as error:  # noqa: BLE001 - reported; the fog does not need it
        print(f"no relief map for {map_data.editor_id}: {type(error).__name__}: {error}",
              flush=True)
        return None
    pixels = render_relief(terrain.heights, terrain.water, CELL_UNITS / SAMPLES_PER_CELL)
    return Image.fromarray(pixels, mode="RGB")


def build_assets(data_dir: str, out_dir, sources=MAP_SOURCES) -> dict:
    """Extract each available map image to ``out_dir`` and return (and write) the manifest.

    A worldspace whose ESM or archive is absent -- DLC the player does not own -- is
    skipped and named. Everything is read before anything is written, and the manifest
    is written last, so its presence means the assets are complete.
    """
    out_dir = str(out_dir)
    loaded = []
    missing: list[str] = []

    for source in sources:
        esm = os.path.join(data_dir, source.esm)
        archive = os.path.join(data_dir, source.archive)
        absent = [os.path.basename(p) for p in (esm, archive) if not os.path.isfile(p)]
        if absent:
            missing.extend(absent)
            print(f"skipped {source.editor_id}: missing {', '.join(absent)}", flush=True)
            continue

        bounds = read_worldspace_map_data(esm)
        if source.editor_id not in bounds:
            raise KeyError(f"{source.editor_id} has no map data in {source.esm}")
        dds = extract_texture(archive, source.texture)
        image = _base_intensity(Image.open(io.BytesIO(dds)))
        relief = _relief(esm, bounds[source.editor_id])
        loaded.append((source, bounds[source.editor_id], image, relief))

    if not loaded:
        raise AssetsUnavailable(
            f"no map could be built from {data_dir}; missing {', '.join(missing)}"
        )

    os.makedirs(out_dir, exist_ok=True)
    manifest: dict[str, dict] = {}
    for source, map_data, image, relief in loaded:
        image_name = f"worldmap_{source.editor_id}.png"
        image.save(os.path.join(out_dir, image_name), optimize=True)
        relief_name = None
        if relief is not None:
            relief_name = f"relief_{source.editor_id}.png"
            relief.save(os.path.join(out_dir, relief_name), optimize=True)
        manifest[source.editor_id] = {
            "editor_id": source.editor_id,
            "form_id": f"0x{map_data.form_id:08X}",
            "nw_cell": [map_data.nw_cell_x, map_data.nw_cell_y],
            "se_cell": [map_data.se_cell_x, map_data.se_cell_y],
            "width_px": image.width,
            "height_px": image.height,
            "image": image_name,
            # None when the terrain could not be read; present either way, so the
            # companion can tell a failed relief from assets built before reliefs.
            "relief": relief_name,
        }

    # Written aside and renamed into place, so the manifest never exists half-written.
    final = os.path.join(out_dir, MANIFEST_NAME)
    partial = final + ".partial"
    try:
        with open(partial, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
        os.replace(partial, final)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return manifest
