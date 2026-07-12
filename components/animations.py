"""
Animation helpers for the FPL Hub app.

Provides a global CSS injection (keyframes + utility classes), an SVG
"scribble" overlay used when swapping squad players, and a confetti
celebration burst for captaincy / top-pick moments.

Streamlit reruns the script top-to-bottom on every interaction, so
anything rendered once with an `animation: ... forwards` CSS keyframe
plays exactly once per rerun. That matches the desired UX: animate on
swap, fade away, then the next rerun clears the overlay.
"""

from __future__ import annotations

import random
import streamlit as st


# ── Global CSS · inject once per page ─────────────────────────────────────────
_GLOBAL_CSS = """
<style>
/* ────── Keyframes ────── */
@keyframes fplh-fade-in-up {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes fplh-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes fplh-pulse-gold {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,215,0,0.45); }
  50%      { box-shadow: 0 0 24px 6px rgba(255,215,0,0.45); }
}
@keyframes fplh-pop-in {
  0%   { transform: scale(0.6); opacity: 0; }
  70%  { transform: scale(1.06); opacity: 1; }
  100% { transform: scale(1); opacity: 1; }
}
@keyframes fplh-shake-x {
  0%,100% { transform: translateX(0); }
  20%     { transform: translateX(-3px); }
  40%     { transform: translateX(3px); }
  60%     { transform: translateX(-2px); }
  80%     { transform: translateX(2px); }
}
@keyframes fplh-count-tick {
  from { opacity: 0; transform: scale(1.18); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes fplh-scribble-draw {
  0%   { stroke-dashoffset: 3000; }
  100% { stroke-dashoffset: 0; }
}
@keyframes fplh-x-mark {
  0%   { stroke-dashoffset: 400; opacity: 0; }
  20%  { opacity: 1; }
  100% { stroke-dashoffset: 0; opacity: 1; }
}
@keyframes fplh-overlay-fade {
  0%,75% { opacity: 1; }
  100%   { opacity: 0; visibility: hidden; }
}
@keyframes fplh-confetti-fall {
  0%   { transform: translateY(-20px) rotate(0deg); opacity: 1; }
  100% { transform: translateY(120vh) rotate(540deg); opacity: 0; }
}

/* ────── Utility classes ────── */
.fplh-animate-in {
  animation: fplh-fade-in-up 0.55s cubic-bezier(0.2, 0.8, 0.2, 1) both;
}
/* Stagger: apply to grid children */
.fplh-stagger > * { animation: fplh-fade-in-up 0.55s cubic-bezier(0.2, 0.8, 0.2, 1) both; }
.fplh-stagger > *:nth-child(1)  { animation-delay: 0.02s; }
.fplh-stagger > *:nth-child(2)  { animation-delay: 0.06s; }
.fplh-stagger > *:nth-child(3)  { animation-delay: 0.10s; }
.fplh-stagger > *:nth-child(4)  { animation-delay: 0.14s; }
.fplh-stagger > *:nth-child(5)  { animation-delay: 0.18s; }
.fplh-stagger > *:nth-child(6)  { animation-delay: 0.22s; }
.fplh-stagger > *:nth-child(7)  { animation-delay: 0.26s; }
.fplh-stagger > *:nth-child(8)  { animation-delay: 0.30s; }
.fplh-stagger > *:nth-child(9)  { animation-delay: 0.34s; }
.fplh-stagger > *:nth-child(10) { animation-delay: 0.38s; }
.fplh-stagger > *:nth-child(n+11) { animation-delay: 0.42s; }

.fplh-card-hover {
  transition: transform 0.18s cubic-bezier(0.2, 0.8, 0.2, 1),
              border-color 0.18s ease,
              box-shadow 0.18s ease;
}
.fplh-card-hover:hover {
  transform: translateY(-3px);
  border-color: rgba(0,255,135,0.45) !important;
  box-shadow: 0 10px 24px rgba(0,0,0,0.35), 0 0 0 1px rgba(0,255,135,0.18);
}

.fplh-captain-pulse {
  animation: fplh-pulse-gold 2.2s ease-in-out infinite;
  border-radius: 50%;
}

.fplh-pop {
  animation: fplh-pop-in 0.35s cubic-bezier(0.2, 0.8, 0.2, 1) both;
}
.fplh-shake { animation: fplh-shake-x 0.4s ease-in-out; }

.fplh-count {
  display: inline-block;
  animation: fplh-count-tick 0.45s ease-out both;
}

/* ────── Count-up numbers (pure CSS · registered custom properties) ────── */
@property --fplh-n  { syntax: "<integer>"; initial-value: 0; inherits: false; }
@property --fplh-d  { syntax: "<integer>"; initial-value: 0; inherits: false; }
@keyframes fplh-countup   { from { --fplh-n: 0; } }
@keyframes fplh-countup-d { from { --fplh-d: 0; } }
.fplh-countup {
  display: inline-block;
  font-variant-numeric: tabular-nums;
  animation: fplh-countup 1.1s cubic-bezier(0.16, 1, 0.3, 1) both;
  counter-reset: fplh-n calc(var(--fplh-n));
}
.fplh-countup::after { content: counter(fplh-n); }
.fplh-countup.fplh-countup-dec {
  animation: fplh-countup 1.1s cubic-bezier(0.16, 1, 0.3, 1) both,
             fplh-countup-d 1.1s cubic-bezier(0.16, 1, 0.3, 1) both;
  counter-reset: fplh-n calc(var(--fplh-n)) fplh-d calc(var(--fplh-d));
}
.fplh-countup.fplh-countup-dec::after { content: counter(fplh-n) "." counter(fplh-d); }
</style>
"""


