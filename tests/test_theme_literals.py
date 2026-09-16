"""A page that hardcodes dark-palette colours is broken in light mode.

`ui/theme.py` emits every colour as a `--ff-*` CSS variable and CLAUDE.md is
explicit: write `var(--ff-mint)` in inline HTML, never `#00FF87`. A literal does
not follow the palette, so on the light theme a near-white label lands on a
white card and a dark card lands on a light page.

Audited 2026-08-09: 364 hex literals and 281 hardcoded rgba-whites across 17 of
19 view files · only the Draft page and the Chip Planner were clean.

This is a static scan, like `test_na_sentinel` and `test_cache_keys`, because
the failure is invisible until someone flips the toggle.
"""
import re
from pathlib import Path

import pytest

from ui.theme import DARK

VIEWS = sorted(Path("views").glob("*.py"))

# Colours that are the SAME in both palettes are allowed as literals · they
# carry their own ground and do not follow the theme.
from ui.theme import FDR_COLORS, LIGHT
_SAME = {v.lower() for k, v in DARK.items() if LIGHT.get(k) == v}
_SAME |= {v.lower() for v in FDR_COLORS.values()}
_SAME |= {"#ffffff", "#fff", "#000000", "#000"}     # pure black/white on chips

_DARK_LITERALS = {v.lower() for k, v in DARK.items()
                  if isinstance(v, str) and v.startswith("#")
                  and LIGHT.get(k) != v} - _SAME

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_WHITE_RGBA = re.compile(r"rgba\(\s*255\s*,\s*255\s*,\s*255\s*,")
# White TEXT is a dark-theme assumption · on the light page it lands on white.
# It is legitimate only on a vivid chip, which supplies its own ground.
_WHITE_TEXT = re.compile(r"color\s*:\s*#(?:fff|ffffff)\b", re.I)
_CHIP_BG = re.compile(r"background\s*:\s*(?:var\(--ff-[a-z]+-v\)|#[0-9a-fA-F]{6})")
# A near-black ground is the same assumption in reverse.
_DARK_GROUND = re.compile(r"rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0?\.\d+\s*\)")


def _offenders(src: str):
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue                                  # a comment, not a colour
        for m in _HEX.findall(line):
            if m.lower() in _DARK_LITERALS:
                out.append("%d: %s" % (i, m))
        if _WHITE_RGBA.search(line):
            out.append("%d: rgba(255,255,255,...)" % i)
        if _WHITE_TEXT.search(line) and not _CHIP_BG.search(line):
            out.append("%d: white text off a chip" % i)
        if _DARK_GROUND.search(line) and "shadow" not in line.lower():
            out.append("%d: near-black ground" % i)
    return out


@pytest.mark.parametrize("path", VIEWS, ids=lambda p: p.name)
def test_page_uses_theme_tokens_not_literals(path):
    bad = _offenders(path.read_text())
    assert not bad, (
        "%s hardcodes palette colours, so it does not follow the light theme. "
        "Use ui.theme.var('token') in HTML, or theme.fill('token') where CSS "
        "cannot reach:\n  %s" % (path.name, "\n  ".join(bad[:12])))
