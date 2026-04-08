"""
Football pitch view component.

Renders a squad on a stylised green pitch with FPL shirt images,
captain/VC badges, form labels, and a bench section below.

Shirt images served from the official FPL CDN using each team's code field.
  Outfield:    shirt_{code}_1-66.png
  Goalkeeper:  shirt_{code}_2-66.png
"""

import pandas as pd
import streamlit as st
from typing import List


_SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"


def _shirt_url(team_code: int, is_gkp: bool) -> str:
    t = "2" if is_gkp else "1"
    return f"{_SHIRT_BASE}/shirt_{team_code}_{t}-66.png"


def _card(row: pd.Series, is_bench: bool = False) -> str:
    code   = int(row.get("team_code", 1) or 1)
    is_gkp = str(row.get("position", "")) == "GKP"
    name   = str(row.get("web_name", "?"))
    form   = float(row.get("form", 0) or 0)
    is_cap = bool(row.get("is_captain", False))
    is_vc  = bool(row.get("is_vice_captain", False))
    status = str(row.get("status", "a"))

    url      = _shirt_url(code, is_gkp)
    fallback = f"{_SHIRT_BASE}/shirt_1_1-66.png"

    badge = ""
    if is_cap:
        badge = (
            '<div style="position:absolute;top:-7px;right:-7px;'
            'background:#00FF87;color:#000;border-radius:50%;'
            'width:18px;height:18px;line-height:18px;text-align:center;'
            'font-size:10px;font-weight:900;border:1px solid #000;">C</div>'
        )
    elif is_vc:
        badge = (
            '<div style="position:absolute;top:-7px;right:-7px;'
            'background:#ccc;color:#000;border-radius:50%;'
            'width:18px;height:18px;line-height:18px;text-align:center;'
            'font-size:10px;font-weight:900;border:1px solid #888;">V</div>'
        )

    dot = ""
    if status == "i":
        dot = ('<div style="position:absolute;bottom:0;left:0;'
               'background:#FF4B4B;border-radius:50%;width:10px;height:10px;'
               'border:1px solid #fff;"></div>')
    elif status == "d":
        dot = ('<div style="position:absolute;bottom:0;left:0;'
               'background:#FFA500;border-radius:50%;width:10px;height:10px;'
               'border:1px solid #fff;"></div>')

    opacity = "0.6" if is_bench else "1"
    label   = (name[:9] + ".") if len(name) > 10 else name

    return (
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'width:72px;opacity:{opacity};">'
        f'<div style="position:relative;display:inline-block;">'
        f'<img src="{url}" width="44" onerror="this.src=\'{fallback}\'" />'
        f'{badge}{dot}'
        f'</div>'
        f'<div style="background:rgba(0,0,0,0.72);color:#fff;padding:2px 5px;'
        f'border-radius:3px;font-size:11px;margin-top:3px;white-space:nowrap;'
        f'max-width:70px;overflow:hidden;text-overflow:ellipsis;'
        f'text-align:center;">{label}</div>'
        f'<div style="color:#00FF87;font-size:10px;margin-top:1px;">{form:.1f}</div>'
        f'</div>'
    )


def _position_row(players: List[pd.Series]) -> str:
    cards = "".join(_card(p) for p in players)
    return (
        '<div style="display:flex;justify-content:space-evenly;'
        'align-items:flex-start;padding:14px 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.07);">'
        + cards +
        '</div>'
    )


def render_pitch_view(squad_df: pd.DataFrame) -> None:
    """
    Render the squad on a green pitch with FPL-style shirts.

    Required columns: web_name, position, team_code, form,
                      is_captain, is_vice_captain, on_bench,
                      squad_position, status
    """
    xi    = squad_df[~squad_df["on_bench"]].sort_values("squad_position")
    bench = squad_df[squad_df["on_bench"]].sort_values("squad_position")

    gkps = [r for _, r in xi.iterrows() if r["position"] == "GKP"]
    defs = [r for _, r in xi.iterrows() if r["position"] == "DEF"]
    mids = [r for _, r in xi.iterrows() if r["position"] == "MID"]
    fwds = [r for _, r in xi.iterrows() if r["position"] == "FWD"]

    formation   = f"{len(defs)}-{len(mids)}-{len(fwds)}"
    bench_cards = "".join(_card(r, is_bench=True) for _, r in bench.iterrows())

    html = (
        '<div style="font-family:sans-serif;max-width:600px;margin:0 auto;">'

        f'<div style="text-align:right;color:rgba(255,255,255,0.4);'
        f'font-size:12px;margin-bottom:5px;">Formation: {formation}</div>'

        '<div style="background:linear-gradient(180deg,'
        '#1a5e16 0%,#22721d 20%,#1a5e16 40%,'
        '#22721d 60%,#1a5e16 80%,#22721d 100%);'
        'border:2px solid rgba(255,255,255,0.12);'
        'border-radius:8px;overflow:hidden;">'

        '<div style="margin:0 10%;border:1px solid rgba(255,255,255,0.08);'
        'border-radius:4px;">'
        + _position_row(fwds)
        + _position_row(mids)
        + _position_row(defs)
        + _position_row(gkps)
        + '</div>'

        '<div style="border-top:2px dashed rgba(255,255,255,0.25);'
        'padding:10px 8px 12px;background:rgba(0,0,0,0.15);">'
        '<div style="color:rgba(255,255,255,0.4);font-size:10px;'
        'letter-spacing:3px;text-align:center;margin-bottom:8px;">BENCH</div>'
        '<div style="display:flex;justify-content:space-evenly;">'
        + bench_cards
        + '</div></div></div>'

        '<div style="color:rgba(255,255,255,0.3);font-size:10px;'
        'margin-top:5px;text-align:center;line-height:1.8;">'
        'Number = form&nbsp;|&nbsp;'
        '<span style="background:#00FF87;color:#000;border-radius:50%;'
        'display:inline-block;width:14px;height:14px;line-height:14px;'
        'text-align:center;font-size:9px;font-weight:900;">C</span>&nbsp;Captain&nbsp;|&nbsp;'
        '<span style="background:#ccc;color:#000;border-radius:50%;'
        'display:inline-block;width:14px;height:14px;line-height:14px;'
        'text-align:center;font-size:9px;font-weight:900;">V</span>&nbsp;Vice&nbsp;|&nbsp;'
        '<span style="background:#FF4B4B;border-radius:50%;display:inline-block;'
        'width:8px;height:8px;vertical-align:middle;"></span>&nbsp;Injured&nbsp;|&nbsp;'
        '<span style="background:#FFA500;border-radius:50%;display:inline-block;'
        'width:8px;height:8px;vertical-align:middle;"></span>&nbsp;Doubt'
        '</div></div>'
    )

    st.markdown(html, unsafe_allow_html=True)