_COUNTUP_SEQ = 0


def count_up(value, decimals: int = 0) -> str:
    """An inline count-up number (CSS counters, no JS · Chromium/Safari 16.4+).

    Returns a <span> for embedding in st.markdown HTML. Supports 0 or 1
    decimal places and non-negative values only; anything else falls back
    to plain formatted text so the number is always shown.

    The target value travels in a per-instance <style> rule, NOT an inline
    style attribute · Streamlit's HTML sanitiser strips style attributes
    that contain only CSS custom properties.
    """
    global _COUNTUP_SEQ
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v < 0 or decimals not in (0, 1):
        return f"{v:,.{max(decimals, 0)}f}"
    _COUNTUP_SEQ += 1
    uid = f"fplh-cu-{_COUNTUP_SEQ}"
    if decimals == 0:
        return (f'<span class="fplh-countup {uid}"></span>'
                f'<style>.{uid}{{--fplh-n:{int(round(v))};}}</style>')
    ip = int(v)
    dp = int(round((v - ip) * 10))
    if dp == 10:          # e.g. 56.96 rounds up to 57.0
        ip, dp = ip + 1, 0
    return (f'<span class="fplh-countup fplh-countup-dec {uid}"></span>'
            f'<style>.{uid}{{--fplh-n:{ip};--fplh-d:{dp};}}</style>')


def inject_global_animations() -> None:
    """Inject global CSS (keyframes + utility classes). Safe to call multiple times.

    Must run on EVERY rerun · Streamlit drops elements that aren't re-emitted,
    so a session-state guard here silently kills all animation CSS after the
    first interaction (hover lifts, count-ups, stagger all stop working).
    """
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


