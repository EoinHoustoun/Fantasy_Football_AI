"""The player sheet · one dialog, reachable from the rail on every page.

Face, the engine's xP for each of the next eight gameweeks against his fixtures,
where those points come from, this season's minutes and underlying numbers, and
the same background notes the transfer audit uses. The point is to look anyone
up without leaving the page you are on.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from analytics import brain, service
from analytics import transfer_audit as TA
from components.team_identity import face_html
from ui import charts, theme
from ui.theme import FDR_COLORS, fill, var as V


def _one(html: str) -> str:
    return "".join(seg.strip() for seg in html.splitlines())


def _stat(label: str, value: str, tone: str = "text") -> str:
    return (f'<div style="flex:1;min-width:88px;padding:10px 12px;border-radius:12px;'
            f'background:{V("row-alt")};"><div style="font-size:10.5px;font-weight:700;'
            f'letter-spacing:0.12em;text-transform:uppercase;color:{V("muted2")};">{label}</div>'
            f'<div class="ff-display ff-num" style="font-size:20px;font-weight:900;color:{V(tone)};">'
            f'{value}</div></div>')


@st.dialog("Player", width="large")
def show(code: int) -> None:
    long = service.projections(allow_compute=False)
    players = service.inputs()["players"]
    row = players[players["code"] == int(code)]
    if row.empty:
        st.write("Player not found.")
        return
    p = row.iloc[0]
    prof = TA.profile(int(code), service.season_rows(), players)
    face = face_html(int(code), int(p.get("team_code") or 1), p["position"] == "GKP", 84)
    status = "" if (p.get("status") or "a") == "a" else (
        f'<div style="margin-top:6px;font-size:13px;color:{V("orange")};">'
        f'{theme.icon("warning", 16, V("orange"))} {p.get("news") or "flagged"}</div>')
    st.markdown(_one(f"""
<div style="display:flex;gap:18px;align-items:center;">
  <div style="width:84px;flex-shrink:0;">{face}</div>
  <div style="flex:1;">
    <div class="ff-display" style="font-size:30px;font-weight:900;color:{V('text')};">{p['web_name']}</div>
    <div style="font-size:14px;color:{V('muted')};">{p.get('team')} · {p['position']} · £{float(p['price']):.1f}m ·
      {float(p.get('ownership') or 0):.1f}% owned</div>{status}
  </div>
</div>"""), unsafe_allow_html=True)

    if long is not None:
        mine = long[long["code"] == int(code)].sort_values("gw")
        gws = [int(g) for g in mine["gw"]]
        fx = service.fixtures_for(int(p["team_id"]), gws) if gws else []
        _fxdf = service.inputs()["fixtures"]
        fdrs = [TA.fixture_ease(int(p["team_id"]), _fxdf, [g]) for g in gws]
        if gws:
            opt = {"backgroundColor": "transparent", "animationDuration": 900,
                   "grid": {"left": 36, "right": 12, "top": 22, "bottom": 46},
                   "tooltip": {**charts._tooltip(), "trigger": "item", "formatter": "{b}: {c} xP"},
                   "xAxis": {**charts._axis("category", ["GW%d\n%s" % (g, f) for g, f in zip(gws, fx)]),
                             "axisLabel": {"color": fill("muted2"), "fontSize": 10, "interval": 0}},
                   "yAxis": charts._axis("value"),
                   "series": [{"type": "bar", "barWidth": "58%",
                               "data": [{"value": round(float(v), 2), "itemStyle": {
                                   "borderRadius": [6, 6, 0, 0],
                                   "color": FDR_COLORS.get(int(round(d or 3)), fill("mint"))}}
                                   for v, d in zip(mine["xp"], fdrs)],
                               "label": {"show": True, "position": "top", "color": fill("text"),
                                         "fontSize": 10}}]}
            st.markdown(f'<div style="font-size:11px;font-weight:700;letter-spacing:0.14em;'
                        f'color:{V("muted2")};margin-top:14px;">EXPECTED POINTS, NEXT {len(gws)} GAMEWEEKS · BAR COLOUR = FIXTURE DIFFICULTY · '
                        f'{mine["xp"].sum():.1f} IN TOTAL</div>', unsafe_allow_html=True)
            charts.render(opt, height="230px", key="sheet_xp_%d" % int(code))
            parts = brain.point_parts(mine.head(1))
            if not parts.empty:
                r = parts.iloc[0]
                bits = " · ".join("%s %.2f" % (lab, float(r[c])) for c, lab in brain.POINT_PARTS if float(r[c]) >= 0.05)
                st.caption("GW%d breakdown: %s. Chance of 60+ minutes %d%%." % (
                    gws[0], bits, round(100 * float(r["p60"]))))

    st.markdown(_one(
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">'
        + _stat("Starts", "%d/%d" % (prof["starts"], prof["gws"]))
        + _stat("xGI / 90", "%.2f" % prof["xgi90"], "cyan")
        + _stat("G+A / 90", "%.2f" % prof["ga90"])
        + _stat("Luck", "%+.1f" % prof["luck"], "gold" if abs(prof["luck"]) >= 2 else "text")
        + _stat("Pts / start", "%.1f" % prof["pts_per_start"], "mint")
        + (_stat("DEFCON", "%d%%" % round(100 * prof["defcon_rate"]), "mint")
           if prof.get("defcon_rate") is not None else "")
        + (_stat("Penalties", "#%d" % prof["penalties"]) if prof.get("penalties") else "")
        + '</div>'), unsafe_allow_html=True)
    st.caption("Minutes by gameweek: %s. Luck = goals and assists minus xGI: it does not "
               "persist, xGI per 90 does." % (", ".join(map(str, prof["mins_list"])) or "none"))
    # Cup and European minutes (FPL-Core-Insights, cached locally). Context only:
    # in 2025-26 midweek minutes did NOT predict weekend rotation (research note
    # docs/research/midweek_minutes.md), so nothing here changes a projection.
    try:
        from analytics.component_model import active_season
        from data.fetchers.core_insights import midweek_minutes
        mw = midweek_minutes(active_season())
        mine_mw = mw[mw["code"] == int(code)].sort_values("kickoff", ascending=False).head(4) \
            if not mw.empty else mw
        if not mine_mw.empty:
            st.caption("Outside the league: " + " · ".join(
                "%d' %s (%s)" % (r["minutes"], r["competition"], r["kickoff"].strftime("%d %b"))
                for _, r in mine_mw.iterrows()))
    except Exception:  # noqa: BLE001 · context, never a blocker
        pass
    b1, b2 = st.columns(2)
    with b1:
        st.page_link("views/02_transfer_suggestions.py", label="Check a move with him →")
    with b2:
        st.page_link("views/06_captain_picker.py", label="Captain options →")


def rail_search() -> None:
    """A player search in the rail. Picking a name opens the sheet once."""
    players = st.session_state.get("players_df")
    if players is None or "code" not in players.columns:
        return
    df = players.sort_values("ownership", ascending=False)
    codes = [None] + [int(c) for c in df["code"]]
    labels = dict(zip(df["code"].astype(int),
                      df["web_name"] + " · " + df["team_short"].astype(str)))
    pick = st.selectbox("Find a player", codes, index=0, key="rail_player",
                        format_func=lambda c: "Search any player…" if c is None else labels.get(c, c),
                        label_visibility="collapsed")
    last = st.session_state.get("_rail_player_last")
    if pick is not None and pick != last:
        st.session_state["_rail_player_last"] = pick
        show(int(pick))
    elif pick is None:
        st.session_state["_rail_player_last"] = None
