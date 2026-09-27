"""The in-season player card · everything on the one engine (2026-09-27).

My Team used the preseason Draft card, which mixed three sources in one dialog:
a preseason board ("season 134, 3rd of 141"), a Hub snapshot that still said
Saka plays "35 minutes a game" (he has started all five), and the engine
(69 expected minutes, 4.3 xP) in the tile beneath. This card reads only the
live engine and this season's matches, so nothing in it can disagree.

  header    face, club colour, set pieces, status, price and ownership sparklines
  verdict   owned: keep, or his exit week and the best affordable swap
            not owned: against your weakest player in his position, via the
            same move audit the Transfers page uses
  next 8    xP by gameweek, bars coloured by fixture difficulty, minutes line
  delivering  this season's points per gameweek against his xGI
  numbers   minutes pattern, xGI/90, luck, points per start, penalties, DEFCON
  breakdown where next week's expected points come from
"""

from __future__ import annotations

from typing import Callable, Optional, Set

import pandas as pd
import streamlit as st

from analytics import brain, service
from analytics import transfer_audit as TA
from components.team_identity import face_html, team_color
from ui import charts, theme
from ui.theme import FDR_COLORS, fill, var as V


def _one(html: str) -> str:
    return "".join(seg.strip() for seg in html.splitlines())


def _chip(txt: str, tone: str) -> str:
    return (f'<span style="padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:700;'
            f'background:{V(tone + "-v")};color:#0B0F17;">{txt}</span>')


def _stat(label: str, value: str, sub: str = "", tone: str = "text") -> str:
    return (f'<div style="flex:1;min-width:96px;padding:10px 12px;border-radius:12px;background:{V("row-alt")};">'
            f'<div style="font-size:10.5px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;'
            f'color:{V("muted2")};">{label}</div>'
            f'<div class="ff-display ff-num" style="font-size:20px;font-weight:900;color:{V(tone)};">{value}</div>'
            + (f'<div style="font-size:11px;color:{V("muted")};">{sub}</div>' if sub else "") + '</div>')


def _spark(values, tone: str, key: str) -> None:
    vals = [None if v is None or pd.isna(v) else round(float(v), 2) for v in values]
    opt = {"backgroundColor": "transparent", "animationDuration": 900,
           "grid": {"left": 2, "right": 2, "top": 6, "bottom": 2},
           "xAxis": {"type": "category", "show": False, "data": list(range(len(vals)))},
           "yAxis": {"type": "value", "show": False, "scale": True},
           "tooltip": {"show": False},
           "series": [{"type": "line", "data": vals, "smooth": 0.4, "symbol": "none",
                       "lineStyle": {"width": 2.5, "color": fill(tone)},
                       "areaStyle": {"color": charts._rgba(fill(tone), 0.18)}}]}
    charts.render(opt, height="54px", key=key)


