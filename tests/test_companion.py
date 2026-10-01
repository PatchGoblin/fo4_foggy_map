"""The companion's entry point: arguments, first-run asset build, then watch."""

import json

import pytest

from foggymap.companion import main


class Recorder:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result if result is not None else {"Commonwealth": {}}
        self.error = error

    def __call__(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


def _write_manifest(assets_dir):
    assets_dir.mkdir(parents=True)
    (assets_dir / "worldspaces.json").write_text(json.dumps({"Commonwealth": {}}))


def test_both_paths_are_required():
    with pytest.raises(SystemExit):
        main(["--data", "x"])
    with pytest.raises(SystemExit):
        main(["--game-data", "x"])


def test_builds_assets_under_data_when_missing_then_watches(tmp_path):
    data = tmp_path / "Foggy Map"  # a space, as in real install paths
    build, watch = Recorder(), Recorder()

    code = main(["--data", str(data), "--game-data", r"X:\Game\Data"],
                watch_fn=watch, build_fn=build)

    assert code == 0
    assert build.calls == [(r"X:\Game\Data", str(data / "assets"))]
    assert watch.calls == [(str(data / "assets"), str(data))]


def test_existing_assets_are_not_rebuilt(tmp_path):
    data = tmp_path / "data"
    _write_manifest(data / "assets")
    build, watch = Recorder(), Recorder()

    main(["--data", str(data), "--game-data", "unused"], watch_fn=watch, build_fn=build)

    assert build.calls == []
    assert watch.calls == [(str(data / "assets"), str(data))]


def test_an_explicit_assets_folder_wins(tmp_path):
    custom = tmp_path / "repo_assets"
    _write_manifest(custom)
    watch = Recorder()

    main(["--data", str(tmp_path), "--game-data", "unused", "--assets", str(custom)],
         watch_fn=watch, build_fn=Recorder())

    assert watch.calls == [(str(custom), str(tmp_path))]


def test_a_failed_build_exits_non_zero_without_watching(tmp_path, capsys):
    """Watching a manifest that does not exist would look idle, not broken."""
    build = Recorder(error=RuntimeError("no Fallout4.esm in X:\\Game\\Data"))
    watch = Recorder()

    code = main(["--data", str(tmp_path), "--game-data", r"X:\Game\Data"],
                watch_fn=watch, build_fn=build)

    assert code == 1
    assert watch.calls == []
    assert "no Fallout4.esm" in capsys.readouterr().out


def test_reports_the_paths_it_was_given(tmp_path, capsys):
    """The first thing in companion.log, so a mangled argument is visible at once."""
    main(["--data", str(tmp_path), "--game-data", r"X:\Game\Data"],
         watch_fn=Recorder(), build_fn=Recorder())

    out = capsys.readouterr().out
    assert f"data: {tmp_path}" in out
    assert r"game data: X:\Game\Data" in out
