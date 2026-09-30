"""Headless companion: keeps the Pip-Boy fog up to date while you play.

Launched by the plugin. No window, no Qt -- so nothing here can crash a GUI and
silently stop the in-game fog updating. Run viewer.pyw separately if you want the
desktop map.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from foggymap.exporter import watch  # noqa: E402


def main() -> None:
    assets = os.environ.get("FOGGYMAP_ASSETS", os.path.join(REPO, "assets"))
    data = os.environ.get(
        "FOGGYMAP_DATA", os.path.join(os.environ.get("LOCALAPPDATA", "."), "FoggyMap")
    )
    watch(assets, data)


if __name__ == "__main__":
    main()
