"""Design system · tokens, light/dark palettes, and one global-CSS injector.

Two palettes, one set of variable names. Every surface reads `var(--ff-*)` rather
than a literal, so switching theme is a CSS swap and nothing has to re-render.

Two families of accent exist on purpose:

  `--ff-mint`   an INK colour, safe to read as text on the current background.
                Dark theme: the bright brand mint. Light theme: a deeper mint
                that actually passes contrast on white.
  `--ff-mint-v` a VIVID FILL, for chips and badges that carry black text. Nearly
                identical in both themes, because a chip supplies its own ground
                and does not have to fight the page.

Mixing those two up is what makes a naive light mode unreadable. Ink for text
and borders, vivid only for fills.

Usage (once, in app.py, after inject_global_animations):
    from ui.theme import inject_theme, theme_toggle
    theme_toggle()      # in the sidebar
    inject_theme()

Import tokens anywhere:
    from ui.theme import COLORS, var, is_light
"""

from __future__ import annotations

from typing import Dict, Optional

import streamlit as st

THEME_KEY = "ff_theme"
DEFAULT_THEME = "dark"

# Session state dies on a hard reload, so the choice is also written to a tiny
# file. Without it the app snapped back to dark every refresh and you had to
# pick light again, all day.
_PREF_PATH = None


def _pref_file():
    global _PREF_PATH
    if _PREF_PATH is None:
        import os
        from config import CACHE_DIR
        _PREF_PATH = os.path.join(CACHE_DIR, "ui_prefs.json")
    return _PREF_PATH


def _read_pref() -> Optional[str]:
    import json
    try:
        with open(_pref_file()) as fh:
            v = json.load(fh).get("theme")
        return v if v in ("light", "dark") else None
    except Exception:
        return None


def _write_pref(theme: str) -> None:
    import json
    import os
    try:
        os.makedirs(os.path.dirname(_pref_file()), exist_ok=True)
        with open(_pref_file(), "w") as fh:
            json.dump({"theme": theme}, fh)
    except Exception:
        pass        # a preference is never worth an exception


# ── Palettes ──────────────────────────────────────────────────────────────────
DARK: Dict[str, str] = {
    "bg": "#10141F", "bg2": "#161B28",
    "s1": "#1B2131", "s2": "#232B3E", "s3": "#2E374E",
    "card": "rgba(30,37,54,0.88)",
    "card-solid": "#1B2131",
    "line": "rgba(255,255,255,0.11)",
    "line-strong": "rgba(255,255,255,0.20)",
    "text": "#EEF1F5",
    "muted": "rgba(236,241,245,0.86)",
    "muted2": "rgba(236,241,245,0.66)",
    # ink accents · read as text
    "mint": "#00FF87", "gold": "#FFD700", "cyan": "#04F5FF",
    "mag": "#E90052", "red": "#FF4B4B", "orange": "#FFA500",
    # vivid fills · carry black text
    "mint-v": "#00FF87", "gold-v": "#FFD700", "cyan-v": "#04F5FF",
    "mag-v": "#E90052", "red-v": "#FF4B4B", "orange-v": "#FF8C42",
    "glass": "rgba(35,43,62,0.62)",
    "shadow": "0 18px 44px rgba(0,0,0,0.45)",
    "row-hover": "rgba(255,255,255,0.07)",
    "row-alt": "rgba(255,255,255,0.035)",
    "chip-bg": "rgba(255,255,255,0.10)",
    "grid": "rgba(255,255,255,0.10)",
    # The sidebar used to be FPL purple against near-black, which was the
    # harshest edge on the screen. A blue-slate a step lighter than the content
    # reads as the same room rather than a different one.
    "side": "#5EE0F2", "side2": "#12BBD6", "side-ink": "#05222B",
    "side-line": "rgba(5,34,43,0.22)",
}

