# FPL Analytics App — Workflow & Current State

_Last updated: 2026-03-24 (session 6)_

## Project Summary
Building a Fantasy Premier League analytics web app (Streamlit + Python) for data-driven transfer, captain, and team selection decisions. Running on Python 3.8.

## How to Run
```bash
cd /home/eoin/Desktop/ML/FF
streamlit run app.py
# Opens at http://localhost:8501
# If port 8501 is in use:
streamlit run app.py --server.port 8502
```

## Current Phase
**Phase 1–3 complete ✅ — Full working app with 16 pages**

### Pages Built
| Page | File | Status |
|------|------|--------|
| My Team | `pages/00_my_team.py` | ✅ Live — pitch view (FPL shirts), squad table, sell candidates, captain pick, bench cost stat, transfer suggestions, points history |
| Dashboard | `pages/01_dashboard.py` | ✅ Updated — avg PPG by position (20% season filter), points-per-million scatter |
| Transfer Suggestions | `pages/02_transfer_suggestions.py` | ✅ Redesigned — #1 pick hero + reasoning, captain note, price alerts, owned-player filter, season outlook, haul/ceiling tab, Free Hit chip |
| Transfer Planner | `pages/03_transfer_planner.py` | ✅ Live — fixture difficulty grid |
| Differentials | `pages/04_differentials.py` | ✅ Live — low-ownership picks, bubble chart |
| xG Tracker | `pages/05_xg_underperformers.py` | ✅ Live — xG gap / haul potential |
| Captain Picker | `pages/06_captain_picker.py` | ✅ New — armband hero card, top 5 squad captains, top 5 differentials, score breakdown chart |
| Buy / Sell | `pages/07_buy_sell.py` | ✅ New — sell→buy pairing cards for every squad player, PPG gain, FDR improvement |
| Injuries | `pages/08_injuries.py` | ✅ New — squad alerts first, full league injury board grouped by status, team chart |
| Wildcard Planner | `pages/09_wildcard.py` | ✅ New — simulates optimal 15 for every remaining GW, recommends best wildcard week |
| Ownership Trend | `pages/10_ownership_trend.py` | ✅ New — season riser/faller charts, scatter, player search |
| GW History | `pages/11_gw_history.py` | ✅ New — your score vs global avg, fill above/below, rank chart, cumulative vs avg |
| Predictions | `pages/12_predictions.py` | ✅ New — Random Forest on GW-by-GW data; RMSE/MAE/R², per-position accuracy, predicted vs actual scatter, your squad predictions, model misses |
| Free Hit | `pages/13_free_hit.py` | ✅ New — XGBoost optimal 15-man squad within budget, position-by-position comparison vs user's team |
| Chip Planner | `pages/14_chip_planner.py` | ✅ New — Best GW to play Bench Boost & Triple Captain, hero cards, bar charts, squad preview per GW |
| Mini-League | `pages/15_mini_league.py` | ✅ New — Enter league ID, cumulative pts line chart, rank progression, GW-by-GW bars, standings cards, key moments |

### Next to Build (priority order)
- [ ] **Fantasy Football Hub integration** — per-GW AI predictions = biggest accuracy upgrade. Awaiting credentials.
- [ ] **FPL Scout set piece data** — penalty/corner takers → bonus weight for attackers.
- [ ] **Mini-league season line chart** — everyone's cumulative pts over the full season on one chart.
- [ ] **FBRef deep stats** — `pip install soccerdata` to activate — fetcher already built.

### Recently Completed (session 6)
- ✅ Minutes as multiplier — replaced additive `minutes_security * 0.05` term with `mins_multiplier = (avg_mins/90)^0.5` in both `transfer_engine.py` and `captain_picker.py`; uses DEFCON avg_mins (EWM-weighted) when available, falls back to `total_minutes / gws_played`; formula: 90min=1.0 · 75=0.91 · 60=0.82 · 45=0.71
- ✅ Set piece scoring fixed — replaced `== / <=` comparisons with `.eq()` / `.le()` to handle NaN safely; transfer engine weights: pen#1=+0.08, pen#2=+0.03, corners≤2=+0.02, FK≤2=+0.02; captain picker: pen#1=+0.10, pen#2=+0.04
- ✅ Badges component (`components/badges.py`) — `render_badges(player)` returns HTML pill badges for: ⚽ Pen #1, ⚽ Pen 2, 🎯 Corners, 🦶 FK, 🛡️ DEFCON Monster (≥0.35), ⚠️ Mins warning (<60)
- ✅ Badges wired into: Captain Picker hero + mini cards · Transfer Suggestions hero section + avg mins metric · Buy/Sell buy-side cards
- ✅ Dixon-Coles team ratings (`data/fetchers/dixon_coles.py`) — MLE model fitted on 1,069 matches (2023–26) with 16-week exponential decay; replaces raw FPL FDR in composite FDR formula; new blend: 50% DC + 50% Understat xGC/xGA; 24h cache
- ✅ Fixed `get_current_gameweek` bug — was returning the finished GW (`is_current=True, finished=True`) instead of the upcoming one; now returns `is_next` GW when current is finished, so all FDR/transfer/captain windows look forward correctly

