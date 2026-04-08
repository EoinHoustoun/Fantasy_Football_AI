"""
Ownership Trend — visual-only tracking of how player ownership has moved
across the season, using vaastav GW-by-GW data.

Shows:
  • Biggest ownership risers this season (line chart)
  • Biggest ownership fallers this season (line chart)
  • Search any player to see their ownership trajectory
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import Optional, List

st.set_page_config(page_title="Ownership Trend — FPL Hub", layout="wide")

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_gw_history():
    from data.fetchers.vaastav import fetch_gw_history
    return fetch_gw_history()


@st.cache_data(ttl=1800, show_spinner=False)
def load_universe():
    from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    players = build_player_universe(bootstrap=bs, understat_df=understat_df)
    gw = get_current_gameweek(bs)
    return players, gw


def _ownership_series(gw_df: pd.DataFrame, players_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Build a wide DataFrame: rows = GW, columns = player web_name, values = selected_by_percent.
    Uses vaastav 'selected' column (ownership count) + total players to estimate %.
    """
    if gw_df is None:
        return None

    # Vaastav uses 'selected' column = number of FPL managers who owned that player
    if "selected" not in gw_df.columns or "GW" not in gw_df.columns:
        return None

    # Approximate total FPL managers per GW (constant ~11M in 24-25 season)
    TOTAL_MANAGERS = 11_000_000

    # Get current ownership from FPL API for reference
    fpl_own = players_df[["web_name", "ownership"]].copy()
    fpl_own = fpl_own.groupby("web_name").first().reset_index()

    # Need to identify players by name. vaastav uses 'name' column (full name).
    name_col = "name" if "name" in gw_df.columns else None
    if name_col is None:
        return None

    # Build name->web_name mapping from players_df
    # vaastav full name ≈ FPL full name (first_name + second_name)
    from data.processors.player_stats import build_player_universe
    players_subset = players_df[["name", "web_name", "position", "team"]].drop_duplicates("web_name")
    name_to_webname = dict(zip(players_subset["name"].str.lower(), players_subset["web_name"]))
    name_to_pos = dict(zip(players_subset["name"].str.lower(), players_subset["position"]))
    name_to_team = dict(zip(players_subset["name"].str.lower(), players_subset["team"]))

    gw_df = gw_df.copy()
    gw_df["ownership_pct"] = (gw_df["selected"] / TOTAL_MANAGERS * 100).round(2)
    gw_df["name_lower"] = gw_df[name_col].str.lower()
    gw_df["web_name"]   = gw_df["name_lower"].map(name_to_webname)
    gw_df["position"]   = gw_df["name_lower"].map(name_to_pos)
    gw_df["team"]       = gw_df["name_lower"].map(name_to_team)

    # Keep only matched players with valid GW
    gw_df = gw_df.dropna(subset=["web_name", "GW"])
    gw_df["GW"] = gw_df["GW"].astype(int)

    return gw_df


def _ownership_change(gw_own: pd.DataFrame, current_gw: int) -> pd.DataFrame:
    """
    For each player, compute ownership at GW1 vs latest GW to find biggest movers.
    Returns DataFrame: web_name, position, team, gw1_own, latest_own, change
    """
    earliest_gw = int(gw_own["GW"].min())
    latest_gw   = min(int(gw_own["GW"].max()), current_gw)

    early = gw_own[gw_own["GW"] == earliest_gw][["web_name", "ownership_pct"]].copy()
    early.columns = ["web_name", "early_own"]
    late  = gw_own[gw_own["GW"] == latest_gw][["web_name", "ownership_pct", "position", "team"]].copy()
    late.columns  = ["web_name", "late_own", "position", "team"]

    merged = early.merge(late, on="web_name", how="inner")
    merged["change"] = merged["late_own"] - merged["early_own"]
    return merged.dropna(subset=["change"])


def _sparkline_chart(
    gw_own: pd.DataFrame,
    players: List[str],
    title: str,
    color_map: Optional[dict] = None,
    height: int = 350,
) -> go.Figure:
    """Build a multi-line ownership trend chart for a list of players."""
    fig = go.Figure()

    colors = [
        "#00FF87", "#04f5ff", "#e90052", "#ff6900",
        "#FFD700", "#c084fc", "#f472b6", "#38bdf8",
        "#a3e635", "#fb923c",
    ]

    for i, player in enumerate(players):
        pdata = gw_own[gw_own["web_name"] == player].sort_values("GW")
        if pdata.empty:
            continue
        col = color_map.get(player, colors[i % len(colors)]) if color_map else colors[i % len(colors)]
        pos  = pdata["position"].iloc[0] if "position" in pdata.columns else ""
        team = pdata["team"].iloc[0] if "team" in pdata.columns else ""
        fig.add_trace(go.Scatter(
            x=pdata["GW"].tolist(),
            y=pdata["ownership_pct"].tolist(),
            mode="lines+markers",
            name=f"{player} ({team})",
            line=dict(color=col, width=2.5),
            marker=dict(size=5),
            hovertemplate=f"<b>{player}</b><br>GW%{{x}}: %{{y:.1f}}% owned<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        xaxis=dict(
            title="Gameweek",
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(color="rgba(255,255,255,0.6)"),
        ),
        yaxis=dict(
            title="Ownership %",
            gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(color="rgba(255,255,255,0.6)"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0.3)",
            bordercolor="rgba(255,255,255,0.1)",
            borderwidth=1,
            font=dict(size=11),
        ),
        font=dict(color="rgba(255,255,255,0.8)"),
        margin=dict(t=50, b=20),
        hovermode="x unified",
    )
    return fig


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("📈 Ownership Trend")
st.caption("Who's been bought and sold across the season — visualised.")

