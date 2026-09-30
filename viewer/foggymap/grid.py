"""Mapping between Fallout 4 world units and pixels of a worldspace's map image."""

from __future__ import annotations

from dataclasses import dataclass

from foggymap.config import CELL_UNITS


@dataclass(frozen=True)
class Grid:
    """Bounds of a worldspace's map image, in world units.

    World Y runs north-positive while image rows run north-to-south, so the two
    disagree on direction and ``to_px`` flips it.
    """

    min_x: float
    min_y: float
    max_x: float
    max_y: float
    width_px: int
    height_px: int

    @classmethod
    def from_cells(
        cls,
        nw_cell_x: int,
        nw_cell_y: int,
        se_cell_x: int,
        se_cell_y: int,
        width_px: int,
        height_px: int,
    ) -> Grid:
        """Build a grid from a WRLD record's MNAM cell bounds.

        The bounds are inclusive of whole cells, so the east and north edges sit on
        the far side of the named cell.
        """
        return cls(
            min_x=nw_cell_x * CELL_UNITS,
            min_y=se_cell_y * CELL_UNITS,
            max_x=(se_cell_x + 1) * CELL_UNITS,
            max_y=(nw_cell_y + 1) * CELL_UNITS,
            width_px=width_px,
            height_px=height_px,
        )

    @property
    def width_units(self) -> float:
        return self.max_x - self.min_x

    @property
    def height_units(self) -> float:
        return self.max_y - self.min_y

    @property
    def units_per_px_x(self) -> float:
        return self.width_units / self.width_px

    @property
    def units_per_px_y(self) -> float:
        return self.height_units / self.height_px

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        """World position to fractional (column, row). Row 0 is the north edge."""
        return (
            (x - self.min_x) / self.units_per_px_x,
            (self.max_y - y) / self.units_per_px_y,
        )

    def from_px(self, col: float, row: float) -> tuple[float, float]:
        """Fractional (column, row) back to a world position."""
        return (
            self.min_x + col * self.units_per_px_x,
            self.max_y - row * self.units_per_px_y,
        )
