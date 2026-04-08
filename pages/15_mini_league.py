"""
Mini-League Tracker

Enter a classic mini-league ID to see every manager's rank and
cumulative points over the season on one chart.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import requests
from typing import List, Dict, Optional

st.set_page_config(page_title="Mini-League — FPL Hub", layout="wide")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)"}

# ── Fetch helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_league(league_id: int) -> Optional[dict]:
    try:
        url  = f"https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_manager_history(team_id: int) -> List[dict]:
    try:
        url  = f"https://fantasy.premierleague.com/api/entry/{team_id}/history/"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json().get("current", [])
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_my_leagues(team_id: int) -> List[Dict]:
    """Return the manager's classic mini-leagues (excludes global/system leagues)."""
    try:
        url  = f"https://fantasy.premierleague.com/api/entry/{team_id}/"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        classics = data.get("leagues", {}).get("classic", [])
        # league_type 'x' = global/FPL-official, 'c' = created (private), 's' = system
        # Show 'c' (private mini-leagues) first, then 's' (public/invitational), skip 'x' (global)
        private = [l for l in classics if l.get("league_type") == "c"]
        public  = [l for l in classics if l.get("league_type") == "s"]
        return private + public
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_global_avg() -> Dict[int, float]:
    """Return dict of GW -> average score from bootstrap events."""
    try:
        from data.fetchers.fpl_api import fetch_bootstrap
        bs = fetch_bootstrap()
        return {
            e["id"]: float(e.get("average_entry_score") or 0)
            for e in bs["events"]
            if e.get("finished")
        }
    except Exception:
        return {}


# ── Build combined DataFrame ───────────────────────────────────────────────────

def build_league_df(standings: List[dict]) -> pd.DataFrame:
    """Fetch every manager's history and return long-format cumulative pts DataFrame."""
    rows = []
    prog = st.progress(0, text="Loading manager histories...")
    n = len(standings)

    for i, mgr in enumerate(standings):
        team_id   = mgr["entry"]
        team_name = mgr.get("entry_name", f"Team {team_id}")
        manager   = mgr.get("player_name", "")

        history = fetch_manager_history(team_id)
        cumulative = 0
        for gw_row in history:
            pts     = gw_row.get("points", 0) - gw_row.get("event_transfers_cost", 0)
            cumulative += pts
            rows.append({
                "GW":          gw_row["event"],
                "team_id":     team_id,
                "team_name":   team_name,
                "manager":     manager,
                "gw_pts":      pts,
                "cumulative":  cumulative,
                "rank":        gw_row.get("overall_rank"),
            })

        prog.progress((i + 1) / n, text=f"Loading {team_name}...")

    prog.empty()
    return pd.DataFrame(rows)


# ── Chart builders ─────────────────────────────────────────────────────────────

PALETTE = [
    "#00FF87", "#FFD700", "#04f5ff", "#FF4B4B", "#c084fc",
    "#ff6900", "#e90052", "#a3e635", "#fb923c", "#38bdf8",
    "#f472b6", "#34d399", "#facc15", "#818cf8", "#f87171",
]


