"""The release must not carry anything that identifies the maintainer."""

import subprocess
import sys
from pathlib import Path

from foggymap.identity import default_terms, find_leaks

TERM = "SomeoneSpecific"


def test_a_clean_folder_has_no_leaks(tmp_path):
    (tmp_path / "a.txt").write_text("nothing to see")

    assert find_leaks(str(tmp_path), [TERM]) == []


def test_finds_an_ascii_term_case_insensitively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.dll").write_bytes(b"\x00\x01C:\\USERS\\someonespecific\\x\x00")

    assert find_leaks(str(tmp_path), [TERM]) == [("sub\\b.dll", TERM)]


def test_finds_a_utf16_term(tmp_path):
    """Windows binaries store paths as UTF-16."""
    (tmp_path / "c.exe").write_bytes(b"\x00" + f"D:\\{TERM}\\y".encode("utf-16-le"))

    assert find_leaks(str(tmp_path), [TERM]) == [("c.exe", TERM)]


def test_default_terms_include_the_username_and_profile_folder(monkeypatch):
    """The profile folder can differ from the username, and both identify the maintainer."""
    monkeypatch.setenv("USERNAME", "probe_user")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\probe_profile")

    terms = default_terms()

    assert "probe_user" in terms
    assert "probe_profile" in terms


def test_other_peoples_users_paths_are_not_leaks(monkeypatch, tmp_path):
    """numpy and scipy ship paths from their CI machines; those name nobody here."""
    monkeypatch.setenv("USERNAME", "probe_user")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\probe_profile")
    (tmp_path / "scipy.pyd").write_bytes(b"C:\\Users\\runneradmin\\build /Users/runner/x")

    assert find_leaks(str(tmp_path), default_terms()) == []


def test_the_release_tool_still_runs_from_anywhere(tmp_path):
    """package_release.ps1 runs it as a script, without the test path setup."""
    (tmp_path / "a.txt").write_text("nothing to see")
    tool = Path(__file__).parent.parent / "tools" / "identity_scan.py"

    result = subprocess.run([sys.executable, str(tool), str(tmp_path)],
                            capture_output=True, text=True, cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "identity scan clean: 1 files" in result.stdout