### Recently Completed (session 5)
- ✅ Dashboard: avg PPG by position (20% season filter) + PPM value scatter
- ✅ Captain Picker (page 06): hero armband card, top 5 from squad, top 5 differentials, score breakdown
- ✅ Buy/Sell Pairing (page 07): sell→buy cards for each squad player, PPG/FDR/cost comparison
- ✅ Injury Tracker (page 08): squad alerts + full league board grouped by status
- ✅ Wildcard Planner (page 09): simulates optimal 15 per remaining GW, bar chart of opportunity
- ✅ Ownership Trend (page 10): season risers/fallers, scatter, player search, line charts
- ✅ GW History (page 11): your score vs global avg (fill above/below), rank progression, cumulative
- ✅ CLAUDE.md created at project root for auto-briefing

### Recently Completed (session 4)
- ✅ Fixed `matplotlib.colormaps` crash — upgraded matplotlib to 3.7.5 (`pip3 install --upgrade matplotlib`)
- ✅ Fixed `player_table.py` — replaced `background_gradient` (requires matplotlib ≥3.5) with `bar` (pure pandas)
- ✅ Fixed `attach_fixture_difficulty` KeyError — handles empty team_fdrs gracefully (defaults to 3.0)

### Recently Completed (session 3)
- ✅ Composite FDR: FDR (35%) + Understat xGC/xGA (65%), position-aware
- ✅ DGW/BGW detection: per-team, per-GW fixture counting; +15%/-25% score multipliers
- ✅ Rolling xGI: vaastav last 4 GWs, 2-pass name matching (~67% coverage)
- ✅ FPL Opta xG per90 fields added to player universe (always present, no fallback needed)
- ✅ Fixture ticker: DGW `2x` markers, BGW dark grey cells
- ✅ Transfer page: DGW/BGW callouts in hero section and top-3 cards
- ✅ Data freshness indicator in sidebar (shows minutes/hours since last refresh)

## Architecture
- **Framework**: Streamlit + Plotly
- **Python**: 3.8 — ALWAYS use `List`, `Union`, `Optional` from `typing`. Never `list[x]` or `dict[x]` syntax.
- **Data layer**: JSON file cache with TTL (no database). Two-layer cache: file on disk + Streamlit in-memory (`@st.cache_data`). Both layers TTL at same interval so they expire together.
- **Analytics**: Pure Python modules in `analytics/` — no Streamlit imports, fully testable
- **Config**: All weights, TTLs, thresholds, and scoring constants in `config.py` — tune here after each GW

## Data Sources
| Source | What | Status |
|--------|------|--------|
| FPL Public API | Prices, ownership, fixtures, GW stats, squad picks, Opta xG per90 | ✅ Working |
| Understat | Player xG/xA, team xGC/xGA (last 6 games, async, 6h cache) | ✅ Integrated |
| vaastav GitHub | Rolling xGI last 4 GWs per player (GW-level data) | ✅ Integrated — wired into player universe |
| football-data.co.uk | Historical PL results 2023–26 for Dixon-Coles team ratings | ✅ Integrated — `data/fetchers/dixon_coles.py` |
| FBRef | Progressive passes/carries, key passes | 🔧 Fetcher built — `pip install soccerdata` to activate |
| Fantasy Football Hub | Premium stats | ⏳ Awaiting credentials |

## Data Freshness
- FPL bootstrap (players, prices, form): auto-refreshes every **4 hours**
- Fixtures: auto-refreshes every **24 hours**
- Understat player xG: auto-refreshes every **24 hours**
- Understat team xGC/xGA: auto-refreshes every **6 hours**
- vaastav rolling xGI: auto-refreshes every **6 hours**
- Dixon-Coles team ratings (football-data.co.uk): auto-refreshes every **24 hours**
- **"Refresh Data" button** in sidebar forces an immediate full refresh at any time; sidebar shows data age ("Xm ago" / "~Xh ago — refresh recommended")
- Cache files live in `data/cache/` — safe to delete if you want to force a cold fetch

