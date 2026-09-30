"""Position samples recorded by the F4SE plugin, and the walkable segments between them."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from foggymap.config import MAX_SEGMENT_UNITS

CSV_HEADER = "t_ms,x,y,z"


@dataclass(frozen=True)
class Sample:
    """One recorded player position. Coordinates are raw Fallout 4 world units."""

    t_ms: int
    x: float
    y: float
    z: float


def load_samples(csv_path) -> list[Sample]:
    """Read a ``path_<worldspace>.csv`` written by the plugin.

    Malformed rows are skipped rather than raised on: the plugin is terminated when
    the game exits, so the final row can be half written.
    """
    if not os.path.exists(csv_path):
        return []

    samples: list[Sample] = []
    with open(csv_path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.strip().split(",")
            if len(fields) != 4:
                continue
            try:
                samples.append(
                    Sample(int(fields[0]), float(fields[1]), float(fields[2]), float(fields[3]))
                )
            except ValueError:
                continue  # the header row, or a partially flushed line
    return samples


def build_segments(
    samples: list[Sample], max_units: float = MAX_SEGMENT_UNITS
) -> list[tuple[Sample, Sample]]:
    """Pair up consecutive samples the player plausibly walked between.

    Pairs further apart than ``max_units`` are dropped, which is what stops a fast
    travel from painting a false trail across the map. Both endpoints still get
    credit on their own, because the player really was at each of them.
    """
    return [
        (a, b)
        for a, b in zip(samples, samples[1:])
        if math.dist((a.x, a.y), (b.x, b.y)) <= max_units
    ]
