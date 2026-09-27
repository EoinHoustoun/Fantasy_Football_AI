"""
Mini-League Tracker

Enter a classic mini-league ID to see every manager's rank and
cumulative points over the season on one chart.
"""

import streamlit as st
from ui.page import section as _sec

from components.loading import LINES_GENERIC, fpl_loader
from ui import charts
import pandas as pd
import requests
from typing import List, Dict, Optional

# set_page_config is owned by the app.py router (st.navigation)

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
        # league_type 's' = system (Overall, country, club, GW1). Everything else
        # is a user-created league: FPL used 'c' for these and moved to 'x' by
        # 2026-27, which silently emptied this page. Treat any non-system type as
        # private rather than guessing the next letter.
        private = [l for l in classics if l.get("league_type") != "s"]
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
    "var(--ff-mint)", "var(--ff-gold)", "var(--ff-cyan)", "var(--ff-red)", "#c084fc",
    "#ff6900", "var(--ff-mag)", "#a3e635", "#fb923c", "#38bdf8",
    "#f472b6", "#34d399", "#facc15", "#818cf8", "#f87171",
]


def _league_lines(df: pd.DataFrame, value_col: str, title: str, height: int,
                  key: str, highlight: Optional[str] = None,
                  reversed_y: bool = False) -> None:
    """Multi-manager line chart with the selected manager emphasised."""
    series = []
    for i, team in enumerate(df["team_name"].unique()):
        t_df = df[df["team_name"] == team].sort_values("GW").dropna(subset=[value_col])
        series.append((team, list(zip(t_df["GW"], t_df[value_col])),
                       PALETTE[i % len(PALETTE)]))
    opt = charts.multi_line_option(series, x_name="Gameweek")
    for s, (team, _, _) in zip(opt["series"], series):
        focus = highlight is None or team == highlight
        s["lineStyle"]["width"] = 3 if team == highlight else 1.5
        s["lineStyle"]["opacity"] = 1.0 if focus else 0.35
    if reversed_y:
        opt["yAxis"]["inverse"] = True
    opt["title"] = {"text": title, "textStyle": {
        "color": "var(--ff-text)", "fontSize": 13, "fontWeight": "bold"}}
    opt["legend"]["top"] = 22
    opt["grid"]["top"] = 56
    charts.render(opt, height=f"{height}px", key=key)


def _gw_scores_chart(df: pd.DataFrame, highlight: Optional[str] = None) -> None:
    """Bar chart of GW scores per manager side-by-side."""
    pivot = df.pivot_table(index="GW", columns="team_name", values="gw_pts",
                           aggfunc="first").sort_index()
    teams = list(df["team_name"].unique())
    series = []
    for i, team in enumerate(teams):
        vals = [None if pd.isna(v) else int(v) for v in pivot.get(team, pd.Series())]
        series.append((team, vals, PALETTE[i % len(PALETTE)]))
    opt = charts.grouped_bars_option([f"{g}" for g in pivot.index], series)
    for s, (team, _, _) in zip(opt["series"], series):
        s["itemStyle"]["opacity"] = 1.0 if (highlight is None or team == highlight) else 0.4
    opt["title"] = {"text": "GW Scores (net of hits)", "textStyle": {
        "color": "var(--ff-text)", "fontSize": 13, "fontWeight": "bold"}}
    opt["legend"]["top"] = 22
    opt["grid"]["top"] = 56
    charts.render(opt, height="350px", key="ml_gw_scores")


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
                gap        = f"<div style='font-size:11px;color:var(--ff-muted2);'>-{diff} pts</div>"
            st.markdown(
                f"""<div style="
                    background:var(--ff-row-alt);
                    border:1px solid var(--ff-row-alt);
                    border-top:3px solid {color};
                    border-radius:8px;padding:14px 12px;
                    text-align:center;margin-bottom:8px;
                ">
                  <div style="font-size:20px;">{medal}</div>
                  <div style="font-size:13px;font-weight:700;color:var(--ff-text);margin:4px 0 2px;">{row['team_name']}</div>
                  <div style="font-size:11px;color:var(--ff-muted2);">{row['manager']}</div>
                  <div style="font-size:20px;font-weight:800;color:{color};margin-top:6px;">{int(row['cumulative'])}</div>
                  {gap}
                </div>""",
                unsafe_allow_html=True,
            )


# ── Page ────────────────────────────────────────────────────────────────────────