with st.spinner("Loading ownership data..."):
    players_df, current_gw = load_universe()
    gw_raw = load_gw_history()

if gw_raw is None:
    st.error("Ownership history data unavailable. Vaastav data source may be temporarily down.")
    st.stop()

gw_own = _ownership_series(gw_raw, players_df)

if gw_own is None or gw_own.empty:
    st.error("Could not process ownership data — vaastav columns may have changed.")
    st.stop()

movers = _ownership_change(gw_own, current_gw)

# ── Summary metrics ────────────────────────────────────────────────────────────
n_rising  = (movers["change"] > 3).sum()
n_falling = (movers["change"] < -3).sum()
top_riser = movers.nlargest(1, "change").iloc[0] if not movers.empty else None
top_faller= movers.nsmallest(1, "change").iloc[0] if not movers.empty else None

m1, m2, m3, m4 = st.columns(4)
m1.metric("Players rising 3%+",  f"{n_rising}")
m2.metric("Players falling 3%+", f"{n_falling}")
if top_riser is not None:
    m3.metric("Biggest riser",   top_riser["web_name"],
              f"+{top_riser['change']:.1f}%")
if top_faller is not None:
    m4.metric("Biggest faller",  top_faller["web_name"],
              f"{top_faller['change']:.1f}%")

st.markdown("---")

# ── Rising vs Falling scatter ──────────────────────────────────────────────────
st.markdown("### Season Ownership Movement")
st.caption("Each bubble is a player. Right = owned more now. Left = owned less. Size = current ownership.")

scatter_df = movers.merge(
    players_df[["web_name", "price", "ownership", "total_points"]].drop_duplicates("web_name"),
    on="web_name", how="left",
)
scatter_df = scatter_df[scatter_df["ownership"].notna()]
scatter_df["size"] = scatter_df["ownership"].clip(lower=1)

fig_scatter = px.scatter(
    scatter_df,
    x="change",
    y="late_own",
    color="position",
    size="size",
    hover_name="web_name",
    hover_data={"team": True, "change": True, "late_own": True, "price": True},
    color_discrete_map=POS_COLORS,
    labels={
        "change":   "Ownership Change (season start → now)",
        "late_own": "Current Ownership %",
        "team":     "Team",
        "price":    "Price (£m)",
    },
    size_max=35,
    title="Ownership Change vs Current Ownership",
)
fig_scatter.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.3)")
fig_scatter.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=400,
    font=dict(color="rgba(255,255,255,0.8)"),
    margin=dict(t=50, b=20),
)
st.plotly_chart(fig_scatter, use_container_width=True)

st.markdown("---")

# ── Top Risers chart ───────────────────────────────────────────────────────────
st.markdown("### 📈 Biggest Ownership Risers")
st.caption("Players who've been bought most heavily across the season.")

col_rise, col_fall = st.columns(2)

with col_rise:
    top_risers_10 = movers.nlargest(10, "change")["web_name"].tolist()
    if top_risers_10:
        fig_r = _sparkline_chart(gw_own, top_risers_10, "Top 10 Ownership Risers")
        st.plotly_chart(fig_r, use_container_width=True)

        # Summary bar
        riser_df = movers.nlargest(10, "change")[["web_name", "position", "team", "change", "late_own"]]
        riser_df["change"] = riser_df["change"].round(1)
        riser_df["late_own"] = riser_df["late_own"].round(1)
        riser_df = riser_df.rename(columns={
            "web_name": "Player", "position": "Pos", "team": "Team",
            "change": "Change %", "late_own": "Now %",
        })
        st.dataframe(riser_df, use_container_width=True, hide_index=True)

with col_fall:
    st.markdown("### 📉 Biggest Ownership Fallers")
    st.caption("Players managers have been selling all season.")
    top_fallers_10 = movers.nsmallest(10, "change")["web_name"].tolist()
    if top_fallers_10:
        fig_f = _sparkline_chart(gw_own, top_fallers_10, "Top 10 Ownership Fallers")
        st.plotly_chart(fig_f, use_container_width=True)

        faller_df = movers.nsmallest(10, "change")[["web_name", "position", "team", "change", "late_own"]]
        faller_df["change"] = faller_df["change"].round(1)
        faller_df["late_own"] = faller_df["late_own"].round(1)
        faller_df = faller_df.rename(columns={
            "web_name": "Player", "position": "Pos", "team": "Team",
            "change": "Change %", "late_own": "Now %",
        })
        st.dataframe(faller_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ── Search any player ──────────────────────────────────────────────────────────
st.markdown("### 🔍 Track Any Player")

all_tracked = sorted(gw_own["web_name"].dropna().unique().tolist())
selected_players = st.multiselect(
    "Search and add players to compare",
    all_tracked,
    default=[],
    max_selections=10,
    placeholder="Type a player name...",
)

if selected_players:
    pos_map = dict(zip(players_df["web_name"], players_df["position"]))
    color_map = {p: POS_COLORS.get(pos_map.get(p, "MID"), "#00FF87") for p in selected_players}
    fig_search = _sparkline_chart(gw_own, selected_players, "Ownership Trend — Selected Players",
                                   color_map=color_map, height=380)
    st.plotly_chart(fig_search, use_container_width=True)
else:
    st.caption("Add players above to see their ownership trend side-by-side.")
