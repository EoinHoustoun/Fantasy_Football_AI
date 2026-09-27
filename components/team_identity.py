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

from pathlib import Path
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


def _photo_primary(code) -> str:
    return ("https://resources.premierleague.com/premierleague25/"
            f"photos/players/110x140/{int(code)}.png")


# ── Face resolution ───────────────────────────────────────────────────────────
# Streamlit strips `onerror` from st.markdown HTML, so a browser-side fallback
# never fired outside the component iframes: a missing photo rendered as an
# empty box. Instead, which URL actually exists is resolved once per player on
# the server (current path, then the older 'p' path) and cached on disk; a
# player with neither gets the kit. Unknown players are resolved in the
# background and use the current path until then.
_FACE_CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "face_urls.json"
_FACES: dict = {}
_FACES_LOADED = False
_PENDING: set = set()


def _load_faces() -> None:
    global _FACES_LOADED, _FACES
    if _FACES_LOADED:
        return
    _FACES_LOADED = True
    try:
        import json
        _FACES = json.loads(_FACE_CACHE.read_text())
    except Exception:  # noqa: BLE001
        _FACES = {}


def resolve_faces(codes, workers: int = 4) -> None:
    """Check which headshot URL exists for each code (cached to disk). Gentle
    on the PL server: few workers, GET with a short timeout, one retry."""
    import json
    import requests
    from concurrent.futures import ThreadPoolExecutor
    _load_faces()
    todo = [int(c) for c in codes if str(int(c)) not in _FACES]
    if not todo:
        return

    def _ok(url):
        for _ in range(2):
            try:
                r = requests.get(url, timeout=6)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    return True
                if r.status_code in (403, 404):
                    return False
            except Exception:  # noqa: BLE001
                pass
        return None          # unknown (network trouble): do not cache

    def _one(c):
        a = _ok(_photo_primary(c))
        if a:
            return c, _photo_primary(c)
        b = _ok(player_photo_url_legacy(c))
        if b:
            return c, player_photo_url_legacy(c)
        if a is False and b is False:
            return c, ""
        return c, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, url in ex.map(_one, todo):
            if url is not None:
                _FACES[str(c)] = url
    try:
        _FACE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FACE_CACHE.write_text(json.dumps(_FACES))
    except Exception:  # noqa: BLE001
        pass


def _queue(code: int) -> None:
    # Never reach the network from tests or scripts: only a running app
    # (Streamlit loaded, not under pytest) resolves unknown faces.
    import sys
    if "pytest" in sys.modules or "streamlit.runtime.scriptrunner" not in sys.modules:
        return
    if code in _PENDING or len(_PENDING) > 64:
        return
    _PENDING.add(code)
    import threading
    threading.Thread(target=lambda: (resolve_faces([code]), _PENDING.discard(code)),
                     daemon=True).start()


def player_photo_url(code) -> str:
    """Best known headshot URL for a player `code`, or "" when he has none
    (callers then show the kit). Resolved and cached; see resolve_faces."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return ""
    _load_faces()
    hit = _FACES.get(str(c))
    if hit is not None:
        return hit
    _queue(c)
    return _photo_primary(c)


def player_photo_url_legacy(code) -> str:
    """The PL's older headshot path (with the 'p' prefix). Measured 27 Sep 2026:
    it serves some players the premierleague25 path 403s (Konsa among them),
    so it is the second try before the kit."""
    try:
        return ("https://resources.premierleague.com/premierleague/"
                f"photos/players/110x140/p{int(code)}.png")
    except (TypeError, ValueError):
        return ""


def face_html(player_code, team_code: int, is_gkp: bool = False,
              width: int = 56) -> str:
    """Player headshot, or the club kit when he has no photo · use anywhere a
    card talks about ONE player. The URL is resolved server-side (see
    resolve_faces) because Streamlit strips onerror fallbacks from HTML."""
    kit = shirt_html(int(team_code or 1), is_gkp=is_gkp, width=max(40, width - 8))
    photo = player_photo_url(player_code)
    if not photo:
        return kit
    return (
        f'<img src="{photo}" width="{width}" loading="lazy" '
        f'style="border-radius:10px;display:block;'
        f'filter:drop-shadow(0 4px 8px rgba(0,0,0,0.45));"/>'
    )
