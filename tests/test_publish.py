"""Building the static site payload: what a published progress page is made of."""

import json
import os
from datetime import datetime, timezone

import numpy as np
import pytest
from PIL import Image

from foggymap.paths import Sample
from foggymap.markers import marker_kind
from foggymap.publish import build_site, path_runs
from foggymap.grid import Grid

CELL = 4096
NOW = datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc)
MARKER_HEADER = "worldspace,form_id,name,x,y,radius,marker_type,discovered,disabled"


@pytest.fixture
def assets(tmp_path):
    directory = tmp_path / "assets"
    directory.mkdir()
    intensity = np.zeros((64, 64), dtype=np.uint8)
    intensity[:, :32] = 180  # land in the west half only
    manifest = {}
    relief = np.zeros((65, 65, 3), dtype=np.uint8)
    relief[:, :, 1] = 130
    for editor_id in ("Commonwealth", "NukaWorld"):
        Image.fromarray(intensity, mode="L").save(directory / f"worldmap_{editor_id}.png")
        Image.fromarray(relief, mode="RGB").save(directory / f"relief_{editor_id}.png")
        manifest[editor_id] = {
            "editor_id": editor_id, "nw_cell": [0, 1], "se_cell": [1, 0],
            "width_px": 64, "height_px": 64, "image": f"worldmap_{editor_id}.png",
            "relief": f"relief_{editor_id}.png",
        }
    (directory / "worldspaces.json").write_text(json.dumps(manifest))
    return directory


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "path_Commonwealth.csv").write_text(
        "t_ms,x,y,z\n" + "".join(
            f"{i * 1000},{0.5 * CELL},{0.2 * CELL + i * 150.0},0\n" for i in range(40)
        )
    )
    (directory / "markers.csv").write_text(
        MARKER_HEADER + "\n"
        + f'Commonwealth,0x1,"Found Place",{0.5 * CELL},{0.5 * CELL},,15,1,0\n'
        + f'Commonwealth,0x2,"Secret Place",{1.5 * CELL},{1.5 * CELL},,3,0,0\n'
        + f'Commonwealth,0x3,"Disabled Place",{1.0 * CELL},{1.0 * CELL},,3,1,1\n'
    )
    return directory


@pytest.fixture
def template(tmp_path):
    directory = tmp_path / "template"
    directory.mkdir()
    (directory / "index.html").write_text("<!doctype html>")
    (directory / "js").mkdir()
    (directory / "js" / "app.js").write_text("// app")
    return directory


