"""The process the plugin launches: builds map assets on first run, then keeps the
Pip-Boy fog current.

Everything it needs arrives as arguments from the plugin, so it has no idea where it
is installed -- which is what lets it run from a repo, a venv, or a frozen bundle.
"""

from __future__ import annotations

import argparse
import os

from foggymap.assets import build_assets
from foggymap.exporter import watch
from foggymap.pipeline import MANIFEST_NAME


def main(argv: list[str] | None = None, watch_fn=watch, build_fn=build_assets) -> int:
    parser = argparse.ArgumentParser(prog="FoggyMapCompanion", description=__doc__)
    parser.add_argument("--data", required=True,
                        help="where the plugin writes its CSVs and the fog files go")
    parser.add_argument("--game-data", required=True,
                        help="the game's Data folder, read only to build the map assets")
    parser.add_argument("--assets", help="map assets folder (default: <data>\\assets)")
    args = parser.parse_args(argv)

    assets = args.assets or os.path.join(args.data, "assets")
    print(f"data: {args.data}", flush=True)
    print(f"game data: {args.game_data}", flush=True)
    print(f"assets: {assets}", flush=True)

    if not os.path.isfile(os.path.join(assets, MANIFEST_NAME)):
        print("building map assets from the game files", flush=True)
        try:
            built = build_fn(args.game_data, assets)
        except Exception as error:  # noqa: BLE001 - reported, then a clean non-zero exit
            print(f"could not build map assets: {type(error).__name__}: {error}", flush=True)
            return 1
        print(f"built map assets for {', '.join(built)}", flush=True)

    watch_fn(assets, args.data)
    return 0
