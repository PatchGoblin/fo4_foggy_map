"""When the companion publishes, and what it does with publish.ini."""

import json
from datetime import datetime, timezone

import pytest

from foggymap.gitpublish import PublishError
from foggymap.publisher import PublishConfig, Publisher, load_publish_config

HOUR = 3600.0
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)
CONFIG = PublishConfig(remote="https://example.invalid/site.git", author_name="Bot",
                       author_email="bot@example.invalid")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Calls:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return "sha"


@pytest.fixture
def dirs(tmp_path):
    assets, data = tmp_path / "assets", tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    (assets / "worldspaces.json").write_text(json.dumps({"Commonwealth": {}}))
    (data / "path_Commonwealth.csv").write_text("t_ms,x,y,z\n0,1,2,3\n")
    return assets, data


def _publisher(dirs, clock, build=None, push=None, config=CONFIG):
    assets, data = dirs
    return Publisher(config, assets, data, clock=clock, now=lambda: NOW,
                     build=build or Calls(), push=push or Calls())


def _walk(data, more="1,5,6,7\n"):
    with open(data / "path_Commonwealth.csv", "a") as handle:
        handle.write(more)


# --- publish.ini -------------------------------------------------------------------


def test_no_file_means_publishing_is_off(tmp_path):
    assert load_publish_config(tmp_path) is None


def test_disabled_means_off(tmp_path):
    (tmp_path / "publish.ini").write_text("[Publish]\nEnabled=0\nRemote=x\n")

    assert load_publish_config(tmp_path) is None


def test_reads_every_setting(tmp_path):
    (tmp_path / "publish.ini").write_text(
        "; comment\n[Publish]\nEnabled=1\nRemote=https://h/r.git\nBranch=site\n"
        "AuthorName=Bot\nAuthorEmail=b@x\nIntervalMinutes=30\nGit=C:\\Git\\git.exe\nLeakCheck=0\n")

    assert load_publish_config(tmp_path) == PublishConfig(
        remote="https://h/r.git", branch="site", author_name="Bot", author_email="b@x",
        interval_minutes=30.0, git="C:\\Git\\git.exe", leak_check=False)


def test_defaults(tmp_path):
    (tmp_path / "publish.ini").write_text("[Publish]\nEnabled=1\nRemote=r\n")

    config = load_publish_config(tmp_path)

    assert (config.branch, config.interval_minutes, config.git, config.leak_check) == (
        "main", 60.0, "git", True)


def test_enabled_without_a_remote_is_an_error_not_silence(tmp_path):
    (tmp_path / "publish.ini").write_text("[Publish]\nEnabled=1\n")

    with pytest.raises(PublishError, match="Remote"):
        load_publish_config(tmp_path)


# --- scheduling --------------------------------------------------------------------


def test_publishes_unpublished_data_at_startup(dirs):
    """Which also catches up when the last session's exit publish never ran."""
    push = Calls()
    publisher = _publisher(dirs, Clock(), push=push)

    assert publisher.tick() is True
    assert len(push.calls) == 1


def test_nothing_new_since_the_last_publish_means_no_push(dirs):
    _publisher(dirs, Clock()).tick()
    push = Calls()

    later = _publisher(dirs, Clock(), push=push)  # the next session

    assert later.tick() is False
    assert push.calls == []


def test_waits_out_the_interval_before_publishing_again(dirs):
    clock, push = Clock(), Calls()
    publisher = _publisher(dirs, clock, push=push)
    publisher.tick()
    _walk(dirs[1])

    clock.now += HOUR - 1
    assert publisher.tick() is False
    clock.now += 1
    assert publisher.tick() is True
    assert len(push.calls) == 2


def test_an_unchanged_hour_publishes_nothing(dirs):
    clock, push = Clock(), Calls()
    publisher = _publisher(dirs, clock, push=push)
    publisher.tick()

    clock.now += 2 * HOUR
    assert publisher.tick() is False
    assert len(push.calls) == 1


def test_builds_into_a_fresh_staging_folder_and_pushes_it(dirs):
    assets, data = dirs
    build, push = Calls(), Calls()
    staging = data / "publish" / "staging"
    staging.mkdir(parents=True)
    (staging / "left_over.txt").write_text("x")

    _publisher(dirs, Clock(), build=build, push=push).tick()

    (build_args, _), = build.calls
    assert build_args[:4] == (assets, data, str(staging), NOW)
    assert not (staging / "left_over.txt").exists()
    (_, push_kwargs), = push.calls
    assert push_kwargs["staging_dir"] == str(staging)
    assert push_kwargs["repo_dir"] == str(data / "publish" / "repo.git")
    assert push_kwargs["remote"] == CONFIG.remote
    assert push_kwargs["author_name"] == "Bot"
    assert push_kwargs["leak_terms"] is None, "None means the full default scan"


def test_leak_check_off_passes_no_terms(dirs):
    push = Calls()
    config = PublishConfig(remote="r", author_name="a", author_email="e", leak_check=False)

    _publisher(dirs, Clock(), push=push, config=config).tick()

    assert push.calls[0][1]["leak_terms"] == []


def test_a_failure_is_reported_and_retried_later_not_every_second(dirs, capsys):
    clock = Clock()
    push = Calls(error=PublishError("git push failed: offline"))
    publisher = _publisher(dirs, clock, push=push)

    assert publisher.tick() is False
    assert "offline" in capsys.readouterr().out
    clock.now += 60
    publisher.tick()
    assert len(push.calls) == 1, "no hammering"

    clock.now += 5 * 60
    publisher.tick()
    assert len(push.calls) == 2, "but a retry well before the hour is up"


