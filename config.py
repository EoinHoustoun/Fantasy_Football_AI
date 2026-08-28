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

# Off-season sandbox: how many future gameweeks to simulate (GW1..N replayed as
# GW39..38+N). The My Team planner scrubs through these to plan transfers week
# by week, banking free transfers when a week is skipped.
SIM_HORIZON = 5

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

# Value-verdict engine (analytics/value_verdicts.py). Buckets each player by
# comparing projected points (from the 2025/26 archive) against their ACTUAL
# 2026/27 launch price. `pricing_surprise` = predicted price − actual price:
# positive means FPL priced them below the model (a bargain), negative a tax.
# All thresholds are per-position percentiles unless noted (0-1 fractions).
VALUE_VERDICTS = {
    "necessity_pts_pctile": 0.85,     # genuinely top-tier projected points, AND
    "necessity_ownership": 25.0,      # template ownership (%) · everyone has them
    "value_pts_floor_pctile": 0.40,   # a "value" pick must clear this pts floor
    "value_score_pctile": 0.75,       # strong points-per-actual-£m at position
    "value_surprise_m": 0.5,          # OR FPL priced >= this much below model
    "premium_price": 7.5,             # a pricey anchor · value must justify it
    "premium_value_pctile": 0.55,     # premium with value <= this pctile = tax
    "pedigree_pts_pctile": 0.70,      # "was good last year" (top-30% 25/26 points)
    "pedigree_min_price": 6.0,        # and still priced up, but value not there
}

# Manual projection overrides (analytics/projection_overrides.py). Facts a model
# can't derive · fitness, role, regression · live in
# assets/player_overrides_2026_27.json. These are the minutes a bare
# "nailed"/"benched" flag maps to when no explicit minutes are given.
PROJECTION_OVERRIDE = {"nailed_minutes": 3100, "bench_minutes": 200}

# Projection confidence (analytics/projection_confidence.py). How much to trust a
# projected-points number, driven by last season's minutes sample and whether a
# manual override (an assumption) was applied. `spread` is the +/- fraction used
# to turn a point estimate into an honest range per tier.
PROJECTION_CONFIDENCE = {
    "high_minutes": 2500,     # near a full season · reliable rate
    "medium_minutes": 1500,   # partial season
    "spread": {"High": 0.18, "Medium": 0.30, "Low": 0.45},
}

# Chip timing (analytics/chip_timing.py). 2026/27 gives two of every chip; the
# FIRST batch (WC/FH/BB/TC) must be spent by GW19, so the first-half planner only
# scans GW1-19. A player's per-GW points = season projection / 38, scaled by that
# week's fixture ease (`fdr_slope` per FDR step from average); a blank scores 0,
# a double stacks both fixtures.
CHIP_TIMING = {
    "first_batch_gw_hi": 19,
    "fdr_slope": 0.15,        # each FDR step easier than 3 adds 15%
    "factor_floor": 0.4,      # hardest fixtures still score something
}

# Opening-fixtures weighting for the draft. With one free transfer a week and the
# first wildcard usually gone by ~GW10, a squad that holds up over the opening
# run needs fewer early moves. `opening_factor` per player = mean fixture ease
# over GW1..gw_hi; the draft can lean on it via a slider.
OPENING_FIXTURES = {"gw_hi": 6, "fdr_slope": 0.28, "factor_floor": 0.4}

# Season Opener · the early chip route. An early Bench Boost and an early
# Wildcard are ONE decision, not two: a Bench Boost needs fifteen playing assets,
# which dilutes the XI every week you carry it, and the Wildcard is what repairs
# the dilution. `bench_price_cap` is what a cheap-bench manager actually fields,
# `min_bench_mins` is the minutes floor that makes a bench player Boost-worthy.
SEASON_OPENER = {
    "opening_window": (1, 6),      # the run the draft is built for
    "swing_early": (1, 6),         # ease before the swing
    "swing_late": (7, 12),         # ease after it
    "min_bench_mins": 2000,        # a BB bench player must genuinely start
    "bench_price_cap": 4.5,        # what real cheap-bench fodder costs
    "season_gws": 38.0,            # season totals are spread over this
}

