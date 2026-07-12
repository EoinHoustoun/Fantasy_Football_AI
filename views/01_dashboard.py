"""
Dashboard page · GW snapshot and team overview.
"""

import streamlit as st
import pandas as pd

from ui import charts

# set_page_config is owned by the app.py router (st.navigation)

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
# Minimum minutes threshold for scatter: 20% of season played so far
MIN_SEASON_PCT = 0.20
min_minutes = int(current_gw * 90 * MIN_SEASON_PCT)
qualified = players_df[players_df["minutes"] >= min_minutes].copy()

# Stricter threshold for the points-per-position chart: 10+ full-game
# equivalents (90-minute blocks) so squad players and cameo scorers don't
# distort the per-position averages.
PPG_MIN_GAMES = 10
ppg_min_minutes = PPG_MIN_GAMES * 90
ppg_qualified = players_df[players_df["minutes"] >= ppg_min_minutes].copy()

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("#### Avg Points per Game by Position")
    st.caption(f"Players with ≥{PPG_MIN_GAMES} games played (≥{ppg_min_minutes} mins)")
    pos_avg = ppg_qualified.groupby("position")["points_per_game"].mean().reset_index()
    pos_avg.columns = ["position", "avg_ppg"]
    pos_avg = pos_avg.sort_values("avg_ppg", ascending=False)
    # Order: GKP, DEF, MID, FWD for display
    pos_order = ["GKP", "DEF", "MID", "FWD"]
    pos_avg["position"] = pd.Categorical(pos_avg["position"], categories=pos_order, ordered=True)
    pos_avg = pos_avg.sort_values("position")
    _pos_colors = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}
    opt = charts.bar_option(
        x=list(pos_avg["position"].astype(str)),
        y=[round(float(v), 2) for v in pos_avg["avg_ppg"]],
        colors=[_pos_colors.get(p, "#00FF87") for p in pos_avg["position"].astype(str)],
    )
    for item in opt["series"][0]["data"]:
        item["label"] = {"show": True, "position": "top", "formatter": "{c}",
                         "color": "rgba(255,255,255,0.7)", "fontSize": 10}
    opt["yAxis"]["max"] = round(float(pos_avg["avg_ppg"].max()) * 1.2, 1)
    opt["tooltip"]["formatter"] = "{b}: {c} pts/game"
    charts.render(opt, height="320px", key="dash_ppg_pos")

with col_right:
    st.markdown("#### Points per £m · Season Value")
    st.caption(f"Players with ≥{min_minutes} mins. Bubble size = ownership %")
    _sizes = charts.scale_sizes(list(qualified["ownership"]), lo=6.0, hi=30.0)
    _groups = []
    for pos, col in _pos_colors.items():
        d = qualified[qualified["position"] == pos]
        pts = []
        for _, r in d.iterrows():
            idx = qualified.index.get_loc(r.name)
            pts.append({
                "x": round(float(r["points_per_million"]), 2),
                "y": int(r["total_points"]),
                "name": str(r["web_name"]), "size": _sizes[idx],
                "tip": (f"<b>{r['web_name']}</b><br/>"
                        f"{r['points_per_million']:.1f} pts/£m · {int(r['total_points'])} pts<br/>"
                        f"£{r['price']:.1f}m · {r['ownership']:.1f}% owned"),
            })
        if pts:
            _groups.append((pos, col, pts))
    charts.render(
        charts.multi_scatter_option(_groups, x_name="Points per £m",
                                    y_name="Total Points"),
        height="320px", key="dash_value_scatter",
    )

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
