"""Detecting when the plugin has written new data.

Re-rendering on a blind timer is what made the viewer feel laggy: a full render costs
roughly a second, and while you are standing still nothing has changed. The viewer
takes a cheap fingerprint instead and only re-renders when it moves.
"""

from __future__ import annotations

import os


def fingerprint(data_dir, editor_id: str) -> tuple:
    """A cheap, hashable snapshot of the data files for one worldspace.

    Compares equal when nothing has been written. Uses size alongside modification
    time because the path CSV is appended to, and coarse filesystem timestamps could
    otherwise miss a same-second append.
    """
    directory = str(data_dir)
    names = (f"path_{editor_id}.csv", "markers.csv")
    return (editor_id,) + tuple(_stamp(os.path.join(directory, name)) for name in names)


def _stamp(path: str) -> tuple:
    try:
        info = os.stat(path)
    except OSError:
        return (0, 0.0)  # absent is a valid, stable state
    return (info.st_size, info.st_mtime)
