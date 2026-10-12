"""Pushing the built site to a git remote as a single, correctly attributed commit."""

import subprocess

import pytest

from foggymap.gitpublish import PublishError, push_site

AUTHOR = ("Site Bot", "bot@example.invalid")


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "remote.git"
    _git("init", "--bare", "-q", str(path))
    return path


@pytest.fixture
def staging(tmp_path):
    path = tmp_path / "staging"
    (path / "data").mkdir(parents=True)
    (path / "index.html").write_text("<!doctype html>\n")
    (path / "data" / "summary.json").write_text("{}")
    return path


def _push(staging, tmp_path, remote, **overrides):
    options = dict(staging_dir=staging, repo_dir=tmp_path / "local.git", remote=str(remote),
                   branch="main", author_name=AUTHOR[0], author_email=AUTHOR[1], leak_terms=[])
    options.update(overrides)
    return push_site(**options)


def _files(remote, ref="main"):
    return sorted(_git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", ref).splitlines())


def test_pushes_the_staged_files(staging, tmp_path, remote):
    sha = _push(staging, tmp_path, remote)

    assert _git("--git-dir", str(remote), "rev-parse", "main") == sha
    assert _files(remote) == ["data/summary.json", "index.html"]


def test_each_publish_is_one_parentless_commit(staging, tmp_path, remote):
    """The site repo must not grow with every publish."""
    _push(staging, tmp_path, remote)
    (staging / "data" / "summary.json").write_text('{"more": 1}')
    (staging / "index.html").unlink()

    _push(staging, tmp_path, remote)

    assert _git("--git-dir", str(remote), "rev-list", "--count", "main") == "1"
    assert _files(remote) == ["data/summary.json"], "removed files leave the site"


def test_author_and_committer_come_from_the_config(staging, tmp_path, remote):
    """Never the global identity, which may be someone's real name."""
    _push(staging, tmp_path, remote)

    stamp = _git("--git-dir", str(remote), "log", "-1", "--format=%an <%ae> | %cn <%ce>", "main")
    assert stamp == "Site Bot <bot@example.invalid> | Site Bot <bot@example.invalid>"


@pytest.mark.parametrize("name, email", [("", "bot@example.invalid"), ("Site Bot", "")])
def test_refuses_without_an_author(staging, tmp_path, remote, name, email):
    with pytest.raises(PublishError, match="Author"):
        _push(staging, tmp_path, remote, author_name=name, author_email=email)

    assert _git("--git-dir", str(remote), "for-each-ref") == ""


def test_refuses_to_push_anything_that_names_someone(staging, tmp_path, remote):
    (staging / "data" / "oops.txt").write_text(r"C:\Users\SomeoneSpecific\x")

    with pytest.raises(PublishError, match="oops.txt"):
        _push(staging, tmp_path, remote, leak_terms=["SomeoneSpecific"])

    assert _git("--git-dir", str(remote), "for-each-ref") == ""


def test_recovers_from_a_stale_lock(staging, tmp_path, remote):
    """The game kills the companion with it, possibly mid-publish."""
    _push(staging, tmp_path, remote)
    (tmp_path / "local.git" / "index.lock").write_text("")
    (staging / "index.html").write_text("changed\n")

    _push(staging, tmp_path, remote)

    assert _git("--git-dir", str(remote), "show", "main:index.html") == "changed"


def test_a_failed_push_raises_with_gits_reason(staging, tmp_path):
    with pytest.raises(PublishError, match="push"):
        _push(staging, tmp_path, tmp_path / "no-such-remote.git")


def test_files_are_pushed_byte_for_byte(staging, tmp_path, remote):
    """A global autocrlf must not rewrite the site's line endings."""
    (staging / "index.html").write_bytes(b"a\nb\n")

    _push(staging, tmp_path, remote)

    out = subprocess.run(["git", "--git-dir", str(remote), "cat-file", "blob", "main:index.html"],
                         capture_output=True, check=True).stdout
    assert out == b"a\nb\n"
