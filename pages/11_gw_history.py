"""
GW History — your gameweek points history vs the global average.

Shows:
  • Line chart: your GW score vs global average each week
  • Colour-filled area: green above average, red below
  • Rank progression chart over the season
  • Key stats: best/worst GW, total hits, bench points lost, avg vs average
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
import requests
from typing import Optional

st.set_page_config(page_title="GW History — FPL Hub", layout="wide")


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


def _fill_between_chart(hist_df: pd.DataFrame, gw_avgs: pd.DataFrame) -> go.Figure:
    """
    Line chart of your GW score vs global average, with green fill above
    and red fill below the average line.
    """
    merged = hist_df.merge(gw_avgs, on="gw", how="left")
    merged["global_avg"] = merged["global_avg"].fillna(merged["net_points"].mean())

    gws   = merged["gw"].tolist()
    yours = merged["net_points"].tolist()
    avgs  = merged["global_avg"].tolist()
    diff  = [y - a for y, a in zip(yours, avgs)]

    fig = go.Figure()

    # Global average line
    fig.add_trace(go.Scatter(
        x=gws, y=avgs,
        mode="lines",
        name="Global Average",
        line=dict(color="rgba(255,255,255,0.35)", width=1.5, dash="dot"),
        hovertemplate="GW%{x} avg: %{y:.0f}<extra></extra>",
    ))

    # Filled area ABOVE average (green)
    yours_above = [y if y >= a else a for y, a in zip(yours, avgs)]
    fig.add_trace(go.Scatter(
        x=gws + gws[::-1],
        y=yours_above + avgs[::-1],
        fill="toself",
        fillcolor="rgba(0,255,135,0.15)",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Filled area BELOW average (red)
    yours_below = [y if y <= a else a for y, a in zip(yours, avgs)]
    fig.add_trace(go.Scatter(
        x=gws + gws[::-1],
        y=yours_below + avgs[::-1],
        fill="toself",
        fillcolor="rgba(255,75,75,0.15)",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Your score line
    point_colors = ["#00FF87" if y >= a else "#FF4B4B" for y, a in zip(yours, avgs)]
    fig.add_trace(go.Scatter(
        x=gws,
        y=yours,
        mode="lines+markers",
        name="Your Score",
        line=dict(color="#00FF87", width=2.5),
        marker=dict(
            color=point_colors,
            size=8,
            line=dict(color="rgba(0,0,0,0.4)", width=1),
        ),
        hovertemplate=(
            "<b>GW%{x}</b><br>"
            "Your score: <b>%{y}</b><br>"
            "<extra></extra>"
        ),
    ))

    # Annotate biggest beats / misses
    merged["diff"] = merged["net_points"] - merged["global_avg"]
    best_beat = merged.loc[merged["diff"].idxmax()]
    worst_miss = merged.loc[merged["diff"].idxmin()]

    fig.add_annotation(
        x=int(best_beat["gw"]), y=float(best_beat["net_points"]) + 3,
        text=f"Best: +{best_beat['diff']:.0f}",
        showarrow=False,
        font=dict(color="#00FF87", size=11, family="monospace"),
    )
    fig.add_annotation(
        x=int(worst_miss["gw"]), y=float(worst_miss["net_points"]) - 5,
        text=f"Worst: {worst_miss['diff']:.0f}",
        showarrow=False,
        font=dict(color="#FF4B4B", size=11, family="monospace"),
    )

    fig.update_layout(
        title="Your GW Score vs Global Average",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=380,
        xaxis=dict(
            title="Gameweek",
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(color="rgba(255,255,255,0.6)"),
        ),
        yaxis=dict(
            title="Points",
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(color="rgba(255,255,255,0.6)"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0.3)",
            bordercolor="rgba(255,255,255,0.1)",
            borderwidth=1,
        ),
        font=dict(color="rgba(255,255,255,0.8)"),
        margin=dict(t=50, b=20),
        hovermode="x unified",
    )
    return fig


def _rank_chart(hist_df: pd.DataFrame) -> go.Figure:
    """Overall rank progression — inverted so better rank = higher on chart."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_df["gw"].tolist(),
        y=hist_df["overall_rank"].tolist(),
        mode="lines+markers",
        line=dict(color="#04f5ff", width=2.5),
        marker=dict(size=6, color="#04f5ff"),
        hovertemplate="GW%{x}<br>Rank: <b>%{y:,}</b><extra></extra>",
        fill="tozeroy",
        fillcolor="rgba(4,245,255,0.06)",
        name="Overall Rank",
    ))

    # Annotate best and worst rank
    best_rank = hist_df.loc[hist_df["overall_rank"].idxmin()]
    fig.add_annotation(
        x=int(best_rank["gw"]),
        y=int(best_rank["overall_rank"]),
        text=f"Best: {int(best_rank['overall_rank']):,}",
        showarrow=True, arrowhead=2,
        arrowcolor="#00FF87",
        font=dict(color="#00FF87", size=10),
        ax=0, ay=-30,
    )

    fig.update_layout(
        title="Overall Rank Progression",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        xaxis=dict(
            title="Gameweek",
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(color="rgba(255,255,255,0.6)"),
        ),
        yaxis=dict(
            title="Overall Rank",
            autorange="reversed",    # lower rank number = better = top of chart
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(color="rgba(255,255,255,0.6)"),
            tickformat=",",
        ),
        font=dict(color="rgba(255,255,255,0.8)"),
        margin=dict(t=50, b=20),
        showlegend=False,
    )
    return fig


