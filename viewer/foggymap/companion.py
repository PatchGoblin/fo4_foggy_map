"""The process the plugin launches: builds map assets on first run, then keeps the
Pip-Boy fog current.

Everything it needs arrives as arguments from the plugin, so it has no idea where it
is installed -- which is what lets it run from a repo, a venv, or a frozen bundle.
"""

from __future__ import annotations

import argparse
import json
import os

from foggymap.assets import MAP_SOURCES, build_assets
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

    have = _built_worldspaces(assets)
    reason = _rebuild_reason(have, args.game_data)
    if reason:
        print(f"building map assets from the game files: {reason}", flush=True)
        try:
            built = build_fn(args.game_data, assets)
        except Exception as error:  # noqa: BLE001 - reported, never silent
            print(f"could not build map assets: {type(error).__name__}: {error}", flush=True)
            if not have:
                return 1
            print("carrying on with the map assets already built", flush=True)
        else:
            print(f"built map assets for {', '.join(built)}", flush=True)

    watch_fn(assets, args.data)
    return 0


def _built_worldspaces(assets_dir: str) -> set[str] | None:
    """The worldspaces the manifest lists, or None if there is no usable manifest."""
    try:
        with open(os.path.join(assets_dir, MANIFEST_NAME), "r", encoding="utf-8") as handle:
            return set(json.load(handle))
    except (OSError, ValueError):
        return None


def _rebuild_reason(have: set[str] | None, game_data: str) -> str | None:
    if have is None:
        return "no usable manifest"
    # DLC installed since the last build would otherwise never get fog.
    available = {
        source.editor_id for source in MAP_SOURCES
        if os.path.isfile(os.path.join(game_data, source.esm))
        and os.path.isfile(os.path.join(game_data, source.archive))
    }
    new = sorted(available - have)
    return f"new worldspaces {', '.join(new)}" if new else None