LIGHT: Dict[str, str] = {
    "bg": "#F4F6FA", "bg2": "#FFFFFF",
    "s1": "#FFFFFF", "s2": "#F1F4F9", "s3": "#E6EBF3",
    "card": "rgba(255,255,255,0.94)",
    "card-solid": "#FFFFFF",
    "line": "rgba(16,24,40,0.10)",
    "line-strong": "rgba(16,24,40,0.20)",
    "text": "#101828",
    "muted": "rgba(16,24,40,0.86)",
    "muted2": "rgba(16,24,40,0.68)",
    # Deepened so they survive on white. The brand still reads as mint and gold.
    "mint": "#00874A", "gold": "#9A6E00", "cyan": "#0369A1",
    "mag": "#BE0046", "red": "#C62B22", "orange": "#B45309",
    # Fills stay vivid · they provide their own ground and carry black text.
    "mint-v": "#00E37A", "gold-v": "#FFCC00", "cyan-v": "#22D3EE",
    "mag-v": "#F5006B", "red-v": "#FF5A52", "orange-v": "#FF9640",
    "glass": "rgba(255,255,255,0.74)",
    "shadow": "0 14px 34px rgba(16,24,40,0.12)",
    "row-hover": "rgba(16,24,40,0.05)",
    "row-alt": "rgba(16,24,40,0.024)",
    "chip-bg": "rgba(16,24,40,0.06)",
    "grid": "rgba(16,24,40,0.10)",
    "side": "#5EE0F2", "side2": "#12BBD6", "side-ink": "#05222B",
    "side-line": "rgba(5,34,43,0.22)",
}

# Fixture difficulty always carries black text on a solid chip, so one scale
# works in both themes. 1/2 easy through 5 brutal.
FDR_COLORS = {1: "#00E37A", 2: "#00E37A", 3: "#FFD60A", 4: "#FF8C42", 5: "#FF4B4B"}

# Position accents, as token names · resolve through `fill()` for a chip.
POS_TOKENS = {"GKP": "mint-v", "DEF": "cyan-v", "MID": "mag-v", "FWD": "orange-v"}

PITCH = {"g1": "#0d3f20", "g2": "#12592e", "g3": "#16632f"}

DISPLAY_STACK = "'Archivo','SF Pro Display',system-ui,-apple-system,sans-serif"


# ── Access ────────────────────────────────────────────────────────────────────
def current() -> str:
    """'dark' or 'light'.

    Session state first. On a fresh reload it is empty, and `inject_theme` runs
    before the sidebar toggle is built, so the saved preference is read here
    too · otherwise the page painted dark and then flipped to light a moment
    later. Seeded into session state so the file is read once, not per call.
    """
    if THEME_KEY not in st.session_state:
        st.session_state[THEME_KEY] = _read_pref() or DEFAULT_THEME
    return st.session_state[THEME_KEY]


def is_light() -> bool:
    return current() == "light"


def palette() -> Dict[str, str]:
    return LIGHT if is_light() else DARK


def var(name: str) -> str:
    """CSS variable reference for inline styles · `var(--ff-mint)`.

    Prefer this over a literal in any HTML a page builds, so the surface follows
    the theme without the page having to know which one is active.
    """
    return "var(--ff-%s)" % name.replace("_", "-")


def fill(token: str) -> str:
    """Resolved literal for a token · for places a CSS variable cannot reach
    (chart series colours, canvas, anything crossing into JSON)."""
    return palette().get(token.replace("_", "-"), token)


def pos_color(position: str) -> str:
    """Resolved position accent, for charts and other non-CSS contexts."""
    return fill(POS_TOKENS.get(str(position), "mint-v"))


# Backwards compatibility · older pages import COLORS with the long key names.
COLORS: Dict[str, str] = {
    "bg": DARK["bg"], "bg2": DARK["bg2"],
    "surface1": DARK["s1"], "surface2": DARK["s2"], "surface3": DARK["s3"],
    "line": DARK["line"], "text": DARK["text"],
    "muted": DARK["muted"], "muted2": DARK["muted2"],
    "mint": DARK["mint"], "gold": DARK["gold"], "cyan": DARK["cyan"],
    "magenta": DARK["mag"], "red": DARK["red"], "orange": DARK["orange"],
}
GLASS = DARK["glass"]
GLASS_BRD = DARK["line"]
VAR = var


