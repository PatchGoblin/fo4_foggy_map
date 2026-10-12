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
from foggymap.markers import load_pois
from foggymap.paths import Sample, load_samples
from foggymap.pipboy import fog_opacity
from foggymap.pipeline import Settings, load_manifest, load_worldspace, render

# The full map resolution, so the fog stays crisp when the page is zoomed in. It
# compresses to almost nothing: the fog has only a few levels.
MAX_FOG_PX = 2048

# Lossy but visually clean, and a fraction of the size of a PNG of shaded terrain.
RELIEF_QUALITY = 82

# What each map marker type is, as an icon (a Lucide name; see tools/fetch_icons.py)
# and a word for the hover label. Grouped from the names the game gives each type.
MARKER_KINDS: dict[int, tuple[str, str]] = {
    0: ("mountain", "Cave"),
    1: ("building-2", "Apartments"),
    2: ("star", "City"),
    3: ("house", "House"),
    4: ("warehouse", "Workshop"),
    5: ("landmark", "Landmark"),
    6: ("train-front", "Metro station"),
    7: ("shield", "Military base"),
    8: ("flag", "Landmark"),
    9: ("store", "Shop"),
    10: ("house", "Neighbourhood"),
    11: ("building", "Ruins"),
    12: ("house", "Settlement"),
    13: ("map-pin", "Settlement"),
    14: ("construction", "Tunnel"),
    15: ("cog", "Vault"),
    16: ("plane", "Aircraft"),
    17: ("landmark", "Monument"),
    18: ("caravan", "Trailer park"),
    19: ("construction", "Bridge"),
    20: ("church", "Church"),
    22: ("clock", "Tower"),
    23: ("clapperboard", "Entertainment"),
    24: ("construction", "Overpass"),
    25: ("landmark", "Landmark"),
    26: ("wheat", "Farm"),
    27: ("fuel", "Filling station"),
    28: ("trees", "Park"),
    29: ("hotel", "Hotel"),
    30: ("cross", "Cemetery"),
    31: ("hospital", "Hospital"),
    32: ("zap", "Power plant"),
    33: ("factory", "Factory"),
    35: ("fish", "Fishery"),
    36: ("trash-2", "Junkyard"),
    37: ("telescope", "Lookout"),
    38: ("anchor", "Harbour"),
    39: ("droplets", "Lake"),
    40: ("pickaxe", "Quarry"),
    41: ("radiation", "Crater"),
    42: ("radio-tower", "Radio tower"),
    43: ("skull", "Museum"),
    44: ("school", "School"),
    45: ("ship", "Shipwreck"),
    47: ("bird", "Pond"),
    49: ("ferris-wheel", "Amusement park"),
    51: ("shirt", "Shop"),
    52: ("package", "Bunker"),
    53: ("castle", "Fort"),
    54: ("building-2", "Office tower"),
    55: ("sailboat", "Raider fleet"),
    56: ("building", "Roadside stop"),
    58: ("siren", "Police station"),
    61: ("train-front", "Station"),
    62: ("satellite-dish", "Satellite array"),
    63: ("rocket", "Missile silo"),
    64: ("ship", "Ship"),
    66: ("utensils", "Restaurant"),
    70: ("rocket", "Arcade"),
    73: ("train-front", "Station"),
    74: ("ferris-wheel", "Ride"),
    75: ("paw-print", "Safari"),
    78: ("mountain", "Mountain"),
    79: ("building", "Parlour"),
    80: ("music", "Amphitheatre"),
}
UNKNOWN_KIND = ("map-pin", "Location")


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
    template_dir=None, settings: Settings | None = None,
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

    _write_json(os.path.join(out_dir, "data", "summary.json"), summary)
    return list(summary["worldspaces"])


def marker_kind(marker_type: int) -> tuple[str, str]:
    """(icon, label) for a map marker type, or a plain pin for one we have not named."""
    return MARKER_KINDS.get(marker_type, UNKNOWN_KIND)


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