## Team Details
- Default team ID: **38148** ("Vicario Kart")
- Any team ID can be entered in the My Team sidebar
- GW31, rank ~1.26M
- Bank: £0.3m, Value: £103.5m
- Squad: Verbruggen; Gabriel, Virgil, Timber, Richards; B.Fernandes, Mbeumo, Enzo, Schade; Thiago, Haaland (C)
- Bench: Dubravka, Rogers, Kroupi.Jr, Struijk

## Fantasy Football Hub Integration Plan
**URL**: https://www.fantasyfootballhub.co.uk/
**Status**: Awaiting credentials — fetcher placeholder exists at `data/fetchers/ffhub.py`

**What they provide that we want:**
- Per-GW AI points predictions per player → replaces our naive `PPG × games` season estimate
- Rotation risk scores → fixes biggest gap in ceiling model
- Set piece data (who takes penalties/corners) → better assist/goal probability for attackers

**How to get credentials:**
1. Log in at fantasyfootballhub.co.uk
2. Go to Account Settings → look for "API", "Developer", or "Data Access"
3. If no API key exists: use username + password, OR copy session cookie from browser dev tools (F12 → Network tab → reload → find cookie header)
4. If no self-serve API: contact them directly — paying subscribers can often request access

**Integration steps once credentials are in hand:**
1. Add `FFHUB_EMAIL`, `FFHUB_PASSWORD` (or `FFHUB_API_KEY`) to `.env` and `.env.example`
2. Build `fetch_ffhub_predictions()` in `data/fetchers/ffhub.py` — fetch per-GW predictions, cache 6h
3. Wire into `build_player_universe()` in `player_stats.py` via `_merge_ffhub()`
4. Update `estimate_season_points()` in `transfer_engine.py` to use FFHub predictions as primary source
5. Update `score_players()` to use FFHub prediction as a scoring signal

**FPL Scout set piece data:**
- URL: https://www.fplintelligence.com/ or https://www.fplscout.com/ team news section
- Scrape penalty takers, corner/free kick takers per team
- Add `set_piece_role` column to player universe (penalty_taker, corner_taker, none)
- Bonus weight in `score_players()` for penalty takers especially

## Known Issues / Bugs Fixed
- `matplotlib.colormaps` error → fixed by upgrading to matplotlib 3.7.5
- `player_table.py background_gradient` → replaced with `bar` (no matplotlib dependency)
- `attach_fixture_difficulty` KeyError on empty fixtures → now defaults to 3.0

## Key Config (tunable in config.py)
- `TRANSFER_WEIGHTS` — adjust scoring weights after each GW
- `FIXTURE_LOOKAHEAD` — default 6 GWs (short-term fixture window)
- `DIFFERENTIAL_MAX_OWNERSHIP` — default 10%
- `XG_MIN_THRESHOLD` — min xG to flag underperformer (default 2.0)
- `XG_GAP_THRESHOLD` — min xG gap to flag (default 1.5)
- `HAUL_THRESHOLD` — ceiling pts to flag as haul candidate (default 15)
- `TWENTY_PLUS_THRESHOLD` — ceiling pts for 20+ flag (default 20)
- `TRANSFER_CLOSE_MARGIN` — score gap within which top 3 are shown together (default 0.04)
- `FPL_GOAL_PTS` / `FPL_CS_PTS` — scoring system by position (used in ceiling model)

## Analytics Modules
### `analytics/transfer_engine.py`
| Function | What it does |
|----------|-------------|
| `score_players()` | Weighted composite score (form, fixture, xG, value, trend, minutes); uses **composite FDR** (position-aware), **rolling xGI** form, **DGW +15% / BGW -25%** multipliers |
| `get_transfer_targets()` | Filtered, ranked buy targets |
| `estimate_season_points()` | Projects remaining season pts: PPG × games left × fixture ease |
| `estimate_ceiling()` | Max single-game haul: primary source is FPL Opta xG/xA per90 (`fpl_xg_per90`, `fpl_xa_per90`), fallback to Understat then rolling xGI |
| `build_transfer_reasoning()` | Plain-English explanation of why to buy a player |
| `get_top_recommendation()` | Returns #1 pick (or top 3 if close) with reasoning; excludes owned players |
| `apply_free_hit_adjustment()` | Strips the Free Hit GW from `season_avg_fdr` + `remaining_fixtures` so regular-squad projections are correct |
| `get_free_hit_targets()` | Best players to pick for the Free Hit GW specifically, sorted by that week's FDR |

