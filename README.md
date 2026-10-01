# FoggyMap

A fog-of-war overlay for Fallout 4 exploration. It records where you have actually
walked and shows it over the Pip-Boy world maps, so you can tell a thoroughly swept
region from one you only passed through.

The fog is drawn **on the Pip-Boy world map itself**, as a layer over the real map, with
a desktop window available for detail. It is **informational only**: it never modifies
the map art, never touches your save or load order, and does not change gameplay.

## Two fog layers

**Area fog** is cleared by walking, using a deliberately generous radius. It answers
"did I sweep this ground?", which is the only way to find unmarked locations, loot and
collectibles.

**POI fog** is a small disc per point of interest, cleared *only* by the game reporting
that marker as discovered — never by walking nearby. It is drawn on top of the area
fog, so:

- a location you walked past but never found leaves a **dark circle** punched through
  ground you otherwise cleared;
- a location you found before FoggyMap existed leaves a **small clear circle** in
  terrain that is still fogged, which is the honest claim: you found the place, but
  earned no credit for sweeping around it.

Undiscovered POIs are deliberately *not* outlined or labelled — that would hand you
the locations you are trying to discover. The desktop window's **No spoilers** option
removes their fog circles too, so the map stops hinting at them entirely.

Because the POI layer enforces "no marked location was missed" exactly, the area
radius does not have to be conservative. It defaults to 60% of a global sight estimate
of 8192 units — about 70 m — which clears a 140 m swath as you walk. That is wider
than one map tile, so a single pass clears the tiles it crosses and roughly
tile-spaced sweeps reach 100% without walking the map in a grid.

Only map markers carry a discovered flag, so unmarked locations get no POI disc. That
is precisely what the area fog layer is for.

## Layout

```
plugin/    F4SE plugin (C++): records position, dumps markers, draws the Pip-Boy overlay
viewer/    Python: foggymap/ is the library, the .pyw/.py files are entry points
tools/     developer and release tooling: asset CLI, release packaging
tests/     pytest, covering everything in viewer/ and tools/
assets/    generated and gitignored -- Bethesda's data, see assets/README.md
local/     gitignored scratch for machine-specific files
```

Data flows one way through files in `%LOCALAPPDATA%\FoggyMap`: the plugin writes CSVs,
the exporter turns them into fog, the plugin draws it. So the maths is testable without
launching anything, and everything works with the game closed.

## Setup

```powershell
# Python side
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy scipy pillow pytest PySide6

# Base maps and worldspace bounds, read out of the installed game files
.\.venv\Scripts\python.exe tools\build_assets.py

# Tests
.\.venv\Scripts\python.exe -m pytest tests/
```

### Building the plugin