def render(code: int, gw: int, owned: Set[int],
           on_replace: Optional[Callable] = None, on_compare: Optional[Callable] = None,
           on_captain: Optional[Callable] = None) -> None:
    code = int(code)
    players = service.inputs()["players"]
    row = players[players["code"] == code]
    if row.empty:
        st.write("Player not found.")
        return
    p = row.iloc[0]
    long = service.projections(allow_compute=False)
    prof = TA.profile(code, service.season_rows(), players)
    is_mine = code in owned
    col = team_color(p.get("team_short"))

    # ── Header ────────────────────────────────────────────────────────────────
    chips = [_chip(p["position"], {"GKP": "mint", "DEF": "cyan", "MID": "mag", "FWD": "orange"}
                   .get(p["position"], "mint"))]
    if prof.get("penalties") == 1:
        chips.append(_chip("Penalties", "gold"))
    for k, lab in (("corners_order", "Corners"), ("freekicks_order", "Free kicks")):
        if pd.notna(p.get(k)) and int(p.get(k)) == 1:
            chips.append(_chip(lab, "cyan"))
    if (p.get("status") or "a") != "a":
        chips.append(_chip(p.get("news") or "Flagged", "orange"))
    st.markdown(_one(f"""
<div class="ff-rise" style="display:flex;gap:18px;align-items:center;padding:16px 18px;border-radius:16px;
  background:linear-gradient(120deg, {charts._rgba(col, 0.28) if col.startswith('#') else V('card')} 0%, {V('card')} 60%);
  border:1px solid {V('line')};">
  <div style="width:96px;flex-shrink:0;">{face_html(code, int(p.get('team_code') or 1), p['position'] == 'GKP', 96)}</div>
  <div style="flex:1;min-width:0;">
    <div class="ff-display" style="font-size:32px;font-weight:900;color:{V('text')};line-height:1.05;">{p['web_name']}</div>
    <div style="font-size:14px;color:{V('muted')};margin:2px 0 8px;">{p.get('team')} · £{float(p['price']):.1f}m ·
      {float(p.get('ownership') or 0):.1f}% owned{' · in your squad' if is_mine else ''}</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;">{''.join(chips)}</div>
  </div>
</div>"""), unsafe_allow_html=True)

    hist = None
    try:
        hist = service.ownership_history(min_own=0.0, top_traded=0)
        hist = hist[hist["code"] == code].sort_values("GW")
    except Exception:  # noqa: BLE001
        hist = None
    if hist is not None and not hist.empty:
        total = float((st.session_state.get("bootstrap") or {}).get("total_players") or 11_000_000)
        s1, s2 = st.columns(2)
        with s1:
            st.caption("Price by gameweek · £%.1fm → £%.1fm" % (hist["value"].iloc[0] / 10, hist["value"].iloc[-1] / 10))
            _spark(hist["value"] / 10, "gold", "ec_price_%d" % code)
        with s2:
            st.caption("Ownership by gameweek · %.1f%% → %.1f%%" % (100 * hist["selected"].iloc[0] / total,
                                                                 100 * hist["selected"].iloc[-1] / total))
            _spark(100 * hist["selected"] / total, "cyan", "ec_own_%d" % code)

    # ── Verdict ───────────────────────────────────────────────────────────────
    verdict_html = ""
    try:
        if is_mine:
            em = service.squad_exit_map(None, horizon=8)
            me = next((r for r in em["rows"] if r["code"] == code), None)
            bm = service.best_moves(None, horizon=6, top_n=15)
            swap = next((m for m in bm["moves"] if m["out_code"] == code), None)
            if me and not me["exit_gw"]:
                verdict_html = (f'<b style="color:{V("mint")};">Keep.</b> Nobody you can afford in his position '
                                f'outscores him by a point in the next {len(em["gws"])} gameweeks.')
                tone = "mint"
            elif me:
                tone = "gold" if (swap and swap["gain"] >= 2) else "cyan"
                verdict_html = (f'<b style="color:{V(tone)};">Exit around GW{me["exit_gw"]}.</b> An affordable '
                                f'{p["position"]} outscores him in {me["weeks_beaten"]} of {len(em["gws"])} weeks.')
                if swap:
                    verdict_html += (f' Best swap now: <b>{swap["in"]}</b>, {swap["gain"]:+.1f} team points over '
                                     f'six weeks. Check it on Transfers before you move.')
        else:
            t = service.team(None)
            mine_pos = [m for m in t["squad"] if m["position"] == p["position"]]
            summ = brain.summary(long, sorted(long["gw"].unique())[:6]).set_index("code") if long is not None else None
            if mine_pos and summ is not None:
                weakest = min(mine_pos, key=lambda m: float(summ.at[m["code"], "xp_total"])
                              if m["code"] in summ.index else 0.0)
                d = service.move_dossier(int(weakest["code"]), code)
                tone = d["tone"]
                verdict_html = (f'<b style="color:{V(tone)};">{d["verdict"]}</b> as a replacement for your weakest '
                                f'{p["position"]}, {weakest["name"]}: {d["why"].lower()}. Team points over six weeks: '
                                f'<b>{(d["team_gain_6"] or 0):+.1f}</b>.')
    except Exception:  # noqa: BLE001 · the card must open even if a verdict cannot be formed
        verdict_html = ""
        tone = "cyan"
    if verdict_html:
        st.markdown(_one(f'<div class="ff-rise-2" style="margin-top:10px;padding:12px 16px;border-radius:12px;'
                         f'background:{V("card")};border-left:3px solid {V(tone)};font-size:14px;'
                         f'line-height:1.55;color:{V("text")};">{verdict_html}</div>'), unsafe_allow_html=True)

    # ── Next 8 gameweeks ──────────────────────────────────────────────────────
    if long is not None:
        mine = long[long["code"] == code].sort_values("gw")
        gws = [int(g) for g in mine["gw"]]
        if gws:
            fx = service.fixtures_for(int(p["team_id"]), gws)
            fxdf = service.inputs()["fixtures"]
            fdrs = [TA.fixture_ease(int(p["team_id"]), fxdf, [g]) for g in gws]
            opt = {"backgroundColor": "transparent", "animationDuration": 900,
                   "grid": {"left": 34, "right": 40, "top": 26, "bottom": 46},
                   "tooltip": {**charts._tooltip(), "trigger": "axis"},
                   "legend": {"top": 0, "right": 0, "textStyle": {"color": fill("muted2"), "fontSize": 10}},
                   "xAxis": {**charts._axis("category", ["GW%d\n%s" % (g, f) for g, f in zip(gws, fx)]),
                             "axisLabel": {"color": fill("muted2"), "fontSize": 10, "interval": 0}},
                   "yAxis": [charts._axis("value"),
                             {**charts._axis("value"), "max": 90, "splitLine": {"show": False},
                              "axisLabel": {"color": fill("muted2"), "fontSize": 9, "formatter": "{value}'"}}],
                   "series": [{"name": "xP", "type": "bar", "barWidth": "56%",
                               "itemStyle": {"color": fill("gold")},
                               "data": [{"value": round(float(v), 2), "itemStyle": {
                                   "borderRadius": [6, 6, 0, 0],
                                   "color": FDR_COLORS.get(int(round(d or 3)), fill("mint"))}}
                                   for v, d in zip(mine["xp"], fdrs)],
                               "label": {"show": True, "position": "top", "color": fill("text"), "fontSize": 10}},
                              {"name": "Expected minutes", "type": "line", "yAxisIndex": 1,
                               "data": [round(float(v), 0) for v in mine["exp_minutes"]],
                               "symbol": "circle", "symbolSize": 5, "smooth": 0.3,
                               "lineStyle": {"color": fill("cyan"), "type": "dashed", "width": 2},
                               "itemStyle": {"color": fill("cyan")}}]}
            st.markdown(f'<div style="font-size:11px;font-weight:700;letter-spacing:0.14em;color:{V("muted2")};'
                        f'margin-top:14px;">NEXT {len(gws)} GAMEWEEKS · {mine["xp"].sum():.1f} xP · BARS COLOURED BY '
                        f'FIXTURE DIFFICULTY</div>', unsafe_allow_html=True)
            charts.render(opt, height="240px", key="ec_next_%d" % code)

    # ── Is he delivering? ─────────────────────────────────────────────────────
    rows = service.season_rows()
    r = rows[rows["code"] == code].groupby("gw").agg(pts=("total_points", "sum"), mins=("minutes", "sum"),
                                                    xg=("xg", "sum"), xa=("xa", "sum")).reset_index()
    if not r.empty:
        opt2 = {"backgroundColor": "transparent", "animationDuration": 900,
                "grid": {"left": 34, "right": 40, "top": 26, "bottom": 26},
                "tooltip": {**charts._tooltip(), "trigger": "axis"},
                "legend": {"top": 0, "right": 0, "textStyle": {"color": fill("muted2"), "fontSize": 10}},
                "xAxis": charts._axis("category", ["GW%d" % g for g in r["gw"]]),
                "yAxis": [charts._axis("value"), {**charts._axis("value"), "splitLine": {"show": False}}],
                "series": [{"name": "Points", "type": "bar", "barWidth": "50%",
                            "itemStyle": {"color": fill("mint")},
                            "data": [{"value": int(v), "itemStyle": {"borderRadius": [6, 6, 0, 0],
                                     "color": fill("mint") if v >= 6 else (fill("cyan") if v >= 3 else fill("muted2"))}}
                                     for v in r["pts"]],
                            "label": {"show": True, "position": "top", "color": fill("text"), "fontSize": 10}},
                           {"name": "xGI (goals + assists expected)", "type": "line", "yAxisIndex": 1,
                            "data": [round(float(a + b), 2) for a, b in zip(r["xg"], r["xa"])],
                            "smooth": 0.3, "symbol": "circle", "symbolSize": 6,
                            "lineStyle": {"color": fill("gold"), "width": 2.5},
                            "itemStyle": {"color": fill("gold")}}]}
        st.markdown(f'<div style="font-size:11px;font-weight:700;letter-spacing:0.14em;color:{V("muted2")};'
                    f'margin-top:10px;">IS HE DELIVERING? · POINTS PER GAMEWEEK AGAINST HIS UNDERLYING xGI</div>',
                    unsafe_allow_html=True)
        charts.render(opt2, height="200px", key="ec_season_%d" % code)

    # ── Numbers ───────────────────────────────────────────────────────────────
    luck_tone = "gold" if prof["luck"] >= 2 else ("cyan" if prof["luck"] <= -2 else "text")
    luck_sub = ("running hot" if prof["luck"] >= 2 else ("running cold" if prof["luck"] <= -2 else "about even"))
    parts = [_stat("Starts", "%d/%d" % (prof["starts"], prof["gws"]), "%.0f min a start" % prof["mins_per_start"]),
             _stat("xGI / 90", "%.2f" % prof["xgi90"], "the part that persists", "cyan"),
             _stat("G+A / 90", "%.2f" % prof["ga90"]),
             _stat("Luck", "%+.1f" % prof["luck"], luck_sub, luck_tone),
             _stat("Pts / start", "%.1f" % prof["pts_per_start"], "", "mint")]
    if p["position"] in ("DEF", "MID") and prof.get("defcon_rate") is not None:
        parts.append(_stat("DEFCON", "%d%%" % round(100 * prof["defcon_rate"]), "of 60-min games", "mint"))
    st.markdown(_one('<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">' + "".join(parts) + '</div>'),
                unsafe_allow_html=True)

    # ── Next-week breakdown ───────────────────────────────────────────────────
    if long is not None:
        nxt = long[(long["code"] == code) & (long["gw"] == int(gw))]
        if nxt.empty:
            nxt = long[long["code"] == code].sort_values("gw").head(1)
        if not nxt.empty:
            b = brain.point_parts(nxt).iloc[0]
            tot = max(float(b["xp"]), 1e-6)
            seg_cols = {"pts_appear": "muted2", "pts_goals": "mint", "pts_assists": "cyan",
                        "pts_cs": "gold", "pts_bonus": "mag", "pts_dc": "orange"}
            segs = "".join(
                f'<div title="{lab} {float(b[c]):.2f}" style="width:{100 * float(b[c]) / tot:.1f}%;background:{V(seg_cols[c])};"></div>'
                for c, lab in brain.POINT_PARTS if float(b[c]) > 0.01)
            legend = " · ".join("%s %.2f" % (lab, float(b[c])) for c, lab in brain.POINT_PARTS if float(b[c]) >= 0.05)
            st.markdown(_one(
                f'<div style="margin-top:12px;font-size:11px;font-weight:700;letter-spacing:0.14em;color:{V("muted2")};">'
                f'GW{int(b["gw"])} · {float(b["xp"]):.2f} xP · WHERE IT COMES FROM</div>'
                f'<div class="ff-grow" style="display:flex;height:14px;border-radius:7px;overflow:hidden;margin:6px 0;">{segs}</div>'
                f'<div style="font-size:12px;color:{V("muted")};">{legend} · {round(100 * float(b["p60"]))}% chance of 60+ minutes</div>'),
                unsafe_allow_html=True)

    # ── Actions ───────────────────────────────────────────────────────────────
    a1, a2, a3 = st.columns(3)
    with a1:
        if on_replace and is_mine and st.button("Replace him", icon=":material/swap_horiz:",
                                                use_container_width=True, key="ec_rep_%d" % code):
            on_replace(code)
    with a2:
        if on_compare and st.button("Compare", icon=":material/balance:", use_container_width=True,
                                    key="ec_cmp_%d" % code):
            on_compare(code)
    with a3:
        if on_captain and is_mine and st.button("Captain GW%d" % int(gw), icon=":material/military_tech:",
                                                use_container_width=True, key="ec_cap_%d" % code):
            on_captain(code)


@st.dialog("Player", width="large")
def open_card(code: int, gw: int, owned: Set[int], on_replace=None, on_compare=None,
              on_captain=None) -> None:
    render(code, gw, owned, on_replace, on_compare, on_captain)