def _vars_block(p: Dict[str, str]) -> str:
    return "".join("--ff-%s:%s;" % (k.replace("_", "-"), v) for k, v in p.items())


# ── Global CSS ────────────────────────────────────────────────────────────────
def _css(p: Dict[str, str], light: bool) -> str:
    ink = p["text"]
    # Streamlit's own chrome is configured dark in config.toml, and config cannot
    # switch at runtime, so light mode has to override it here.
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0&display=swap');
:root {{
  --ff-display:{DISPLAY_STACK};
  {_vars_block(p)}
}}

[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1100px 560px at 8% -10%, {'rgba(0,135,74,0.07)' if light else 'rgba(0,255,135,0.11)'}, transparent 58%),
    radial-gradient(900px 480px at 100% 2%, {'rgba(3,105,161,0.06)' if light else 'rgba(4,245,255,0.09)'}, transparent 55%),
    radial-gradient(760px 520px at 55% 110%, {'rgba(190,0,70,0.04)' if light else 'rgba(233,0,82,0.07)'}, transparent 60%),
    var(--ff-bg) !important;
  color: {ink} !important;
}}
[data-testid="stHeader"] {{ background: transparent !important; }}

/* Streamlit reserves ~6rem above the first element and caps the content width.
   On a laptop that is most of a pitch's worth of vertical space spent on
   nothing, so reclaim it · the app is dense on purpose. */
.stMainBlockContainer, [data-testid="stMainBlockContainer"], .block-container {{
  padding-top: 2.2rem !important; padding-bottom: 2.5rem !important;
  max-width: 100% !important;
}}

/* Body copy, captions and labels · Streamlit hard-codes these against its base */
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] li,
[data-testid="stAppViewContainer"] label,
[data-testid="stMarkdownContainer"] {{ color: {ink}; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
  color: var(--ff-muted) !important;
}}
h1, h2, h3, h4 {{ color: {ink} !important; }}

/* ── Sidebar ──
   Blue-slate in dark, light blue in light · a step away from the content rather
   than a slab of purple against black. Nav links get a soft resting state and a
   real selected state so the current page is obvious without a hard edge. */
