"""Elevated design system · tokens + one global-CSS injector.

The "elevate current identity" direction: keep FF's dark + mint DNA, add depth
(deeper cinematic ground, surface tiers, glass, glow, subtle 3D on hover). This
module is additive · it complements the base CSS in app.py and the keyframes in
components/animations.py rather than replacing them, so existing pages keep working
while every surface gains the new depth.

Usage (once, in app.py after inject_global_animations):
    from ui.theme import inject_theme
    inject_theme()

Import tokens anywhere:
    from ui.theme import COLORS, GLASS
"""

from __future__ import annotations

from typing import Dict

import streamlit as st

# ── Tokens (single source of truth for the elevated palette) ──────────────────
COLORS: Dict[str, str] = {
    "bg":        "#0B0E13",   # deepened cinematic ground (was #151922)
    "bg2":       "#0E1219",
    "surface1":  "#151922",
    "surface2":  "#1B2130",
    "surface3":  "#232B3B",
    "line":      "rgba(255,255,255,0.08)",
    "text":      "#EEF1F5",
    "muted":     "rgba(236,241,245,0.56)",
    "muted2":    "rgba(236,241,245,0.34)",
    "mint":      "#00FF87",   # primary / positive / glow
    "gold":      "#FFD700",   # captain / premium
    "cyan":      "#04F5FF",   # data / xP
    "magenta":   "#E90052",   # MID / highlight
    "red":       "#FF4B4B",   # danger
    "orange":    "#FFA500",   # warning
}
GLASS = "rgba(26,32,46,0.55)"
GLASS_BRD = "rgba(255,255,255,0.08)"

# Pitch (stadium depth) · used by the pitch redesign in Phase 2.
PITCH = {"g1": "#0d3f20", "g2": "#12592e", "g3": "#16632f"}


# Display face: Archivo (modern grotesque with heavy/expanded weights) for
# headings + big stat numbers · a broadcast-graphics feel. Body stays on the
# Inter/SF system stack. If the webfont can't load (offline), the stack falls back
# cleanly, so nothing breaks.
DISPLAY_STACK = "'Archivo','SF Pro Display',system-ui,-apple-system,sans-serif"

_THEME_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0&display=swap');
:root {{
  --ff-display:{DISPLAY_STACK};
  --ff-bg:{COLORS['bg']}; --ff-bg2:{COLORS['bg2']};
  --ff-s1:{COLORS['surface1']}; --ff-s2:{COLORS['surface2']}; --ff-s3:{COLORS['surface3']};
  --ff-line:{COLORS['line']};
  --ff-text:{COLORS['text']}; --ff-mut:{COLORS['muted']}; --ff-mut2:{COLORS['muted2']};
  --ff-mint:{COLORS['mint']}; --ff-gold:{COLORS['gold']}; --ff-cyan:{COLORS['cyan']};
  --ff-mag:{COLORS['magenta']}; --ff-red:{COLORS['red']}; --ff-orange:{COLORS['orange']};
  --ff-glass:{GLASS}; --ff-glass-brd:{GLASS_BRD};
}}

/* ── Cinematic ground · gradient mesh over the deepened base ── */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1200px 620px at 12% -8%, rgba(0,255,135,0.07), transparent 60%),
    radial-gradient(1000px 520px at 100% 0%, rgba(4,245,255,0.05), transparent 55%),
    var(--ff-bg) !important;
}}
[data-testid="stHeader"] {{ background: transparent !important; }}

/* ── Refined scrollbar ── */
::-webkit-scrollbar {{ width:10px; height:10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{
  background: rgba(255,255,255,0.10); border-radius:999px;
  border:2px solid transparent; background-clip: padding-box;
}}
::-webkit-scrollbar-thumb:hover {{ background: rgba(0,255,135,0.30); background-clip: padding-box; }}

/* ── Reusable depth utilities (opt-in via class) ── */
.ff-glass {{
  background: var(--ff-glass); border:1px solid var(--ff-glass-brd);
  border-radius:16px; backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}}
.ff-glow-mint {{ box-shadow: 0 0 24px rgba(0,255,135,0.18); }}
.ff-glow-gold {{ box-shadow: 0 0 24px rgba(255,215,0,0.20); }}
.ff-hairline {{ height:1px; background: var(--ff-line); border:0; }}

/* Professional icons (Material Symbols) for inline HTML · use ui.theme.icon() */
.mi {{
  font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal;
  line-height: 1; vertical-align: middle; display: inline-block;
  -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga';
  -webkit-font-smoothing: antialiased; user-select: none;
}}

/* Subtle 3D lift on hover · pair with an existing card */
.ff-card-3d {{
  transition: transform .18s cubic-bezier(.2,.8,.2,1),
              box-shadow .18s ease, border-color .18s ease;
  transform-style: preserve-3d;
}}
.ff-card-3d:hover {{
  transform: translateY(-4px);
  box-shadow: 0 18px 44px rgba(0,0,0,0.45), 0 0 0 1px rgba(0,255,135,0.20);
  border-color: rgba(0,255,135,0.35) !important;
}}

/* ── Type · display face on headings + big numbers (broadcast scale) ── */
h1, h2, h3 {{ font-family: var(--ff-display) !important; }}
h1 {{ letter-spacing:-0.03em !important; font-weight:900 !important; }}
h2, h3 {{ letter-spacing:-0.01em !important; }}
[data-testid="stMetricValue"] {{ font-family: var(--ff-display) !important; }}
.ff-display {{ font-family: var(--ff-display); letter-spacing:-0.02em; }}

@media (prefers-reduced-motion: reduce) {{
  .ff-card-3d {{ transition:none; }}
}}

/* ── Mobile fit · phone-width tuning without touching page code ── */
@media (max-width: 640px) {{
  /* Reclaim horizontal space Streamlit reserves for desktop */
  .stMainBlockContainer, [data-testid="stMainBlockContainer"],
  .block-container {{
    padding-left: 1rem !important; padding-right: 1rem !important;
  }}
  /* Custom heroes are inline-styled at 40-48px; cap what we can reach */
  h1 {{ font-size: 1.7rem !important; }}
  h2 {{ font-size: 1.3rem !important; }}
  /* Big inline-styled display numbers and hero titles wrap instead of clipping */
  [data-testid="stMarkdownContainer"] div {{
    overflow-wrap: break-word;
  }}
  /* Stat strips and card rows built as flex always wrap on phones */
  [data-testid="stMarkdownContainer"] .fplh-stagger,
  [data-testid="stMarkdownContainer"] .fplh-animate-in {{
    flex-wrap: wrap !important;
  }}
  /* Dataframes and wide tables scroll inside their own box */
  [data-testid="stDataFrame"] {{ overflow-x: auto; }}
}}
</style>
"""


def inject_theme() -> None:
    """Inject the elevated global CSS. Safe to call repeatedly.

    Runs on EVERY rerun · Streamlit removes elements that aren't re-emitted,
    so guarding with session state kills the theme after the first interaction.
    """
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def icon(name: str, size: int = 18, color: str = "currentColor") -> str:
    """Professional Material Symbol as an inline HTML span (for st.markdown cards).

    Prefer this over emojis in HTML. Example: icon("mic", 16, COLORS["gold"]).
    Streamlit-native widgets (st.button, st.Page) should use ":material/<name>:".
    """
    return (f'<span class="mi" style="font-size:{size}px;color:{color};">'
            f'{name}</span>')
