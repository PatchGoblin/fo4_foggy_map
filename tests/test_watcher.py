"""Noticing when the plugin has written new data.

Re-rendering on a blind timer was the cause of the viewer feeling laggy: a full render
costs about a second, and most ticks have nothing new to show.
"""

from foggymap.watcher import fingerprint


def test_fingerprint_is_stable_when_nothing_changes(tmp_path):
    (tmp_path / "path_Test.csv").write_text("t_ms,x,y,z\n0,1,2,3\n")

    assert fingerprint(tmp_path, "Test") == fingerprint(tmp_path, "Test")


def test_fingerprint_changes_when_samples_are_appended(tmp_path):
    csv = tmp_path / "path_Test.csv"
    csv.write_text("t_ms,x,y,z\n0,1,2,3\n")
    before = fingerprint(tmp_path, "Test")

    with csv.open("a") as handle:
        handle.write("1000,4,5,6\n")

    assert fingerprint(tmp_path, "Test") != before


def test_fingerprint_changes_when_markers_are_rewritten(tmp_path):
    markers = tmp_path / "markers.csv"
    markers.write_text("worldspace,form_id,name,x,y,radius,marker_type,discovered\n")
    before = fingerprint(tmp_path, "Test")

    markers.write_text(
        "worldspace,form_id,name,x,y,radius,marker_type,discovered\nTest,0x1,A,0,0,,1,1\n"
    )

    assert fingerprint(tmp_path, "Test") != before


def test_fingerprint_tracks_each_worldspace_separately(tmp_path):
    (tmp_path / "path_Alpha.csv").write_text("t_ms,x,y,z\n0,1,2,3\n")

    assert fingerprint(tmp_path, "Alpha") != fingerprint(tmp_path, "Beta")


def test_missing_files_fingerprint_without_raising(tmp_path):
    assert fingerprint(tmp_path, "Test") == fingerprint(tmp_path, "Test")
