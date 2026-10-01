"""Refuse to ship anything that names the maintainer.

Scans every file under a folder for the Windows username, the global git identity,
and any \\Users\\ path -- in ASCII and UTF-16, and inside PyInstaller's compressed
archives, where frozen code records the paths it was built from.

    python tools/identity_scan.py dist/stage
"""

from __future__ import annotations

import os
import subprocess
import sys


def default_terms() -> list[str]:
    terms = [os.environ.get("USERNAME", "")]
    for key in ("user.name", "user.email"):
        try:
            terms.append(subprocess.run(
                ["git", "config", "--global", key], capture_output=True, text=True, check=False
            ).stdout.strip())
        except OSError:
            pass
    terms += ["\\Users\\", "/Users/"]
    return [term for term in terms if term]


def _contains(blob: bytes, term: str) -> bool:
    lowered = blob.lower()
    return any(
        needle in lowered
        for needle in (term.lower().encode("utf-8"), term.lower().encode("utf-16-le"))
    )


def _archive_blobs(path: str):
    """Decompressed contents of a PyInstaller executable's archive, if it has one."""
    try:
        from PyInstaller.archive.readers import PKG_ITEM_PYZ, CArchiveReader
    except ImportError:
        return
    try:
        package = CArchiveReader(path)
    except Exception:  # noqa: BLE001 - not a PyInstaller archive
        return
    for name, entry in package.toc.items():
        yield package.extract(name)
        if entry[-1] == PKG_ITEM_PYZ:
            pyz = package.open_embedded_archive(name)
            for module in pyz.toc:
                data = pyz.extract(module, raw=True)
                if data:
                    yield data


def find_leaks(root: str, terms: list[str]) -> list[tuple[str, str]]:
    leaks: list[tuple[str, str]] = []
    for folder, _, files in os.walk(root):
        for file in sorted(files):
            path = os.path.join(folder, file)
            relative = os.path.relpath(path, root)
            with open(path, "rb") as handle:
                blobs = [handle.read()]
            if file.lower().endswith(".exe"):
                blobs.extend(_archive_blobs(path))
            for term in terms:
                if any(_contains(blob, term) for blob in blobs):
                    leaks.append((relative, term))
    return leaks


def main() -> int:
    root = sys.argv[1]
    leaks = find_leaks(root, default_terms())
    for relative, term in leaks:
        print(f"LEAK {relative}: {term}")
    if leaks:
        return 1
    count = sum(len(files) for _, _, files in os.walk(root))
    print(f"identity scan clean: {count} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
