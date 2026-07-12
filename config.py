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
    # minutes_security removed · minutes is now a score MULTIPLIER, not additive
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
HAUL_THRESHOLD  = 15   # pts · flagged as haul candidate
TWENTY_PLUS_THRESHOLD = 20  # pts · flagged as 20+ capable

# Transfer recommendation: if top 3 scores are within this margin, show all 3
TRANSFER_CLOSE_MARGIN = 0.04

# ── Historical archive / Season Lab ──────────────────────────────────────────
ARCHIVE_SEASONS = [
    "2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
    "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
]
LAST_COMPLETE_SEASON = "2025-26"
NEXT_SEASON = "2026-27"

# Perfect Season (hindsight MILP) configuration
PERFECT_SEASON = {
    "season": LAST_COMPLETE_SEASON,
    "budget": 100.0,
    "squad_limits": {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3},
    "lineup_min":   {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1},
    "max_per_club": 3,
    "hit_cost": 4,
    "max_banked_ft": 5,          # 2025-26 rule: bank up to 5 free transfers
    # pool pruning: top-N by season points per position
    "pool_top_by_points": {"GKP": 12, "DEF": 35, "MID": 40, "FWD": 22},
    "pool_top_by_value": 10,     # per position, by pts per £m
    "pool_cheapest": 5,          # per position, by min in-season price
    # 2025-26 chip rules: one full set per half (H1 = GW1-19, H2 = GW20-38)
    "chip_halves": [(1, 19), (20, 38)],
    "solver_time_limit": 1800,   # seconds
    "solver_gap": 0.01,          # accept within 1% of proven optimum
}

# ── Local AI (Ollama) ─────────────────────────────────────────────────────────
# All AI features run against a local Ollama server · free, offline, private.
# The app stays fully usable when Ollama is off; AI is an enhancement layer that
# degrades to deterministic templates. Override the model with OLLAMA_MODEL in .env.
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")  # fast; mistral:latest for higher quality
OLLAMA_TIMEOUT = 60          # seconds per request (covers a cold model load on slower Macs)
AI_TEMPERATURE = 0.35        # low · factual, grounded briefings

# ── UI ────────────────────────────────────────────────────────────────────────
APP_TITLE     = "FPL Analytics Hub"
ACCENT_COLOR  = "#00FF87"   # FPL green
DANGER_COLOR  = "#FF4B4B"
WARNING_COLOR = "#FFA500"

# ── Club identity colours ─────────────────────────────────────────────────────
# (primary, secondary) hex per club, keyed by FPL team_short.
# Used by components/team_identity.py to tint fixtures, cards, and badges.
# User-editable each season · covers current + recently-promoted PL clubs so the
# map survives promotion/relegation without code changes. Unknown clubs fall
# back to the FPL green accent.
TEAM_COLORS = {
    "ARS": ("#EF0107", "#FFFFFF"),   # Arsenal
    "AVL": ("#670E36", "#95BFE5"),   # Aston Villa
    "BOU": ("#DA291C", "#000000"),   # Bournemouth
    "BRE": ("#E30613", "#FBB800"),   # Brentford
    "BHA": ("#0057B8", "#FFFFFF"),   # Brighton
    "BUR": ("#6C1D45", "#99D6EA"),   # Burnley
    "CHE": ("#034694", "#FFFFFF"),   # Chelsea
    "CRY": ("#1B458F", "#C4122E"),   # Crystal Palace
    "EVE": ("#003399", "#FFFFFF"),   # Everton
    "FUL": ("#000000", "#FFFFFF"),   # Fulham
    "IPS": ("#3A64A3", "#FFFFFF"),   # Ipswich
    "LEE": ("#FFCD00", "#1D428A"),   # Leeds
    "LEI": ("#003090", "#FDBE11"),   # Leicester
    "LIV": ("#C8102E", "#FFFFFF"),   # Liverpool
    "MCI": ("#6CABDD", "#FFFFFF"),   # Man City
    "MUN": ("#DA291C", "#FBE122"),   # Man Utd
    "NEW": ("#241F20", "#FFFFFF"),   # Newcastle
    "NFO": ("#DD0000", "#FFFFFF"),   # Nott'm Forest
    "SOU": ("#D71920", "#FFFFFF"),   # Southampton
    "TOT": ("#132257", "#FFFFFF"),   # Tottenham
    "WHU": ("#7A263A", "#1BB1E7"),   # West Ham
    "WOL": ("#FDB913", "#231F20"),   # Wolves
    "SUN": ("#EB172B", "#FFFFFF"),   # Sunderland
    "SHU": ("#EE2737", "#000000"),   # Sheffield Utd
    "LUT": ("#F78F1E", "#002D62"),   # Luton
    "WBA": ("#122F67", "#FFFFFF"),   # West Brom
    "NOR": ("#FFF200", "#00A650"),   # Norwich
    "MID": ("#E21C38", "#FFFFFF"),   # Middlesbrough
}
