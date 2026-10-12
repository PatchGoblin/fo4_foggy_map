"""Keeps the in-game Pip-Boy fog current, without a window.

The Pip-Boy overlay is the primary way this mod is used, so what feeds it should not
depend on a GUI staying alive. This module is deliberately Qt-free: it watches the
plugin's CSVs and rewrites the fog files, nothing else. The desktop window remains
useful for detail and for reviewing between sessions, but is now optional.
"""

from __future__ import annotations

import time

from foggymap.pipboy import export_for_pipboy
from foggymap.pipeline import Settings, load_manifest, load_worldspace, render
from foggymap.watcher import fingerprint


def export_once(assets_dir, data_dir, settings: Settings | None = None) -> list[str]:
    """Render and export every worldspace once, returning the files written."""
    return _export(assets_dir, data_dir, list(load_manifest(assets_dir)), settings)


def export_changed(
    assets_dir, data_dir, seen: dict[str, tuple], settings: Settings | None = None
) -> list[str]:
    """Export only the worldspaces whose data changed since ``seen``, which is updated.

    Each worldspace's fingerprint covers its own path file and the shared markers.csv,
    so a step re-renders just the map you are on while a new discovery re-renders all.
    The Commonwealth alone takes most of the time; re-rendering the DLC maps on every
    step only delayed it.
    """
    changed = []
    for editor_id in load_manifest(assets_dir):
        current = fingerprint(data_dir, editor_id)
        if seen.get(editor_id) != current:
            seen[editor_id] = current
            changed.append(editor_id)
    return _export(assets_dir, data_dir, changed, settings) if changed else []


def _export(assets_dir, data_dir, editor_ids, settings: Settings | None) -> list[str]:
    """A worldspace that fails -- a missing image, a malformed file -- is skipped rather
    than aborting the rest, so one broken map cannot stop the others updating.
    """
    settings = settings or Settings()
    written: list[str] = []

    for editor_id in editor_ids:
        try:
            worldspace = load_worldspace(assets_dir, editor_id)
            fog = render(worldspace, str(data_dir), settings, with_rgb=False)
            written.append(export_for_pipboy(worldspace, fog, data_dir))
        except Exception as error:  # noqa: BLE001 - one bad map must not stop the others
            print(f"skipped {editor_id}: {type(error).__name__}: {error}", flush=True)

    return written


def watch(assets_dir, data_dir, interval: float = 1.0) -> None:
    """Export whenever the plugin writes new data. Runs until killed.

    Re-exports only on a fingerprint change, so standing still costs nothing.
    """
    print(f"watching {data_dir} every {interval:g}s", flush=True)
    seen: dict[str, tuple] = {}

    while True:
        written = export_changed(assets_dir, data_dir, seen)
        if written:
            print(f"exported {len(written)} fog files", flush=True)
        time.sleep(interval)
