"""
FPL Analytics Hub — Main Streamlit App.

Entry point. Run with:
    streamlit run app.py
"""

import streamlit as st
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="FPL Analytics Hub",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
      font-size: 0.8rem !important;
      color: rgba(255,255,255,0.5) !important;
      text-transform: uppercase;
      letter-spacing: 0.05em;
  }
  [data-testid="stMetricDelta"] { font-size: 0.8rem !important; }

  /* ── Headings ── */
  h1 { color: #00FF87 !important; letter-spacing: -0.5px; }
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
      background: transparent;
      border: 1px solid rgba(255,255,255,0.2);
      color: #e2e2e2;
      border-radius: 6px;
      font-weight: 500;
      transition: border-color 0.15s, color 0.15s;
  }
  .stButton > button:hover {
      border-color: #00FF87 !important;
      color: #00FF87 !important;
  }
  .stButton > button[kind="primary"] {
      background: #00FF87 !important;
      border-color: #00FF87 !important;
      color: #000 !important;
      font-weight: 700;
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

  /* ── Dataframes ── */
  .stDataFrame { border-radius: 8px; overflow: hidden; }
  [data-testid="stDataFrame"] th {
      background: rgba(0,255,135,0.08) !important;
      color: #00FF87 !important;
      font-size: 0.78rem !important;
      text-transform: uppercase;
      letter-spacing: 0.06em;
  }

  /* ── Page link nav items ── */
  [data-testid="stPageLink"] a {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 14px;
      border-radius: 8px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      text-decoration: none !important;
      color: #e2e2e2 !important;
      font-size: 0.88rem;
      transition: background 0.15s, border-color 0.15s;
      margin-bottom: 4px;
  }
  [data-testid="stPageLink"] a:hover {
      background: rgba(0,255,135,0.08) !important;
      border-color: rgba(0,255,135,0.3) !important;
      color: #00FF87 !important;
  }

  /* ── Expander ── */
  details { border: 1px solid rgba(255,255,255,0.08) !important; border-radius: 8px !important; }

  /* ── Success / warning / error banners ── */
  [data-testid="stAlert"] { border-radius: 8px !important; }

  /* ── Dividers ── */
  hr { border-color: rgba(255,255,255,0.08) !important; }

  /* ── Hide Streamlit branding ── */
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Shared data loading (cached, all pages can read from session_state) ────────

@st.cache_data(ttl=4 * 3600, show_spinner="Loading player data...")
def load_player_universe():
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


@st.cache_data(ttl=4 * 3600, show_spinner=False)
def load_bootstrap():
    from data.fetchers.fpl_api import fetch_bootstrap
    return fetch_bootstrap()


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_fixtures():
    from data.fetchers.fpl_api import fetch_fixtures, fetch_bootstrap, get_fixtures_df
    bs = fetch_bootstrap()
    return get_fixtures_df(bootstrap=bs)


for key in ("players_df", "bootstrap", "fixtures_df"):
    if key not in st.session_state:
        st.session_state[key] = None


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='text-align:center;padding:12px 0 4px;'>"
        "<span style='font-size:28px;'>⚽</span>"
        "<div style='font-size:17px;font-weight:800;color:#00FF87;letter-spacing:-0.3px;'>FPL Analytics Hub</div>"
        "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-top:2px;'>Data-driven FPL decisions</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Refresh + data freshness
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.players_df = None
        st.rerun()

    _cache = Path("data/cache/fpl_bootstrap.json")
    if _cache.exists():
        _age = int((time.time() - _cache.stat().st_mtime) / 60)
        if _age < 2:
            freshness, fresh_color = "Just updated", "#00FF87"
        elif _age < 60:
            freshness, fresh_color = f"{_age}m ago", "#00FF87"
        else:
            freshness, fresh_color = f"~{_age // 60}h ago — refresh", "#FFA500"
        st.markdown(
            f"<div style='text-align:center;font-size:11px;color:{fresh_color};"
            f"padding:4px 0 8px;'>Data: {freshness}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Live GW stats (loaded once data is available)
    if st.session_state.get("bootstrap"):
        from data.fetchers.fpl_api import get_current_gameweek
        _gw = get_current_gameweek(st.session_state.bootstrap)
        st.markdown(
            f"<div style='text-align:center;padding:8px 0;'>"
            f"<div style='font-size:11px;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.1em;'>Current Gameweek</div>"
            f"<div style='font-size:32px;font-weight:900;color:#00FF87;line-height:1.1;'>GW{_gw}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

    st.caption("v0.5 · FPL Analytics Hub")


# ── Load data ──────────────────────────────────────────────────────────────────
try:
    with st.spinner("Loading data..."):
        bs          = load_bootstrap()
        players_df  = load_player_universe()
        fixtures_df = load_fixtures()

    st.session_state.players_df  = players_df
    st.session_state.bootstrap   = bs
    st.session_state.fixtures_df = fixtures_df

    from data.fetchers.fpl_api import get_current_gameweek
    current_gw = get_current_gameweek(bs)
    n_players  = len(players_df)

except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.info("Check your internet connection and try Refresh.")
    raise


# ── Hero banner ────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='padding:32px 0 8px;'>"
    "<div style='font-size:38px;font-weight:900;color:#00FF87;letter-spacing:-1px;line-height:1;'>FPL Analytics Hub</div>"
    "<div style='font-size:16px;color:rgba(255,255,255,0.45);margin-top:8px;'>Data-driven decisions for your Fantasy Premier League team.</div>"
    "</div>",
    unsafe_allow_html=True,
)

# ── Live stats strip ───────────────────────────────────────────────────────────
top_form    = players_df.nlargest(1, "form").iloc[0]
top_xfer_in = players_df.nlargest(1, "transfers_in_event").iloc[0]
n_injured   = (players_df["status"] == "i").sum()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Gameweek",           f"GW {current_gw}")
m2.metric("Players Loaded",     f"{n_players:,}")
m3.metric("Best Form",          top_form["web_name"],          f"{top_form['form']:.1f} pts/game")
m4.metric("Most Transferred In",top_xfer_in["web_name"],       f"+{top_xfer_in['transfers_in_event']:,}")

st.markdown("---")


# ── Feature card grid ──────────────────────────────────────────────────────────
st.markdown("### Navigate to a tool")

PAGES = [
    # (emoji, title, description, file)
    ("👤", "My Team",            "Your squad, pitch view, sell candidates & captain pick",   "pages/00_my_team.py"),
    ("🏆", "Captain Picker",     "Who to captain this GW — squad picks & differentials",     "pages/06_captain_picker.py"),
    ("💰", "Buy / Sell",         "Sell X → Buy Y pairings with projected pts gain",          "pages/07_buy_sell.py"),
    ("🚑", "Injuries",           "Squad & league availability tracker with live news",        "pages/08_injuries.py"),
    ("🔄", "Transfer Suggestions","#1 transfer pick with reasoning, Free Hit & season view", "pages/02_transfer_suggestions.py"),
    ("📅", "GW History",         "Your score vs the global average every gameweek",           "pages/11_gw_history.py"),
    ("📊", "Dashboard",          "GW snapshot, avg pts by position & value scatter",         "pages/01_dashboard.py"),
    ("📈", "Ownership Trend",    "Rising & falling players across the season",                "pages/10_ownership_trend.py"),
    ("🗓️",  "Transfer Planner",  "Multi-week fixture difficulty planner",                    "pages/03_transfer_planner.py"),
    ("🃏", "Wildcard Planner",   "Best remaining GW to play your Wildcard chip",             "pages/09_wildcard.py"),
    ("💎", "Differentials",      "Low-ownership picks with high upside",                     "pages/04_differentials.py"),
    ("⚡", "xG Tracker",         "Players underperforming their xG — due a big score",       "pages/05_xg_underperformers.py"),
    ("🤖", "Predictions",        "XGBoost model: predicted pts per player with RMSE",        "pages/12_predictions.py"),
    ("🎯", "Free Hit",           "Optimal 15-man squad + position vs position comparison",   "pages/13_free_hit.py"),
    ("🎰", "Chip Planner",       "Best GW to play Bench Boost & Triple Captain",             "pages/14_chip_planner.py"),
    ("🏅", "Mini-League",        "Every manager's season journey on one chart",              "pages/15_mini_league.py"),
]

CARD_COLORS = [
    "#00FF87", "#FFD700", "#04f5ff", "#FF4B4B",
    "#00FF87", "#04f5ff", "#e90052", "#ff6900",
    "#00FF87", "#FFD700", "#04f5ff", "#e90052",
    "#c084fc", "#f5c518",
    "#FFD700", "#04f5ff",
]

cols = st.columns(4)
for i, (emoji, title, desc, path) in enumerate(PAGES):
    col = cols[i % 4]
    accent = CARD_COLORS[i]
    with col:
        st.markdown(
            f"""<div style="
                background:rgba(255,255,255,0.03);
                border:1px solid rgba(255,255,255,0.08);
                border-top: 3px solid {accent};
                border-radius:10px;
                padding:16px 16px 12px;
                margin-bottom:4px;
                min-height:90px;
            ">
              <div style="font-size:22px;margin-bottom:6px;">{emoji}</div>
              <div style="font-size:14px;font-weight:700;color:#fff;margin-bottom:4px;">{title}</div>
              <div style="font-size:12px;color:rgba(255,255,255,0.4);line-height:1.4;">{desc}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.page_link(path, label=f"Open {title} →", use_container_width=True)

st.markdown("---")


# ── Quick form leaders ─────────────────────────────────────────────────────────
st.markdown("### In-Form Players Right Now")
st.caption("Highest form score across all positions this week.")

top10 = players_df.nlargest(10, "form")[[
    "web_name", "team", "position", "price", "ownership", "form", "total_points", "points_per_million"
]].copy()

from components.player_table import render_player_table
render_player_table(top10, highlight_col="Form")
