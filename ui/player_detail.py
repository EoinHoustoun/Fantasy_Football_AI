"""Player deep-dive panel · "why this player is (or isn't) delivering".

A reusable panel: HD kit + identity + role tags (penalty / DEFCON / set-piece),
a strengths-vs-weaknesses radar (percentile within position), and per-gameweek
form + xG-vs-goals charts, all in the shared ECharts look.

Used by the My Team pitch (ℹ️ deep-dive) and reusable across the app.
Python 3.8: typing only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from ui import charts
from ui.theme import COLORS
from components.team_identity import shirt_html, team_color
from components.badges import render_badges


@st.cache_data(ttl=3600, show_spinner=False)
def _gw_history(fpl_id: int) -> List[Dict[str, Any]]:
    """Per-gameweek history for a player from the FPL element-summary endpoint."""
    import requests
    try:
        r = requests.get(
            f"https://fantasy.premierleague.com/api/element-summary/{int(fpl_id)}/",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        r.raise_for_status()
        hist = r.json().get("history", []) or []
    except Exception:  # noqa: BLE001 · history is optional; degrade to radar-only
        return []
    return [{
        "gw": h.get("round"),
        "points": int(h.get("total_points", 0) or 0),
        "goals": int(h.get("goals_scored", 0) or 0),
        "xg": round(float(h.get("expected_goals", 0) or 0), 2),
    } for h in hist if h.get("round") is not None]


# Radar metrics: (label, column, higher_is_better). Only those present are shown.
_RADAR_METRICS: List[Tuple[str, str, bool]] = [
    ("Points",  "total_points",       True),
    ("Form",    "form",               True),
    ("xP",      "ep_next",            True),
    ("xG",      "xg",                 True),
    ("xGI/90",  "fpl_xgi_per90",      True),
    ("Minutes", "minutes",            True),
    ("Value",   "points_per_million", True),
]


def _percentile(peers: pd.Series, value: float) -> float:
    """Percentile (0-100) of `value` within the peer series."""
    s = pd.to_numeric(peers, errors="coerce").dropna()
    if s.empty:
        return 50.0
    return float((s < value).mean() * 100.0)


def radar_percentiles(universe: pd.DataFrame, row: pd.Series
                      ) -> Tuple[List[Dict[str, Any]], List[float]]:
    """(indicators, values) · the player's percentile within their position on
    each radar metric. Shared by the deep-dive panel and head-to-head dialogs."""
    peers = universe[universe["position"] == str(row.get("position", ""))]
    indicators, values = [], []
    for label, col, _ in _RADAR_METRICS:
        if col in universe.columns:
            indicators.append({"name": label, "max": 100})
            values.append(round(_percentile(peers[col], float(row.get(col, 0) or 0)), 1))
    return indicators, values


def price_band_baseline(universe: pd.DataFrame, row: pd.Series,
                        band: float = 1.0) -> Tuple[List[float], str]:
    """The comparison polygon: average percentile of positional peers priced
    within ±band £m of this player (so 'is he good FOR HIS PRICE?').

    Widens the band if fewer than 8 peers qualify. Returns (values, label).
    """
    pos = str(row.get("position", ""))
    price = float(row.get("price", 0) or 0)
    peers = universe[universe["position"] == pos]
    for b in (band, band * 2, 99.0):
        band_df = peers[(peers["price"] >= price - b) & (peers["price"] <= price + b)
                        & (peers["fpl_id"] != row.get("fpl_id"))]
        if len(band_df) >= 8:
            break
    values = []
    for label, col, _ in _RADAR_METRICS:
        if col in universe.columns:
            s = pd.to_numeric(peers[col], errors="coerce").dropna()
            bvals = pd.to_numeric(band_df[col], errors="coerce").dropna()
            if s.empty or bvals.empty:
                values.append(50.0)
            else:
                values.append(round(float(
                    bvals.apply(lambda v: (s < v).mean() * 100.0).mean()), 1))
    lo, hi = max(3.5, price - b), price + b
    return values, f"{pos} £{lo:.1f}–{hi:.1f}m avg"


def _stat_tile(label: str, value: str, color: str) -> str:
    return (
        f'<div style="text-align:center;min-width:56px;">'
        f'<div style="font-family:\'Archivo\',sans-serif;font-size:18px;font-weight:900;color:{color};">{value}</div>'
        f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
        f'color:rgba(255,255,255,0.45);font-weight:700;">{label}</div></div>'
    )


def render_player_detail(fpl_id: int, universe: pd.DataFrame,
                         key_prefix: str = "pd") -> None:
    """Render the deep-dive for one player, using the full player universe."""
    match = universe[universe["fpl_id"] == int(fpl_id)]
    if match.empty:
        st.info("Player not found in the current data.")
        return
    row = match.iloc[0]
    pos = str(row.get("position", ""))
    peers = universe[universe["position"] == pos]

    # ── Header: face (kit fallback) + identity + role tags + key stats ───────
    is_gkp = pos == "GKP"
    kit = shirt_html(int(row.get("team_code", 1) or 1), is_gkp=is_gkp, width=54)
    tcol = team_color(row.get("team_short"))
    tags = render_badges(row, size="sm")

    # Official player headshot · falls back to the club kit if the photo CDN
    # misses (new signings, youth players).
    _code = row.get("code")
    if pd.notna(_code):
        face = (
            f'<div style="position:relative;width:64px;flex-shrink:0;">'
            f'<img src="https://resources.premierleague.com/premierleague25/'
            f'photos/players/110x140/{int(_code)}.png" width="64" loading="lazy" '
            f'style="display:block;border-radius:10px;'
            f'filter:drop-shadow(0 4px 8px rgba(0,0,0,0.45));" '
            f"onerror=\"this.parentElement.innerHTML='{kit.replace(chr(34), chr(39))}';\"/>"
            f'<span style="position:absolute;bottom:-6px;right:-8px;transform:scale(0.55);'
            f'transform-origin:bottom right;">{kit}</span></div>'
        )
    else:
        face = kit

    hcol_id, hcol_stats = st.columns([1.2, 2])
    with hcol_id:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:12px;">{face}'
            f'<div><div style="font-family:\'Archivo\',sans-serif;font-size:22px;font-weight:900;'
            f'color:#fff;line-height:1;">{row.get("web_name","?")}</div>'
            f'<div style="font-size:12px;color:rgba(255,255,255,0.55);margin-top:3px;">'
            f'{row.get("team","?")} · {pos} · £{float(row.get("price",0) or 0):.1f}m</div>'
            f'<div style="margin-top:6px;">{tags}</div></div></div>',
            unsafe_allow_html=True,
        )
    with hcol_stats:
        tiles = "".join([
            _stat_tile("Points", f"{int(row.get('total_points',0) or 0)}", COLORS["mint"]),
            _stat_tile("Form", f"{float(row.get('form',0) or 0):.1f}", COLORS["cyan"]),
            _stat_tile("xP", f"{float(row.get('ep_next',0) or 0):.1f}", COLORS["cyan"]),
            _stat_tile("Own%", f"{float(row.get('ownership',0) or 0):.1f}", COLORS["gold"]),
            _stat_tile("£/m", f"{float(row.get('points_per_million',0) or 0):.1f}", COLORS["magenta"]),
        ])
        st.markdown(
            f'<div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;'
            f'padding-top:6px;">{tiles}</div>', unsafe_allow_html=True)

    # ── Charts row: radar (strengths) + form + xG ─────────────────────────────
    c_radar, c_form, c_xg = st.columns([1.15, 1, 1])

    with c_radar:
        st.markdown("<div style='font-size:10px;letter-spacing:0.14em;text-transform:uppercase;"
                    "font-weight:800;color:rgba(255,255,255,0.5);'>Strengths vs price peers</div>",
                    unsafe_allow_html=True)
        indicators, values = radar_percentiles(universe, row)
        if len(indicators) >= 3:
            base_vals, base_label = price_band_baseline(universe, row)
            charts.render(charts.radar_compare_option(indicators, [
                (base_label, base_vals, "#8891A5", 0.12),
                (str(row.get("web_name", "")), values, COLORS["mint"], 0.28),
            ]), height="250px", key=f"{key_prefix}_radar_{fpl_id}")
        else:
            st.caption("Not enough metrics to chart.")

    hist = _gw_history(int(fpl_id))
    recent = hist[-10:] if hist else []
    gws = [f"GW{h['gw']}" for h in recent]

    with c_form:
        st.markdown("<div style='font-size:10px;letter-spacing:0.14em;text-transform:uppercase;"
                    "font-weight:800;color:rgba(255,255,255,0.5);'>Form · points / GW</div>",
                    unsafe_allow_html=True)
        if recent:
            charts.render(charts.line_option(gws, [h["points"] for h in recent], "Points",
                                             color=COLORS["cyan"]),
                          height="240px", key=f"{key_prefix}_form_{fpl_id}")
        else:
            st.caption("No gameweek history available.")

    with c_xg:
        st.markdown("<div style='font-size:10px;letter-spacing:0.14em;text-transform:uppercase;"
                    "font-weight:800;color:rgba(255,255,255,0.5);'>xG vs Goals</div>",
                    unsafe_allow_html=True)
        if recent:
            charts.render(charts.grouped_bars_option(gws, [
                ("xG", [h["xg"] for h in recent], "rgba(4,245,255,0.55)"),
                ("Goals", [h["goals"] for h in recent], COLORS["mint"]),
            ]), height="240px", key=f"{key_prefix}_xg_{fpl_id}")
        else:
            st.caption("No gameweek history available.")


def intel_lookup(universe: pd.DataFrame, key: str = "intel") -> None:
    """Drop-in "🔍 Player intel" expander for any page · search any player and
    get the same face/radar/form/xG panel the My Team pitch shows. Keeps the
    stats experience consistent across the app."""
    with st.expander("🔍 Player intel · face, form, price-peer radar, xG"):
        opts = universe.sort_values("total_points", ascending=False)
        ids = opts["fpl_id"].astype(int).tolist()
        names = dict(zip(opts["fpl_id"].astype(int),
                         opts["web_name"] + " · " + opts["team"].astype(str)))
        pid = st.selectbox("Player", ids, format_func=lambda i: names.get(i, str(i)),
                           key=f"{key}_pick", label_visibility="collapsed")
        if pid:
            render_player_detail(int(pid), universe, key_prefix=key)
