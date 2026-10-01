"""Build the map assets by hand, for development.

The companion does this itself on first run; this is for regenerating the repo's
own assets/ folder.

    python tools/build_assets.py [--data <Fallout 4 Data dir>] [--out assets]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer"))

from foggymap.assets import build_assets  # noqa: E402

from game_paths import data_dir  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=data_dir(), help="Fallout 4 Data directory")
    parser.add_argument("--out", default="assets", help="where to write images and manifest")
    args = parser.parse_args()

    manifest = build_assets(args.data, args.out)
    for editor_id, entry in manifest.items():
        nw, se = entry["nw_cell"], entry["se_cell"]
        cells_x = se[0] - nw[0] + 1
        cells_y = nw[1] - se[1] + 1
        print(
            f"{editor_id:16s} {entry['width_px']}x{entry['height_px']} px  "
            f"{cells_x}x{cells_y} cells  -> {entry['image']}"
        )


if __name__ == "__main__":
    main()