from ui.page import header as _header
_header("Mini-League", "Every manager's season: cumulative points, rank progression and head to head.", kicker="History", icon="leaderboard")

# Sidebar
with st.sidebar:
    st.markdown("### Your Team")
    from config import FPL_TEAM_ID
    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=int(st.session_state.get("squad_team_id") or FPL_TEAM_ID or 1),
        step=1,
        help="Your FPL team ID · used to auto-load your leagues.",
    )

    st.markdown("---")
    st.markdown("### Select League")

    # Fetch both private (user-created) and system (official/region/team) leagues
    all_leagues = fetch_my_leagues(team_id)
    private_leagues = [l for l in all_leagues if l.get("league_type") != "s"]
    system_leagues  = [l for l in all_leagues if l.get("league_type") == "s"]

    show_public = st.toggle(
        "Include public / region leagues",
        value=False,
        help="Off by default · these are FPL-official leagues like country, team supporters.",
    )

    visible_leagues = private_leagues + (system_leagues if show_public else [])

    league_id  = None
    if visible_leagues:
        def _label(l):
            tag = "🔒 Private" if l.get("league_type") != "s" else "🌐 Public"
            return f"{tag} · {l['name']}"

        league_options = {_label(l): l["id"] for l in visible_leagues}
        from analytics import prefs as _prefs0
        _remembered = _prefs0.get("league_id")
        _names = list(league_options.keys())
        _idx = next((k for k, n in enumerate(_names) if league_options[n] == _remembered), 0)
        selected_name  = st.selectbox(
            "Your leagues",
            options=_names,
            index=_idx,
            help="Private leagues listed first. Toggle above to include public leagues.",
        )
        league_id = league_options[selected_name]
        st.caption(f"League ID: {league_id}")
    elif private_leagues == [] and not show_public:
        st.info(
            "No private leagues found on this team. "
            "Toggle **Include public / region leagues** above, or paste a league ID below."
        )
    else:
        st.caption("Could not load leagues · enter ID manually below.")

    manual_id = st.number_input(
        "Or enter league ID manually",
        min_value=0,
        value=0,
        step=1,
        help="Paste the number from fantasy.premierleague.com/leagues/**XXXXXX**/standings/c",
    )
    if manual_id > 0:
        league_id = manual_id

    st.markdown("---")
    st.caption("Classic leagues only. Head-to-head leagues not supported.")

if league_id:
    # Remember it: Home and Captain read the league last viewed here.
    from analytics import prefs as _prefs
    _prefs.set("league_id", int(league_id))

if league_id is None or league_id == 0:
    st.info("Your leagues will appear in the dropdown once your team ID is loaded.")
    st.stop()

# Load league
with fpl_loader("Gathering the league", LINES_GENERIC):
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
_sec("Current Standings")
_standings_cards(league_df, current_gw)

# ── Rivals on the engine ──────────────────────────────────────────────────────
# Every rival's current fifteen projected exactly like yours (best XI and
# captain each week), plus the players that decide a mini-league: the ones
# most of them own and you do not, and yours that few of them have.
try:
    from analytics import service as _svc
    from components import ff_table as _T
    from components.team_identity import player_photo_url as _ppu
    from ui.theme import fill as _fill
    with st.spinner("Projecting every rival's squad"):
        _R = _svc.league_rivals(int(league_id), int(team_id), top_n=20)
except Exception as _e:  # noqa: BLE001
    _R = None
    st.caption("Rival projections unavailable: %s" % _e)
