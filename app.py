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
from ui.theme import inject_theme, theme_toggle
inject_global_animations()
inject_theme()   # elevated design system (depth/glass/glow) · see docs/OVERHAUL_PLAN.md

# Global CSS, metrics, tabs, controls and the sidebar all live in ui/theme.py
# now, so they can switch with the palette. Do not re-add a hard-coded block
# here · it would fight light mode at equal specificity.

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
        "<div style='padding:10px 4px 2px;'>"
        "<div class='ff-display' style='font-size:24px;font-weight:900;letter-spacing:-0.6px;"
        "color:var(--ff-side-ink);line-height:1;'>FPL <span style='color:var(--ff-side-accent);'>Hub</span></div>"
        "<div style='font-size:12px;color:var(--ff-side-muted);margin-top:4px;'>One engine · every decision</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    theme_toggle(st)
    st.markdown("---")

    if st.button("Refresh data", icon=":material/refresh:", use_container_width=True):
        st.cache_data.clear()
        for _key in ("players_df", "bootstrap", "fixtures_df", "current_gw", "season_phase", "plan_gw", "simulating_gw"):
            st.session_state[_key] = None
        st.rerun()

    # Off-season sandbox · only OFFERED while the season is over, and it
    # auto-disappears (forced off) the moment the new season's fixtures are
    # live, so nothing plans against synthetic gameweeks by accident.
    try:
        from data.fetchers.fpl_api import get_season_phase as _gsp
        _offseason = _gsp(load_bootstrap()).get("phase") == "offseason"
    except Exception:
        _offseason = False
    if _offseason:
        sim_gw39 = st.toggle(
            "🧪 Simulate GW39", value=True, key="sim_gw39",
            help="Off-season sandbox: replays GW1-5's fixtures as synthetic "
                 "future gameweeks so the My Team planner, free hit and pick "
                 "team tools work. Disappears automatically at season launch.",
        )
    else:
        st.session_state.sim_gw39 = False

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
    # Every page reads the team from here. It used to be set only by Home, so a
    # page opened by URL (or by Claude) had no team and fell back to a blank.
    if not st.session_state.get("squad_team_id"):
        from config import FPL_TEAM_ID as _TID
        if _TID:
            st.session_state.squad_team_id = int(_TID)

    # The shared projection engine (analytics/brain) rebuilds once per finished
    # gameweek; start it early so the first page that needs it is instant.
    from analytics import brain as _brain
    _brain.warm_async(bs, players_df, fixtures_df)
except Exception as e:  # noqa: BLE001 · surface any load failure to the UI
    st.error(f"Failed to load data: {e}")
    st.info("Check your internet connection and try **🔄 Refresh Data**.")


# ── Navigation · four groups, fourteen pages (2026-09-27) ─────────────────────
# Grouped by intent: this week, planning ahead, research, what already happened.
# Merged away in the Floodlit overhaul: Buy/Sell and Differentials (Transfers'
# best moves and target board), Wildcard and Free Hit (the Chips page solves
# both squads on the engine), Predictions (the engine replaced its model).
# Streamlit's own nav lists every page under every header at once, so it is
# hidden and the rail builds an accordion with st.page_link instead.
PAGES = {
    "This week": [
        st.Page("views/home.py",                    title="Home",          icon=":material/home:", default=True),
        st.Page("views/00_my_team.py",              title="My Team",       icon=":material/groups:"),
        st.Page("views/06_captain_picker.py",       title="Captain",       icon=":material/military_tech:"),
        st.Page("views/02_transfer_suggestions.py", title="Transfers",     icon=":material/swap_horiz:"),
        st.Page("views/08_injuries.py",             title="Injuries",      icon=":material/medical_services:"),
    ],
    "Plan": [
        st.Page("views/14_chip_planner.py",         title="Chips",         icon=":material/casino:"),
        st.Page("views/18_draft_2026_27.py",        title="Squad Builder", icon=":material/draw:"),
    ],
    "Research": [
        st.Page("views/05_xg_underperformers.py",   title="xG Tracker",    icon=":material/bolt:"),
        st.Page("views/10_ownership_trend.py",      title="Ownership",     icon=":material/trending_up:"),
        st.Page("views/17_value_lab.py",            title="Value Lab",     icon=":material/science:"),
        st.Page("views/19_playbook.py",             title="Playbook",      icon=":material/menu_book:"),
    ],
    "History": [
        st.Page("views/11_gw_history.py",           title="GW History",    icon=":material/history:"),
        st.Page("views/15_mini_league.py",          title="Mini-League",   icon=":material/leaderboard:"),
        st.Page("views/16_perfect_season.py",       title="Perfect Season", icon=":material/emoji_events:"),
    ],
}
CATEGORY_ICONS = {"This week": ":material/sports_soccer:", "Plan": ":material/event_note:",
                  "Research": ":material/insights:", "History": ":material/history:"}

nav = st.navigation(PAGES, position="hidden")

# Open the category the current page lives in, so a reload never collapses you
# out of where you are.
_current = getattr(nav, "title", None)
_home_cat = next((c for c, ps in PAGES.items()
                  if any(getattr(p, "title", None) == _current for p in ps)), "This week")
st.session_state.setdefault("nav_cat", _home_cat)

with st.sidebar:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    # Look anyone up from any page: the player sheet opens as a dialog.
    try:
        from ui.player_sheet import rail_search
        rail_search()
    except Exception:  # noqa: BLE001 · the search is a convenience, never a blocker
        pass
    for _cat, _pages in PAGES.items():
        _open = st.session_state["nav_cat"] == _cat
        if st.button(_cat, key=f"navcat_{_cat}", icon=CATEGORY_ICONS[_cat],
                     use_container_width=True,
                     type="primary" if _open else "secondary"):
            # Clicking the open one closes it · a category is a toggle.
            st.session_state["nav_cat"] = "" if _open else _cat
            st.rerun()
        if _open:
            for _pg in _pages:
                st.page_link(_pg, icon=None)

    # The deadline lives in the rail on every page · the one number that
    # matters wherever you are.
    try:
        from datetime import datetime, timezone
        _nx = next((e for e in (st.session_state.get("bootstrap") or {}).get("events", [])
                    if e.get("is_next")), None)
        if _nx:
            _dl = datetime.fromisoformat(_nx["deadline_time"].replace("Z", "+00:00"))
            _left = _dl - datetime.now(timezone.utc)
            _d, _h = _left.days, _left.seconds // 3600
            _txt = ("%dd %dh" % (_d, _h)) if _d >= 1 else ("%dh %dm" % (_h, (_left.seconds % 3600) // 60))
            _hot = _d < 1
            st.markdown(
                f"<div style='margin:18px 2px 4px;padding:12px 14px;border-radius:12px;"
                f"background:{'rgba(255,75,75,0.10)' if _hot else 'rgba(255,215,0,0.07)'};"
                f"border:1px solid {'var(--ff-red)' if _hot else 'rgba(255,215,0,0.30)'};'>"
                f"<div style='font-size:10px;font-weight:700;letter-spacing:0.16em;"
                f"text-transform:uppercase;color:var(--ff-side-muted);'>GW{_nx['id']} deadline</div>"
                f"<div class='ff-display ff-num' style='font-size:22px;font-weight:900;"
                f"color:{'var(--ff-red)' if _hot else 'var(--ff-gold)'};'>{_txt}</div></div>",
                unsafe_allow_html=True)
    except Exception:  # noqa: BLE001 · a clock is never worth an exception
        pass

nav.run()
