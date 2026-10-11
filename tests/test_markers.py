"""Points of interest and the fog discs they own."""

import numpy as np

from foggymap.grid import Grid
from foggymap.markers import Poi, disc_mask, load_pois

CELL = 4096
SYNTHETIC = Grid(min_x=0.0, min_y=0.0, max_x=10 * CELL, max_y=10 * CELL,
                 width_px=320, height_px=320)

HEADER = "worldspace,form_id,name,x,y,radius,marker_type,discovered"


def test_load_pois_reads_the_plugin_csv(tmp_path):
    csv = tmp_path / "markers.csv"
    csv.write_text(
        f"{HEADER}\n"
        "Commonwealth,0x0021DDB9,Sanctuary Hills,-40789.65,-20621.44,3000,1,1\n"
    )

    pois = load_pois(csv)

    assert len(pois) == 1
    assert pois[0] == Poi(
        worldspace="Commonwealth",
        form_id=0x0021DDB9,
        name="Sanctuary Hills",
        x=-40789.65,
        y=-20621.44,
        radius=3000.0,
        marker_type=1,
        discovered=True,
    )


def test_load_pois_tolerates_a_marker_with_no_radius(tmp_path):
    """Plenty of markers carry no explicit radius and fall back to the game default."""
    csv = tmp_path / "markers.csv"
    csv.write_text(f"{HEADER}\nCommonwealth,0x00248CCE,Somewhere,-90837.6,29422.9,,1,0\n")

    poi = load_pois(csv)[0]

    assert poi.radius is None
    assert poi.discovered is False


def test_load_pois_can_filter_to_one_worldspace(tmp_path):
    csv = tmp_path / "markers.csv"
    csv.write_text(
        f"{HEADER}\n"
        "Commonwealth,0x1,A,0,0,,1,1\n"
        "NukaWorld,0x2,B,0,0,,1,1\n"
    )

    assert [p.name for p in load_pois(csv, worldspace="NukaWorld")] == ["B"]


def test_load_pois_skips_disabled_markers(tmp_path):
    """A disabled marker never shows on the map and can never be discovered.

    Bethesda parks cut locations such as Union's Hope Cathedral behind an initially
    disabled enable parent; treating them as POIs left permanent undiscovered discs.
    """
    csv = tmp_path / "markers.csv"
    csv.write_text(
        f"{HEADER},disabled\n"
        "Commonwealth,0x1,Shown,0,0,,1,0,0\n"
        "Commonwealth,0x000A96E0,Cambridge Graveyard,0,0,,30,0,1\n"
    )

    assert [p.name for p in load_pois(csv)] == ["Shown"]


def test_load_pois_reads_a_csv_from_before_the_disabled_column(tmp_path):
    csv = tmp_path / "markers.csv"
    csv.write_text(f"{HEADER}\nCommonwealth,0x1,Old,0,0,,1,0\n")

    assert [p.name for p in load_pois(csv)] == ["Old"]


def test_disc_mask_covers_the_requested_world_radius():
    radius = 2048.0

    mask = disc_mask(SYNTHETIC, [(5 * CELL, 5 * CELL)], radius_units=radius)

    centre_row = mask[mask.shape[0] // 2]
    width_units = centre_row.sum() * SYNTHETIC.units_per_px_x
    assert abs(width_units - 2 * radius) <= 2 * SYNTHETIC.units_per_px_x


def test_disc_mask_enforces_a_minimum_on_screen_size():
    """A radius of a few world units would otherwise vanish entirely."""
    mask = disc_mask(SYNTHETIC, [(5 * CELL, 5 * CELL)], radius_units=10.0, min_px=4)

    assert mask.sum() > 0
    centre_row = mask[mask.shape[0] // 2]
    assert centre_row.sum() >= 8, "diameter should be at least 2 * min_px"


def test_disc_mask_with_zero_radius_draws_nothing():
    """Turning the POI layer off must not divide by zero."""
    mask = disc_mask(SYNTHETIC, [(5 * CELL, 5 * CELL)], radius_units=0.0, min_px=0)

    assert not mask.any()


def test_disc_mask_with_no_points_is_empty():
    mask = disc_mask(SYNTHETIC, [], radius_units=2048.0)

    assert not mask.any()
    assert mask.shape == (SYNTHETIC.height_px, SYNTHETIC.width_px)


def test_disc_mask_ignores_points_outside_the_map():
    mask = disc_mask(SYNTHETIC, [(-99 * CELL, -99 * CELL)], radius_units=2048.0)

    assert not mask.any()
