"""Refuse to ship anything that names the maintainer.

    python tools/identity_scan.py dist/stage
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer"))

from foggymap.identity import default_terms, find_leaks  # noqa: E402


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
