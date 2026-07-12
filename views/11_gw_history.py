"""
GW History · your gameweek points history vs the global average.

Shows:
  • Line chart: your GW score vs global average each week
  • Colour-filled area: green above average, red below
  • Rank progression chart over the season
  • Key stats: best/worst GW, total hits, bench points lost, avg vs average
"""

import streamlit as st

from components.loading import LINES_GENERIC, fpl_loader
from ui import charts
import pandas as pd
import numpy as np
import requests
from typing import Optional

# set_page_config is owned by the app.py router (st.navigation)


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_team_history(team_id: int) -> Optional[dict]:
    try:
        resp = requests.get(
            f"https://fantasy.premierleague.com/api/entry/{team_id}/history/",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_bootstrap():
    from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek, fetch_team_info
    bs = fetch_bootstrap()
    gw = get_current_gameweek(bs)
    return bs, gw


def get_gw_averages(bootstrap: dict) -> pd.DataFrame:
    """Extract global average score per GW from bootstrap events."""
    records = []
    for event in bootstrap["events"]:
        avg = event.get("average_entry_score")
        if avg and event.get("finished"):
            records.append({"gw": event["id"], "global_avg": avg})
    return pd.DataFrame(records)


def _fill_between_chart(hist_df: pd.DataFrame, gw_avgs: pd.DataFrame) -> None:
    """
    Line chart of your GW score vs global average, with green fill above
    and red fill below the average line.
    """
    merged = hist_df.merge(gw_avgs, on="gw", how="left")
    merged["global_avg"] = merged["global_avg"].fillna(merged["net_points"].mean())

    gws   = merged["gw"].tolist()
    yours = [float(v) for v in merged["net_points"]]
    avgs  = [round(float(v), 1) for v in merged["global_avg"]]

    opt = charts.category_lines_option(gws, [
        ("Global Average", avgs, "rgba(255,255,255,0.35)"),
        ("Your Score", yours, "#00FF87"),
    ])
    opt["series"][0]["lineStyle"].update({"width": 1.5, "type": "dotted"})

    # Per-point markers green above / red below, labels on best beat & worst miss
    merged["diff"] = merged["net_points"] - merged["global_avg"]
    best_i  = int(merged["diff"].idxmax())
    worst_i = int(merged["diff"].idxmin())
    points = []
    for i, (y, a) in enumerate(zip(yours, avgs)):
        item = {"value": y, "itemStyle": {"color": "#00FF87" if y >= a else "#FF4B4B"}}
        if i == best_i:
            item["label"] = {"show": True, "position": "top", "fontSize": 11,
                             "color": "#00FF87",
                             "formatter": f"Best: +{merged['diff'].iloc[i]:.0f}"}
        elif i == worst_i:
            item["label"] = {"show": True, "position": "bottom", "fontSize": 11,
                             "color": "#FF4B4B",
                             "formatter": f"Worst: {merged['diff'].iloc[i]:.0f}"}
        points.append(item)
    opt["series"][1]["data"] = points
    opt["series"][1]["symbol"] = "circle"
    opt["series"][1]["symbolSize"] = 8

    base  = [round(min(y, a), 1) for y, a in zip(yours, avgs)]
    above = [round(max(0.0, y - a), 1) for y, a in zip(yours, avgs)]
    below = [round(max(0.0, a - y), 1) for y, a in zip(yours, avgs)]
    opt["series"].extend(charts.band_fill_series(base, above, below))

    opt["title"] = {"text": "Your GW Score vs Global Average", "textStyle": {
        "color": "#eef1f5", "fontSize": 13, "fontWeight": "bold"}}
    opt["legend"]["top"] = 22
    opt["grid"]["top"] = 56
    charts.render(opt, height="380px", key="gwh_vs_avg")


def _rank_chart(hist_df: pd.DataFrame) -> None:
    """Overall rank progression · inverted so better rank = higher on chart."""
    ranks = [int(v) for v in hist_df["overall_rank"]]
    best_i = ranks.index(min(ranks))
    points = []
    for i, r in enumerate(ranks):
        item = {"value": r}
        if i == best_i:
            item["label"] = {"show": True, "position": "top", "fontSize": 10,
                             "color": "#00FF87", "formatter": f"Best: {r:,}"}
        points.append(item)

    opt = charts.category_lines_option(hist_df["gw"].tolist(),
                                       [("Overall Rank", [], "#04f5ff")])
    s = opt["series"][0]
    s["data"] = points
    s["symbol"] = "circle"
    s["symbolSize"] = 6
    s["areaStyle"] = {"color": "rgba(4,245,255,0.06)"}
    opt["yAxis"]["inverse"] = True   # lower rank number = better = top of chart
    opt["title"] = {"text": "Overall Rank Progression", "textStyle": {
        "color": "#eef1f5", "fontSize": 13, "fontWeight": "bold"}}
    opt["legend"] = {"show": False}
    opt["grid"]["top"] = 40
    opt["grid"]["left"] = 76
    charts.render(opt, height="300px", key="gwh_rank")


def _cumulative_chart(hist_df: pd.DataFrame, gw_avgs: pd.DataFrame) -> None:
    """Cumulative points: yours vs cumulative average."""
    merged = hist_df.merge(gw_avgs, on="gw", how="left")
    merged["global_avg"] = merged["global_avg"].fillna(0)
    merged["cumulative_yours"] = merged["net_points"].cumsum()
    merged["cumulative_avg"]   = merged["global_avg"].cumsum()

    yours = [int(v) for v in merged["cumulative_yours"]]
    avgs  = [round(float(v), 0) for v in merged["cumulative_avg"]]

    final_diff = int(yours[-1] - avgs[-1])
    diff_color = "#00FF87" if final_diff >= 0 else "#FF4B4B"
    points = [{"value": v} for v in yours]
    points[-1]["label"] = {
        "show": True, "position": "left", "fontSize": 12, "color": diff_color,
        "formatter": f"{'+' if final_diff >= 0 else ''}{final_diff} vs avg"}

    opt = charts.category_lines_option(merged["gw"].tolist(), [
        ("Cumulative Average", avgs, "rgba(255,255,255,0.35)"),
        ("Your Cumulative", [], "#00FF87"),
    ])
    opt["series"][0]["lineStyle"].update({"width": 1.5, "type": "dotted"})
    opt["series"][1]["data"] = points
    opt["series"][1]["areaStyle"] = {"color": "rgba(0,255,135,0.08)"}
    opt["title"] = {"text": "Cumulative Points vs Average", "textStyle": {
        "color": "#eef1f5", "fontSize": 13, "fontWeight": "bold"}}
    opt["legend"]["top"] = 22
    opt["grid"]["top"] = 56
    charts.render(opt, height="300px", key="gwh_cumulative")


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("📅 GW History")
st.caption("Your season performance vs the global average, gameweek by gameweek.")

bootstrap, current_gw = load_bootstrap()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Team")
    from config import FPL_TEAM_ID
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input("FPL Team ID", min_value=1, value=default_id, step=1)

# Load data
with fpl_loader(f"Replaying the season for team {team_id}", LINES_GENERIC):
    history = load_team_history(team_id)

if not history:
    st.error(f"Could not load history for team {team_id}. Check your team ID.")
    st.stop()

from data.fetchers.fpl_api import fetch_team_info
try:
    team_info = fetch_team_info(team_id)
    team_name = team_info.get("name", f"Team {team_id}")
    manager   = f"{team_info.get('player_first_name','')} {team_info.get('player_last_name','')}".strip()
except Exception:
    team_name = f"Team {team_id}"
    manager   = ""

gw_history = history.get("current", [])
if not gw_history:
    st.warning("No GW history found for this team.")
    st.stop()

hist_df = pd.DataFrame(gw_history)
hist_df["net_points"] = hist_df["points"] - hist_df["event_transfers_cost"]
hist_df = hist_df.rename(columns={"event": "gw"})
hist_df["gw"] = hist_df["gw"].astype(int)

gw_avgs = get_gw_averages(bootstrap)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"## {team_name}")
if manager:
    st.caption(f"Manager: {manager}")

