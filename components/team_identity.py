"""
Club visual identity · the single source of truth for team crests, colours,
and player shirts.

Historically the shirt-URL helper was copy-pasted across ~9 pages. This module
centralises all three so every surface renders club identity consistently:

  shirt_url(team_code, is_gkp)  → FPL CDN kit image
  badge_url(team_code)          → Premier League CDN club crest
  team_color(key)               → primary hex for a club
  team_color_pair(key)          → (primary, secondary) hex

`team_code` is the stable FPL club code (the integer already threaded through
every player dataframe via data/fetchers/fpl_api.py) and is what both the shirt
and badge CDNs key on. Colours are keyed by `team_short` (e.g. "ARS") which is
human-readable and user-editable each season · see TEAM_COLORS in config.py.
"""

from typing import Optional, Tuple

from config import TEAM_COLORS, ACCENT_COLOR

# ── Shirts (FPL CDN) ──────────────────────────────────────────────────────────
_SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"
# The CDN serves -66, -110, -220 variants. We request the largest (220px) and let
# the browser DOWNSCALE · crisp even on retina. Rendering the old -66 thumbnail at
# 52-72px upscaled it and caused the blurry kits.
_SHIRT_SIZE = 220

# ── Crests (Premier League CDN) ───────────────────────────────────────────────
# 50px badge variant · crisp at card sizes, small payload.
_BADGE_BASE = "https://resources.premierleague.com/premierleague/badges/50"

# Neutral fallbacks
_FALLBACK_COLOR = ACCENT_COLOR              # FPL green
_FALLBACK_SECONDARY = "#FFFFFF"


def shirt_url(team_code: int, is_gkp: bool = False, size: int = _SHIRT_SIZE) -> str:
    """Official FPL kit image for a club (HD: 220px source, downscaled by the browser).

    Outfield:   shirt_{code}-{size}.png
    Goalkeeper: shirt_{code}_1-{size}.png   (the ``_1`` suffix is GK-only)
    """
    suffix = "_1" if is_gkp else ""
    return f"{_SHIRT_BASE}/shirt_{int(team_code)}{suffix}-{int(size)}.png"


def shirt_fallback_url(is_gkp: bool = False, size: int = _SHIRT_SIZE) -> str:
    """Generic shirt used as an <img onerror> fallback."""
    suffix = "_1" if is_gkp else ""
    return f"{_SHIRT_BASE}/shirt_1{suffix}-{int(size)}.png"


def badge_url(team_code: int) -> str:
    """Premier League club crest (PNG) for a club, by stable team code."""
    return f"{_BADGE_BASE}/t{int(team_code)}.png"


def shirt_html(team_code: int, is_gkp: bool = False, width: int = 52,
               crest: bool = False, crest_size: Optional[int] = None) -> str:
    """Standard player kit image.

    The one HTML shirt builder every page should use, so kits render identically
    everywhere. (Club crests are intentionally omitted · the PL crest CDN is not
    reliably reachable and left empty circles; the kit + team-colour accents carry
    club identity instead.)
    """
    code = int(team_code or 1)
    return (
        f'<img src="{shirt_url(code, is_gkp)}" width="{width}" '
        f'onerror="this.src=\'{shirt_fallback_url(is_gkp)}\'" style="display:block;" />'
    )


def team_dot(team_short: Optional[str], size: int = 12) -> str:
    """A small filled circle in the club's primary colour · a reliable, pure-CSS
    identity marker for cards that have no kit image (no network dependency)."""
    c = team_color(team_short)
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:50%;background:{c};flex-shrink:0;'
        f'box-shadow:0 0 0 1px rgba(255,255,255,0.15);"></span>'
    )


def _normalise(key: Optional[str]) -> str:
    return str(key or "").strip().upper()


def team_color(key: Optional[str]) -> str:
    """Primary club colour hex. Accepts a team short code (e.g. "ARS").

    Falls back to the FPL green accent for unknown/blank clubs so callers can
    always tint safely.
    """
    pair = TEAM_COLORS.get(_normalise(key))
    return pair[0] if pair else _FALLBACK_COLOR


def team_color_pair(key: Optional[str]) -> Tuple[str, str]:
    """(primary, secondary) club colours. Safe fallback for unknown clubs."""
    pair = TEAM_COLORS.get(_normalise(key))
    return pair if pair else (_FALLBACK_COLOR, _FALLBACK_SECONDARY)
