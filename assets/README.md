# assets/

Generated, not committed. Run:

```powershell
.\.venv\Scripts\python.exe tools\build_assets.py
```

That extracts the Pip-Boy map textures from the game's BA2 archives and reads each
worldspace's map bounds from the ESMs, producing `worldmap_<worldspace>.png` and
`worldspaces.json`.

These are **Bethesda's assets**. They stay out of the repo for that reason, which is why
this step is a build step rather than a checked-in resource.