Needs MSVC and [xmake](https://xmake.io). Dependencies are not committed:

```powershell
git clone --depth 1 --recurse-submodules --shallow-submodules `
    https://github.com/Dear-Modding-FO4/commonlibf4.git plugin\extern\CommonLibF4

cd plugin
xmake f -m releasedbg -y --deploy_dir="<your MO2 mods folder>/FoggyMap"
xmake
```

`Dear-Modding-FO4/commonlibf4` is the fork that still supports the old-gen 1.10.163
runtime with F4SE 0.6.23. The DLL exports both `F4SEPlugin_Query` (which is what
old-gen F4SE reads) and `F4SEPlugin_Version` (next-gen), so one binary loads on
either. Address Library resolves the per-runtime addresses.

The build copies the DLL and INI straight into its own MO2 mod folder. Enable it in
Mod Organizer like any other mod; disabling it removes FoggyMap completely, since
there is no ESP and nothing is written into your saves.

## Using it

The fog appears on the **Pip-Boy world map itself**, drawn as a layer over the real map.
The plugin launches a headless exporter (`export_fog.pyw`) alongside the game to keep it
current; there is nothing to start or shut down.

The desktop window is optional and no longer auto-launched — run it when you want the
detail view, marker names and hover readouts:

```powershell
.\.venv\Scripts\pythonw.exe viewer\viewer.pyw
```

**Controls.** Drag to pan, wheel to zoom about the cursor. The toolbar picks the
worldspace and holds two checkboxes:

- **No spoilers** — hides every trace of places you have not found: no fog circles on
  undiscovered POIs, and no "nearest undiscovered" in the hover readout. The map then
  only ever tells you where *you* have been.
- **POI names** — labels on discovered locations, which appear once you zoom past
  1.6×. Below that the dots alone stay legible.

Discovered locations are teal dots; your current position is a cyan ring at the most
recent recorded sample. Undiscovered locations are never marked — at most they leave a
dark circle in the fog, and even that goes away with no-spoilers on.

Hovering reports the world position, cell, and how thoroughly that tile was swept.

The window only re-renders when the plugin has actually written new data, and renders
on a worker thread, so panning and zooming stay smooth while the game runs.

For a still image instead of a window:

```powershell
.\.venv\Scripts\python.exe viewer\render_map.py --out .
```

## Configuration

`plugin/FoggyMap.ini`, deployed next to the DLL:

| Key | Default | Meaning |
|---|---|---|
| `OutputDir` | `%LOCALAPPDATA%\FoggyMap` | where the CSVs go; kept out of `Data\` so it never lands in MO2's overwrite folder |
| `SampleIntervalMs` | 1000 | how often your position is captured |
| `MinMoveUnits` | 256 | ignore samples closer than this to the last one (70 units = 1 m) |
| `ForceSampleSeconds` | 30 | record anyway after this long, so idle time still shows |
| `AutoLaunchCompanion` | 1 | start and stop the headless fog exporter with the game |
| `CompanionCommand` | — | full command line for it; output goes to `companion.log` |
| `PipboyOverlay` | 1 | draw the fog on the in-game Pip-Boy map |
| `PipboyFogStrength` | 0.85 | how heavy the fog looks at its densest |
| `PipboyFogGrid` | 256 | cells across the map; higher looks less like a grid |

Fog tuning lives in `viewer/foggymap/config.py`: `SIGHT_DISTANCE_UNITS`,
`SIGHT_FRACTION`, `TILE_CELLS`, `POI_FOG_RADIUS_UNITS` and the tile thresholds.

## Known approximations

- **Percent area explored** counts any tile with drawn map content as reachable. The
  Commonwealth map draws bathymetric contours over open water and a grid over
  everything, so some unreachable tiles are included. This biases the figure
  *downwards*, which is the safe direction — it never claims an area is finished when
  it is not. Tile counts and POI counts are exact.
- **A POI granted by dialogue or a quest** rather than by walking shows as clear
  without a visit, because clearing follows the game's own discovered flag.
- **Fast travel** is detected purely by distance: consecutive samples more than 2048
  units apart are not joined, so no false trail is drawn, but both endpoints still
  earn credit.

## How it works

Position sampling runs on a background timer thread, but the actual read of game state
is posted to the main thread through F4SE's task interface, because touching the
player's cell pointer off-thread could race with a cell change. File writes happen
back on the background thread so the game never waits on disk.

Marker enumeration walks each worldspace's persistent cell and fixed persistent
reference map looking for `ExtraMapMarker`, and reads the discovered flag from the live
game — which is why mod-added markers are included. Parsing the plugin files instead
would have missed them.

The world-to-pixel transform comes from each worldspace's `MNAM` map bounds in the ESM,
so it is exact rather than eyeballed. The Commonwealth is 62×62 cells drawn onto a
2048² texture: exactly 124 units per pixel.

## License

MIT — see [LICENSE](LICENSE). The license covers FoggyMap's own code only. Fallout 4
and its assets, including the map textures and worldspace data that
`tools/build_assets.py` extracts from your installed game, belong to Bethesda Softworks
and are not covered or redistributed here.
