"""Building the static site that shows exploration progress on the web.

The output is a folder of plain files -- the page from ``site/`` plus JSON and images
under ``data/`` -- so any static host can serve it. What goes in is chosen with the
web in mind: the fog alone over our own relief map, never Bethesda's map art, and only
the locations the player has already discovered.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from datetime import datetime

import numpy as np
from PIL import Image

from foggymap.config import MAX_SEGMENT_UNITS
from foggymap.grid import Grid
from foggymap.history import load_events
from foggymap.markers import load_pois, marker_kind
from foggymap.mo2 import read_profile
from foggymap.paths import Sample, load_samples
from foggymap.pipboy import fog_opacity
from foggymap.pipeline import Settings, load_manifest, load_worldspace, render
from foggymap.player import load_player, public_profile, redact

# The full map resolution, so the fog stays crisp when the page is zoomed in. It
# compresses to almost nothing: the fog has only a few levels.
MAX_FOG_PX = 2048

# Lossy but visually clean, and a fraction of the size of a PNG of shaded terrain.
RELIEF_QUALITY = 82



def default_template_dir() -> str:
    """The page shipped with this build: bundled beside a frozen companion, or the
    repo's ``site/`` folder when run from source."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return os.path.join(bundle, "site")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "site")


def build_site(
    assets_dir, data_dir, out_dir, now: datetime,
    template_dir=None, settings: Settings | None = None, show_character_name: bool = False,
    mo2_profile=None,
) -> list[str]:
    """Write the whole site into ``out_dir``, returning the worldspaces published.

    ``out_dir`` must be empty or absent: it becomes the entire published site, so
    anything already in it would be published too.
    """
    out_dir = str(out_dir)
    if os.path.isdir(out_dir) and os.listdir(out_dir):
        raise ValueError(f"refusing to build the site into a non-empty folder: {out_dir}")
    shutil.copytree(str(template_dir or default_template_dir()), out_dir, dirs_exist_ok=True)

    settings = settings or Settings()
    summary: dict = {"published_at": now.isoformat(), "worldspaces": {}}
    for editor_id in load_manifest(assets_dir):
        if not _has_progress(data_dir, editor_id):
            continue
        try:
            summary["worldspaces"][editor_id] = _publish_worldspace(
                assets_dir, data_dir, editor_id, os.path.join(out_dir, "data", editor_id),
                settings)
        except Exception as error:  # noqa: BLE001 - one bad map must not stop the others
            print(f"skipped {editor_id}: {type(error).__name__}: {error}", flush=True)

    # The character, if the plugin has written one: the name stays out unless asked for.
    player = load_player(data_dir)
    summary["player"] = player is not None
    if player is not None:
        profile = public_profile(player, show_name=show_character_name)
        if mo2_profile:
            mo2 = _mo2_mods(mo2_profile)
            if mo2 is not None:
                profile["mods"]["mo2"] = mo2
        _write_json(os.path.join(out_dir, "data", "player.json"), profile)
        events = load_events(data_dir)
        if not show_character_name:
            events = redact(events, (player.get("character") or {}).get("name") or "")
        _write_json(os.path.join(out_dir, "data", "timeline.json"), events)

    _write_json(os.path.join(out_dir, "data", "summary.json"), summary)
    return list(summary["worldspaces"])


def _mo2_mods(profile_dir) -> dict | None:
    """Every enabled mod from the MO2 profile, or None -- with the reason printed -- so
    an unreadable profile costs only the fuller list, never the publish."""
    try:
        return read_profile(profile_dir)
    except (OSError, UnicodeDecodeError) as error:
        print(f"could not read the MO2 profile, listing the load order only: "
              f"{type(error).__name__}: {error}", flush=True)
        return None