def _build(assets, data, tmp_path, template):
    out = tmp_path / "out"
    published = build_site(assets, data, out, NOW, template_dir=template)
    return out, published


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_copies_the_page_template(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    assert (out / "index.html").read_text() == "<!doctype html>"
    assert (out / "js" / "app.js").read_text() == "// app"


def test_only_worldspaces_with_progress_are_published(assets, data, tmp_path, template):
    """Listing a DLC the player has never visited would announce it for nothing."""
    out, published = _build(assets, data, tmp_path, template)

    assert published == ["Commonwealth"]
    assert list(_read(out / "data" / "summary.json")["worldspaces"]) == ["Commonwealth"]
    assert not (out / "data" / "NukaWorld").exists()


def test_summary_carries_the_stats(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    summary = _read(out / "data" / "summary.json")
    stats = summary["worldspaces"]["Commonwealth"]
    assert summary["published_at"] == "2026-10-12T15:30:00+00:00"
    assert stats["samples"] == 40
    assert stats["pois_found"] == 1
    assert stats["pois_total"] == 2, "disabled markers are not on the map"
    assert 0.0 < stats["percent_explored"] <= 100.0
    assert stats["width_px"] == 64 and stats["height_px"] == 64
    col, row = stats["last_position"]
    assert col == pytest.approx(16.0, abs=0.01)
    assert row == pytest.approx(64 - (0.2 * CELL + 39 * 150.0) / 128, abs=0.01)


def test_only_discovered_markers_are_published(assets, data, tmp_path, template):
    """No spoilers: an undiscovered location must not appear anywhere in the payload."""
    out, _ = _build(assets, data, tmp_path, template)

    markers = _read(out / "data" / "Commonwealth" / "markers.json")
    assert [m["name"] for m in markers] == ["Found Place"]
    assert markers[0]["col"] == pytest.approx(16.0)
    assert markers[0]["row"] == pytest.approx(48.0)
    for file in out.rglob("*"):
        if file.is_file():
            assert b"Secret Place" not in file.read_bytes(), file


def test_fog_is_a_transparent_png_of_the_fog_alone(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    fog = Image.open(out / "data" / "Commonwealth" / "fog.png")
    assert fog.mode == "LA"
    assert fog.size == (64, 64)
    luminance, alpha = (np.array(band) for band in fog.split())
    assert luminance.max() == 0, "the map art must never be published"
    assert alpha.min() == 0, "walked ground is clear"
    assert alpha.max() > 0, "unwalked ground is fogged"


def test_fog_keeps_the_map_resolution_for_zooming(assets, data, tmp_path, template):
    manifest = _read(assets / "worldspaces.json")
    big = np.zeros((2048, 2048), dtype=np.uint8)
    Image.fromarray(big, mode="L").save(assets / "worldmap_Commonwealth.png")
    # A real map's scale (128 units/px); a tiny worldspace stretched this big would make
    # the sight radius thousands of pixels wide.
    manifest["Commonwealth"].update(nw_cell=[0, 63], se_cell=[63, 0], width_px=2048, height_px=2048)
    (assets / "worldspaces.json").write_text(json.dumps(manifest))

    out, _ = _build(assets, data, tmp_path, template)

    assert Image.open(out / "data" / "Commonwealth" / "fog.png").size == (2048, 2048)


def test_publishes_our_relief_map_not_the_game_art(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    relief = Image.open(out / "data" / "Commonwealth" / "relief.webp")
    assert relief.size == (65, 65)
    assert _read(out / "data" / "summary.json")["worldspaces"]["Commonwealth"]["relief"] is True


def test_assets_without_a_relief_still_publish(assets, data, tmp_path, template):
    """Terrain that could not be read costs the backdrop, not the page."""
    manifest = _read(assets / "worldspaces.json")
    manifest["Commonwealth"]["relief"] = None
    (assets / "worldspaces.json").write_text(json.dumps(manifest))

    out, published = _build(assets, data, tmp_path, template)

    assert published == ["Commonwealth"]
    assert not (out / "data" / "Commonwealth" / "relief.webp").exists()
    assert _read(out / "data" / "summary.json")["worldspaces"]["Commonwealth"]["relief"] is False


def test_markers_say_what_kind_of_place_they_are(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    (vault,) = _read(out / "data" / "Commonwealth" / "markers.json")
    assert (vault["icon"], vault["kind"]) == ("cog", "Vault")


def test_an_unknown_marker_type_gets_a_plain_pin():
    assert marker_kind(9999) == ("map-pin", "Location")


def test_every_icon_the_markers_use_ships_with_the_page():
    """icons.js is generated by tools/fetch_icons.py; rerun it after changing the table."""
    from foggymap.markers import MARKER_KINDS
    from foggymap.publish import default_template_dir

    with open(os.path.join(default_template_dir(), "icons.js"), encoding="utf-8") as handle:
        shipped = handle.read()
    for icon in {icon for icon, _ in MARKER_KINDS.values()} | {"map-pin"}:
        assert f'"{icon}":' in shipped, icon


def test_no_map_image_is_published(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    assert not list(out.rglob("worldmap_*"))


def test_path_is_published_for_replay(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    runs = _read(out / "data" / "Commonwealth" / "path.json")
    assert len(runs) == 1
    first, last = runs[0][0], runs[0][-1]
    assert first[:2] == pytest.approx([16.0, 64 - 0.2 * CELL / 128], abs=0.01)
    assert last[:2] == pytest.approx([16.0, 64 - (0.2 * CELL + 39 * 150.0) / 128], abs=0.01)


def test_refuses_to_build_into_a_folder_with_something_in_it(assets, data, tmp_path, template):
    """The output becomes the whole site; stray files would be published with it."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "stray.txt").write_text("x")

    with pytest.raises(ValueError):
        build_site(assets, data, out, NOW, template_dir=template)


def test_a_broken_worldspace_is_skipped_not_fatal(assets, data, tmp_path, template, capsys):
    (data / "path_NukaWorld.csv").write_text("t_ms,x,y,z\n0,10,10,0\n")
    (assets / "worldmap_NukaWorld.png").unlink()

    out, published = _build(assets, data, tmp_path, template)

    assert published == ["Commonwealth"]
    assert "skipped NukaWorld" in capsys.readouterr().out


GRID = Grid(min_x=0, min_y=0, max_x=64 * 128, max_y=64 * 128, width_px=64, height_px=64)


def test_runs_break_where_the_player_did_not_walk():
    """A fast travel is a jump, not a line across the map."""
    samples = [Sample(0, 0, 0, 0), Sample(1000, 500, 0, 0),
               Sample(2000, 6000, 0, 0), Sample(3000, 6500, 0, 0)]

    runs = path_runs(GRID, samples)

    assert len(runs) == 2
    assert [p[0] for p in runs[0]] == pytest.approx([0.0, 500 / 128], abs=0.01)
    assert [p[0] for p in runs[1]] == pytest.approx([6000 / 128, 6500 / 128], abs=0.01)


def test_runs_are_thinned_but_keep_their_ends():
    samples = [Sample(i * 1000, i * 10.0, 0, 0) for i in range(100)]  # 10 units = 0.08 px apart

    (run,) = path_runs(GRID, samples, min_step_px=1.0)

    assert len(run) < 20
    assert run[0][0] == pytest.approx(0.0)
    assert run[-1][0] == pytest.approx(990 / 128, abs=0.01)


def test_pacing_is_seconds_since_the_previous_point_clamped():
    """t_ms is a tick count that resets on reboot, so it can run backwards or leap ahead."""
    samples = [Sample(5000, 0, 0, 0), Sample(7000, 500, 0, 0),
               Sample(10_000_000, 1000, 0, 0), Sample(100, 1500, 0, 0)]

    (run,) = path_runs(GRID, samples, max_pause_s=60.0)

    assert [p[2] for p in run] == [0.0, 2.0, 60.0, 0.0]


def test_the_page_ships_with_the_code():
    """Run from source, the template is the repo's site/ folder, complete."""
    from foggymap.publish import default_template_dir

    folder = default_template_dir()

    for name in ("index.html", "app.js", "dossier.js", "icons.js", "style.css", "amplify.yml"):
        assert os.path.isfile(os.path.join(folder, name)), name


def test_a_frozen_build_finds_the_bundled_page(monkeypatch, tmp_path):
    import sys

    from foggymap.publish import default_template_dir

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert default_template_dir() == os.path.join(str(tmp_path), "site")


def _player(data, name="Nora"):
    (data / "player.json").write_text(json.dumps({
        "version": 1,
        "character": {"name": name, "sex": 1, "level": 37, "xp": 56183.89, "caps": 10},
    }), encoding="utf-8")


def test_publishes_the_players_profile_without_their_name(assets, data, tmp_path, template):
    _player(data)

    out, _ = _build(assets, data, tmp_path, template)

    profile = _read(out / "data" / "player.json")
    assert profile["level"] == 37 and profile["name"] == "The Sole Survivor"
    assert _read(out / "data" / "summary.json")["player"] is True
    assert b"Nora" not in (out / "data" / "player.json").read_bytes()


def test_the_name_is_published_when_asked_for(assets, data, tmp_path, template):
    _player(data)
    out = tmp_path / "out"

    build_site(assets, data, out, NOW, template_dir=template, show_character_name=True)

    assert _read(out / "data" / "player.json")["name"] == "Nora"


def test_publishes_the_timeline_newest_first(assets, data, tmp_path, template):
    _player(data)
    (data / "timeline.jsonl").write_text(
        '{"kind": "tracking_began", "text": "Started tracking at level 36"}\n'
        '{"kind": "level", "text": "Reached level 37"}\n', encoding="utf-8")

    out, _ = _build(assets, data, tmp_path, template)

    timeline = _read(out / "data" / "timeline.json")
    assert [e["text"] for e in timeline] == ["Reached level 37", "Started tracking at level 36"]


def test_no_player_file_means_no_player_section(assets, data, tmp_path, template):
    out, _ = _build(assets, data, tmp_path, template)

    assert _read(out / "data" / "summary.json")["player"] is False
    assert not (out / "data" / "player.json").exists()


def test_summary_says_how_far_the_walker_reveals_in_map_pixels(assets, data, tmp_path, template):
    """The replay uncovers the map as it goes, matching the real fog's sight radius."""
    from foggymap.pipeline import Settings

    out, _ = _build(assets, data, tmp_path, template)

    stats = _read(out / "data" / "summary.json")["worldspaces"]["Commonwealth"]
    assert stats["reveal_radius_px"] == pytest.approx(Settings().area_radius / 128, abs=0.01)


def test_a_hidden_name_is_redacted_from_the_timeline(assets, data, tmp_path, template):
    _player(data)
    (data / "timeline.jsonl").write_text('{"kind": "quest_started", "text": "Started Nora\'s Revenge"}\n',
                                         encoding="utf-8")

    out, _ = _build(assets, data, tmp_path, template)

    assert _read(out / "data" / "timeline.json")[0]["text"] == "Started [name]'s Revenge"


def _mo2_profile(tmp_path):
    profile = tmp_path / "mo2" / "profiles" / "Main"
    profile.mkdir(parents=True)
    (profile / "modlist.txt").write_text("+Texture Pack\n-Looks_separator\n", encoding="utf-8")
    return profile


def test_the_mo2_mod_list_is_published_when_a_profile_is_set(assets, data, tmp_path, template):
    _player(data)
    out = tmp_path / "out"

    build_site(assets, data, out, NOW, template_dir=template, mo2_profile=_mo2_profile(tmp_path))

    mo2 = _read(out / "data" / "player.json")["mods"]["mo2"]
    assert mo2["groups"] == [{"label": "Looks", "mods": [{"name": "Texture Pack", "plugins": [], "dlls": []}]}]


def test_without_a_profile_the_mod_list_is_the_load_order_alone(assets, data, tmp_path, template):
    _player(data)

    out, _ = _build(assets, data, tmp_path, template)

    assert "mo2" not in _read(out / "data" / "player.json")["mods"]


def test_an_unreadable_profile_falls_back_to_the_load_order(assets, data, tmp_path, template, capsys):
    _player(data)
    out = tmp_path / "out"

    build_site(assets, data, out, NOW, template_dir=template, mo2_profile=tmp_path / "no such profile")

    assert "mo2" not in _read(out / "data" / "player.json")["mods"]
    assert "MO2 profile" in capsys.readouterr().out