if _R and _R["managers"]:
    _g = _R["gws"]
    _sec("Rivals on the engine",
         "Each squad as it stands, projected over GW%d-%d with its best XI and captain every "
         "week. Where you finish depends on the players below." % (_g[0], _g[-1]))
    _ms = sorted(_R["managers"], key=lambda m: m["xp_window"])
    _o = charts.bar_option([("You · " if m["you"] else "") + str(m["team"])[:22] for m in _ms],
                           [m["xp_window"] for m in _ms], horizontal=True,
                           colors=[_fill("gold") if m["you"] else _fill("cyan") for m in _ms])
    _o["grid"]["left"] = 190
    _o["series"][0]["label"] = {"show": True, "position": "right", "color": _fill("text"),
                                "fontSize": 10, "formatter": "{c}"}
    _o["tooltip"]["formatter"] = "{b}: {c} xP over the window"
    charts.render(_o, height="%dpx" % (60 + 26 * len(_ms)), key="ml_rivals_%s" % league_id)
    _c1, _c2 = st.columns(2)
    with _c1:
        _sec("Threats", "Owned by at least a fifth of your rivals, not by you. Ranked by league "
             "ownership times six-week xP.")
        _T.render([{**t, "sub": t["team"]} for t in _R["threats"]], [
            _T.col_face("code", url_fn=_ppu), _T.col_player("name", sub="sub"),
            _T.col_num("league_own", "Rivals own %", fmt="%.0f"),
            _T.col_num("xp_window", "xP", fmt="%.1f")], key="ml_threats", max_height=380,
            empty="Nobody your rivals share is missing from your team.")
    with _c2:
        _sec("Your swords", "Yours, owned by few rivals (30% or less). If these return, you climb.")
        _T.render([{**t, "sub": t["team"]} for t in _R["swords"]], [
            _T.col_face("code", url_fn=_ppu), _T.col_player("name", sub="sub"),
            _T.col_num("league_own", "Rivals own %", fmt="%.0f"),
            _T.col_num("xp_window", "xP", fmt="%.1f")], key="ml_swords", max_height=380,
            empty="Your team looks like everyone else's.")

st.markdown("---")

# ── Charts ─────────────────────────────────────────────────────────────────────
tab_cum, tab_rank, tab_gw = st.tabs([
    ":material/show_chart: Cumulative points",
    ":material/trending_down: Rank progression",
    ":material/bar_chart: Gameweek by gameweek",
])

with tab_cum:
    _league_lines(league_df, "cumulative", "Cumulative Points · Season",
                  height=450, key="ml_cumulative", highlight=hl)
    st.caption("💡 Tip: Click a team name in the legend to hide/show it.")

with tab_rank:
    _league_lines(league_df, "rank", "Overall Rank Progression",
                  height=400, key="ml_rank", highlight=hl, reversed_y=True)
    st.caption("Lower rank = better. Y-axis is inverted so top of chart = best rank.")

with tab_gw:
    _gw_scores_chart(league_df, highlight=hl)

st.markdown("---")

# ── Full standings table ───────────────────────────────────────────────────────
_sec("Full Season Table")
latest_gw_df = league_df[league_df["GW"] == league_df["GW"].max()].copy()
latest_gw_df = latest_gw_df.sort_values("cumulative", ascending=False).reset_index(drop=True)
latest_gw_df.index += 1

table_df = latest_gw_df[["team_name", "manager", "cumulative", "gw_pts", "rank"]].copy()
table_df.columns = ["Team", "Manager", "Total Pts", f"GW{int(league_df['GW'].max())} Pts", "Overall Rank"]
table_df["Overall Rank"] = table_df["Overall Rank"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")

st.dataframe(table_df, use_container_width=True)

# ── Key moments ───────────────────────────────────────────────────────────────
st.markdown("---")
_sec("Key Moments")
st.caption("Biggest lead changes and best individual GW scores in your league.")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown("**Best Single GW Score**")
    best_gw_row = league_df.loc[league_df["gw_pts"].idxmax()]
    st.markdown(
        f"<div style='background:rgba(255,215,0,0.08);border:1px solid rgba(255,215,0,0.3);"
        f"border-radius:8px;padding:14px 16px;'>"
        f"<div style='font-size:28px;font-weight:900;color:var(--ff-gold);'>{int(best_gw_row['gw_pts'])} pts</div>"
        f"<div style='font-size:14px;color:var(--ff-text);font-weight:700;'>{best_gw_row['team_name']}</div>"
        f"<div style='font-size:12px;color:var(--ff-muted2);'>GW{int(best_gw_row['GW'])}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

with col_b:
    st.markdown("**Worst Single GW Score**")
    worst_gw_row = league_df.loc[league_df["gw_pts"].idxmin()]
    st.markdown(
        f"<div style='background:rgba(255,75,75,0.08);border:1px solid rgba(255,75,75,0.3);"
        f"border-radius:8px;padding:14px 16px;'>"
        f"<div style='font-size:28px;font-weight:900;color:var(--ff-red);'>{int(worst_gw_row['gw_pts'])} pts</div>"
        f"<div style='font-size:14px;color:var(--ff-text);font-weight:700;'>{worst_gw_row['team_name']}</div>"
        f"<div style='font-size:12px;color:var(--ff-muted2);'>GW{int(worst_gw_row['GW'])}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
