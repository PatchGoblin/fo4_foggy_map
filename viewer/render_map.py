"""Render fog maps to PNG files without opening a window.

    python viewer/render_map.py [--worldspace Commonwealth] [--out out_dir]

Useful for checking progress between sessions, and for verifying the pipeline against
whatever the plugin has recorded so far.
"""

from __future__ import annotations

import argparse
import os

from PIL import Image

from foggymap.pipboy import export_for_pipboy
from foggymap.pipeline import Settings, load_manifest, load_worldspace, render

DEFAULT_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "FoggyMap")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="assets", help="directory of extracted maps")
    parser.add_argument("--data", default=DEFAULT_DATA_DIR, help="directory the plugin writes to")
    parser.add_argument("--out", default=".", help="where to write the PNGs")
    parser.add_argument("--worldspace", action="append", help="repeatable; default is all")
    parser.add_argument("--sight-fraction", type=float, default=Settings().sight_fraction)
    args = parser.parse_args()

    settings = Settings(sight_fraction=args.sight_fraction)
    editor_ids = args.worldspace or list(load_manifest(args.assets))

    for editor_id in editor_ids:
        worldspace = load_worldspace(args.assets, editor_id)
        fog = render(worldspace, args.data, settings)

        path = os.path.join(args.out, f"fog_{editor_id}.png")
        Image.fromarray(fog.rgb).save(path)
        export_for_pipboy(worldspace, fog, args.data)
        print(
            f"{editor_id:16s} {fog.percent_area_explored:5.1f}% area  "
            f"{fog.land_tiles_swept}/{fog.land_tile_count} tiles swept  "
            f"{fog.pois_discovered}/{len(fog.pois)} POIs  "
            f"{fog.sample_count} samples  -> {path}"
        )


if __name__ == "__main__":
    main()