# ── Key metrics ────────────────────────────────────────────────────────────────
total_pts     = int(hist_df["points"].sum())
total_hits    = int(hist_df["event_transfers_cost"].sum())
net_total     = total_pts - total_hits
avg_per_gw    = float(hist_df["net_points"].mean())
best_gw_row   = hist_df.loc[hist_df["net_points"].idxmax()]
worst_gw_row  = hist_df.loc[hist_df["net_points"].idxmin()]
total_bench   = int(hist_df["points_on_bench"].sum()) if "points_on_bench" in hist_df.columns else 0

# Vs global average
merged_avg = hist_df.merge(gw_avgs, on="gw", how="left")
merged_avg["diff"] = merged_avg["net_points"] - merged_avg["global_avg"]
gws_above = int((merged_avg["diff"] > 0).sum())
gws_below = int((merged_avg["diff"] <= 0).sum())
total_vs_avg = float(merged_avg["diff"].sum())

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total Points",   f"{net_total:,}")
m2.metric("Avg / GW",       f"{avg_per_gw:.1f}")
m3.metric("Best GW",        f"GW{int(best_gw_row['gw'])}",  f"{int(best_gw_row['net_points'])} pts")
m4.metric("Worst GW",       f"GW{int(worst_gw_row['gw'])}", f"{int(worst_gw_row['net_points'])} pts")
m5.metric("Hit cost (total)", f"{total_hits} pts")
m6.metric("Bench pts lost", f"{total_bench}")