def _cumulative_chart(hist_df: pd.DataFrame, gw_avgs: pd.DataFrame) -> go.Figure:
    """Cumulative points: yours vs cumulative average."""
    merged = hist_df.merge(gw_avgs, on="gw", how="left")
    merged["global_avg"] = merged["global_avg"].fillna(0)
    merged["cumulative_yours"] = merged["net_points"].cumsum()
    merged["cumulative_avg"]   = merged["global_avg"].cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=merged["gw"].tolist(),
        y=merged["cumulative_avg"].tolist(),
        mode="lines",
        name="Cumulative Average",
        line=dict(color="rgba(255,255,255,0.35)", width=1.5, dash="dot"),
        hovertemplate="GW%{x} avg total: %{y:.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=merged["gw"].tolist(),
        y=merged["cumulative_yours"].tolist(),
        mode="lines",
        name="Your Cumulative",
        line=dict(color="#00FF87", width=2.5),
        fill="tonexty",
        fillcolor="rgba(0,255,135,0.08)",
        hovertemplate="GW%{x} your total: <b>%{y}</b><extra></extra>",
    ))
    final_diff = int(merged["cumulative_yours"].iloc[-1] - merged["cumulative_avg"].iloc[-1])
    diff_color = "#00FF87" if final_diff >= 0 else "#FF4B4B"
    fig.add_annotation(
        x=merged["gw"].iloc[-1],
        y=merged["cumulative_yours"].iloc[-1],
        text=f"{'+' if final_diff >= 0 else ''}{final_diff} vs avg",
        showarrow=False,
        font=dict(color=diff_color, size=12, family="monospace"),
        xanchor="right",
        yanchor="bottom",
    )
    fig.update_layout(
        title="Cumulative Points vs Average",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        xaxis=dict(title="Gameweek", gridcolor="rgba(255,255,255,0.06)",
                   tickfont=dict(color="rgba(255,255,255,0.6)")),
        yaxis=dict(title="Cumulative Points", gridcolor="rgba(255,255,255,0.06)",
                   tickfont=dict(color="rgba(255,255,255,0.6)")),
        legend=dict(bgcolor="rgba(0,0,0,0.3)", bordercolor="rgba(255,255,255,0.1)", borderwidth=1),
        font=dict(color="rgba(255,255,255,0.8)"),
        margin=dict(t=50, b=20),
        hovermode="x unified",
    )
    return fig


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
with st.spinner(f"Loading history for team {team_id}..."):
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
fig_main = _fill_between_chart(hist_df, gw_avgs)
st.plotly_chart(fig_main, use_container_width=True)

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
        fig_rank = _rank_chart(hist_df)
        st.plotly_chart(fig_rank, use_container_width=True)

with col_cum:
    fig_cum = _cumulative_chart(hist_df, gw_avgs)
    st.plotly_chart(fig_cum, use_container_width=True)

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
