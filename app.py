"""
FPL Analytics Hub · router / entry point.

This is the single Streamlit entrypoint. It owns everything shared across pages:
  • the one allowed st.set_page_config
  • global CSS + animations
  • shared data loading into st.session_state (players / bootstrap / fixtures)
  • sidebar branding + refresh + data-freshness
  • grouped navigation via st.navigation (20 pages → 6 labelled sections)

Individual pages live in views/ (NOT pages/ · that folder name is reserved by
Streamlit's auto-multipage system and collides with st.navigation) and read from
st.session_state. They must NOT call st.set_page_config (only the entrypoint may).

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import streamlit as st


logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="FPL Analytics Hub",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

from components.animations import inject_global_animations
from ui.theme import inject_theme
inject_global_animations()
inject_theme()   # elevated design system (depth/glass/glow) · see docs/OVERHAUL_PLAN.md

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
      background: linear-gradient(180deg, #37003c 0%, #1a0020 100%) !important;
  }
  [data-testid="stSidebar"] * { color: #ffffff !important; }
  [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15) !important; }

  /* ── Metrics ── */
  [data-testid="stMetricValue"] {
      color: #00FF87 !important;
      font-size: 1.6rem !important;
      font-weight: 800 !important;
  }
  [data-testid="stMetricLabel"] {
      font-size: 0.78rem !important;
      color: rgba(255,255,255,0.5) !important;
      text-transform: uppercase;
      letter-spacing: 0.05em;
  }
  [data-testid="stMetricDelta"] { font-size: 0.8rem !important; }

  /* ── Headings ── */
  h1 { color: #fff !important; letter-spacing: -0.5px; }
  h2 { color: #e2e2e2 !important; }
  h3 { color: #c8c8c8 !important; }

  /* ── Tabs ── */
  button[data-baseweb="tab"] {
      background: transparent !important;
      border-bottom: 2px solid transparent !important;
      color: rgba(255,255,255,0.5) !important;
      font-weight: 500;
  }
  button[data-baseweb="tab"][aria-selected="true"] {
      border-bottom: 2px solid #00FF87 !important;
      color: #00FF87 !important;
      font-weight: 700;
  }

  /* ── Buttons ── */
  .stButton > button {
      transition: transform 0.15s ease, border-color 0.15s, color 0.15s;
  }
  .stButton > button:hover {
      border-color: #00FF87 !important;
      color: #00FF87 !important;
  }

  /* ── Inputs ── */
  .stSelectbox > div > div,
  .stNumberInput > div > div > input,
  .stTextInput > div > div > input {
      background: rgba(255,255,255,0.05) !important;
      border: 1px solid rgba(255,255,255,0.12) !important;
      border-radius: 6px !important;
      color: #e2e2e2 !important;
  }

  /* ── Dividers ── */
  hr { border-color: rgba(255,255,255,0.08) !important; }

  /* ── Hide Streamlit branding ── */
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Shared data loading (cached; every page reads from session_state) ──────────

@st.cache_data(ttl=4 * 3600, show_spinner="Loading player data...")
def load_player_universe(simulate_gw=None):
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players(), simulate_gw=simulate_gw)


@st.cache_data(ttl=4 * 3600, show_spinner=False)
def load_bootstrap():
    from data.fetchers.fpl_api import fetch_bootstrap
    return fetch_bootstrap()


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_fixtures():
    from data.fetchers.fpl_api import fetch_fixtures, fetch_bootstrap, get_fixtures_df
    bs = fetch_bootstrap()
    return get_fixtures_df(bootstrap=bs)


for _key in ("players_df", "bootstrap", "fixtures_df", "current_gw"):
    if _key not in st.session_state:
        st.session_state[_key] = None


# ── Sidebar branding ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='text-align:center;padding:12px 0 4px;'>"
        "<span style='font-size:28px;'>⚽</span>"
        "<div style='font-size:17px;font-weight:800;color:#00FF87;letter-spacing:-0.3px;'>FPL Analytics Hub</div>"
        "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-top:2px;'>Data-driven FPL</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        for _key in ("players_df", "bootstrap", "fixtures_df", "current_gw", "season_phase", "plan_gw", "simulating_gw"):
            st.session_state[_key] = None
        st.rerun()

    # Off-season sandbox · default on when the season is over so the "next
    # gameweek" planning tools (transfers, free hit, pick team) have fixtures.
    try:
        from data.fetchers.fpl_api import get_season_phase as _gsp
        _offseason = _gsp(load_bootstrap()).get("phase") == "offseason"
    except Exception:
        _offseason = False
    sim_gw39 = st.toggle(
        "🧪 Simulate GW39", value=_offseason, key="sim_gw39",
        help="Off-season sandbox: replays GW1's fixtures as a synthetic next "
             "gameweek so you can plan transfers, free hits and pick your team "
             "for the future. Turn off once the real season launches.",
    )

    _cache = Path("data/cache/fpl_bootstrap.json")
    if _cache.exists():
        _age = int((time.time() - _cache.stat().st_mtime) / 60)
        if _age < 2:
            _freshness, _fresh_color = "Just updated", "#00FF87"
        elif _age < 60:
            _freshness, _fresh_color = f"{_age}m ago", "#00FF87"
        else:
            _freshness, _fresh_color = f"~{_age // 60}h ago · refresh", "#FFA500"
        st.markdown(
            f"<div style='text-align:center;font-size:11px;color:{_fresh_color};"
            f"padding:4px 0 8px;'>Data: {_freshness}</div>",
            unsafe_allow_html=True,
        )


# ── Load data into session_state (shared by all pages) ─────────────────────────
try:
    _sim = 39 if st.session_state.get("sim_gw39") else None
    bs          = load_bootstrap()
    players_df  = load_player_universe(_sim)
    fixtures_df = load_fixtures()

    st.session_state.players_df  = players_df
    st.session_state.bootstrap   = bs
    st.session_state.fixtures_df = fixtures_df
    st.session_state.simulating_gw = _sim

    # current_gw stays REAL (for fetching the user's actual squad picks). The
    # simulation only changes the universe's fixtures · plan_gw is the display
    # target for the "next gameweek" tools.
    from data.fetchers.fpl_api import get_current_gameweek, get_season_phase
    st.session_state.current_gw = get_current_gameweek(bs)
    st.session_state.plan_gw = _sim if _sim else st.session_state.current_gw
    st.session_state.season_phase = get_season_phase(bs)
except Exception as e:  # noqa: BLE001 · surface any load failure to the UI
    st.error(f"Failed to load data: {e}")
    st.info("Check your internet connection and try **🔄 Refresh Data**.")


# ── Grouped navigation · 5 sidebar sections (was 20 pages / 6 groups) ──────────
# Overhaul Phase 1: collapse to 5 logical tabs. Captain stays under My Team until
# the unified timeline pitch absorbs captaincy; chips fold into Transfers; all
# analytics under Analysis; the season-long tools under Season Lab.
nav = st.navigation({
    "Home": [
        st.Page("views/home.py",               title="Home",        icon=":material/home:", default=True),
    ],
    "My Team": [
        st.Page("views/00_my_team.py",          title="My Team",     icon=":material/groups:"),
        st.Page("views/06_captain_picker.py",   title="Captain",     icon=":material/military_tech:"),
    ],
    "Transfers": [
        st.Page("views/02_transfer_suggestions.py", title="Transfers",    icon=":material/swap_horiz:"),
        st.Page("views/03_transfer_planner.py",     title="Planner",      icon=":material/calendar_month:"),
        st.Page("views/07_buy_sell.py",             title="Buy / Sell",   icon=":material/payments:"),
        st.Page("views/09_wildcard.py",             title="Wildcard",     icon=":material/style:"),
        st.Page("views/13_free_hit.py",             title="Free Hit",     icon=":material/my_location:"),
        st.Page("views/14_chip_planner.py",         title="Chip Planner", icon=":material/casino:"),
    ],
    "Analysis": [
        st.Page("views/01_dashboard.py",           title="Dashboard",     icon=":material/dashboard:"),
        st.Page("views/04_differentials.py",       title="Differentials", icon=":material/diamond:"),
        st.Page("views/05_xg_underperformers.py",  title="xG Tracker",    icon=":material/bolt:"),
        st.Page("views/12_predictions.py",         title="Predictions",   icon=":material/insights:"),
        st.Page("views/10_ownership_trend.py",     title="Ownership",     icon=":material/trending_up:"),
        st.Page("views/08_injuries.py",            title="Injuries",      icon=":material/medical_services:"),
    ],
    "Season Lab": [
        st.Page("views/11_gw_history.py",     title="GW History",     icon=":material/history:"),
        st.Page("views/15_mini_league.py",    title="Mini-League",    icon=":material/leaderboard:"),
        st.Page("views/16_perfect_season.py", title="Perfect Season", icon=":material/emoji_events:"),
        st.Page("views/17_value_lab.py",      title="Value Lab",      icon=":material/science:"),
        st.Page("views/18_draft_2026_27.py",  title="26/27 Draft",    icon=":material/description:"),
        st.Page("views/19_playbook.py",       title="Playbook",       icon=":material/menu_book:"),
    ],
})

nav.run()
