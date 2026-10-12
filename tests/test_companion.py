"""The companion's entry point: arguments, first-run asset build, then watch."""

import json

import pytest

from foggymap.companion import main


class Recorder:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result if result is not None else {"Commonwealth": {}}
        self.error = error

    def __call__(self, *args, **kwargs):
        self.calls.append(args + ((kwargs,) if kwargs else ()))
        if self.error:
            raise self.error
        return self.result


def _write_manifest(assets_dir):
    assets_dir.mkdir(parents=True)
    (assets_dir / "worldspaces.json").write_text(
        json.dumps({"Commonwealth": {"relief": "relief_Commonwealth.png"}}))


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


def _install(game_data, *names):
    game_data.mkdir(parents=True, exist_ok=True)
    for name in names:
        (game_data / name).write_bytes(b"")


def test_dlc_installed_since_the_last_build_triggers_a_rebuild(tmp_path):
    """Otherwise a player who buys Far Harbor later never gets fog there."""
    data = tmp_path / "data"
    _write_manifest(data / "assets")  # Commonwealth only
    game = tmp_path / "Data"
    _install(game, "DLCCoast.esm", "DLCCoast - Textures.ba2")
    build = Recorder()

    main(["--data", str(data), "--game-data", str(game)], watch_fn=Recorder(), build_fn=build)

    assert build.calls == [(str(game), str(data / "assets"))]


def test_a_failed_rebuild_keeps_watching_with_the_assets_it_has(tmp_path, capsys):
    data = tmp_path / "data"
    _write_manifest(data / "assets")
    game = tmp_path / "Data"
    _install(game, "DLCCoast.esm", "DLCCoast - Textures.ba2")
    watch = Recorder()

    code = main(["--data", str(data), "--game-data", str(game)],
                watch_fn=watch, build_fn=Recorder(error=ValueError("corrupt archive")))

    assert code == 0
    assert watch.calls == [(str(data / "assets"), str(data))]
    assert "corrupt archive" in capsys.readouterr().out


def test_assets_from_before_the_relief_map_are_rebuilt(tmp_path, capsys):
    """Otherwise an existing install would never get a map for its published site."""
    data = tmp_path / "data"
    (data / "assets").mkdir(parents=True)
    (data / "assets" / "worldspaces.json").write_text(json.dumps({"Commonwealth": {"image": "x.png"}}))
    build = Recorder()

    main(["--data", str(data), "--game-data", "unused"], watch_fn=Recorder(), build_fn=build)

    assert build.calls == [("unused", str(data / "assets"))]
    assert "relief" in capsys.readouterr().out


def test_a_relief_that_failed_to_build_is_not_retried_every_launch(tmp_path):
    data = tmp_path / "data"
    (data / "assets").mkdir(parents=True)
    (data / "assets" / "worldspaces.json").write_text(json.dumps({"Commonwealth": {"relief": None}}))
    build = Recorder()

    main(["--data", str(data), "--game-data", "unused"], watch_fn=Recorder(), build_fn=build)

    assert build.calls == []


def test_an_unreadable_manifest_is_rebuilt(tmp_path):
    """A manifest cut short by a kill mid-write must not wedge every later launch."""
    data = tmp_path / "data"
    (data / "assets").mkdir(parents=True)
    (data / "assets" / "worldspaces.json").write_text("")
    build = Recorder()

    main(["--data", str(data), "--game-data", "unused"], watch_fn=Recorder(), build_fn=build)

    assert build.calls == [("unused", str(data / "assets"))]


# --- publishing ----------------------------------------------------------------------


class FakePublisher:
    instances = []

    def __init__(self, config, assets_dir, data_dir):
        self.config, self.assets_dir, self.data_dir = config, assets_dir, data_dir
        self.published = 0
        FakePublisher.instances.append(self)

    def tick(self):
        return False

    def publish_if_changed(self):
        self.published += 1
        return True


@pytest.fixture(autouse=True)
def _fresh_publishers():
    FakePublisher.instances = []


@pytest.fixture
def publishing(tmp_path):
    data = tmp_path / "data"
    _write_manifest(data / "assets")
    (data / "publish.ini").write_text(
        "[Publish]\nEnabled=1\nRemote=https://example.invalid/site.git\n"
        "AuthorName=Bot\nAuthorEmail=bot@example.invalid\n")
    return data