# Chip routes compared side by side. BB1+WC5 is kept deliberately even though the
# break-even maths says it loses · seeing it rank last is more convincing than
# asserting it. `bb_gw` None means no early Bench Boost.
CHIP_ROUTES = [
    {"label": "BB GW1 · WC GW3", "bb_gw": 1, "wc_gw": 3},
    {"label": "BB GW2 · WC GW4", "bb_gw": 2, "wc_gw": 4},
    {"label": "BB GW1 · WC GW5", "bb_gw": 1, "wc_gw": 5},
    {"label": "No early BB · WC GW7", "bb_gw": None, "wc_gw": 7},
    {"label": "No early BB · WC GW10", "bb_gw": None, "wc_gw": 10},
]

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

# ── Experimental points model · SANDBOXED, off by default ────────────────────
# `analytics/component_model.py` predicts the countable events (minutes, goals,
# assists, clean sheets, bonus, defensive contribution) and adds them up with the
# scoring table, instead of regressing the points total directly the way
# `analytics/points_model.py` does.
#
# It stays behind this flag until it beats the incumbent in the walk-forward
# benchmark AND Eoin has approved the swap. Turn it on for a session with
# FF_COMPONENT_MODEL=1 in the environment, never by editing the default here.
#
#   FF_COMPONENT_MODEL=1 streamlit run app.py --server.port 8510
#   python3 scripts/benchmark_points_models.py            # the evidence
COMPONENT_MODEL = {
    "enabled": os.getenv("FF_COMPONENT_MODEL", "0") == "1",
    # Seasons the model may train on. More history is the point of it, but a
    # rule change makes old seasons a different game · the benchmark reports
    # per-season so the cut can be argued from evidence.
    "train_seasons": 10,
    # Minimum career appearances before a player gets a prediction. Below this
    # the rolling features are mostly empty and the number is a guess.
    "min_career_games": 3,
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
    "COV": ("#6CADDF", "#0E1B3D"),   # Coventry City
    "CRY": ("#1B458F", "#C4122E"),   # Crystal Palace
    "EVE": ("#003399", "#FFFFFF"),   # Everton
    "FUL": ("#000000", "#FFFFFF"),   # Fulham
    "HUL": ("#F5A12D", "#000000"),   # Hull City
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

# ── 26/27 Draft page ──────────────────────────────────────────────────────────
# Tunables that were literals scattered through views/18_draft_2026_27.py. The
# project rule is that every weight, threshold and scoring constant lives here.
DRAFT_UI = {
    # Pool table · how many rows at a time, and how deep it will go.
    "pool_page": 22,
    # Below this season projection a player is noise in a comparison, not a
    # candidate. Used to keep the grading baselines honest.
    "pool_floor_points": 40.0,
    # Price band either side of a player when building his peer group.
    "price_band": 0.6,
    # Percentile cuts for a graded stat · good, then fair, then poor.
    "grade_good": 0.90,
    "grade_fair": 0.67,
    # XI points a set of locks may cost before the conviction reads as
    # expensive. Negative because it is a cost against the free optimum.
    "conviction_free": -12.0,
    "conviction_real": -35.0,
    # A full season of minutes · 38 x 90.
    "season_minutes": 3420.0,
}

# Bar maxima were hardcoded at 190 / 32 / 110 and will drift as prices and
# projections move. Derived from the board at render time where possible; these
# are the floors so a sparse board cannot produce a meaningless full-width bar.
DRAFT_BAR_FLOORS = {"season": 120.0, "per_m": 20.0, "gap": 60.0}

# ── Bench Boost ───────────────────────────────────────────────────────────────
# What a boosted bench should actually return in the week you play it. Eoin's
# call, and it is a sensible one: a bench is four players, so 15 is roughly
# every one of them starting and returning a normal score. Below 14 the chip is
# being spent on fodder; above 18 it is a genuinely strong week to spend it.
#
# The caveat matters as much as the target: a bench good enough to boost costs
# XI strength every week you carry it, so these are read ALONGSIDE what the
# playing bench costs the starting eleven, never on their own.
BENCH_BOOST = {
    "target": 15.0,        # what we are aiming for
    "acceptable": 14.0,    # will take it
    "strong": 18.0,        # a good week to play the chip
    "weak": 11.0,          # below this the chip is close to wasted
}


# ── What a NEW draft starts as ────────────────────────────────────────────────
# The New draft button used to clone whatever draft you were on, which meant a
# fresh start inherited whatever you had been fiddling with. These are Eoin's
# standing opening assumptions for 2026-27, so a new draft begins from the plan
# he is actually working to rather than from the last experiment.
#
# `cover` is by team SHORT code, resolved to a live team_id at build time · club
# ids are reassigned between seasons and a hardcoded integer would silently
# point at a different club.
NEW_DRAFT_DEFAULTS = {
    "bench_boost_gw": 1,
    # A Wildcard at GW4 is what makes the objective GW1-3 · the draft page
    # derives the optimisation window from this, so it is the only thing that
    # needs setting for "optimise for the first three gameweeks".
    "wildcard_gw": 4,
    # RESET 2026-08-16, Eoin's words: "haaland and fernandes and mbeumo in,
    # thats rules". Everything else is expressed as vetoes below · the old
    # bench locks (Kinsky, Le Fée, Ballard, O'Shea, Maguire, Calvert-Lewin)
    # measured 1.4 pts against the free optimum and were dropped. Fernandes
    # was re-examined the same evening: the spread draft beats him by 0.9 in
    # the solver but only 51.5/48.5 in the Monte Carlo · a coin flip at ~48%
    # ownership means own the template.
    # João Pedro added 2026-08-16 late: 57.9% owned (higher than Fernandes),
    # tearing up preseason, and Eoin called him "a likely guy we will need" ·
    # the same own-the-template logic that closed the Fernandes question.
    "locks": ["Haaland", "B.Fernandes", "Mbeumo", "João Pedro (Joao Pedro)"],
    # "I should have a minimum of one for Arsenal" (defensive cover · GKP+DEF
    # count toward it), and only Gabriel, Raya or Mosquera may fill it · the
    # other Arsenal defensive names are vetoed below. Mosquera's minutes rest
    # on Saliba's back injury (status 'i', no return date, checked 16 Aug).
    "cover": (("ARS", "def", 1),),
    # "I don't want three Sunderland players" · at most two from SUN, on top
    # of FPL's own three-per-club limit. By club SHORT code, resolved to a
    # live team id at build time like `cover`.
    "max_from_club": (("SUN", 2),),
    # "Max one Brighton midfielder" (2026-08-16, after a Groß+Gomez+Verbruggen
    # triple appeared). Implemented as the attack-correlation cap scoped to
    # BHA alone: at most ONE Brighton MID/FWD, every other club exempt. The
    # keeper and defenders are untouched · their points ride clean sheets,
    # not the attack.
    "cap_attackers": True,
    "max_defenders_per_club": None,
    "attack_cap_exempt": ("ARS", "AVL", "BOU", "BRE", "CHE", "COV", "CRY",
                          "EVE", "FUL", "HUL", "IPS", "LEE", "LIV", "MCI",
                          "MUN", "NEW", "NFO", "SUN", "TOT"),
    # The price-band rules are OFF · the 2026-08-16 veto list bans the fodder
    # tiers BY NAME instead (Eoin's list, applied verbatim plus Davis). Two
    # consequences worth remembering: a new cheap signing next month is NOT
    # covered the way a band rule would cover him, and Georginio (BHA) is the
    # only sub-£6.0 forward left in the game, so he is picked by elimination.
    "ban_price_bands": (),
    "price_band_exempt": (),
    "min_price_by_position": {},
    # Only ever ONE £4.0m defender · reinstated 2026-08-16 after banning Davis
    # by name simply produced Diop, the next £4.0m Ipswich body. The band rule
    # ends the whack-a-mole a name list has to play forever.
    "max_price_band": (("DEF", 4.0, 1),),
    # Eoin only captains a penalty taker. Enforced inside the MILP.
    "captain_must_take_pens": True,
    # 2026-08-16 · Eoin's list, 140 names, cost measured at 0.7 pts against
    # the unrestricted optimum (only Collins, Simms, Kadıoğlu, N.Williams,
    # Dewsbury-Hall and Wieffer were ever solver picks; Davis added after
    # review). Kadıoğlu's old £4.5-band exemption is dead · he is banned.
    "vetoes": [
        "Shaw", "McBurnie", "Evanilson", "Damsgaard", "Kostoulas",
        "Caicedo", "Brobbey", "Gvardiol", "Xhaka", "Dewsbury-Hall",
        "Bruno G.", "Thiaw", "Watkins", "Kudus", "Semenyo",
        "Doku", "Thiago", "Richarlison", "Collins", "Osula",
        "Woltemade", "Angulo", "Zambrano", "Muniz", "Iwobi",
        "Hirst", "Beto", "Sarr", "Saka", "Slater",
        "Alderete", "Maatsen", "Kelleher", "Crooks", "Acheampong",
        "Aina", "Anselmino", "B.Badiashile", "Bassey", "Bogle",
        "Bornauw", "Boscagli", "Cardines", "Cash", "Castagne",
        "Chadi Riad", "Coppola", "Costinha", "De Cuyper", "Digne",
        "Disasi", "Dunk", "Gudmundsson", "Hato", "Heaven",
        "Henry", "Hickey", "Igor", "J.Araujo", "J.Cuenca",
        "Jair Cunha", "Ji-soo", "Justin", "Kayode", "Konsa",
        "Lewis", "Lindelöf (Lindelof)", "M.Sarr", "Mazraoui", "Meunier",
        "Mings", "Mingueza", "Mitchell", "Mykolenko", "Netz",
        "Patterson (EVE)", "Pau", "Phillips (TOT)", "Pinnock", "Reinildo",
        "Robertson", "Robinson", "Rodon", "Sanchez", "Savona",
        "Schuster", "Seelt", "Sessegnon", "Smith", "Sosa",
        "Spence", "Tete", "Tomiyasu", "Tosin", "Udogie",
        "Vitor Reis", "Abraham", "Akpom", "Al-Hamadi", "Awoniyi",
        "Barry", "Burstow", "Danns", "Delap", "Destan",
        "Emegha", "Emersonn", "Enes Ünal (Enes Unal)", "Ferguson", "Furo",
        "Isidor", "Kalimuendo", "Kusi-Asare", "Madjo", "Marc Guiu",
        "Markelo", "Mateo Joseph", "Mheuka", "Neave", "Nketiah",
        "Nmecha", "Obi", "Piroe", "Scarlett", "Simms",
        "Thomas-Asante", "Tzimas", "Uche", "Walle Egeli", "Wilson (BRE)",
        "Wright", "Zirkzee", "Wieffer", "Ajer", "F.Kadıoğlu (F.Kadioglu)",
        "N.Williams", "Bijol", "Röhl (Rohl)", "Dalot", "Davis", "O'Brien",
        "Arrizabalaga", "Calafiori", "Hincapie", "J.Timber", "White",
        # Keeper allowlist 2026-08-16: only Kinsky, Raya and Lammens are
        # allowed in goal · every other keeper on the board is vetoed.
        # Ibrahim Sangaré (NFO) banned the same evening; the BRE Sangaré
        # (Mamadou) stays available.
        "A.Becker", "Austin", "Bayindir", "Benitez",
        "Bettinelli", "Butland", "Button", "Cartwright",
        "Darlow", "Davies (LIV)", "Dennis", "Donnarumma",
        "Dovin", "Dubravka", "Ellborg", "Forster",
        "Gillespie", "Heaton", "Henderson (CRY)", "Horníček (Hornicek)",
        "Jaouen", "Jaros", "John", "Jörgensen (Jorgensen)",
        "King (EVE)", "Lecomte", "Leno", "Lo-Tutala",
        "M.Bizot", "Mamardashvili", "Martinez (AVL)", "Matthews",
        "McNally", "Meslier", "Palmer (IPS)", "Patterson (SUN)",
        "Pecsi", "Penders", "Perri", "Petrović (Petrovic)",
        "Phillips (HUL)", "Pickford", "Pope", "Roefs",
        "Rulli", "Rushworth", "Scherpen", "Sels",
        "Steele", "Sánchez (Sanchez)", "Trafford", "Travers",
        "Tzolakis", "Valdimarsson", "Van Oevelen", "Verbruggen",
        "Vicario", "Walton", "Wilson (COV)", "Woodman",
        "Sangaré (NFO) (Sangare)",
    ],
}
