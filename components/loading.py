"""
On-brand loading experience.

Replaces Streamlit's raw default spinner (which leaks internal function names
like "Running _replay_lookup().") with a themed overlay: a rolling football on a
mint→purple pitch stripe, a shimmering progress bar, and rotating FPL-flavoured
status lines so waits feel intentional and fun.

Usage:
    from components.loading import fpl_loader

    with fpl_loader("Solving your perfect season", SOLVER_LINES):
        result = expensive_cached_call()

Pair with `@st.cache_data(show_spinner=False)` on the wrapped function so the
default spinner never shows.
"""

from __future__ import annotations

import contextlib
import html
from typing import Iterator, List, Optional

import streamlit as st


# ── Rotating status lines (pick a themed pool per call, or use the default) ─────
LINES_GENERIC: List[str] = [
    "Waking up the data…",
    "Counting every touch…",
    "Reading the xG tea leaves…",
    "Arguing about penalties…",
]
LINES_SQUAD: List[str] = [
    "Fetching your XI…",
    "Checking who's actually fit…",
    "Weighing up your captain…",
    "Scanning the fixture swing…",
]
LINES_SOLVER: List[str] = [
    "Simulating 38 gameweeks…",
    "Trying every transfer path…",
    "Timing the chips…",
    "Chasing the perfect season…",
]
LINES_MODEL: List[str] = [
    "Projecting minutes…",
    "Carrying form forward…",
    "Pricing in the fixtures…",
    "Ranking the contenders…",
]


def _loader_html(title: str, messages: List[str]) -> str:
    safe_title = html.escape(title)
    # Stack the messages; CSS cycles their opacity so the text appears to rotate.
    n = max(1, len(messages))
    span = 100.0 / n
    msg_divs = "".join(
        f'<div class="fplh-load-msg" style="animation-delay:{i * (2.4):.1f}s;">{html.escape(m)}</div>'
        for i, m in enumerate(messages)
    )
    total = n * 2.4
    # Build the keyframe window: each message is visible for its slice of the cycle.
    on = min(90.0, span * 0.75)
    return f"""
<style>
  .fplh-load-wrap {{
      position:relative;overflow:hidden;
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:16px;padding:44px 24px;margin:8px 0 4px;border-radius:20px;
      background:radial-gradient(120% 90% at 50% -20%, rgba(0,255,135,0.14), transparent 55%),
                 radial-gradient(90% 120% at 50% 120%, rgba(4,245,255,0.08), transparent 60%),
                 linear-gradient(135deg, rgba(27,33,48,0.72), rgba(11,14,19,0.82));
      border:1px solid rgba(255,255,255,0.09);
      backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
      box-shadow:0 20px 60px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.05),
                 0 0 40px rgba(0,255,135,0.06);
      font-family:'Inter','SF Pro Display',sans-serif;
  }}
  /* floodlight sweep across the top of the card */
  .fplh-load-wrap::before {{
      content:'';position:absolute;top:-60%;left:50%;transform:translateX(-50%);
      width:70%;height:90%;pointer-events:none;
      background:radial-gradient(ellipse at center, rgba(255,255,255,0.10), transparent 62%);
  }}
  .fplh-load-pitch {{
      position:relative;width:260px;height:14px;border-radius:8px;overflow:hidden;
      background:repeating-linear-gradient(90deg,#12401f 0 26px,#0e3018 26px 52px);
      box-shadow:inset 0 0 18px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.06);
  }}
  .fplh-load-ball {{
      position:absolute;top:-12px;left:0;font-size:28px;line-height:1;
      filter:drop-shadow(0 3px 4px rgba(0,0,0,0.55));
      animation: fplh-roll 1.9s cubic-bezier(.5,0,.4,1) infinite;
  }}
  @keyframes fplh-roll {{
      0%   {{ left:-8px;  transform:rotate(0deg) translateY(0); }}
      50%  {{ transform:rotate(540deg) translateY(-3px); }}
      100% {{ left:242px; transform:rotate(1080deg) translateY(0); }}
  }}
  .fplh-load-title {{
      font-family:'Archivo','SF Pro Display',sans-serif;
      font-size:17px;font-weight:900;color:#fff;letter-spacing:-0.3px;text-align:center;
  }}
  .fplh-load-msgbox {{ position:relative;height:18px;width:100%;max-width:340px; }}
  .fplh-load-msg {{
      position:absolute;left:0;right:0;text-align:center;opacity:0;
      font-size:12px;font-weight:600;color:#04f5ff;letter-spacing:0.02em;
      animation: fplh-msgfade {total:.1f}s infinite;
  }}
  @keyframes fplh-msgfade {{
      0%       {{ opacity:0; transform:translateY(5px); }}
      4%       {{ opacity:1; transform:none; }}
      {on:.0f}% {{ opacity:1; transform:none; }}
      {min(99.0, on + 6):.0f}% {{ opacity:0; transform:translateY(-4px); }}
      100%     {{ opacity:0; }}
  }}
  .fplh-load-bar {{
      width:220px;height:3px;border-radius:3px;overflow:hidden;background:rgba(255,255,255,0.08);
  }}
  .fplh-load-bar::after {{
      content:'';display:block;height:100%;width:40%;border-radius:3px;
      background:linear-gradient(90deg, transparent, #00FF87, transparent);
      animation: fplh-shimmer 1.3s linear infinite;
  }}
  @keyframes fplh-shimmer {{ 0%{{transform:translateX(-100%);}} 100%{{transform:translateX(320%);}} }}
</style>
<div class="fplh-load-wrap">
  <div class="fplh-load-title">{safe_title}</div>
  <div class="fplh-load-pitch"><span class="fplh-load-ball">⚽</span></div>
  <div class="fplh-load-bar"></div>
  <div class="fplh-load-msgbox">{msg_divs}</div>
</div>
"""


@contextlib.contextmanager
def fpl_loader(title: str = "Crunching the numbers",
               messages: Optional[List[str]] = None) -> Iterator[None]:
    """Show the themed loader while the wrapped block runs, then clear it."""
    placeholder = st.empty()
    placeholder.markdown(_loader_html(title, messages or LINES_GENERIC),
                         unsafe_allow_html=True)
    try:
        yield
    finally:
        placeholder.empty()
