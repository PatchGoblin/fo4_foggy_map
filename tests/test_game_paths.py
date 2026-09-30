"""Finding the installed game without hardcoding one machine's layout."""

import os

from game_paths import data_dir


def test_the_environment_variable_wins(monkeypatch, tmp_path):
    """So a differently installed game needs no code change."""
    monkeypatch.setenv("FALLOUT4_DATA", str(tmp_path))

    assert data_dir() == str(tmp_path)


def test_falls_back_to_a_known_install_location(monkeypatch):
    monkeypatch.delenv("FALLOUT4_DATA", raising=False)

    found = data_dir()

    assert isinstance(found, str)
    assert found.lower().endswith("data")


def test_a_missing_install_still_returns_a_path_to_report(monkeypatch):
    """Callers skip or explain; they should not have to handle None."""
    monkeypatch.delenv("FALLOUT4_DATA", raising=False)
    monkeypatch.setattr("game_paths.CANDIDATES", [r"X:\nope\Data"])

    assert data_dir() == r"X:\nope\Data"
    assert not os.path.exists(data_dir())
