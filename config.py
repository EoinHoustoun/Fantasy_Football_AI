"""
Central configuration for the FPL Analytics App.
All tunable weights, TTLs, thresholds, and API endpoints live here.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
CACHE_DIR = ROOT_DIR / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── FPL API ───────────────────────────────────────────────────────────────────
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_BOOTSTRAP  = f"{FPL_BASE}/bootstrap-static/"   # All players, teams, events
FPL_FIXTURES   = f"{FPL_BASE}/fixtures/"            # All fixtures
FPL_LIVE_GW    = f"{FPL_BASE}/event/{{gw}}/live/"  # Live GW points
FPL_TEAM       = f"{FPL_BASE}/entry/{{team_id}}/event/{{gw}}/picks/" # User picks
FPL_TRANSFERS  = f"{FPL_BASE}/entry/{{team_id}}/transfers/"
FPL_MY_TEAM    = f"{FPL_BASE}/my-team/{{team_id}}/"

# ── Cache TTLs (seconds) ──────────────────────────────────────────────────────
CACHE_TTL = {
    "fpl_bootstrap": 4 * 3600,      # 4 hours
    "fpl_fixtures":  24 * 3600,     # 24 hours
    "fpl_live":      30 * 60,       # 30 min (match days)
    "understat":     24 * 3600,     # 24 hours
    "fbref":         48 * 3600,     # 48 hours
    "ffhub":         6 * 3600,      # 6 hours
}

# ── User credentials (from .env) ──────────────────────────────────────────────
FPL_TEAM_ID   = os.getenv("FPL_TEAM_ID")
FPL_EMAIL     = os.getenv("FPL_EMAIL")
FPL_PASSWORD  = os.getenv("FPL_PASSWORD")
FFH_EMAIL     = os.getenv("FFH_EMAIL")
FFH_PASSWORD  = os.getenv("FFH_PASSWORD")

# ── Fixture Difficulty ────────────────────────────────────────────────────────
# How many upcoming gameweeks to show in fixture tickers
FIXTURE_LOOKAHEAD = 6

# ── Transfer Scoring Weights ──────────────────────────────────────────────────
# These weights drive the transfer suggestion engine.
# Tune these after each gameweek based on what's working.
TRANSFER_WEIGHTS = {
    "form":              0.25,   # Recent points form (last 4 GWs)
    "fixture_ease":      0.25,   # Average FDR of next N fixtures
    "xg_potential":      0.20,   # xG-based upside (Understat)
    "value":             0.15,   # Points per million (PPM)
    "ownership_trend":   0.10,   # Rising ownership = captain/template risk
    # minutes_security removed — minutes is now a score MULTIPLIER, not additive
    # set_piece bonus is computed directly in transfer_engine.py (+0.08 for pen#1, etc.)
}

# ── Differentials ─────────────────────────────────────────────────────────────
# Max ownership % to qualify as a differential pick
DIFFERENTIAL_MAX_OWNERSHIP = 10.0  # %

# ── xG Underperformers ────────────────────────────────────────────────────────
# Minimum xG accumulated before flagging underperformance
XG_MIN_THRESHOLD = 2.0
# Minimum xG-to-actual-goals gap to be considered underperforming
XG_GAP_THRESHOLD = 1.5

# ── Positions ─────────────────────────────────────────────────────────────────
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# ── FPL Scoring System ────────────────────────────────────────────────────────
# Goal points by position
FPL_GOAL_PTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
# Clean sheet points by position
FPL_CS_PTS   = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
# Shared
FPL_ASSIST_PTS = 3
FPL_BONUS_MAX  = 3
FPL_MINUTES_PTS = 2  # awarded for 60+ minutes played

# "Haul" = single game score that qualifies as special
HAUL_THRESHOLD  = 15   # pts — flagged as haul candidate
TWENTY_PLUS_THRESHOLD = 20  # pts — flagged as 20+ capable

# Transfer recommendation: if top 3 scores are within this margin, show all 3
TRANSFER_CLOSE_MARGIN = 0.04

# ── UI ────────────────────────────────────────────────────────────────────────
APP_TITLE     = "FPL Analytics Hub"
ACCENT_COLOR  = "#00FF87"   # FPL green
DANGER_COLOR  = "#FF4B4B"
WARNING_COLOR = "#FFA500"
