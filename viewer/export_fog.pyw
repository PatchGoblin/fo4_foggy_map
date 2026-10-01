"""Headless companion, run from the repo.

The plugin launches this when CompanionCommand points at it, appending --data and
--game-data. Released builds run the same code frozen as FoggyMapCompanion.exe. No
window, no Qt -- run viewer.pyw separately for the desktop map.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from foggymap.companion import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