def _run(data, *extra, spawn=None, wait=None, watch=None):
    return main(["--data", str(data), "--game-data", r"X:\Game\Data", *extra],
                watch_fn=watch or Recorder(), build_fn=Recorder(),
                spawn_fn=spawn or Recorder(), wait_fn=wait or Recorder(),
                publisher_cls=FakePublisher)


def test_without_publish_ini_nothing_publishes(tmp_path):
    data = tmp_path / "data"
    _write_manifest(data / "assets")
    watch, spawn = Recorder(), Recorder()

    _run(data, "--game-pid", "42", watch=watch, spawn=spawn)

    assert watch.calls == [(str(data / "assets"), str(data))]
    assert spawn.calls == []
    assert FakePublisher.instances == []


def test_publishing_rides_the_watch_loop(publishing):
    watch = Recorder()

    _run(publishing, watch=watch)

    (publisher,) = FakePublisher.instances
    assert publisher.config.remote == "https://example.invalid/site.git"
    assert watch.calls == [(str(publishing / "assets"), str(publishing),
                            {"on_tick": publisher.tick})]


def test_starts_an_exit_publisher_for_the_game(publishing):
    spawn = Recorder()

    _run(publishing, "--game-pid", "4242", spawn=spawn)

    ((command, log),) = spawn.calls
    assert command[command.index("--publish-after-pid") + 1] == "4242"
    assert command[command.index("--data") + 1] == str(publishing)
    assert command[command.index("--assets") + 1] == str(publishing / "assets")
    assert log == str(publishing / "publish.log")


def test_without_a_game_pid_there_is_no_exit_publish_and_it_says_so(publishing, capsys):
    spawn = Recorder()

    _run(publishing, spawn=spawn)

    assert spawn.calls == []
    assert "no --game-pid" in capsys.readouterr().out


def test_an_exit_publisher_that_cannot_start_is_reported_not_fatal(publishing, capsys):
    """MO2's own job may forbid breaking away; the next launch catches up instead."""
    watch = Recorder()

    code = _run(publishing, "--game-pid", "1", watch=watch,
                spawn=Recorder(error=PermissionError("access denied")))

    assert code == 0
    assert len(watch.calls) == 1
    assert "access denied" in capsys.readouterr().out


def test_a_broken_publish_ini_is_reported_and_the_fog_still_runs(publishing, capsys):
    (publishing / "publish.ini").write_text("[Publish]\nEnabled=1\n")
    watch = Recorder()

    _run(publishing, watch=watch)

    assert watch.calls == [(str(publishing / "assets"), str(publishing))]
    assert "Remote" in capsys.readouterr().out


def test_exit_mode_waits_for_the_game_then_publishes_once(publishing):
    wait, watch = Recorder(), Recorder()

    code = _run(publishing, "--assets", str(publishing / "assets"),
                "--publish-after-pid", "4242", wait=wait, watch=watch)

    assert code == 0
    assert wait.calls == [(4242,)]
    assert [p.published for p in FakePublisher.instances] == [1]
    assert watch.calls == [], "exit mode never takes over the fog"


def test_exit_mode_with_publishing_off_does_nothing(tmp_path):
    data = tmp_path / "data"
    _write_manifest(data / "assets")

    assert _run(data, "--publish-after-pid", "1") == 0
    assert FakePublisher.instances == []


def test_wait_for_exit_returns_once_the_process_ends():
    import subprocess
    import sys
    import time

    from foggymap.companion import wait_for_exit

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    started = time.monotonic()
    wait_for_exit(child.pid)

    assert child.poll() is not None or child.wait(timeout=1) == 0
    assert time.monotonic() - started >= 0.3


def test_wait_for_exit_returns_at_once_for_a_process_already_gone():
    import subprocess
    import sys

    from foggymap.companion import wait_for_exit

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()

    wait_for_exit(child.pid)  # must not hang


def test_spawn_detached_runs_the_command_into_its_log(tmp_path):
    import sys
    import time

    from foggymap.companion import spawn_detached

    log = tmp_path / "publish.log"
    spawn_detached([sys.executable, "-c", "print('hello from the exit publisher')"], str(log))

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and "hello" not in log.read_text(encoding="utf-8"):
        time.sleep(0.05)
    assert "hello from the exit publisher" in log.read_text(encoding="utf-8")
