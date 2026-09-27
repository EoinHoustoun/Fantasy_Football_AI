"""The Floodlit page masthead and section rule, shared by every page.

One look for every page: a mint kicker, a display title, one lead line. Pages
used to each invent their own (emoji st.title, a cyan headline, a 42px one),
which is what made the app read as three apps.
"""
import streamlit as st

from ui import theme
from ui.theme import var as V


def _one(html: str) -> str:
    return "".join(seg.strip() for seg in html.splitlines())


def header(title: str, lead: str = "", kicker: str = "", icon: str = "") -> None:
    ic = theme.icon(icon, 30, V("mint")) if icon else ""
    st.markdown(_one(
        f'<div class="ff-rise" style="padding:10px 0 14px;">'
        + (f'<div style="font-size:11px;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;'
           f'color:{V("mint")};margin-bottom:6px;">{kicker}</div>' if kicker else "")
        + f'<div style="display:flex;align-items:center;gap:12px;">{ic}'
          f'<div class="ff-display" style="font-size:40px;font-weight:900;letter-spacing:-1.1px;'
          f'line-height:1.02;color:{V("text")};">{title}</div></div>'
        + (f'<div style="font-size:15px;color:{V("muted")};margin-top:8px;max-width:900px;'
           f'line-height:1.5;">{lead}</div>' if lead else "")
        + '</div>'), unsafe_allow_html=True)


def section(title: str, lead: str = "", icon: str = "") -> None:
    ic = theme.icon(icon, 20, V("mint")) if icon else ""
    st.markdown(_one(
        f'<div style="display:flex;align-items:center;gap:12px;margin:26px 0 10px;">{ic}'
        f'<div class="ff-display" style="font-size:20px;font-weight:800;color:{V("text")};">{title}</div>'
        f'<div style="flex:1;height:1px;background:{V("line")};"></div></div>'
        + (f'<div style="font-size:13.5px;color:{V("muted")};margin:-4px 0 12px;">{lead}</div>' if lead else "")),
        unsafe_allow_html=True)


def tiles(items) -> None:
    """A row of stat tiles: [(label, value_html, sub, tone), ...].

    `value_html` may be a `count_up` span. Tone is a token name (mint, gold,
    red, cyan, text); it colours the value and the tile's top rule.
    """
    cells = "".join(
        f'<div style="flex:1;min-width:140px;background:{V("card")};border:1px solid {V("line")};'
        f'border-top:3px solid {V(tone)};border-radius:14px;padding:14px 16px;">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;'
        f'color:{V("muted2")};">{label}</div>'
        f'<div class="ff-display ff-num" style="font-size:28px;font-weight:900;color:{V(tone)};'
        f'margin-top:4px;">{value}</div>'
        f'<div style="font-size:12.5px;color:{V("muted")};margin-top:2px;">{sub}</div></div>'
        for label, value, sub, tone in items)
    st.markdown(_one(f'<div class="fplh-stagger" style="display:flex;gap:12px;flex-wrap:wrap;'
                     f'margin:6px 0 14px;">{cells}</div>'), unsafe_allow_html=True)
