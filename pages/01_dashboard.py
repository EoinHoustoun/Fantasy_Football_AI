"""
Dashboard page — GW snapshot and team overview.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Dashboard — FPL Hub", layout="wide")

st.title("📊 Dashboard")
st.caption("Current gameweek snapshot and league overview.")


def get_data():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df, st.session_state.bootstrap
    from data.processors.player_stats import build_player_universe
    from data.fetchers.fpl_api import fetch_bootstrap
    from data.fetchers.understat import fetch_understat_players
    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    return build_player_universe(bootstrap=bs, understat_df=understat_df), bs


players_df, bootstrap = get_data()

from data.fetchers.fpl_api import get_current_gameweek
current_gw = get_current_gameweek(bootstrap)

# ── GW Snapshot metrics ────────────────────────────────────────────────────────
st.markdown(f"### Gameweek {current_gw} Snapshot")
col1, col2, col3, col4 = st.columns(4)

with col1:
    top_scorer = players_df.nlargest(1, "total_points").iloc[0]
    st.metric("Top Points", top_scorer["web_name"], f"{top_scorer['total_points']} pts")
with col2:
    top_form = players_df.nlargest(1, "form").iloc[0]
    st.metric("Best Form", top_form["web_name"], f"Form: {top_form['form']:.1f}")
with col3:
    most_transferred_in = players_df.nlargest(1, "transfers_in_event").iloc[0]
    st.metric("Most Transferred In", most_transferred_in["web_name"],
              f"+{most_transferred_in['transfers_in_event']:,}")
with col4:
    most_transferred_out = players_df.nlargest(1, "transfers_out_event").iloc[0]
    st.metric("Most Transferred Out", most_transferred_out["web_name"],
              f"-{most_transferred_out['transfers_out_event']:,}")

st.markdown("---")

# ── Charts ─────────────────────────────────────────────────────────────────────
# Minimum minutes threshold: 20% of season played so far
MIN_SEASON_PCT = 0.20
min_minutes = int(current_gw * 90 * MIN_SEASON_PCT)
qualified = players_df[players_df["minutes"] >= min_minutes].copy()

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("#### Avg Points per Game by Position")
    st.caption(f"Players with ≥{min_minutes} mins ({int(MIN_SEASON_PCT*100)}% of season, GW{current_gw})")
    pos_avg = qualified.groupby("position")["points_per_game"].mean().reset_index()
    pos_avg.columns = ["position", "avg_ppg"]
    pos_avg = pos_avg.sort_values("avg_ppg", ascending=False)
    # Order: GKP, DEF, MID, FWD for display
    pos_order = ["GKP", "DEF", "MID", "FWD"]
    pos_avg["position"] = pd.Categorical(pos_avg["position"], categories=pos_order, ordered=True)
    pos_avg = pos_avg.sort_values("position")
    fig = px.bar(
        pos_avg,
        x="position", y="avg_ppg",
        color="position",
        color_discrete_map={"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"},
        title="Average Points per Game by Position",
        labels={"avg_ppg": "Avg Pts/Game", "position": "Position"},
        text=pos_avg["avg_ppg"].round(2),
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, paper_bgcolor="rgba(0,0,0,0)", height=320, yaxis_range=[0, pos_avg["avg_ppg"].max() * 1.2])
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.markdown("#### Points per £m — Season Value")
    st.caption(f"Players with ≥{min_minutes} mins. Bubble size = ownership %")
    fig2 = px.scatter(
        qualified,
        x="points_per_million",
        y="total_points",
        color="position",
        size="ownership",
        hover_name="web_name",
        hover_data={"price": True, "ownership": True, "points_per_million": True, "total_points": True},
        title="Points per £m vs Total Points",
        labels={
            "points_per_million": "Points per £m",
            "total_points": "Total Points",
            "ownership": "Ownership %",
            "price": "Price (£m)",
        },
        color_discrete_map={"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"},
        size_max=30,
    )
    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=320)
    st.plotly_chart(fig2, use_container_width=True)

# ── Top players tables by position ────────────────────────────────────────────
st.markdown("---")
st.markdown("### Top Players by Position")

from components.player_table import render_player_table

tabs = st.tabs(["MID", "FWD", "DEF", "GKP"])
for tab, pos in zip(tabs, ["MID", "FWD", "DEF", "GKP"]):
    with tab:
        pos_df = players_df[players_df["position"] == pos].nlargest(10, "total_points")[
            ["web_name", "team", "price", "ownership", "form", "total_points", "points_per_million", "goals_scored", "assists"]
        ]
        render_player_table(pos_df, highlight_col="Pts", height=350)
