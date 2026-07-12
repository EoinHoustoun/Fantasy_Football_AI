"""
Ownership Trend · visual-only tracking of how player ownership has moved
across the season, using vaastav GW-by-GW data.

Shows:
  • Biggest ownership risers this season (line chart)
  • Biggest ownership fallers this season (line chart)
  • Search any player to see their ownership trajectory
"""

import streamlit as st

from components.loading import LINES_GENERIC, fpl_loader
from ui import charts
import pandas as pd
import numpy as np
from typing import Optional, List

# set_page_config is owned by the app.py router (st.navigation)

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
    key: str = "own_trend",
) -> None:
    """Render a multi-line ownership trend chart for a list of players."""
    colors = [
        "#00FF87", "#04f5ff", "#e90052", "#ff6900",
        "#FFD700", "#c084fc", "#f472b6", "#38bdf8",
        "#a3e635", "#fb923c",
    ]

    series = []
    for i, player in enumerate(players):
        pdata = gw_own[gw_own["web_name"] == player].sort_values("GW")
        if pdata.empty:
            continue
        col = color_map.get(player, colors[i % len(colors)]) if color_map else colors[i % len(colors)]
        team = pdata["team"].iloc[0] if "team" in pdata.columns else ""
        series.append((
            f"{player} ({team})",
            list(zip(pdata["GW"], pdata["ownership_pct"].round(1))),
            col,
        ))

    opt = charts.multi_line_option(series, x_name="Gameweek", y_name="Ownership %")
    for s in opt["series"]:
        s["symbol"] = "circle"
        s["symbolSize"] = 5
    opt["title"] = {"text": title, "textStyle": {
        "color": "#eef1f5", "fontSize": 13, "fontWeight": "bold"}}
    opt["legend"]["top"] = 22
    opt["grid"]["top"] = 52
    charts.render(opt, height=f"{height}px", key=key)


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("📈 Ownership Trend")
st.caption("Who's been bought and sold across the season · visualised.")

with fpl_loader("Tracking the transfer market", LINES_GENERIC):
    players_df, current_gw = load_universe()
    gw_raw = load_gw_history()

if gw_raw is None:
    st.error("Ownership history data unavailable. Vaastav data source may be temporarily down.")
    st.stop()

gw_own = _ownership_series(gw_raw, players_df)

if gw_own is None or gw_own.empty:
    st.error("Could not process ownership data · vaastav columns may have changed.")
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

_sizes = charts.scale_sizes(list(scatter_df["size"]), lo=7.0, hi=35.0)
_groups = []
for pos, col in POS_COLORS.items():
    sub = scatter_df[scatter_df["position"] == pos]
    pts = []
    for _, r in sub.iterrows():
        idx = scatter_df.index.get_loc(r.name)
        pts.append({
            "x": round(float(r["change"]), 1),
            "y": round(float(r["late_own"]), 1),
            "name": str(r["web_name"]), "size": _sizes[idx],
            "tip": (f"<b>{r['web_name']}</b> · {r['team']}<br/>"
                    f"Change {r['change']:+.1f}% → now {r['late_own']:.1f}%<br/>"
                    f"£{r['price']:.1f}m"),
        })
    if pts:
        _groups.append((pos, col, pts))
opt = charts.multi_scatter_option(
    _groups, x_name="Ownership Change (season start → now)",
    y_name="Current Ownership %")
opt["title"] = {"text": "Ownership Change vs Current Ownership",
                "textStyle": {"color": "#eef1f5", "fontSize": 13,
                              "fontWeight": "bold"}}
opt["legend"]["top"] = 22
charts.with_vertical_marks(opt, [(0, "")], color="rgba(255,255,255,0.3)")
charts.render(opt, height="400px", key="own_change_scatter")

st.markdown("---")

# ── Top Risers chart ───────────────────────────────────────────────────────────
st.markdown("### 📈 Biggest Ownership Risers")
st.caption("Players who've been bought most heavily across the season.")

col_rise, col_fall = st.columns(2)

with col_rise:
    top_risers_10 = movers.nlargest(10, "change")["web_name"].tolist()
    if top_risers_10:
        _sparkline_chart(gw_own, top_risers_10, "Top 10 Ownership Risers",
                         key="own_risers")

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
        _sparkline_chart(gw_own, top_fallers_10, "Top 10 Ownership Fallers",
                         key="own_fallers")

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
    _sparkline_chart(gw_own, selected_players, "Ownership Trend · Selected Players",
                     color_map=color_map, height=380, key="own_search")
else:
    st.caption("Add players above to see their ownership trend side-by-side.")