def path_runs(
    grid: Grid,
    samples: list[Sample],
    min_step_px: float = 1.0,
    max_units: float = MAX_SEGMENT_UNITS,
    max_pause_s: float = 60.0,
) -> list[list[list[float]]]:
    """The recorded path as runs of ``[col, row, seconds_since_previous_point]``.

    A run ends wherever the player did not walk -- the same rule as
    ``paths.build_segments`` -- so replay shows a fast travel as a jump. Points closer
    than ``min_step_px`` to the last kept one are dropped, though a run always keeps its
    final point. The pause is clamped because ``t_ms`` is a tick count that resets on
    reboot and spans idle time, so it can leap or run backwards.
    """
    runs: list[list[list[float]]] = []
    run: list[list[float]] = []
    pending: list[float] | None = None
    previous: Sample | None = None
    kept: Sample | None = None

    def point(sample: Sample, since: Sample | None) -> list[float]:
        col, row = grid.to_px(sample.x, sample.y)
        pause = 0.0 if since is None else (sample.t_ms - since.t_ms) / 1000.0
        return [round(col, 2), round(row, 2), min(max(pause, 0.0), max_pause_s)]

    for sample in samples:
        if previous is not None and math.dist(
                (previous.x, previous.y), (sample.x, sample.y)) > max_units:
            if pending is not None:
                run.append(pending)
            runs.append(run)
            run, pending, kept = [], None, None
        if kept is None:
            run.append(point(sample, None))
            kept = sample
        elif math.dist(grid.to_px(kept.x, kept.y), grid.to_px(sample.x, sample.y)) >= min_step_px:
            run.append(point(sample, kept))
            kept, pending = sample, None
        else:
            pending = point(sample, kept)
        previous = sample

    if pending is not None:
        run.append(pending)
    if run:
        runs.append(run)
    return runs


def _has_progress(data_dir, editor_id: str) -> bool:
    if load_samples(os.path.join(str(data_dir), f"path_{editor_id}.csv")):
        return True
    pois = load_pois(os.path.join(str(data_dir), "markers.csv"), worldspace=editor_id)
    return any(poi.discovered for poi in pois)


def _publish_worldspace(assets_dir, data_dir, editor_id, out, settings) -> dict:
    worldspace = load_worldspace(assets_dir, editor_id)
    grid = worldspace.grid
    fog = render(worldspace, str(data_dir), settings, with_rgb=False)
    samples = load_samples(os.path.join(str(data_dir), f"path_{editor_id}.csv"))
    os.makedirs(out, exist_ok=True)

    _write_fog_png(os.path.join(out, "fog.png"), fog.alpha)
    relief = load_manifest(assets_dir)[editor_id].get("relief")
    if relief:
        Image.open(os.path.join(str(assets_dir), relief)).convert("RGB").save(
            os.path.join(out, "relief.webp"), quality=RELIEF_QUALITY, method=6)
    _write_json(os.path.join(out, "path.json"), path_runs(grid, samples))
    _write_json(os.path.join(out, "markers.json"), [
        {"name": poi.name, "col": round(col, 2), "row": round(row, 2),
         "icon": icon, "kind": kind}
        for poi in fog.pois if poi.discovered
        for col, row in [grid.to_px(poi.x, poi.y)]
        for icon, kind in [marker_kind(poi.marker_type)]
    ])

    last = None
    if fog.player_position is not None:
        last = [round(value, 2) for value in grid.to_px(*fog.player_position)]
    return {
        "width_px": grid.width_px,
        "height_px": grid.height_px,
        "percent_explored": round(fog.percent_area_explored, 2),
        "pois_found": fog.pois_discovered,
        "pois_total": len(fog.pois),
        "samples": fog.sample_count,
        "last_position": last,
        "relief": bool(relief),
        # How far around the path counts as seen, so the replay can uncover the map
        # the way the real fog was built.
        "reveal_radius_px": round(settings.area_radius / grid.units_per_px_x, 2),
    }


def _write_fog_png(path: str, alpha: np.ndarray) -> None:
    """Black with the fog as transparency, so the page can tint it however it likes."""
    opacity = Image.fromarray(fog_opacity(alpha), mode="L")
    width, height = opacity.size
    if width > MAX_FOG_PX:
        opacity = opacity.resize((MAX_FOG_PX, round(height * MAX_FOG_PX / width)), Image.BOX)
    black = Image.new("L", opacity.size, 0)
    Image.merge("LA", (black, opacity)).save(path, optimize=True)


def _write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