def _cumulative_chart(df: pd.DataFrame, highlight: Optional[str] = None) -> go.Figure:
    fig = go.Figure()
    teams = df["team_name"].unique()

    for i, team in enumerate(teams):
        t_df  = df[df["team_name"] == team].sort_values("GW")
        color = PALETTE[i % len(PALETTE)]
        width = 3 if team == highlight else 1.5
        opacity = 1.0 if (highlight is None or team == highlight) else 0.35

        fig.add_trace(go.Scatter(
            x=t_df["GW"],
            y=t_df["cumulative"],
            mode="lines",
            name=team,
            line=dict(color=color, width=width),
            opacity=opacity,
            hovertemplate=f"<b>{team}</b><br>GW%{{x}}: %{{y}} pts<extra></extra>",
        ))

    fig.update_layout(
        title="Cumulative Points — Season",
        xaxis_title="Gameweek",
        yaxis_title="Cumulative Points",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e2e2",
        legend=dict(
            bgcolor="rgba(0,0,0,0.3)",
            bordercolor="rgba(255,255,255,0.1)",
            font_size=11,
        ),
        height=450,
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    return fig


def _rank_chart(df: pd.DataFrame, highlight: Optional[str] = None) -> go.Figure:
    fig = go.Figure()
    teams = df["team_name"].unique()

    for i, team in enumerate(teams):
        t_df  = df[df["team_name"] == team].sort_values("GW").dropna(subset=["rank"])
        color = PALETTE[i % len(PALETTE)]
        width = 3 if team == highlight else 1.5
        opacity = 1.0 if (highlight is None or team == highlight) else 0.35

        fig.add_trace(go.Scatter(
            x=t_df["GW"],
            y=t_df["rank"],
            mode="lines",
            name=team,
            line=dict(color=color, width=width),
            opacity=opacity,
            hovertemplate=f"<b>{team}</b><br>GW%{{x}}: rank %{{y:,}}<extra></extra>",
        ))

    fig.update_layout(
        title="Overall Rank Progression",
        xaxis_title="Gameweek",
        yaxis_title="Overall Rank",
        yaxis_autorange="reversed",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e2e2",
        legend=dict(
            bgcolor="rgba(0,0,0,0.3)",
            bordercolor="rgba(255,255,255,0.1)",
            font_size=11,
        ),
        height=400,
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    return fig


def _gw_scores_chart(df: pd.DataFrame, highlight: Optional[str] = None) -> go.Figure:
    """Bar chart of GW scores per manager side-by-side."""
    teams = list(df["team_name"].unique())
    latest_gw = int(df["GW"].max())

    fig = go.Figure()
    for i, team in enumerate(teams):
        t_df = df[df["team_name"] == team].sort_values("GW")
        color = PALETTE[i % len(PALETTE)]
        opacity = 1.0 if (highlight is None or team == highlight) else 0.4
        fig.add_trace(go.Bar(
            name=team,
            x=t_df["GW"],
            y=t_df["gw_pts"],
            marker_color=color,
            opacity=opacity,
            hovertemplate=f"<b>{team}</b><br>GW%{{x}}: %{{y}} pts<extra></extra>",
        ))

    fig.update_layout(
        title="GW Scores (net of hits)",
        barmode="group",
        xaxis_title="Gameweek",
        yaxis_title="Points",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e2e2",
        height=350,
        legend=dict(bgcolor="rgba(0,0,0,0.3)", font_size=11),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    return fig


def _standings_cards(df: pd.DataFrame, current_gw: int) -> None:
    """Current standings as coloured rank cards."""
    latest = df[df["GW"] == df["GW"].max()].sort_values("cumulative", ascending=False).reset_index(drop=True)
    cols = st.columns(min(len(latest), 5))
    medals = ["🥇", "🥈", "🥉"]

    for i, (_, row) in enumerate(latest.iterrows()):
        with cols[i % 5]:
            medal  = medals[i] if i < 3 else f"#{i + 1}"
            color  = PALETTE[i % len(PALETTE)]
            gap    = ""
            if i > 0:
                leader_pts = int(latest.iloc[0]["cumulative"])
                diff       = leader_pts - int(row["cumulative"])
                gap        = f"<div style='font-size:11px;color:rgba(255,255,255,0.4);'>-{diff} pts</div>"
            st.markdown(
                f"""<div style="
                    background:rgba(255,255,255,0.03);
                    border:1px solid rgba(255,255,255,0.08);
                    border-top:3px solid {color};
                    border-radius:8px;padding:14px 12px;
                    text-align:center;margin-bottom:8px;
                ">
                  <div style="font-size:20px;">{medal}</div>
                  <div style="font-size:13px;font-weight:700;color:#fff;margin:4px 0 2px;">{row['team_name']}</div>
                  <div style="font-size:11px;color:rgba(255,255,255,0.4);">{row['manager']}</div>
                  <div style="font-size:20px;font-weight:800;color:{color};margin-top:6px;">{int(row['cumulative'])}</div>
                  {gap}
                </div>""",
                unsafe_allow_html=True,
            )


# ── Page ────────────────────────────────────────────────────────────────────────

st.markdown(
    "<div style='padding:20px 0 4px;'>"
    "<div style='font-size:30px;font-weight:900;color:#04f5ff;'>🏅 Mini-League Tracker</div>"
    "<div style='font-size:14px;color:rgba(255,255,255,0.4);margin-top:4px;'>"
    "See every manager's season journey — cumulative points, rank progression &amp; head-to-head."
    "</div></div>",
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
    st.markdown("### Your Team")
    from config import FPL_TEAM_ID
    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=int(FPL_TEAM_ID or 1),
        step=1,
        help="Your FPL team ID — used to auto-load your leagues.",
    )

    st.markdown("---")
    st.markdown("### Select League")

    my_leagues = fetch_my_leagues(team_id)
    league_id  = None

    if my_leagues:
        league_options = {l["name"]: l["id"] for l in my_leagues}
        selected_name  = st.selectbox(
            "Your leagues",
            options=list(league_options.keys()),
            help="All classic leagues you're in — private leagues listed first.",
        )
        league_id = league_options[selected_name]
        st.caption(f"League ID: {league_id}")
    else:
        st.caption("Could not load your leagues — enter ID manually below.")

    manual_id = st.number_input(
        "Or enter league ID manually",
        min_value=0,
        value=0,
        step=1,
        help="fantasy.premierleague.com/leagues/**XXXXXX**/standings/c",
    )
    if manual_id > 0:
        league_id = manual_id

    st.markdown("---")
    st.caption("Classic leagues only. Head-to-head leagues not supported.")

if league_id is None or league_id == 0:
    st.info("Your leagues will appear in the dropdown once your team ID is loaded.")
    st.stop()

# Load league
with st.spinner("Loading league..."):
    league_data = fetch_league(league_id)

if league_data is None:
    st.error(f"Could not load league {league_id}. Check the ID is correct and it's a classic league.")
    st.stop()

league_name = league_data.get("league", {}).get("name", f"League {league_id}")
standings   = league_data.get("standings", {}).get("results", [])

if not standings:
    st.warning("No managers found in this league.")
    st.stop()

st.markdown(f"## {league_name}")
st.caption(f"{len(standings)} managers")

# Load histories
league_df = build_league_df(standings)

if league_df.empty:
    st.warning("Could not load manager histories.")
    st.stop()

from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
current_gw = get_current_gameweek(fetch_bootstrap())

# ── Highlight selector ────────────────────────────────────────────────────────
team_names = sorted(league_df["team_name"].unique().tolist())
highlight  = st.selectbox(
    "Highlight a team (optional)",
    ["All teams"] + team_names,
    index=0,
)
hl = None if highlight == "All teams" else highlight

st.markdown("---")

# ── Current standings ──────────────────────────────────────────────────────────
st.markdown("### Current Standings")
_standings_cards(league_df, current_gw)

st.markdown("---")

# ── Charts ─────────────────────────────────────────────────────────────────────
tab_cum, tab_rank, tab_gw = st.tabs([
    "📈 Cumulative Points",
    "📉 Rank Progression",
    "📊 GW by GW",
])

with tab_cum:
    st.plotly_chart(_cumulative_chart(league_df, highlight=hl), use_container_width=True)
    st.caption("💡 Tip: Click a team name in the legend to hide/show it.")

with tab_rank:
    st.plotly_chart(_rank_chart(league_df, highlight=hl), use_container_width=True)
    st.caption("Lower rank = better. Y-axis is inverted so top of chart = best rank.")

with tab_gw:
    st.plotly_chart(_gw_scores_chart(league_df, highlight=hl), use_container_width=True)

st.markdown("---")

# ── Full standings table ───────────────────────────────────────────────────────
st.markdown("### Full Season Table")
latest_gw_df = league_df[league_df["GW"] == league_df["GW"].max()].copy()
latest_gw_df = latest_gw_df.sort_values("cumulative", ascending=False).reset_index(drop=True)
latest_gw_df.index += 1

table_df = latest_gw_df[["team_name", "manager", "cumulative", "gw_pts", "rank"]].copy()
table_df.columns = ["Team", "Manager", "Total Pts", f"GW{int(league_df['GW'].max())} Pts", "Overall Rank"]
table_df["Overall Rank"] = table_df["Overall Rank"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")

st.dataframe(table_df, use_container_width=True)

# ── Key moments ───────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### Key Moments")
st.caption("Biggest lead changes and best individual GW scores in your league.")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown("**Best Single GW Score**")
    best_gw_row = league_df.loc[league_df["gw_pts"].idxmax()]
    st.markdown(
        f"<div style='background:rgba(255,215,0,0.08);border:1px solid rgba(255,215,0,0.3);"
        f"border-radius:8px;padding:14px 16px;'>"
        f"<div style='font-size:28px;font-weight:900;color:#FFD700;'>{int(best_gw_row['gw_pts'])} pts</div>"
        f"<div style='font-size:14px;color:#fff;font-weight:700;'>{best_gw_row['team_name']}</div>"
        f"<div style='font-size:12px;color:rgba(255,255,255,0.4);'>GW{int(best_gw_row['GW'])}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

with col_b:
    st.markdown("**Worst Single GW Score**")
    worst_gw_row = league_df.loc[league_df["gw_pts"].idxmin()]
    st.markdown(
        f"<div style='background:rgba(255,75,75,0.08);border:1px solid rgba(255,75,75,0.3);"
        f"border-radius:8px;padding:14px 16px;'>"
        f"<div style='font-size:28px;font-weight:900;color:#FF4B4B;'>{int(worst_gw_row['gw_pts'])} pts</div>"
        f"<div style='font-size:14px;color:#fff;font-weight:700;'>{worst_gw_row['team_name']}</div>"
        f"<div style='font-size:12px;color:rgba(255,255,255,0.4);'>GW{int(worst_gw_row['GW'])}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