def test_an_unexpected_error_is_reported_never_raised(dirs, capsys):
    """The watch loop also feeds the Pip-Boy; publishing must never take it down."""
    publisher = _publisher(dirs, Clock(), build=Calls(error=MemoryError("boom")))

    assert publisher.tick() is False
    assert "MemoryError: boom" in capsys.readouterr().out


def test_a_failed_publish_is_retried_next_session(dirs):
    _publisher(dirs, Clock(), push=Calls(error=PublishError("offline"))).tick()
    push = Calls()

    _publisher(dirs, Clock(), push=push).tick()

    assert len(push.calls) == 1


def test_publish_now_ignores_the_interval_but_not_the_data(dirs):
    """What the exit publisher runs once the game has closed."""
    clock, push = Clock(), Calls()
    publisher = _publisher(dirs, clock, push=push)
    publisher.tick()

    assert publisher.publish_if_changed() is False
    _walk(dirs[1])
    assert publisher.publish_if_changed() is True
    assert len(push.calls) == 2


def test_rewriting_identical_markers_is_not_a_change(dirs):
    """The plugin rewrites markers.csv on a timer whether or not anything was found."""
    clock, push = Clock(), Calls()
    (dirs[1] / "markers.csv").write_text("worldspace\n")
    publisher = _publisher(dirs, clock, push=push)
    publisher.tick()

    (dirs[1] / "markers.csv").write_text("worldspace\n")
    clock.now += 2 * HOUR

    assert publisher.tick() is False
    assert len(push.calls) == 1


def test_one_publish_at_a_time_across_processes(dirs, capsys):
    """The exit publisher and the next launch's companion can overlap."""
    from foggymap.publisher import publish_lock

    push = Calls()
    with publish_lock(dirs[1] / "publish") as held:
        assert held
        with publish_lock(dirs[1] / "publish") as second:
            assert not second
        assert _publisher(dirs, Clock(), push=push).tick() is False

    assert push.calls == []
    assert "another publish is in progress" in capsys.readouterr().out


def test_a_new_page_or_rebuilt_assets_count_as_changes(dirs, tmp_path):
    """An update to the site, or a relief map built since, must reach the published page."""
    assets, data = dirs
    template = tmp_path / "template"
    template.mkdir()
    (template / "app.js").write_text("// v1")
    clock, push = Clock(), Calls()
    publisher = Publisher(CONFIG, assets, data, clock=clock, now=lambda: NOW,
                          build=Calls(), push=push, template_dir=template)
    publisher.tick()

    clock.now += 2 * HOUR
    (template / "app.js").write_text("// v2")
    assert publisher.tick() is True

    clock.now += 2 * HOUR
    (assets / "worldspaces.json").write_text(json.dumps({"Commonwealth": {"relief": "r.png"}}))
    assert publisher.tick() is True
    assert len(push.calls) == 3


def test_show_character_name_is_off_unless_set(tmp_path):
    (tmp_path / "publish.ini").write_text("[Publish]\nEnabled=1\nRemote=r\n")
    assert load_publish_config(tmp_path).show_character_name is False

    (tmp_path / "publish.ini").write_text("[Publish]\nEnabled=1\nRemote=r\nShowCharacterName=1\n")
    assert load_publish_config(tmp_path).show_character_name is True


def test_the_setting_reaches_the_site_build(dirs):
    build = Calls()
    config = PublishConfig(remote="r", author_name="a", author_email="e", show_character_name=True)

    _publisher(dirs, Clock(), build=build, config=config).tick()

    assert build.calls[0][1]["show_character_name"] is True


def test_the_timeline_updates_every_tick_even_between_publishes(dirs):
    """Hourly publishing must not mean hourly timeline resolution."""
    assets, data = dirs
    clock = Clock()
    publisher = _publisher(dirs, clock)
    (data / "player.json").write_text(json.dumps({"character": {"level": 10}}))
    publisher.tick()

    (data / "player.json").write_text(json.dumps({"character": {"level": 11}}))
    clock.now += 60
    publisher.tick()

    assert '"Reached level 11"' in (data / "timeline.jsonl").read_text()


def test_mo2_profile_is_read_from_publish_ini(tmp_path):
    (tmp_path / "publish.ini").write_text(
        "[Publish]\nEnabled=1\nRemote=r\nMO2Profile=D:\Modding\Some Instance\profiles\Main\n")

    assert load_publish_config(tmp_path).mo2_profile == "D:\Modding\Some Instance\profiles\Main"
    (tmp_path / "publish.ini").write_text("[Publish]\nEnabled=1\nRemote=r\n")
    assert load_publish_config(tmp_path).mo2_profile == ""


def test_the_profile_reaches_the_build_and_its_changes_republish(dirs, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "modlist.txt").write_text("+One\n")
    config = PublishConfig(remote="r", author_name="a", author_email="e", mo2_profile=str(profile))
    clock, build = Clock(), Calls()
    publisher = _publisher(dirs, clock, build=build, config=config)
    publisher.tick()

    clock.now += 2 * HOUR
    (profile / "modlist.txt").write_text("+One\n+Two\n")

    assert publisher.tick() is True
    assert build.calls[0][1]["mo2_profile"] == str(profile)
