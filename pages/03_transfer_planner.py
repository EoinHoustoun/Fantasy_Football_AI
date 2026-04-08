"""
Transfer Planner page.

Multi-week planning view: shows fixture difficulty across positions
to help plan transfers 2-4 gameweeks ahead.
"""

import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Transfer Planner — FPL Hub", layout="wide")

st.title("🗓️ Transfer Planner")
st.caption("Plan your transfers across multiple gameweeks using fixture data.")

st.info("🚧 Full multi-week optimiser coming in Phase 5. For now, use the fixture difficulty view below to plan manually.")


def get_data():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df, st.session_state.fixtures_df, st.session_state.bootstrap
    from data.processors.player_stats import build_player_universe
    from data.fetchers.fpl_api import fetch_bootstrap, get_fixtures_df
    from data.fetchers.understat import fetch_understat_players
    bs = fetch_bootstrap()
    return (
        build_player_universe(bootstrap=bs, understat_df=fetch_understat_players()),
        get_fixtures_df(bootstrap=bs),
        bs,
    )


players_df, fixtures_df, bootstrap = get_data()

from data.fetchers.fpl_api import get_current_gameweek
current_gw = get_current_gameweek(bootstrap)

# ── Filters ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Planner Settings")
    lookahead = st.slider("Gameweeks ahead", 3, 8, 6)
    position = st.selectbox("Focus position", ["All", "GKP", "DEF", "MID", "FWD"])
    max_price = st.slider("Max price (£m)", 4.0, 15.0, 12.0, step=0.5)
    top_n = st.slider("Show top N players", 5, 30, 15)

# ── Fixture difficulty grid ────────────────────────────────────────────────────
st.markdown(f"### Fixture Difficulty: GW{current_gw} → GW{current_gw + lookahead - 1}")

from data.processors.fixture_difficulty import attach_fixture_difficulty

pos_df = players_df.copy()
if position != "All":
    pos_df = pos_df[pos_df["position"] == position]
pos_df = pos_df[pos_df["price"] <= max_price]
pos_df = pos_df[pos_df["status"] == "a"]

# Re-attach with requested lookahead
if "upcoming_fixtures" in players_df.columns:
    from data.processors.fixture_difficulty import attach_fixture_difficulty
    if fixtures_df is not None:
        pos_df = attach_fixture_difficulty(
            players_df[players_df["position"] != "placeholder"].copy() if position == "All"
            else players_df[players_df["position"] == position].copy(),
            fixtures_df,
            current_gw,
            lookahead,
        )
        if max_price:
            pos_df = pos_df[pos_df["price"] <= max_price]

fdr_col = f"avg_fdr_next_{lookahead}"
if fdr_col not in pos_df.columns:
    fdr_col = next((c for c in pos_df.columns if c.startswith("avg_fdr_next_")), None)

if fdr_col:
    best_fixtures = pos_df.nsmallest(top_n, fdr_col)
else:
    best_fixtures = pos_df.nlargest(top_n, "form")

st.markdown(f"**Players with easiest fixtures over next {lookahead} GWs:**")

from components.fixture_ticker import render_fixture_ticker
render_fixture_ticker(best_fixtures, top_n=top_n)

st.markdown("---")

# ── Best fixtures table ────────────────────────────────────────────────────────
st.markdown("### Fixture Ease Rankings")

display_cols = ["web_name", "team", "position", "price", "ownership", "form", "total_points"]
if fdr_col and fdr_col in best_fixtures.columns:
    display_cols.append(fdr_col)

available_cols = [c for c in display_cols if c in best_fixtures.columns]

from components.player_table import render_player_table
render_player_table(
    best_fixtures[available_cols].reset_index(drop=True),
    highlight_col=fdr_col.replace("avg_fdr_next_", "FDR (") + ")" if fdr_col else None,
    height=400,
)
