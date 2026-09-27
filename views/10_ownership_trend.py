"""
Ownership · the crowd, set against the engine (rebuilt 2026-09-27).

The old page read ownership from the live gameweek feed, which stamps today's
figure on every past week, so every player showed a 0% change and the season
chart collapsed onto one line. It now reads FPL's per-player history
(`service.ownership_history`), which carries the real `selected` count per week.

  movers        biggest ownership rises and falls since GW1, faces on the axis
  crowd vs engine  ownership against the engine's six-week projection: the
                 differentials worth owning and the template picks the numbers
                 do not support
  journeys      week-by-week ownership for any players you pick
  pressure      who is closest to a price move right now
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics import brain, service
from analytics.price_radar import price_watch
from components.animations import count_up, inject_global_animations
from components.loading import LINES_GENERIC, fpl_loader
from components.team_identity import face_html, player_photo_url
from ui import charts, theme
from ui.page import header, section, tiles
from ui.theme import fill, var as V

inject_global_animations()
header("Ownership", "Where the crowd has moved this season, and whether the engine agrees.",
       kicker="Research", icon="trending_up")

bs = st.session_state.get("bootstrap") or {}
total = float(bs.get("total_players") or 11_000_000)
with fpl_loader("Reading every player's ownership history", LINES_GENERIC):
    hist = service.ownership_history()
players = service.inputs()["players"]
if hist is None or hist.empty or hist["GW"].nunique() < 2:
    st.info("Ownership movement needs two finished gameweeks.")
    st.stop()

hist = hist.copy()
hist["own"] = 100.0 * hist["selected"].astype(float) / total
g0, g1 = int(hist["GW"].min()), int(hist["GW"].max())
w = hist.pivot_table(index="code", columns="GW", values="own")
meta = hist.drop_duplicates("code").set_index("code")
chg = (w[g1] - w[g0]).dropna().sort_values()

tiles([
    ("Rising 3 points+", count_up(int((chg >= 3).sum())), "ownership up since GW%d" % g0, "mint"),
    ("Falling 3 points+", count_up(int((chg <= -3).sum())), "ownership down since GW%d" % g0, "red"),
    ("Biggest riser", meta.at[chg.index[-1], "web_name"], "+%.1f points of ownership" % chg.iloc[-1], "mint"),
    ("Biggest faller", meta.at[chg.index[0], "web_name"], "%.1f points of ownership" % chg.iloc[0], "red"),
])

# ── Movers ────────────────────────────────────────────────────────────────────
section("Biggest movers since GW%d" % g0,
        "Change in the share of managers who own him, in percentage points.", "swap_vert")
mv = pd.concat([chg.head(8), chg.tail(8)]).sort_values()
names = [meta.at[c, "web_name"] for c in mv.index]
opt = charts.bar_option(names, [round(v, 1) for v in mv.values], horizontal=True,
                        colors=[fill("mint") if v > 0 else fill("red") for v in mv.values])
opt["grid"]["left"] = 150
opt["series"][0]["label"] = {"show": True, "position": "right", "color": fill("text"),
                             "fontSize": 10, "formatter": "{c}"}
opt["tooltip"]["formatter"] = "{b}: {c} pts of ownership"
opt["animationDuration"], opt["animationEasing"] = 1100, "cubicOut"
charts.with_image_labels(opt, [player_photo_url(c) for c in mv.index], size=24)
charts.render(opt, height="%dpx" % (40 + 30 * len(mv)), key="own_movers")

# ── Crowd vs engine ───────────────────────────────────────────────────────────
long = service.projections(allow_compute=False)
if long is not None:
    section("The crowd against the engine",
            "Ownership across, the engine's six-week xP up. Top left: owned by few, "
            "projected well (differentials). Bottom right: owned by many, projected "
            "modestly. Faces mark the extremes.", "scatter_plot")
    s = brain.summary(long, sorted(long["gw"].unique())[:6])
    s = s[s["xmins"] >= 45]
    s["own"] = s["ownership"].fillna(0).astype(float)
    fit = s[["own", "xp_total"]]
    slope = float(pd.Series(fit["xp_total"]).corr(fit["own"]) * fit["xp_total"].std() / max(fit["own"].std(), 1e-9))
    base = float(fit["xp_total"].mean() - slope * fit["own"].mean())
    s["resid"] = s["xp_total"] - (base + slope * s["own"])
    faces = set(s.nlargest(6, "resid")["code"]) | set(s.nsmallest(5, "resid")["code"])
    pos_col = {"GKP": fill("mint"), "DEF": fill("cyan"), "MID": fill("mag"), "FWD": fill("orange")}
    groups = []
    for pos, col in pos_col.items():
        pts = []
        for _, r in s[s["position"] == pos].iterrows():
            d = {"value": [round(r["own"], 1), round(r["xp_total"], 1)], "name": r["web_name"],
                 "itemStyle": {"color": col, "opacity": 0.55}}
            if r["code"] in faces:
                d["symbol"] = "image://" + player_photo_url(int(r["code"]))
                d["symbolSize"] = 34
                d["label"] = {"show": True, "formatter": r["web_name"], "position": "top",
                              "color": fill("text"), "fontSize": 10}
            else:
                d["symbolSize"] = 8
            pts.append(d)
        groups.append({"name": pos, "type": "scatter", "data": pts,
                       "itemStyle": {"color": col}})
    xs = [0, float(s["own"].max())]
    groups.append({"name": "typical", "type": "line", "symbol": "none", "silent": True,
                   "data": [[x, base + slope * x] for x in xs],
                   "lineStyle": {"type": "dashed", "color": fill("muted2"), "width": 1}})
    sc = {"backgroundColor": "transparent", "animationDuration": 1200,
          "grid": {"left": 50, "right": 24, "top": 30, "bottom": 40},
          "legend": {"top": 0, "right": 8, "textStyle": {"color": fill("muted2")},
                     "data": list(pos_col)},
          "tooltip": {**charts._tooltip(), "trigger": "item",
                      "formatter": "{b}<br/>owned {c0}%"},
          "xAxis": {**charts._axis("value"), "name": "Owned %", "nameLocation": "middle",
                    "nameGap": 26, "nameTextStyle": {"color": fill("muted2")}},
          "yAxis": {**charts._axis("value"), "name": "xP, next six", "scale": True,
                    "nameTextStyle": {"color": fill("muted2")}},
          "series": groups}
    from streamlit_echarts import JsCode
    sc["tooltip"]["formatter"] = JsCode(
        "function(p){if(!p.value)return '';return p.name+'<br/>owned '+p.value[0]+'% · '"
        "+p.value[1]+' xP next six';}").js_code
    charts.render(sc, height="440px", key="own_vs_engine")
    top_d = s.nlargest(3, "resid")
    over = s.nsmallest(3, "resid")
    st.markdown(
        f'<div class="ff-stack" style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">'
        f'<div style="padding:12px 16px;border-radius:12px;background:{V("card")};border-left:3px solid {V("mint")};">'
        f'<b style="color:{V("mint")};">Under-owned for what he projects:</b> '
        + ", ".join("%s (%.1f%%)" % (r["web_name"], r["own"]) for _, r in top_d.iterrows())
        + f'</div><div style="padding:12px 16px;border-radius:12px;background:{V("card")};border-left:3px solid {V("red")};">'
        f'<b style="color:{V("red")};">Owned beyond what he projects:</b> '
        + ", ".join("%s (%.1f%%)" % (r["web_name"], r["own"]) for _, r in over.iterrows())
        + '</div></div>', unsafe_allow_html=True)

# ── Journeys ──────────────────────────────────────────────────────────────────
section("Ownership journeys", "Week by week. Starts with your squad; add anyone.", "show_chart")
try:
    mine = [p["code"] for p in service.team()["squad"]]
except Exception:  # noqa: BLE001
    mine = []
opts = [int(c) for c in w.index]
lab = {c: "%s · %s" % (meta.at[c, "web_name"], meta.at[c, "team_short"]) for c in opts}
default = [c for c in mine if c in opts][:6] or list(chg.index[-5:])
pick = st.multiselect("Players", opts, default=default, format_func=lambda c: lab.get(c, c),
                      key="own_pick", label_visibility="collapsed")
if pick:
    gws = [int(g) for g in w.columns]
    palette = [fill(t) for t in ("mint", "cyan", "gold", "mag", "orange", "red")] * 4
    series = []
    for k, c in enumerate(pick):
        vals = [None if pd.isna(w.at[c, g]) else round(float(w.at[c, g]), 2) for g in gws]
        series.append({"name": meta.at[c, "web_name"], "type": "line", "smooth": 0.35, "data": vals,
                       "symbol": "circle", "symbolSize": 6, "lineStyle": {"width": 3, "color": palette[k]},
                       "itemStyle": {"color": palette[k]},
                       "endLabel": {"show": True, "formatter": "{a}", "color": palette[k], "fontSize": 11},
                       "emphasis": {"focus": "series"}})
    jo = {"backgroundColor": "transparent", "animationDuration": 1400,
          "grid": {"left": 44, "right": 110, "top": 20, "bottom": 30},
          "tooltip": charts._tooltip(),
          "xAxis": {**charts._axis("category", ["GW%d" % g for g in gws]), "boundaryGap": False},
          "yAxis": {**charts._axis("value"), "name": "Owned %",
                    "nameTextStyle": {"color": fill("muted2")}},
          "series": series}
    charts.render(jo, height="360px", key="own_journeys")

# ── Price pressure ────────────────────────────────────────────────────────────
section("Price pressure", "Net transfers this gameweek, scaled by ownership: who is closest "
        "to a price move. A heuristic ordering, not FPL's formula.", "price_change")
_uni = st.session_state.get("players_df")
_r, _f = price_watch(_uni if _uni is not None else players, top_n=8)


def _rows(df, tone, arrow):
    if df.empty:
        return f'<div style="padding:12px;color:{V("muted2")};">Market asleep.</div>'
    out = ""
    for _, r in df.iterrows():
        code = int(players.loc[players["web_name"] == r["web_name"], "code"].iloc[0]) \
            if (players["web_name"] == r["web_name"]).any() else None
        face = face_html(code, int(r.get("team_code") or 1), False, 28) if code else ""
        out += (f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;'
                f'border-bottom:1px solid {V("line")};">'
                f'<span style="width:28px;flex-shrink:0;">{face}</span>'
                f'<span style="flex:1;color:{V("text")};font-weight:700;font-size:13px;">{r["web_name"]}'
                f'<span style="color:{V("muted2")};font-weight:400;font-size:12px;"> · £{float(r["price"]):.1f}m</span></span>'
                f'<span style="width:90px;height:6px;background:{V("row-alt")};border-radius:3px;overflow:hidden;">'
                f'<span class="ff-grow" style="display:block;height:100%;width:{int(r["pressure"])}%;background:{V(tone)};"></span></span>'
                f'<span class="ff-num" style="width:60px;text-align:right;font-size:12px;color:{V("muted")};">'
                f'{arrow} {int(r["transfer_balance"]) // 1000:+d}k</span></div>')
    return out


c1, c2 = st.columns(2)
with c1:
    st.markdown(f'<div style="font-size:11px;letter-spacing:0.16em;font-weight:700;color:{V("mint")};'
                f'margin-bottom:6px;">LIKELY RISERS</div>' + _rows(_r, "mint", "▲"), unsafe_allow_html=True)
with c2:
    st.markdown(f'<div style="font-size:11px;letter-spacing:0.16em;font-weight:700;color:{V("red")};'
                f'margin-bottom:6px;">LIKELY FALLERS</div>' + _rows(_f, "red", "▼"), unsafe_allow_html=True)
