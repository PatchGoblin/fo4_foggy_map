"""Launcher for the FoggyMap desktop window.

A .pyw so pythonw.exe opens it without a console. Run it by hand whenever you want the
detail view; the plugin launches the headless companion, not this.
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