### xG data priority chain (in `score_players` / `estimate_ceiling`)
1. **FPL Opta** — `fpl_xg_per90`, `fpl_xa_per90`, `fpl_xgi_per90` (most accurate, always present)
2. **Vaastav rolling** — `rolling_xgi` (last 4 GWs, ~67% player coverage via 2-pass name match)
3. **Understat season** — `xg_per90`, `xa_per90` (full-season totals, fuzzy name match)
4. **FPL form / points_per_game** — always available fallback

### Free Hit behaviour
When Free Hit GW is set (e.g. GW34):
- `apply_free_hit_adjustment()` recalculates `season_avg_fdr` and `remaining_fixtures` **excluding GW34** — because your regular squad doesn't play that week
- Changing to GW35 brings GW34 back and excludes GW35 instead — fully dynamic
- Season Outlook tab shows a separate **Free Hit Targets** section: best picks for that specific GW by fixture ease
- The Free Hit recommendation itself ignores the owned-player filter (you can pick anyone)

### `data/processors/fixture_difficulty.py`
| Function | What it does |
|----------|-------------|
| `attach_fixture_difficulty()` | Avg FDR for next N GWs + upcoming fixture list |
| `attach_season_difficulty()` | Avg FDR + remaining fixture count to end of season (GW38) |
| `attach_composite_fixture_difficulty()` | Blends FPL FDR (35%) + Understat xGC/xGA (65%) into position-aware composite score: `composite_att_fdr_next_N` for MID/FWD, `composite_def_fdr_next_N` for DEF/GKP |
| `attach_dgw_bgw()` | Detects Double/Blank Gameweeks per team in lookahead window; adds `has_dgw`, `has_bgw`, `dgw_gameweeks`, `bgw_gameweeks` |

### Composite FDR detail
- **Attackers (MID/FWD)**: uses opponent's xGC per game — high xGC = easy fixture (low composite FDR)
- **Defenders/GKPs**: uses opponent's xGA per game — high xGA = dangerous opponent (high composite FDR)
- xGC/xGA values are based on last 6 completed EPL matches per team, fetched from Understat match results
- Falls back to raw FDR if Understat team stats are unavailable

### DGW/BGW in scoring
- Transfer engine applies a **+15% fixture score multiplier** for players with a Double Gameweek in the lookahead window
- Applies a **-25% fixture score multiplier** for players with a Blank Gameweek
- Fixture ticker shows `2x` marker on DGW cells and dark grey `BGW` on blank cells

## Project Structure
```
FF/
├── app.py                          # Entry point — run this
├── config.py                       # All constants, weights, scoring system
├── requirements.txt
├── .env                            # Credentials (gitignored)
├── .env.example                    # Template
├── pages/
│   ├── 00_my_team.py               # Pitch view, squad table, sell candidates, captain pick, bench cost, transfer suggestions
│   ├── 01_dashboard.py             # GW snapshot + position breakdowns
│   ├── 02_transfer_suggestions.py  # #1 recommendation + reasoning, owned-player filter, season outlook, haul potential, Free Hit (GW-aware)
│   ├── 03_transfer_planner.py      # Fixture difficulty planner
│   ├── 04_differentials.py         # Low-ownership picks + bubble chart
│   └── 05_xg_underperformers.py    # xG gap / haul potential + scatter
├── data/
│   ├── fetchers/
│   │   ├── fpl_api.py              # FPL official API + caching (CORE)
│   │   ├── understat.py            # xG/xA async fetch
│   │   ├── fbref.py                # Advanced stats (needs soccerdata)
│   │   ├── vaastav.py              # Historical FPL data from GitHub
│   │   └── ffhub.py                # Placeholder — awaiting credentials
│   ├── processors/
│   │   ├── player_stats.py         # CENTRAL: merges all sources into one DataFrame
│   │   ├── fixture_difficulty.py   # FDR calculations (next-N + full season)
│   │   └── differentials.py        # Ownership-adjusted scoring
│   ├── cache/                      # Auto-generated, gitignored
│   └── models/
│       └── player.py               # Pydantic schemas
├── analytics/
│   ├── transfer_engine.py          # Transfer scoring, ceiling model, recommendation engine
│   ├── xg_divergence.py            # xG underperformer/overperformer
│   └── differentials.py            # Low-ownership picks
├── components/
│   ├── fixture_ticker.py           # Plotly FDR heatmap
│   ├── pitch_view.py               # HTML pitch with FPL shirt images (team code → CDN URL)
│   └── player_table.py             # Styled Streamlit dataframe
└── docs/
    └── WORKFLOW.md                 # This file — read at start of every session
```

---
_Start each new session by reading this file._
