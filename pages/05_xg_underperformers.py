"""
xG Underperformers Tracker page.

Identifies players who have accumulated significant xG but scored fewer goals —
statistically likely to "haul" soon as their luck normalises.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="xG Tracker — FPL Hub", layout="wide")

st.title("📈 xG Underperformers")
st.markdown("""
Players who have **more expected goals (xG) than actual goals** are statistically
likely to score soon — their finishing luck is due to normalise.

> *xG Gap = xG accumulated − goals scored. Higher gap = more "owed" goals.*
""")


def get_players():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


players_df = get_players()

# Check xG data availability
has_xg = "xg" in players_df.columns and players_df["xg"].notna().any()

if not has_xg:
    st.error("xG data is not available. Understat data could not be loaded.")
    st.info("Check your internet connection and use the Refresh button on the home page.")
    st.stop()

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filters")
    positions = st.multiselect(
        "Positions",
        ["MID", "FWD", "DEF"],
        default=["MID", "FWD"],
    )
    min_xg = st.slider("Min xG threshold", 0.5, 6.0, 2.0, step=0.5,
                        help="Only players who have accumulated at least this much xG")
    min_gap = st.slider("Min xG gap", 0.5, 5.0, 1.5, step=0.25,
                        help="Min difference between xG and actual goals")
    show_overperformers = st.checkbox("Also show overperformers (sell candidates)", value=False)

# ── Get data ───────────────────────────────────────────────────────────────────
from analytics.xg_divergence import get_xg_underperformers, get_xg_overperformers

underperformers = get_xg_underperformers(
    players_df,
    min_xg=min_xg,
    min_gap=min_gap,
    positions=positions,
)

# ── Metrics ────────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Players Flagged", len(underperformers))
if not underperformers.empty:
    with col2:
        top = underperformers.iloc[0]
        st.metric("Top Haul Candidate", top["web_name"], f"Gap: +{top['xg_gap']:.2f} xG")
    with col3:
        total_gap = underperformers["xg_gap"].sum() if "xg_gap" in underperformers.columns else 0
        st.metric("Total 'Owed' Goals", f"{total_gap:.1f}")
    with col4:
        avg_own = underperformers["ownership"].mean() if "ownership" in underperformers.columns else 0
        st.metric("Avg Ownership", f"{avg_own:.1f}%")

st.markdown("---")

# ── Main content ───────────────────────────────────────────────────────────────
if underperformers.empty:
    st.info("No players match your filters. Try lowering the xG gap threshold.")
else:
    tab1, tab2 = st.tabs(["📋 Underperformers", "📊 xG vs Goals Chart"])

    with tab1:
        from components.player_table import render_player_table
        render_player_table(underperformers, highlight_col="Haul Score", height=500)

    with tab2:
        # xG vs actual goals scatter
        # Include all attacking players with xG data for context
        chart_df = players_df[
            (players_df["position"].isin(positions)) &
            (players_df["xg"].notna()) &
            (players_df["xg"] >= 0.5)
        ].copy()

        if not chart_df.empty:
            # Mark underperformers
            underperformer_names = set(underperformers["web_name"].tolist()) if not underperformers.empty else set()
            chart_df["category"] = chart_df["web_name"].apply(
                lambda x: "Underperforming (buy?)" if x in underperformer_names else "On track"
            )

            fig = px.scatter(
                chart_df,
                x="goals_scored",
                y="xg",
                color="category",
                hover_name="web_name",
                hover_data=["team", "price", "ownership", "form"],
                title="xG vs Actual Goals — Players above the line are underperforming",
                labels={"goals_scored": "Actual Goals", "xg": "Expected Goals (xG)"},
                color_discrete_map={
                    "Underperforming (buy?)": "#00FF87",
                    "On track":              "#888888",
                },
                size="xg",
                size_max=20,
            )

            # Diagonal reference line (xG = actual goals)
            max_val = max(chart_df["xg"].max(), chart_df["goals_scored"].max(), 1)
            fig.add_trace(go.Scatter(
                x=[0, max_val],
                y=[0, max_val],
                mode="lines",
                line=dict(color="rgba(255,255,255,0.3)", dash="dash", width=1),
                name="xG = Goals (perfect)",
                showlegend=True,
            ))

            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                height=500,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("""
            > **Above the diagonal line** = scored fewer goals than xG predicts → underperforming → potential buy
            > **Below the diagonal line** = scored more goals than xG predicts → overperforming → potential sell
            """)

# ── Overperformers section ─────────────────────────────────────────────────────
if show_overperformers:
    st.markdown("---")
    st.markdown("### ⚠️ Overperformers — Potential Sells")
    st.caption("Players who have scored significantly more than their xG — could regress.")

    overperformers = get_xg_overperformers(players_df, positions=positions)
    if overperformers.empty:
        st.info("No significant overperformers found.")
    else:
        from components.player_table import render_player_table
        render_player_table(overperformers, height=300)
