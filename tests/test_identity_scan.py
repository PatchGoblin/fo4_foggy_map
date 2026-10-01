"""The release must not carry anything that identifies the maintainer."""

from identity_scan import default_terms, find_leaks

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


def test_default_terms_include_the_username_and_users_folder(monkeypatch):
    monkeypatch.setenv("USERNAME", "probe_user")

    terms = default_terms()

    assert "probe_user" in terms
    assert "\\Users\\" in terms
