"""A stat badge: the number, what it means, and how good it is.

A bare number is not information. "6.7 DEFCON per 90" tells you nothing unless
you already know the distribution; "better than 84% of defenders" tells you
everything, and the bar says it before you have read the words.

Pure string building, no Streamlit, so it is unit-testable · same shape as
`ff_table.build_html`.

Every function returns ONE line. `st.markdown` stops passing raw HTML through
when a line is whitespace-only and renders the rest as literal `<span>` text,
which has already bitten the Value Board cards.
"""
from typing import Dict, List, Optional

from ui.theme import var as V

# Where a percentile stops being good news. Deliberately generous at the top:
# on projections that validate at Spearman ~0.4, the difference between the
# 80th and 90th percentile is not a difference anyone should act on.
_GOOD, _OK = 70, 40


def tone_for(percentile: Optional[int]) -> str:
    """Colour token for a rank. Muted when there is no rank to show."""
    if percentile is None:
        return "muted"
    if percentile >= _GOOD:
        return "mint"
    if percentile >= _OK:
        return "gold"
    return "red"


def _fmt(value) -> str:
    if value is None:
        return "—"
    s = str(value)
    return s if s.strip() and s.lower() != "nan" else "—"


def badge_html(label: str, value, sub: str = "", percentile: Optional[int] = None,
               tone: Optional[str] = None, note: str = "",
               bar: Optional[int] = None) -> str:
    """One stat, with an optional 0-100 bar under it.

    `percentile` is a RANK · it draws the bar and captions it "Top X%".
    `bar` is any other 0-100 quantity, most often a probability. It draws the
    same bar and says nothing about rank, because a 39% clean-sheet chance is
    not a position in a distribution and calling it "Top 61%" is nonsense.
    """
    tone = tone or tone_for(percentile if percentile is not None else bar)
    col = V(tone)
    fill = percentile if percentile is not None else bar
    bar_html = ""
    if fill is not None:
        pct = max(0, min(100, int(fill)))
        caption = ("Top %d%%" % (100 - pct)) if percentile is not None else ""
        if note:
            caption = ("%s · %s" % (caption, note)) if caption else note
        bar_html = (f'<div class="ff-badge-bar" style="height:3px;border-radius:2px;'
                    f'background:{V("line")};margin-top:7px;overflow:hidden;">'
                    f'<div style="height:3px;width:{pct}%;background:{col};'
                    f'border-radius:2px;"></div></div>'
                    + (f'<div style="font-size:9.5px;color:{V("muted")};'
                       f'margin-top:4px;letter-spacing:0.04em;">{caption}</div>'
                       if caption else ""))
    elif note:
        bar_html = (f'<div style="font-size:9.5px;color:{V("muted")};'
                    f'margin-top:6px;">{note}</div>')

    return "".join(seg.strip() for seg in (
        f'<div style="flex:1 1 132px;min-width:132px;background:{V("card")};'
        f'border:1px solid {V("line")};border-radius:10px;padding:11px 12px;">'
        f'<div style="font-size:9.5px;font-weight:800;letter-spacing:0.14em;'
        f'text-transform:uppercase;color:{V("muted")};">{label}</div>'
        f'<div class="ff-display" style="font-size:23px;font-weight:900;'
        f'color:{col};line-height:1.15;margin-top:3px;'
        f'font-variant-numeric:tabular-nums;">{_fmt(value)}</div>'
        + (f'<div style="font-size:10.5px;color:{V("muted")};margin-top:1px;">'
           f'{sub}</div>' if sub else '')
        + bar_html
        + '</div>').splitlines())


def badges_row(items: List[Dict]) -> str:
    """A responsive row of badges. Each item takes badge_html's arguments."""
    if not items:
        return ""
    inner = "".join(badge_html(**it) for it in items)
    return ('<div style="display:flex;flex-wrap:wrap;gap:9px;margin:8px 0 4px;">'
            + inner + '</div>')