# ── Scribble swap overlay ─────────────────────────────────────────────────────
def scribble_swap_overlay(
    out_name: str = "",
    in_name: str = "",
    duration_ms: int = 1600,
) -> str:
    """Return HTML for a full-screen scribble overlay shown on a squad swap.

    Draws a gold scribble across the screen, X's out the old player's name,
    then fades in the new player's name with a "signed in" accent. The whole
    overlay auto-fades after ~`duration_ms`.
    """
    draw_dur = duration_ms * 0.55   # scribble draw
    x_dur    = duration_ms * 0.35   # X mark
    fade_dur = duration_ms / 1000.0

    return f"""
<div class="fplh-swap-overlay" style="
    position:fixed; top:0; left:0; right:0; bottom:0; z-index:9999;
    pointer-events:none;
    animation: fplh-overlay-fade {fade_dur:.2f}s ease-in forwards;
    animation-delay: 0s;
">
  <svg viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid meet"
       style="width:100%;height:100%;">
    <!-- Paper-scribble streak (gold, hand-drawn look) -->
    <path
      d="M 80,360 Q 200,200 340,360 T 640,360 T 940,360 T 1120,360"
      stroke="#FFD700" stroke-width="10" fill="none"
      stroke-linecap="round" stroke-linejoin="round"
      stroke-dasharray="3000" stroke-dashoffset="3000"
      style="animation: fplh-scribble-draw {draw_dur:.0f}ms cubic-bezier(0.5,0.1,0.2,1) forwards;
             filter: drop-shadow(0 2px 2px rgba(0,0,0,0.25));"
    />

    <!-- Red X mark across left half for the OUT player -->
    <g style="opacity:0; animation: fplh-fade-in 0.2s {draw_dur * 0.6:.0f}ms forwards;">
      <line x1="260" y1="260" x2="500" y2="460" stroke="#FF4B4B" stroke-width="12"
            stroke-linecap="round" stroke-dasharray="400" stroke-dashoffset="400"
            style="animation: fplh-x-mark {x_dur:.0f}ms {draw_dur * 0.6:.0f}ms forwards;"/>
      <line x1="500" y1="260" x2="260" y2="460" stroke="#FF4B4B" stroke-width="12"
            stroke-linecap="round" stroke-dasharray="400" stroke-dashoffset="400"
            style="animation: fplh-x-mark {x_dur:.0f}ms {draw_dur * 0.75:.0f}ms forwards;"/>
    </g>

    <!-- OUT name (struck-through) -->
    <text x="380" y="360" text-anchor="middle"
          font-family="Inter, sans-serif" font-size="44" font-weight="800"
          fill="#ffffff" opacity="0.75"
          style="animation: fplh-fade-in 0.3s 0.2s both;">
      {_escape(out_name)}
    </text>

    <!-- IN name (green, pops in) -->
    <text x="820" y="360" text-anchor="middle"
          font-family="Inter, sans-serif" font-size="52" font-weight="900"
          fill="#00FF87"
          style="opacity:0; animation: fplh-pop-in 0.4s {draw_dur:.0f}ms forwards;">
      {_escape(in_name)}
    </text>

    <!-- Arrow -->
    <g style="opacity:0; animation: fplh-fade-in 0.3s {draw_dur * 0.3:.0f}ms forwards;">
      <path d="M 560,360 L 720,360" stroke="#ffffff" stroke-width="5" stroke-linecap="round"/>
      <path d="M 700,340 L 720,360 L 700,380" stroke="#ffffff" stroke-width="5"
            stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </g>
  </svg>
</div>
"""


def _escape(text: str) -> str:
    """Minimal XML escape for SVG <text>."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ── Confetti burst (captain picked / 20+ haul) ────────────────────────────────
_CONFETTI_COLORS = ["#00FF87", "#FFD700", "#04f5ff", "#e90052", "#FF7B00", "#a3e635"]


def confetti_burst(n_pieces: int = 80, duration_ms: int = 2500) -> str:
    """Return HTML for a short confetti burst overlay."""
    pieces = []
    for _ in range(n_pieces):
        left = random.randint(0, 100)
        delay = random.randint(0, 400)
        dur = random.randint(1400, duration_ms)
        size = random.randint(6, 12)
        rotate = random.randint(-45, 45)
        color = random.choice(_CONFETTI_COLORS)
        pieces.append(
            f'<span style="position:absolute;top:-20px;left:{left}%;width:{size}px;'
            f'height:{size}px;background:{color};transform:rotate({rotate}deg);'
            f'border-radius:2px;animation:fplh-confetti-fall {dur}ms {delay}ms '
            f'cubic-bezier(0.4,0,0.6,1) forwards;"></span>'
        )
    return (
        '<div style="position:fixed;top:0;left:0;right:0;bottom:0;z-index:9998;'
        'pointer-events:none;overflow:hidden;">'
        + "".join(pieces) + "</div>"
    )
