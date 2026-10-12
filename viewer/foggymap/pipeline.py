"""Loading everything for one worldspace and producing the finished fog image."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image

from foggymap import config
from foggymap.coverage import (
    SWEPT,
    classify_tiles,
    coverage_mask,
    land_tile_mask,
    rasterize_path,
    tile_scores,
)
from foggymap.grid import Grid
from foggymap.markers import Poi, disc_mask, load_pois
from foggymap.paths import build_segments, load_samples
from foggymap.render import fog_alpha, tint_map

MANIFEST_NAME = "worldspaces.json"


@dataclass(frozen=True)
class Settings:
    """The knobs worth exposing to the user."""

    sight_distance: float = config.SIGHT_DISTANCE_UNITS
    sight_fraction: float = config.SIGHT_FRACTION
    tile_units: float = config.TILE_UNITS
    poi_fog_radius: float = config.POI_FOG_RADIUS_UNITS
    poi_min_px: int = config.POI_MIN_SCREEN_PX
    close_units: float = config.CELL_UNITS / 4

    # Off is "no spoilers": undiscovered POIs leave no mark, so the map cannot give
    # away a location the player has not found yet.
    show_missed_pois: bool = True

    @property
    def area_radius(self) -> float:
        return config.area_fog_radius_units(self.sight_distance, self.sight_fraction)


@dataclass(frozen=True)
class Worldspace:
    """Static assets for one worldspace, loaded once."""

    editor_id: str
    grid: Grid
    intensity: np.ndarray


@dataclass(frozen=True)
class FogMap:
    """A rendered fog map plus the numbers worth putting on screen."""

    # None when rendered with ``with_rgb=False``, for callers that need only the mask.
    rgb: np.ndarray | None

    # Raw fog opacity, kept because other renderers (the Pip-Boy exporter) need the
    # mask rather than the tinted image.
    alpha: np.ndarray

    tile_class: np.ndarray
    land_tiles: np.ndarray
    tile_coverage: np.ndarray
    pois: list[Poi]
    sample_count: int

    # Where the player was at the most recent sample, if there is one.
    player_position: tuple[float, float] | None

    @property
    def pois_discovered(self) -> int:
        return sum(1 for poi in self.pois if poi.discovered)

    @property
    def percent_area_explored(self) -> float:
        """Mean coverage across tiles containing drawn land. Approximate by nature."""
        if not self.land_tiles.any():
            return 0.0
        return 100.0 * float(self.tile_coverage[self.land_tiles].mean())

    @property
    def land_tiles_swept(self) -> int:
        return int(((self.tile_class == SWEPT) & self.land_tiles).sum())

    @property
    def land_tile_count(self) -> int:
        return int(self.land_tiles.sum())


def load_manifest(assets_dir) -> dict:
    with open(os.path.join(str(assets_dir), MANIFEST_NAME), "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_worldspace(assets_dir, editor_id: str) -> Worldspace:
    entry = load_manifest(assets_dir)[editor_id]
    grid = Grid.from_cells(
        nw_cell_x=entry["nw_cell"][0],
        nw_cell_y=entry["nw_cell"][1],
        se_cell_x=entry["se_cell"][0],
        se_cell_y=entry["se_cell"][1],
        width_px=entry["width_px"],
        height_px=entry["height_px"],
    )
    image_path = os.path.join(str(assets_dir), entry["image"])
    intensity = np.array(Image.open(image_path).convert("L"))
    return Worldspace(editor_id=editor_id, grid=grid, intensity=intensity)


def render(
    worldspace: Worldspace,
    data_dir: str,
    settings: Settings = Settings(),
    with_rgb: bool = True,
) -> FogMap:
    """Build the fog map for one worldspace from the plugin's recorded data.

    ``with_rgb=False`` skips tinting the map art, which only the desktop window shows.
    """
    grid = worldspace.grid
    samples = load_samples(os.path.join(data_dir, f"path_{worldspace.editor_id}.csv"))
    pois = load_pois(os.path.join(data_dir, "markers.csv"), worldspace=worldspace.editor_id)

    coverage = coverage_mask(
        rasterize_path(grid, samples, build_segments(samples)),
        grid,
        radius_units=settings.area_radius,
        close_units=settings.close_units,
    )
    tile_coverage = tile_scores(coverage, grid, settings.tile_units)

    found_points = [(p.x, p.y) for p in pois if p.discovered]
    missed_points = [(p.x, p.y) for p in pois if not p.discovered]
    cleared = disc_mask(grid, found_points, settings.poi_fog_radius, settings.poi_min_px)
    fogged = (
        disc_mask(grid, missed_points, settings.poi_fog_radius, settings.poi_min_px)
        if settings.show_missed_pois
        else np.zeros(coverage.shape, dtype=bool)
    )

    tile_class = classify_tiles(tile_coverage)
    alpha = fog_alpha(
        grid=grid,
        coverage=coverage,
        tile_class=tile_class,
        poi_cleared=cleared,
        poi_fogged=fogged,
        tile_units=settings.tile_units,
    )

    # POIs are drawn as scene markers by the viewer, not burnt into the fog: outlines
    # here gave away undiscovered locations and could not be toggled off.
    return FogMap(
        rgb=tint_map(worldspace.intensity, alpha) if with_rgb else None,
        alpha=alpha,
        tile_class=tile_class,
        land_tiles=land_tile_mask(worldspace.intensity, grid, settings.tile_units),
        tile_coverage=tile_coverage,
        pois=pois,
        sample_count=len(samples),
        player_position=(samples[-1].x, samples[-1].y) if samples else None,
    )
