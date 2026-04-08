"""
Differentials Spotter page.

Identifies low-ownership players with high upside —
the picks that give you an edge over the template team.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Differentials — FPL Hub", layout="wide")

st.title("🎯 Differentials Spotter")
st.caption("Low-ownership, high-ceiling picks to separate you from the pack.")


def get_players():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


players_df = get_players()

# ── Sidebar filters ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filters")
    max_own = st.slider("Max ownership (%)", 1.0, 20.0, 10.0, step=0.5)
    position = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    max_price = st.slider("Max price (£m)", 4.0, 15.0, 12.0, step=0.5)
    top_n = st.slider("Show top N", 5, 30, 20)

from analytics.differentials import get_differentials

pos_filter = None if position == "All" else position

with st.spinner("Finding differentials..."):
    diffs = get_differentials(
        players_df,
        max_ownership=max_own,
        position=pos_filter,
        max_price=max_price,
        top_n=top_n,
    )

if diffs.empty:
    st.warning("No differentials found with these filters. Try relaxing ownership threshold.")
    st.stop()

# ── Metrics ────────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    top = diffs.iloc[0]
    st.metric("Top Differential", top["web_name"], f"{top['ownership']:.1f}% owned")
with col2:
    st.metric("Players Found", len(diffs))
with col3:
    avg_own = diffs["ownership"].mean() if "ownership" in diffs.columns else 0
    st.metric("Avg Ownership", f"{avg_own:.1f}%")

st.markdown("---")

tab1, tab2 = st.tabs(["📋 Rankings", "📊 Ownership vs Form"])

with tab1:
    from components.player_table import render_player_table
    render_player_table(diffs, highlight_col="Diff Score", height=600)

with tab2:
    # Ownership vs Form bubble chart
    # Bubble size = differential score, colour = position
    if "ownership" in diffs.columns and "form" in diffs.columns:
        fig = px.scatter(
            diffs,
            x="ownership",
            y="form",
            size="differential_score",
            color="position" if "position" in diffs.columns else None,
            hover_name="web_name",
            hover_data=["price", "total_points"],
            title="Ownership vs Form (bubble size = differential score)",
            labels={"ownership": "Ownership (%)", "form": "Form"},
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        # Add annotation for top pick
        top_row = diffs.iloc[0]
        fig.add_annotation(
            x=top_row["ownership"],
            y=top_row["form"],
            text=f"  {top_row['web_name']}",
            showarrow=False,
            font=dict(color="#00FF87", size=12),
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("""
    > **How to read this chart:**
    > - **Left** = lower ownership (more differential)
    > - **Higher** = better form
    > - **Larger bubble** = higher differential score
    > - Ideal differential: bottom-left, high position, large bubble
    """)
