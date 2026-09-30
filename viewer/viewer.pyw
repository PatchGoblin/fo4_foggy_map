"""Launcher for the FoggyMap window.

A .pyw so pythonw.exe opens it without a console. The plugin starts this minimised
when Fallout 4 launches and closes it when the game exits, but it is also fine to run
by hand between sessions.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from foggymap.app import main  # noqa: E402

if __name__ == "__main__":
    main(
        assets_dir=os.environ.get("FOGGYMAP_ASSETS", os.path.join(REPO, "assets")),
        data_dir=os.environ.get("FOGGYMAP_DATA"),
    )