st.markdown("---")

# ── GW vs average ────────────────────────────────────────────────────────────
_fill_between_chart(hist_df, gw_avgs)

# ── Above vs below summary banner ─────────────────────────────────────────────
delta_color  = "#00FF87" if total_vs_avg >= 0 else "#FF4B4B"
delta_sign   = "+" if total_vs_avg >= 0 else ""
st.markdown(
    f"<div style='display:flex;gap:32px;padding:14px 20px;"
    f"background:rgba(255,255,255,0.03);border-radius:10px;font-family:sans-serif;'>"
    f"<div><span style='color:rgba(255,255,255,0.4);font-size:12px;'>GWs above average</span>"
    f"<div style='font-size:20px;font-weight:800;color:#00FF87;'>{gws_above}</div></div>"
    f"<div><span style='color:rgba(255,255,255,0.4);font-size:12px;'>GWs below average</span>"
    f"<div style='font-size:20px;font-weight:800;color:#FF4B4B;'>{gws_below}</div></div>"
    f"<div><span style='color:rgba(255,255,255,0.4);font-size:12px;'>Total vs average</span>"
    f"<div style='font-size:20px;font-weight:800;color:{delta_color};'>"
    f"{delta_sign}{total_vs_avg:.0f} pts</div></div>"
    f"</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ── Bottom charts: rank + cumulative ─────────────────────────────────────────
col_rank, col_cum = st.columns(2)

with col_rank:
    if "overall_rank" in hist_df.columns:
        _rank_chart(hist_df)

with col_cum:
    _cumulative_chart(hist_df, gw_avgs)

# ── Hit analysis ──────────────────────────────────────────────────────────────
if total_hits > 0:
    st.markdown("---")
    st.markdown("### Transfer Hit Analysis")
    hits_df = hist_df[hist_df["event_transfers_cost"] > 0][
        ["gw", "points", "event_transfers_cost", "net_points"]
    ].copy()
    hits_df.columns = ["GW", "Gross Pts", "Hit Cost", "Net Pts"]
    st.dataframe(hits_df, use_container_width=True, hide_index=True)
    st.caption(f"Total hit cost this season: **{total_hits} pts** across {len(hits_df)} GW(s).")
