"""Generating site/icons.js from a pinned Lucide release."""

import json
import re

import pytest

from fetch_icons import build_icons_js, fetch_icons, icon_names, svg_body

COG = """<!-- @license lucide-static v0.460.0 - ISC -->
<svg
  class="lucide lucide-cog"
  xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 24 24"
  stroke="currentColor"
>
  <path d="M12 20a8 8 0 1 0 0-16" />
  <circle cx="12" cy="12" r="2" />
</svg>
"""


def test_keeps_only_the_drawing_inside_the_svg():
    assert svg_body(COG) == '<path d="M12 20a8 8 0 1 0 0-16" /><circle cx="12" cy="12" r="2" />'


def test_refuses_something_that_is_not_an_svg():
    with pytest.raises(ValueError):
        svg_body("<html>404</html>")


def test_the_script_carries_the_licence_and_every_icon():
    script = build_icons_js({"cog": "<path d='x' />"}, "0.460.0", "ISC License\nCopyright...")

    assert "ISC License" in script
    assert "lucide-static@0.460.0" in script
    body = re.search(r"const ICONS = (\{.*\});", script, re.S).group(1)
    assert json.loads(body) == {"cog": "<path d='x' />"}


def test_the_names_cover_every_marker_kind_and_the_fallback():
    from foggymap.markers import MARKER_KINDS

    names = icon_names()

    assert names == sorted(set(names))
    assert "map-pin" in names
    assert {icon for icon, _ in MARKER_KINDS.values()} <= set(names)


def test_fetches_each_icon_and_the_licence_from_the_pinned_release():
    requested = []

    def get(url):
        requested.append(url)
        return "ISC License" if url.endswith("/LICENSE") else COG

    script = fetch_icons(["cog", "map-pin"], "0.460.0", get=get)

    assert requested == [
        "https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/icons/cog.svg",
        "https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/icons/map-pin.svg",
        "https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/LICENSE",
    ]
    assert '"map-pin":' in script and "ISC License" in script


def test_the_names_cover_the_timeline_icons():
    from foggymap.history import ICONS

    assert set(ICONS.values()) <= set(icon_names())
