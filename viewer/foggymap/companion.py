"""The process the plugin launches: builds map assets on first run, then keeps the
Pip-Boy fog current.

Everything it needs arrives as arguments from the plugin, so it has no idea where it
is installed -- which is what lets it run from a repo, a venv, or a frozen bundle.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys

from foggymap.assets import MAP_SOURCES, build_assets
from foggymap.exporter import watch
from foggymap.gitpublish import PublishError
from foggymap.pipeline import MANIFEST_NAME
from foggymap.publisher import Publisher, load_publish_config


def main(argv: list[str] | None = None, watch_fn=watch, build_fn=build_assets,
         spawn_fn=None, wait_fn=None, publisher_cls=Publisher) -> int:
    parser = argparse.ArgumentParser(prog="FoggyMapCompanion", description=__doc__)
    parser.add_argument("--data", required=True,
                        help="where the plugin writes its CSVs and the fog files go")
    parser.add_argument("--game-data", required=True,
                        help="the game's Data folder, read only to build the map assets")
    parser.add_argument("--assets", help="map assets folder (default: <data>\\assets)")
    parser.add_argument("--game-pid", type=int,
                        help="the game's process, so progress can be published when it exits")
    parser.add_argument("--publish-after-pid", type=int, metavar="PID",
                        help="wait for this process to exit, publish once, then stop")
    args = parser.parse_args(argv)

    assets = args.assets or os.path.join(args.data, "assets")
    config = _publish_config(args.data)

    if args.publish_after_pid is not None:
        if config is not None:
            (wait_fn or wait_for_exit)(args.publish_after_pid)
            print("the game has exited; publishing", flush=True)
            publisher_cls(config, assets, args.data).publish_if_changed()
        return 0

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

    if config is None:
        watch_fn(assets, args.data)
        return 0

    publisher = publisher_cls(config, assets, args.data)
    _start_exit_publisher(args, assets, spawn_fn or spawn_detached)
    watch_fn(assets, args.data, on_tick=publisher.tick)
    return 0


def _publish_config(data_dir):
    try:
        config = load_publish_config(data_dir)
    except PublishError as error:
        print(f"publishing is off: {error}", flush=True)
        return None
    if config is not None:
        print(f"publishing to {config.remote} every {config.interval_minutes:g} minutes",
              flush=True)
    return config


def _start_exit_publisher(args, assets: str, spawn) -> None:
    """The game takes this process down with it, so a separate one publishes on exit."""
    if args.game_pid is None:
        print("no --game-pid, so nothing will publish when the game exits", flush=True)
        return
    command = _self_command() + [
        "--data", args.data, "--game-data", args.game_data, "--assets", assets,
        "--publish-after-pid", str(args.game_pid),
    ]
    try:
        spawn(command, os.path.join(args.data, "publish.log"))
    except OSError as error:
        print(f"could not start the exit publisher ({type(error).__name__}: {error}); "
              "progress will publish at the next launch instead", flush=True)
    else:
        print("exit publisher started; its output goes to publish.log", flush=True)


def _self_command() -> list[str]:
    """How to run this program again: the frozen exe alone, or the interpreter plus the
    script it was started with."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(sys.argv[0])]


def spawn_detached(command: list[str], log_path: str) -> None:
    """Start ``command`` outside the companion's job, so it outlives the game.

    Raises OSError if the job forbids breaking away.
    """
    with open(log_path, "w", encoding="utf-8") as log:
        subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW,
        )


def wait_for_exit(pid: int) -> None:
    """Block until the process exits. Returns at once if it is already gone."""
    synchronize, infinite = 0x00100000, 0xFFFFFFFF
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        kernel32.WaitForSingleObject(ctypes.c_void_p(handle), infinite)
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _built_worldspaces(assets_dir: str) -> dict | None:
    """The manifest's worldspace entries, or None if there is no usable manifest."""
    try:
        with open(os.path.join(assets_dir, MANIFEST_NAME), "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _rebuild_reason(have: dict | None, game_data: str) -> str | None:
    if have is None:
        return "no usable manifest"
    # A relief that failed is recorded as None; only a missing key means old assets.
    if any(not isinstance(entry, dict) or "relief" not in entry for entry in have.values()):
        return "assets predate the relief map"
    # DLC installed since the last build would otherwise never get fog.
    available = {
        source.editor_id for source in MAP_SOURCES
        if os.path.isfile(os.path.join(game_data, source.esm))
        and os.path.isfile(os.path.join(game_data, source.archive))
    }
    new = sorted(available - set(have))
    return f"new worldspaces {', '.join(new)}" if new else None
