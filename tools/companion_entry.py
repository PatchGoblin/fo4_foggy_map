"""PyInstaller's entry script for FoggyMapCompanion.exe. See package_release.ps1."""

import sys

from foggymap.companion import main

sys.exit(main())
