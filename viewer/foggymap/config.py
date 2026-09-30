"""Tunable constants, all in Fallout 4 world units unless named otherwise.

Fallout 4 uses 70 world units per metre and 4096 units per exterior cell.
"""

UNITS_PER_METRE = 70.0
CELL_UNITS = 4096

# Consecutive samples further apart than this were not walked -- the player fast
# travelled, or emerged from an interior somewhere else. Well above sprint speed
# (a few hundred units/second) so real movement is never rejected.
MAX_SEGMENT_UNITS = 2048.0

# How far the player can plausibly notice something worth investigating. A single
# global estimate, never terrain-aware. 8192 units (117 m) is two exterior cells,
# which is how far full-detail cells load at uGridsToLoad=5 -- beyond that things
# are distant LOD rather than noticeable objects.
SIGHT_DISTANCE_UNITS = 8192.0

# Fraction of sight distance that counts as swept. Raise it to walk less and trust
# more; lower it to be stricter. This number carries no guarantee about missed
# locations -- that lives entirely in the POI fog layer.
SIGHT_FRACTION = 0.60

# Tile size for the coarse "did I sweep this?" score, in exterior cells.
#
# One cell (58 m) rather than two: the area fog radius works out to ~4915 units,
# which exceeds a single cell, so a pass anywhere in or beside a tile clears the
# whole tile. At two cells a pass along a tile boundary only reaches 60% of each
# adjoining tile, leaving partial rows behind a perfectly good sweep.
TILE_CELLS = 1
TILE_UNITS = CELL_UNITS * TILE_CELLS

# Tile coverage fractions separating "swept" from "worth another look" from "unvisited".
TILE_CLEAR_THRESHOLD = 0.85
TILE_PARTIAL_THRESHOLD = 0.35


# Fog opacity. Informational only -- the map underneath must always stay readable, so
# these are tints rather than covers.
FOG_ALPHA_UNVISITED = 0.55
FOG_ALPHA_PARTIAL = 0.28

# Each POI owns a disc this big, cleared only by discovering that POI. Small enough to
# read as a marker on the location rather than a claim about the area around it.
POI_FOG_RADIUS_UNITS = 2048.0

# Keeps POI discs visible when zoomed out far enough that the world radius would
# shrink below a few pixels.
POI_MIN_SCREEN_PX = 4


def area_fog_radius_units(
    sight_distance: float = SIGHT_DISTANCE_UNITS, sight_fraction: float = SIGHT_FRACTION
) -> float:
    """Radius around the walked path that counts as explored."""
    return sight_distance * sight_fraction
