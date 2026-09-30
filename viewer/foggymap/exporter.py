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
    """Render and export every worldspace once, returning the files written.

    A worldspace that fails -- a missing image, a malformed file -- is skipped rather
    than aborting the rest, so one broken map cannot stop the others updating.
    """
    settings = settings or Settings()
    written: list[str] = []

    for editor_id in load_manifest(assets_dir):
        try:
            worldspace = load_worldspace(assets_dir, editor_id)
            fog = render(worldspace, str(data_dir), settings)
            written.append(export_for_pipboy(worldspace, fog, data_dir))
        except Exception as error:  # noqa: BLE001 - one bad map must not stop the others
            print(f"skipped {editor_id}: {type(error).__name__}: {error}", flush=True)

    return written


def watch(assets_dir, data_dir, interval: float = 3.0) -> None:
    """Export whenever the plugin writes new data. Runs until killed.

    Re-exports only on a fingerprint change, so standing still costs nothing.
    """
    print(f"watching {data_dir} every {interval:g}s", flush=True)
    seen: dict[str, tuple] = {}

    while True:
        editor_ids = list(load_manifest(assets_dir))
        current = {editor_id: fingerprint(data_dir, editor_id) for editor_id in editor_ids}
        if current != seen:
            written = export_once(assets_dir, data_dir)
            print(f"exported {len(written)} fog files", flush=True)
            seen = current
        time.sleep(interval)
