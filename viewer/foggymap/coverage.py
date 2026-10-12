"""Turning a walked path into revealed area.

The player's recorded path is rasterized onto the worldspace's map grid, then
widened by how far they could plausibly notice something. Distances are computed
in world units via the exact per-axis pixel size, so worldspaces whose map image
is not square (Nuka-World) come out right.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from foggymap.config import TILE_CLEAR_THRESHOLD, TILE_PARTIAL_THRESHOLD
from foggymap.grid import Grid
from foggymap.paths import Sample

UNVISITED = 0
PARTIAL = 1
SWEPT = 2


def rasterize_path(
    grid: Grid, samples: list[Sample], segments: list[tuple[Sample, Sample]]
) -> np.ndarray:
    """Mark every pixel the player stood on or walked through.

    Samples are marked individually so a fast travel arrival still earns credit for
    where it landed, even though no segment leads to it.

    Every point is generated in one numpy pass: a Python loop per segment cost most of
    a second on a long playthrough, which delayed every in-game fog update.
    """
    raster = np.zeros((grid.height_px, grid.width_px), dtype=bool)

    points = [_px(grid, samples)]
    if segments:
        points.append(_segment_points(
            _px(grid, [start for start, _ in segments]),
            _px(grid, [end for _, end in segments]),
        ))
    cols, rows = np.concatenate(points, axis=1).astype(int)

    inside = (rows >= 0) & (rows < raster.shape[0]) & (cols >= 0) & (cols < raster.shape[1])
    raster[rows[inside], cols[inside]] = True
    return raster


def _px(grid: Grid, samples: list[Sample]) -> np.ndarray:
    """Fractional (column, row) for each sample, as a 2xN array."""
    x = np.array([sample.x for sample in samples], dtype=float)
    y = np.array([sample.y for sample in samples], dtype=float)
    return np.array(grid.to_px(x, y)).reshape(2, -1)


def _segment_points(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """Points along each segment, dense enough to leave no gaps.

    Reproduces ``np.linspace`` exactly -- start plus index times step, with the end
    point set exactly -- so a pixel on a boundary lands the same way it always has.
    """
    delta = end - start
    steps = np.floor(np.abs(delta).max(axis=0)).astype(int) + 1
    counts = steps + 1

    segment = np.repeat(np.arange(steps.size), counts)
    index = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    points = start[:, segment] + index * (delta / steps)[:, segment]

    last = np.cumsum(counts) - 1
    points[:, last] = end
    return points


def coverage_mask(
    path_raster: np.ndarray,
    grid: Grid,
    radius_units: float,
    close_units: float = 0.0,
) -> np.ndarray:
    """Widen the path by ``radius_units`` to get the area the player effectively saw.

    ``close_units`` bridges slivers left between passes that fell just too far apart,
    so a thoroughly walked area reads as one blob rather than pinstripes. Defaults to
    off so the raw geometry stays testable.
    """
    if not path_raster.any():
        return np.zeros_like(path_raster)

    distance = ndimage.distance_transform_edt(
        ~path_raster, sampling=(grid.units_per_px_y, grid.units_per_px_x)
    )
    revealed = distance <= radius_units

    if close_units > 0:
        revealed = _close_within_bounds(revealed, _disc(grid, close_units))
    return revealed


def _close_within_bounds(mask: np.ndarray, structure: np.ndarray) -> np.ndarray:
    """``binary_closing`` restricted to the revealed area's bounding box.

    Closing the whole map took over a second while most of it is unexplored. Padding
    the box by twice the structure leaves room for the dilation to grow and keeps the
    erosion's view of the edge all False, matching scipy's default border, so the
    result is identical to closing the whole image.
    """
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    pad_y, pad_x = structure.shape
    top, bottom = max(rows[0] - pad_y, 0), min(rows[-1] + pad_y + 1, mask.shape[0])
    left, right = max(cols[0] - pad_x, 0), min(cols[-1] + pad_x + 1, mask.shape[1])

    closed = np.zeros_like(mask)
    closed[top:bottom, left:right] = ndimage.binary_closing(
        mask[top:bottom, left:right], structure
    )
    return closed


def tile_counts(grid: Grid, tile_units: float) -> tuple[int, int]:
    """Number of (rows, columns) of tiles covering the grid."""
    return (
        int(np.ceil(grid.height_units / tile_units)),
        int(np.ceil(grid.width_units / tile_units)),
    )


def _pixel_tile_indices(grid: Grid, tile_units: float) -> tuple[np.ndarray, np.ndarray]:
    """Tile row for each pixel row, and tile column for each pixel column.

    Tile edges do not generally land on whole pixels, so pixels are binned by the
    world position of their centre rather than by dividing pixel indices.
    """
    rows, cols = tile_counts(grid, tile_units)

    col_centres = grid.min_x + (np.arange(grid.width_px) + 0.5) * grid.units_per_px_x
    row_centres = grid.max_y - (np.arange(grid.height_px) + 0.5) * grid.units_per_px_y

    tile_col = np.clip(((col_centres - grid.min_x) // tile_units).astype(int), 0, cols - 1)
    tile_row = np.clip(((grid.max_y - row_centres) // tile_units).astype(int), 0, rows - 1)
    return tile_row, tile_col


def expand_tiles(tile_values: np.ndarray, grid: Grid, tile_units: float) -> np.ndarray:
    """Blow a per-tile array up to one value per pixel."""
    tile_row, tile_col = _pixel_tile_indices(grid, tile_units)
    return tile_values[np.ix_(tile_row, tile_col)]


def tile_scores(mask: np.ndarray, grid: Grid, tile_units: float) -> np.ndarray:
    """Fraction of each tile that ``mask`` covers, as a (rows, columns) array.

    Row 0 is the northernmost tile row, matching image orientation.
    """
    rows, cols = tile_counts(grid, tile_units)
    tile_row, tile_col = _pixel_tile_indices(grid, tile_units)

    flat_index = (tile_row[:, None] * cols + tile_col[None, :]).ravel()
    total = np.bincount(flat_index, minlength=rows * cols)
    covered = np.bincount(flat_index, weights=mask.ravel().astype(float),
                          minlength=rows * cols)

    with np.errstate(invalid="ignore", divide="ignore"):
        scores = np.where(total > 0, covered / total, 0.0)
    return scores.reshape(rows, cols)


def land_tile_mask(
    intensity: np.ndarray, grid: Grid, tile_units: float, min_content: float = 0.005
) -> np.ndarray:
    """Which tiles contain any drawn map at all.

    Out-of-bounds areas are flat black on the Pip-Boy map, while land carries contour
    lines, roads or buildings. Without this the void would sit permanently in the
    unexplored column and no playthrough could reach 100%.

    This is deliberately permissive and known to be approximate: the Commonwealth map
    draws bathymetric contours over open water and a grid over everything, so some
    unreachable tiles still count as land. That biases the explored percentage
    downwards, which is the safe direction -- it never claims you have finished an
    area you have not. Raise ``min_content`` to trim thin-content tiles.
    """
    return tile_scores(intensity > 0, grid, tile_units) > min_content


def classify_tiles(
    scores: np.ndarray,
    clear_threshold: float = TILE_CLEAR_THRESHOLD,
    partial_threshold: float = TILE_PARTIAL_THRESHOLD,
) -> np.ndarray:
    """Bucket tile coverage fractions into SWEPT / PARTIAL / UNVISITED."""
    classes = np.full(scores.shape, UNVISITED, dtype=np.int8)
    classes[scores >= partial_threshold] = PARTIAL
    classes[scores >= clear_threshold] = SWEPT
    return classes


def _disc(grid: Grid, radius_units: float) -> np.ndarray:
    """A round structuring element of the given world radius."""
    ry = max(1, int(round(radius_units / grid.units_per_px_y)))
    rx = max(1, int(round(radius_units / grid.units_per_px_x)))
    yy, xx = np.ogrid[-ry : ry + 1, -rx : rx + 1]
    return (yy / ry) ** 2 + (xx / rx) ** 2 <= 1.0
