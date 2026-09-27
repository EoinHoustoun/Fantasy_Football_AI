"""
Fixtures · an engine ticker, not a difficulty number (2026-09-27).

FPL's fixture difficulty is one fixed 1-5 score per club. This ticker reads the
engine instead: every club's EXPECTED GOALS (attack) and CLEAN-SHEET chance
(defence) in each of the next eight gameweeks, which already account for the
opponent, venue, current form and doubles. Clubs sort by the window you choose,
so the runs worth buying into sit at the top.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics import service
from components.animations import inject_global_animations
from components.team_identity import shirt_url
from ui import charts
from ui.page import header, section
from ui.theme import fill, var as V

inject_global_animations()
header("Fixtures", "Which clubs to own and when: expected goals and clean-sheet chances from the "
       "engine, gameweek by gameweek.", kicker="Plan", icon="calendar_month")

long = service.projections(allow_compute=False)
if long is None:
    st.info("Projections are rebuilding after the last gameweek. Reload in a few minutes.")
    st.stop()

gws_all = sorted(int(g) for g in long["gw"].unique())
c1, c2 = st.columns([2, 1.2])
with c1:
    mode = st.segmented_control("View", ["Attack · expected goals", "Defence · clean sheet %"],
                                default="Attack · expected goals", key="fx_mode",
                                label_visibility="collapsed") or "Attack · expected goals"
with c2:
    n = st.select_slider("Window", options=[3, 4, 5, 6, 8], value=6, key="fx_n",
                         format_func=lambda v: "next %d" % v)
gws = gws_all[:n]
attack = mode.startswith("Attack")

t = (long[long["gw"].isin(gws_all)]
     .groupby(["team_short", "team_code", "team_id", "gw"])
     .agg(xg=("e_goals", "sum"), cs=("p_clean_sheet", "max")).reset_index())
val = "xg" if attack else "cs"
w = t.pivot_table(index=["team_short", "team_code", "team_id"], columns="gw", values=val).fillna(0)
w = w[gws]
w["_sum"] = w.sum(axis=1)
w = w.sort_values("_sum", ascending=True)          # heatmap draws bottom-up
teams = list(w.index)

data = []
for yi, (short, code, tid) in enumerate(teams):
    labels = service.fixtures_for(int(tid), gws)
    for xi, g in enumerate(gws):
        v = float(w.at[(short, code, tid), g])
        shown = ("%.1f" % v) if attack else ("%d%%" % round(100 * v))
        data.append({"value": [xi, yi, round(v, 3)],
                     "label": {"formatter": "%s\n%s" % (labels[xi], shown)}})
vals = [d["value"][2] for d in data]
opt = {"backgroundColor": "transparent", "animationDuration": 900,
       "grid": {"left": 8, "right": 90, "top": 10, "bottom": 30, "containLabel": True},
       "tooltip": {**charts._tooltip(), "trigger": "item", "position": "top"},
       "xAxis": {**charts._axis("category", ["GW%d" % g for g in gws]), "position": "top",
                 "axisLabel": {"color": fill("muted2"), "fontSize": 11}},
       "yAxis": {**charts._axis("category", [x[0] for x in teams]),
                 "axisLabel": {"color": fill("text"), "fontSize": 11}},
       "visualMap": {"show": False, "min": min(vals), "max": max(vals), "seriesIndex": 0,
                     "inRange": {"color": charts.heat_ramp(diverging=True)}},
       "series": [{"type": "heatmap", "data": data,
                   "label": {"show": True, "color": fill("text"), "fontSize": 10, "lineHeight": 13},
                   "itemStyle": {"borderRadius": 6, "borderColor": fill("bg"), "borderWidth": 3},
                   "emphasis": {"itemStyle": {"shadowBlur": 12,
                                              "shadowColor": charts._rgba(fill("mint"), 0.6)}}},
                  {"type": "bar", "xAxisIndex": 1, "yAxisIndex": 0, "barWidth": "56%",
                   "data": [round(float(w.at[x, "_sum"]), 2) for x in teams],
                   "itemStyle": {"color": charts._rgba(fill("mint"), 0.55), "borderRadius": [0, 4, 4, 0]},
                   "label": {"show": True, "position": "right", "color": fill("text"), "fontSize": 10,
                             "formatter": "{c}"}}]}
opt["xAxis"] = [opt["xAxis"], {"type": "value", "show": False, "gridIndex": 0}]
# Two grids: the heatmap and a total bar beside it.
opt["grid"] = [{"left": 8, "right": "16%", "top": 30, "bottom": 10, "containLabel": True},
               {"left": "85%", "right": 40, "top": 30, "bottom": 10}]
opt["xAxis"][1]["gridIndex"] = 1
opt["yAxis"] = [opt["yAxis"], {**opt["yAxis"], "gridIndex": 1, "axisLabel": {"show": False},
                               "axisLine": {"show": False}}]
opt["series"][1]["yAxisIndex"] = 1
opt["series"][1]["xAxisIndex"] = 1
# Kits on the club axis. The helper edits the axis dict it is handed, so pass
# the heatmap's own y-axis (the option carries two).
charts.with_image_labels({"yAxis": opt["yAxis"][0]}, [shirt_url(int(x[1])) for x in teams], size=22)
charts.render(opt, height="%dpx" % (60 + 34 * len(teams)), key="fx_ticker_%s_%d" % (val, n))

section("Best runs", "The clubs whose next %d gameweeks look best on this measure." % n, "trending_up")
best = list(reversed(teams))[:4]
cols = st.columns(4)
for c, (short, code, tid) in zip(cols, best):
    labs = service.fixtures_for(int(tid), gws)
    tot = float(w.at[(short, code, tid), "_sum"])
    with c:
        st.markdown(
            f'<div class="ff-rise" style="padding:14px 16px;border-radius:14px;background:{V("card")};'
            f'border:1px solid {V("line")};border-top:3px solid {V("mint")};">'
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'<img src="{shirt_url(int(code))}" width="36"/>'
            f'<div class="ff-display" style="font-size:22px;font-weight:900;color:{V("text")};">{short}</div>'
            f'<div style="flex:1;"></div><div class="ff-display ff-num" style="font-size:22px;font-weight:900;'
            f'color:{V("mint")};">{tot:.1f}</div></div>'
            f'<div style="font-size:12px;color:{V("muted")};margin-top:6px;line-height:1.6;">'
            f'{" · ".join(labs)}</div>'
            f'<div style="font-size:11.5px;color:{V("muted2")};margin-top:4px;">'
            f'{"expected goals" if attack else "expected clean sheets"} over the window</div></div>',
            unsafe_allow_html=True)
st.caption("Expected goals sum the engine's per-player goal expectations for each club; clean-sheet "
           "chance is the engine's Poisson estimate from both sides' current ratings. Doubles add up.")