[data-testid="stSidebar"] {{
  background:
    linear-gradient(180deg, rgba(255,255,255,0.55) 0%, rgba(255,255,255,0) 26%),
    linear-gradient(180deg, var(--ff-side) 0%, var(--ff-side2) 100%) !important;
  border-right: 1px solid var(--ff-side-line) !important;
  box-shadow: inset -1px 0 0 rgba(255,255,255,0.5),
              4px 0 24px rgba(12,32,57,0.14) !important;
}}
[data-testid="stSidebar"] * {{ color: var(--ff-side-ink) !important; }}
[data-testid="stSidebar"] hr {{ border-color: var(--ff-side-line) !important; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a,
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] {{
  border-radius: 9px !important; margin: 1px 6px !important;
  padding: 6px 10px !important; font-weight: 500 !important;
  transition: background .13s ease, transform .13s cubic-bezier(.2,.8,.2,1);
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover,
[data-testid="stSidebarNav"] a:hover, [data-testid="stSidebarNavLink"]:hover {{
  background: rgba(5,34,43,0.12) !important; transform: translateX(2px);
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"],
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: rgba(5,34,43,0.16) !important;
  box-shadow: inset 3px 0 0 #05222B;
  font-weight: 700 !important;
}}
[data-testid="stSidebarNav"] a[aria-current="page"] * {{ color: #05222B !important; }}
/* Category headers are the point of the regrouping, so they have to be legible ·
   a hairline under each one separates the four groups without adding a box. */
[data-testid="stNavSectionHeader"] {{
  font-size: 10px !important; font-weight: 800 !important;
  letter-spacing: 0.2em !important; text-transform: uppercase !important;
  color: #05222B !important; opacity: 1 !important;
  /* Streamlit sets visibility:hidden on section headers when the nav is
     collapsed. The categories ARE the navigation here, so bring them back. */
  visibility: visible !important;
  margin: 14px 12px 4px !important; padding: 0 0 5px 0 !important;
  border-bottom: 1px solid var(--ff-side-line) !important;
}}
[data-testid="stNavSectionHeader"]:first-of-type {{ margin-top: 4px !important; }}
[data-testid="stSidebarNavItems"] {{ padding-top: 0 !important; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width:10px; height:10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{
  background: var(--ff-line-strong); border-radius:999px;
  border:2px solid transparent; background-clip: padding-box;
}}
::-webkit-scrollbar-thumb:hover {{ background: var(--ff-mint); background-clip: padding-box; }}

/* ── Custom components ──
   Streamlit gives a declared component's iframe a 300px default width. The
   pitch and the tables both size themselves from their container, so at 300px
   they wrap into a tall, cramped column and then report that height back. Force
   them to fill the block instead. */
[data-testid="stCustomComponentV1"] {{ width: 100% !important; }}
[data-testid="stCustomComponentV1"] iframe,
iframe[title="ff_pitch_click"], iframe[title="ff_table"] {{
  width: 100% !important; border: 0;
}}

/* ── Depth utilities ── */
.ff-glass {{
  background: var(--ff-glass); border:1px solid var(--ff-line);
  border-radius:16px; backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}}
.ff-hairline {{ height:1px; background: var(--ff-line); border:0; }}
.mi {{
  font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal;
  line-height: 1; vertical-align: middle; display: inline-block;
  -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga';
  -webkit-font-smoothing: antialiased; user-select: none;
}}
.ff-card-3d {{
  transition: transform .18s cubic-bezier(.2,.8,.2,1), box-shadow .18s ease, border-color .18s ease;
}}
.ff-card-3d:hover {{
  transform: translateY(-4px); box-shadow: var(--ff-shadow);
  border-color: var(--ff-mint) !important;
}}

/* ── Type ──
   One rule decides the whole feel: body copy is LIGHT and only numbers and
   headings are heavy. Weight is what carries hierarchy here, not size, so the
   page can stay dense without shouting. Three roles, and nothing else:
     body      400/450, 13px, the default for everything readable
     label     600, 10px, uppercase and tracked · the small-caps furniture
     display   800/900, Archivo · headings and any number that matters
*/
h1, h2, h3 {{ font-family: var(--ff-display) !important; }}
h1 {{ letter-spacing:-0.03em !important; font-weight:900 !important; }}
h2, h3 {{ letter-spacing:-0.01em !important; }}
.ff-display {{ font-family: var(--ff-display); letter-spacing:-0.02em;
               font-variant-numeric: tabular-nums; }}

[data-testid="stAppViewContainer"] {{
  font-feature-settings: 'cv02','cv03','cv04','cv11';
}}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {{
  font-weight: 400; font-size: 13.5px; line-height: 1.55;
}}
[data-testid="stCaptionContainer"] p {{
  font-weight: 400 !important; font-size: 12px !important; line-height: 1.5;
}}
/* Any number rendered inline stays on tabular figures so columns line up. */
.ff-num {{ font-variant-numeric: tabular-nums; }}

/* ── Metrics ── */
[data-testid="stMetricValue"] {{
  font-family: var(--ff-display) !important;
  color: var(--ff-mint) !important; font-size:1.6rem !important; font-weight:800 !important;
}}
[data-testid="stMetricLabel"] {{
  font-size:0.78rem !important; color: var(--ff-muted) !important;
  text-transform: uppercase; letter-spacing:0.05em;
}}

/* ── Tabs ── */
button[data-baseweb="tab"] {{
  background: transparent !important; border-bottom: 2px solid transparent !important;
  color: var(--ff-muted) !important; font-weight:500;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
  border-bottom: 2px solid var(--ff-mint) !important;
  color: var(--ff-mint) !important; font-weight:700;
}}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {{ background: transparent !important; }}

/* ── Pills · used as the draft selector, so they carry real weight ──
   Default pills read as filter chips. These are the primary object picker on
   the page, so the selected one gets the accent as a FILL rather than a tint,
   and the rest sit on the raised surface so the row reads as one control. */
[data-testid^="stBaseButton-pills"] {{
  background: var(--ff-s2) !important;
  border: 1px solid var(--ff-line) !important;
  color: {ink} !important;
  border-radius: 9px !important;
  font-size: 12px !important; font-weight: 600 !important;
  padding: 5px 11px !important; white-space: nowrap !important;
  transition: transform .12s cubic-bezier(.2,.8,.2,1), border-color .12s, background .12s;
}}
[data-testid^="stBaseButton-pills"]:hover {{
  border-color: var(--ff-mint) !important; transform: translateY(-1px);
}}
[data-testid^="stBaseButton-pills"] span[data-testid="stIconMaterial"],
[data-testid^="stBaseButton-pills"] .material-icons,
[data-testid^="stBaseButton-pills"] [class*="material"] {{
  font-size: 15px !important; opacity: 0.85;
}}
[data-testid="stBaseButton-pillsActive"] {{
  background: var(--ff-mint) !important;
  border-color: var(--ff-mint) !important;
  color: {'#FFFFFF' if light else '#06251A'} !important;
  font-weight: 800 !important;
  box-shadow: 0 3px 12px rgba(0,0,0,0.28);
}}
[data-testid="stBaseButton-pillsActive"] * {{
  color: {'#FFFFFF' if light else '#06251A'} !important; opacity: 1 !important;
}}
/* Fourteen drafts wrapped to four rows and pushed the pitch off the screen.
   One scrolling line keeps the selector to a single row · the selected pill is
   always visible because Streamlit re-renders with it in place. */
.st-key-planner_draft [data-testid="stButtonGroup"],
.st-key-planner_draft [data-testid="stButtonGroup"] > div,
.st-key-planner_draft [role="radiogroup"] {{
  display: flex !important; flex-wrap: nowrap !important;
  overflow-x: auto !important; overflow-y: hidden !important;
  gap: 6px !important; padding-bottom: 7px;
  scrollbar-width: thin; scroll-behavior: smooth;
}}
.st-key-planner_draft [data-testid^="stBaseButton-pills"] {{ flex: 0 0 auto !important; }}
.st-key-planner_draft [role="radiogroup"]::-webkit-scrollbar {{ height: 6px; }}

/* A rail holding fourteen drafts in 647px of screen scrolls, and a scroll with
   no edge is a scroll nobody finds. These are scroll shadows: the two `local`
   gradients ride the content and sit ON TOP of the two `scroll` shadows, so a
   shadow only becomes visible on a side that actually has more to reveal. That
   self-detection is the point · with "Just mine" selected the rail can hold two
   pills, and a permanent fade there would be a lie. Nothing is masked, so no
   pill label is ever dimmed. */
.st-key-planner_draft [role="radiogroup"] {{
  scroll-snap-type: x proximity;
  background:
    linear-gradient(to right, var(--ff-bg) 40%, transparent) left center /
      44px 100% no-repeat local,
    linear-gradient(to left, var(--ff-bg) 40%, transparent) right center /
      44px 100% no-repeat local,
    radial-gradient(farthest-side at 0 50%, rgba(0,0,0,0.30), transparent)
      left center / 15px 100% no-repeat scroll,
    radial-gradient(farthest-side at 100% 50%, rgba(0,0,0,0.30), transparent)
      right center / 15px 100% no-repeat scroll;
}}
.st-key-planner_draft [data-testid^="stBaseButton-pills"] {{ scroll-snap-align: start; }}

/* ── Narrow viewport ──
   The sidebar is a fixed 336px. On a 900px window that leaves ~560px for a page
   whose job is to show a pitch, so the content column has to actually shrink
   rather than spill. Flex children default to min-width:auto, which REFUSES to
   go below their content and pushes the overflow outside the box · that is what
   put 652px of card inside a 400px column. Everything below is that one fix
   plus the type and image rules that follow from it. */
[data-testid="stMainBlockContainer"], .block-container,
[data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"],
[data-testid="stColumn"], [data-testid="stElementContainer"],
[data-testid="stVerticalBlockBorderWrapper"] {{ min-width: 0 !important; }}

[data-testid="stMainBlockContainer"] img,
[data-testid="stMainBlockContainer"] svg {{ max-width: 100%; }}

/* Hero type scales with the column instead of clipping at the first breakpoint.
   The page hero is deliberately small already · this only lets it shrink. */
.ff-hero-title {{
  font-size: clamp(1.05rem, 2.4vw, 1.5rem) !important;
  line-height: 1.1; overflow-wrap: break-word;
}}

/* Any hand-built row of tiles wraps before it scrolls · a wrapped tile is
   readable, a clipped one is not. */
.ff-wrap-row {{ flex-wrap: wrap !important; }}

@media (max-width: 1100px) {{
  /* Reclaim the sidebar. It is navigation, not content. */
  [data-testid="stSidebar"] {{ min-width: 232px !important; max-width: 262px !important; }}
  [data-testid="stSidebar"] .stButton button {{ padding-left: 10px !important; }}
}}
@media (max-width: 820px) {{
  [data-testid="stSidebar"] {{ min-width: 200px !important; max-width: 216px !important; }}
  .stMainBlockContainer, [data-testid="stMainBlockContainer"], .block-container {{
    padding-left: 1.1rem !important; padding-right: 1.1rem !important;
  }}
}}

/* ── Controls ── */
/* DESCENDANT, not `>`. A button carrying a `help=` tooltip is wrapped by
   Streamlit in stTooltipIcon / stTooltipHoverTarget, so it stops being a direct
   child of .stButton and the child combinator silently missed it. Streamlit's
   own base theme is dark, so in LIGHT mode every button with a tooltip stayed
   near-black with near-black text. "+ New draft" was unreadable. */
.stButton button {{
  background: var(--ff-s2) !important; color: {ink} !important;
  border:1px solid var(--ff-line) !important; border-radius:8px !important;
  transition: transform .15s ease, border-color .15s, color .15s;
}}
.stButton button:hover {{
  border-color: var(--ff-mint) !important; color: var(--ff-mint) !important;
}}
.stSelectbox > div > div, .stMultiSelect > div > div,
.stNumberInput > div > div > input, .stTextInput > div > div > input {{
  background: var(--ff-s2) !important; border:1px solid var(--ff-line) !important;
  border-radius:8px !important; color: {ink} !important;
}}
[data-baseweb="popover"] ul, [data-baseweb="menu"] {{
  background: var(--ff-s1) !important; border:1px solid var(--ff-line) !important;
}}
[data-baseweb="popover"] li, [data-baseweb="menu"] li {{ color: {ink} !important; }}
[data-testid="stExpander"] details {{
  background: var(--ff-card) !important; border:1px solid var(--ff-line) !important;
  border-radius:12px !important;
}}
[data-testid="stExpander"] summary {{ color: {ink} !important; }}
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {{
  color: var(--ff-muted2) !important;
}}
[data-testid="stWidgetLabel"] p {{ color: var(--ff-muted) !important; font-weight:600; }}
[data-testid="stDialog"] > div {{
  background: var(--ff-bg2) !important; border:1px solid var(--ff-line) !important;
}}
hr {{ border-color: var(--ff-line) !important; }}

/* Category buttons · the accordion headers. Open one reads as a solid dark
   plate on the cyan; closed ones are quiet outlines. */
[data-testid="stSidebar"] .stButton button {{
  background: rgba(255,255,255,0.42) !important;
  border: 1px solid rgba(5,34,43,0.20) !important;
  color: var(--ff-side-ink) !important;
  font-weight: 800 !important; font-size: 12.5px !important;
  letter-spacing: 0.06em; text-transform: uppercase;
  border-radius: 10px !important; padding: 8px 12px !important;
  justify-content: flex-start !important;
}}
[data-testid="stSidebar"] .stButton button:hover {{
  background: rgba(255,255,255,0.72) !important;
  border-color: rgba(5,34,43,0.38) !important; color: var(--ff-side-ink) !important;
}}
[data-testid="stSidebar"] .stButton button[kind="primary"] {{
  background: var(--ff-side-ink) !important;
  border-color: var(--ff-side-ink) !important;
  color: #7FEAF8 !important;
}}
/* The label sits in a child element, which the blanket sidebar-ink rule also
   matches · without this the open category is dark text on a dark plate. */
[data-testid="stSidebar"] .stButton button[kind="primary"] * {{
  color: #7FEAF8 !important;
}}
[data-testid="stSidebar"] .stButton button[kind="secondary"] * {{
  color: var(--ff-side-ink) !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] {{ margin: 1px 0 1px 10px; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {{
  font-size: 13px !important; font-weight: 600 !important;
}}

#MainMenu {{ visibility: hidden; }}
footer    {{ visibility: hidden; }}
header    {{ visibility: hidden; }}

@media (prefers-reduced-motion: reduce) {{ .ff-card-3d {{ transition:none; }} }}

/* ── Mobile fit ── */
@media (max-width: 640px) {{
  .stMainBlockContainer, [data-testid="stMainBlockContainer"], .block-container {{
    padding-left: 1rem !important; padding-right: 1rem !important;
  }}
  h1 {{ font-size: 1.7rem !important; }}
  h2 {{ font-size: 1.3rem !important; }}
  [data-testid="stMarkdownContainer"] div {{ overflow-wrap: break-word; }}
  [data-testid="stMarkdownContainer"] .fplh-stagger,
  [data-testid="stMarkdownContainer"] .fplh-animate-in {{ flex-wrap: wrap !important; }}
  [data-testid="stDataFrame"] {{ overflow-x: auto; }}
}}
</style>
"""


def inject_theme() -> None:
    """Inject the global CSS for the active theme. Safe to call repeatedly.

    Runs on EVERY rerun · Streamlit removes elements that are not re-emitted, so
    guarding with session state kills the theme after the first interaction.
    """
    st.markdown(_css(palette(), is_light()), unsafe_allow_html=True)


def theme_toggle(location=None) -> str:
    """Light/dark switch. Returns the active theme.

    A two-option radio rather than a checkbox, so the current mode is readable at
    a glance instead of inferred from a tick.
    """
    host = location if location is not None else st.sidebar
    st.session_state.setdefault(THEME_KEY, _read_pref() or DEFAULT_THEME)
    choice = host.radio(
        "Appearance", ["🌙 Dark", "☀️ Light"],
        index=0 if current() == "dark" else 1,
        horizontal=True, key="_ff_theme_radio", label_visibility="collapsed")
    picked = "light" if "Light" in choice else "dark"
    if picked != st.session_state[THEME_KEY]:
        st.session_state[THEME_KEY] = picked
        _write_pref(picked)
        st.rerun()
    return picked


def component_css() -> str:
    """The variable block alone, for injecting into a component's iframe.

    An iframe does not inherit the host document's custom properties, so any
    bidirectional component that wants to follow the theme has to be handed them.
    Returns a `<style>` element ready to prepend to the component HTML.
    """
    return ("<style>:root{--ff-display:%s;%s}</style>"
            % (DISPLAY_STACK, _vars_block(palette())))


def chart_theme() -> Dict[str, str]:
    """Colours the ECharts helpers need · axis, grid, text, tooltip, accents."""
    p = palette()
    return {
        "text": p["text"], "muted": p["muted"], "grid": p["grid"],
        "axis": p["line-strong"], "tooltip_bg": p["card-solid"],
        "tooltip_border": p["line-strong"],
        "mint": p["mint"], "gold": p["gold"], "cyan": p["cyan"],
        "mag": p["mag"], "red": p["red"], "orange": p["orange"],
    }


def icon(name: str, size: int = 18, color: str = "currentColor") -> str:
    """Material Symbol as an inline HTML span (for st.markdown cards).

    Prefer this over emojis in HTML. Streamlit-native widgets (st.button,
    st.Page) should use ":material/<name>:".
    """
    return f'<span class="mi" style="font-size:{size}px;color:{color};">{name}</span>'
