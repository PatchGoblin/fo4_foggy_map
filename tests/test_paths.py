"""Turning raw position samples into walkable path segments."""

from foggymap.paths import Sample, build_segments, load_samples


def test_load_samples_reads_the_plugin_csv(tmp_path):
    csv = tmp_path / "path_Commonwealth.csv"
    csv.write_text("t_ms,x,y,z\n0,1.5,-2.5,3.0\n1000,4.0,5.0,6.0\n")

    samples = load_samples(csv)

    assert samples == [Sample(0, 1.5, -2.5, 3.0), Sample(1000, 4.0, 5.0, 6.0)]


def test_load_samples_ignores_a_truncated_final_line(tmp_path):
    """The plugin is killed when the game exits, so the last row may be half written."""
    csv = tmp_path / "path_Commonwealth.csv"
    csv.write_text("t_ms,x,y,z\n0,1.5,-2.5,3.0\n1000,4.0")

    samples = load_samples(csv)

    assert samples == [Sample(0, 1.5, -2.5, 3.0)]


def test_load_samples_on_a_missing_file_is_empty(tmp_path):
    assert load_samples(tmp_path / "nope.csv") == []


def test_fast_travel_jump_produces_no_segment():
    """A fast travel leaves a huge gap between samples; the player never walked it."""
    samples = [
        Sample(0, 0.0, 0.0, 0.0),
        Sample(1000, 60000.0, 0.0, 0.0),  # arrived by fast travel
        Sample(2000, 60200.0, 0.0, 0.0),  # walking again at the destination
    ]

    segments = build_segments(samples)

    assert len(segments) == 1, "only the walk at the destination should count"
    assert segments[0][0].x == 60000.0
    assert segments[0][1].x == 60200.0


def test_adjacent_samples_form_one_segment():
    samples = [Sample(0, 0.0, 0.0, 0.0), Sample(1000, 300.0, 0.0, 0.0)]

    segments = build_segments(samples)

    assert len(segments) == 1
    assert segments[0][0].x == 0.0
    assert segments[0][1].x == 300.0
