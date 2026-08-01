# FPL Analytics App · Workflow & Current State

_Last updated: 2026-07-04 (session 8 · nav router, visual rollout, GW39 sandbox, planners)_

## Project Summary
Fantasy Premier League analytics web app (Streamlit + Python 3.8). Data-driven transfer, captain, and team-selection decisions. Running locally for personal use · not deployed.

## How to Run
```bash
cd "/Users/eoinhoustoun/Desktop/Projects/Football Analytics/Claude/FF"
streamlit run app.py                        # http://localhost:8501
streamlit run app.py --server.port 8510     # current dev port
```

## Session 8 (2026-07-04) · major overhaul
- **Navigation:** `app.py` → `st.navigation` router, 6 grouped sidebar sections. Page files moved `pages/` → **`views/`** (the name `pages/` is reserved by Streamlit and collides with `st.navigation`). No page may call `set_page_config`.
- **Home = GW command center** (`views/home.py`): captain/transfer/chip/risk answer cards + team-ID demo default + honest season/sim banner.
- **Team identity:** `components/team_identity.py` centralises kits + `team_color`/`team_dot`. Crest images **removed** (PL crest CDN `resources.premierleague.com` hangs → empty white circles); team-colour dots/accents used instead. Rolled out across Captain, Differentials, xG, Transfers, Predictions, Buy/Sell, Draft, pitch view. Fixed a keeper-kit bug (`_1`/`_2` suffix) in Buy/Sell, Free Hit, Injuries. Fixed 4 analytics engines dropping `team_code`/`team_short`.
- **Loaders:** `components/loading.py` `fpl_loader()` · rolling-football themed spinner (replaces raw `_replay_lookup` default).
- **Off-season sandbox:** `🧪 Simulate GW39` toggle → `build_player_universe(simulate_gw=39)` clones GW1 fixtures as a synthetic next gameweek so fixture/FDR tools work in the summer. `current_gw` stays real (squad fetch); only universe fixtures simulated.
- **Transfer Planner** (`views/03_transfer_planner.py`): sell→buy move verdicts + multi-move plan with hit costs.
- **My Team:** new "✏️ Lineup" tab (subs/captain, live xP) + enhanced "🔁 Pick Team / Transfers" edit mode (search + sort + full replacement list).
- **26/27 Draft:** Minutes-First Target Board (4 lanes + scout questions + minutes→points scatter).
- **Known issue surfaced:** off-season `form`=0 for all players (FPL upstream · no matches in last 30 days). Pending: `points_per_game` fallback for form-based ranking.

## Current Phase
**Off-season polish.** All pages functional under the new router; visual system consistent. Next: off-season form fallback, mobile responsiveness, 2026-27 launch switchover.

## Design System
Binding. Full reference in **CLAUDE.md**. Short version:

- **Base** `#151922` / secondary `#1e2430` / text `#eef1f5`
- **Accents** mint `#00FF87` · gold `#FFD700` · cyan `#04f5ff` · red `#FF4B4B` · orange `#FFA500` · magenta `#e90052`
- **Cards** `rgba(22,26,34,0.85)` + border `rgba(255,255,255,0.08)` + radius 10–18px
- **Typography** Inter / SF Pro · hero 40–48/900 · stat 18–28/900 · label 10–11/800 tracked 0.1–0.22em
- **Grids** `repeat(auto-fill, minmax(320–340px, 1fr)) gap:14px`
- **Animations** module: `components/animations.py` · utility classes `.fplh-animate-in`, `.fplh-stagger`, `.fplh-card-hover`, `.fplh-captain-pulse`
- **Player shirts** `shirt_{team_code}-66.png` (outfield) / `shirt_{team_code}_1-66.png` (GK). *Never invert the suffix.*
- **Rounded 2dp everywhere.** No `0.1234`, no `£8.5`.
- **Real assets preferred** over emoji fluff. PL lion at `assets/prem_symbol.jpg`.

## Pages
| Page | File | Status | Notes |
|------|------|--------|-------|
| Landing (app) | `app.py` | ✅ Overhauled v0.6 | Hero with PL lion · live-pulse row · grouped nav tiles (Your Squad / Transfers & Chips / Analytics / Season) |
| My Team | `pages/00_my_team.py` | ✅ Overhauled v0.6 | Hero identity · **This Week's Decisions** panel (Captain/Sell/Opportunity) · pitch tabs · edit mode with scribble swap · season trend |
| Dashboard | `pages/01_dashboard.py` | ⚡ Needs overhaul | Filter ≥10 games applied to PPG chart. Card treatment pending. |
| Transfer Suggestions | `pages/02_transfer_suggestions.py` | ✅ Overhauled (session 7) | Hero with #1 pick · podium when close · Top Targets card grid · tabbed deep-dives |
| Transfer Planner | `pages/03_transfer_planner.py` | ⚡ Needs overhaul | Old table/chart style |
| Differentials | `pages/04_differentials.py` | ✅ Overhauled | New tagged model (ceiling × momentum × minutes × rank_upside) · tag pills (Template Breaker, Hot Run, Nailed-On Starter, Set-Piece Threat, Underlying Burst, Dream Fixtures, Rising) |
| xG Tracker | `pages/05_xg_underperformers.py` | ✅ Overhauled | Summary strip · card grid · scatter. Now uses correct current season (was 2024 hardcode) |
| Captain Picker | `pages/06_captain_picker.py` | ⚡ Partial | Score weights re-balanced (fixture 0.50 · form 0.30 · xG 0.20) · kit URL fixed · card language not fully rolled out |
| Buy / Sell | `pages/07_buy_sell.py` | ⚡ Needs overhaul | |
| Injuries | `pages/08_injuries.py` | ⚡ Needs overhaul | |
| Wildcard | `pages/09_wildcard.py` | ⚡ Needs overhaul | |
| Ownership Trend | `pages/10_ownership_trend.py` | ⚡ Needs overhaul | |
| GW History | `pages/11_gw_history.py` | ⚡ Needs overhaul | |
| Predictions | `pages/12_predictions.py` | ⚡ Needs overhaul | |
| Free Hit | `pages/13_free_hit.py` | ⚡ Needs overhaul | |
| Chip Planner | `pages/14_chip_planner.py` | ⚡ Needs overhaul | |
| Mini-League | `pages/15_mini_league.py` | ✅ Fixed default | Private leagues (`league_type='c'`) load first · toggle to include public/system leagues (off by default) |

## Working Mode
The user wants the app at 10/10. Always three hats:
1. **Product Designer** · simple, scannable, strong hierarchy, less words.
2. **Data Scientist** · verify math, flag stale data, prefer real signal.
3. **AI / Full-stack Engineer** · clean Streamlit patterns, no races, reproducible fixes.

**Priorities**
1. Fix things that don't work.
2. Aesthetics second · but commit fully to the design system.
3. Use real assets (kits, PL logo, team crests) rather than stock emoji.

**Cadence** · the user redesigns page-by-page. Don't parallel-rewrite the whole app. When they ask for an overhaul, commit (drop redundant sections, restructure, don't patch).

## Session 8 (2026-06-09) · Season Lab: archive, Perfect Season MILP, 2026-27 projections

**The big off-season upgrade.** Three new pages under a "Season Lab" nav group, powered by a 10-season historical archive and exact optimization.

### Data (time-sensitive harvest · DONE, do not delete)
- **`data/cache/archive/` is precious.** The FPL API wipes 2025-26 data when the 2026-27 game launches (~July). We harvested the complete season on 2026-06-09: `fpl_gw_2025_26.parquet` (29,747 rows, 841 players, 38 GWs), `fpl_bootstrap_2025_26_final.json`, `fpl_fixtures_2025_26_final.json`, `my_entry_history_2025_26.json` (Eoin: 2,155 pts, rank 1,443,905). The vaastav repo is permanently stale at GW29 for 2025-26.
- **10-season archive** built from vaastav (2016-17→2024-25) + the harvest: `gw_archive.parquet` (253,568 rows) and `season_summary.parquet` (7,338 player-seasons). Cross-season identity via the stable `code` column (element→id→code join, no fuzzy matching). Schema drift normalized in `data/processors/archive.py` (COVID GW remap, 2024-25 assistant-manager filter, nullable xG/CBIT). Tests in `tests/test_archive.py` (9 passing).
- Rebuild: `python scripts/build_archive.py [--force]` · completed seasons cache forever.

### Perfect Season engine (`analytics/perfect_season.py`)
- Pool pruned 841→130 (top by points/position ∪ top pts/£m ∪ cheapest enablers).
- **Set-and-forget MILP**: best fixed 15 at GW1 prices, weekly best XI + captain → **3,098 pts, proven optimal in ~5s**.
- **Full multi-period MILP** (PuLP/CBC): squad/lineup/captain/buy/sell × 38 GWs, FT banking (≤5, 2025-26 rules), -4 hits, WC/TC/BB in-model (one per half), warm-started from set-and-forget. Free Hit layered post-hoc per half (separable). Conventions: buy=sell=actual GW value; no autosubs/VC needed under hindsight; DGW pre-aggregated.
- Run: `python scripts/run_perfect_season.py [--time-limit 1800]` → `data/cache/perfect_season_2025_26.json`. Page reads the cache.
- `analytics/squad_milp.py` · exact single-period squad MILP, reused by Free Hit pass + 26/27 draft (supersedes greedy for these uses).

### 2026-27 projections
- **Price predictor** (`analytics/price_predictor.py`): 9 season-pair training (3,853 rows), XGBoost beat ridge · backtest on 2024-25→2025-26: **MAE £0.17m, 69% exact £0.5 bucket, 97% within ±£0.5m**. Prices rounded to 0.5 buckets, position floors.
- **Points projector** (`analytics/season_projection.py`): per-position fitted minutes + pp90 carryover (+xGI residual). Honest validation: Spearman ~0.48-0.50 on stable transitions, 0.39 across the DEFCON rule-change year (naive baseline 0.41 · season-to-season FPL is irreducibly noisy; the projector's value is calibrated scale for the optimizer).
- Promoted clubs / new signings excluded (no history) · re-check after launch.

### New pages
| Page | File | Notes |
|------|------|-------|
| Perfect Season | `pages/16_perfect_season.py` | Hero benchmarks · points race vs Eoin · GW replay slider · core holds / armband insights |
| Value Lab | `pages/17_value_lab.py` | 10-season value frontier · price-band ROI · archetypes · DEFCON earners · value-repeatability |
| 26/27 Draft | `pages/18_draft_2026_27.py` | Predicted prices + projected points → exact MILP optimal squad · pre-launch badge · repricing tabs |

New deps: `pulp>=2.7,<3.0`. New config: `ARCHIVE_SEASONS`, `PERFECT_SEASON`, `NEXT_SEASON`.

### Perfect Season 2025-26 · final result (cached JSON)
| Benchmark | Points |
|---|---|
| **Perfect (transfers + chips + FH)** | **4,682** |
| Perfect set-and-forget (proven optimal) | 3,098 |
| Global winner | 2,582 |
| Eoin (Vicario Kart) | 2,155 |
| Game average | 1,895 |

141 hits taken (omniscience makes -4 trivially profitable · note this when drawing lessons). Chips: TC GW2/32, BB GW10/33, WC GW19/26, FH GW16 (+43) / GW25 (+39). Most held: B.Fernandes 25 GWs, Haaland 24, Gabriel 22, Kelleher 20. CBC reached ~9% proven gap at 1800s (incumbent stable across two independent solves); a HiGHS re-run could tighten it.

### Session 8 continued · scenarios, pitch rendering, Wildcard overhaul, Playbook
- **Hit-capped scenarios**: `run_perfect_season.py --scenario nohits|limited|unlimited` → per-scenario JSONs; page 16 scenario radio (incl. Set & Forget view with its own pitch + GW slider).
- **Pitch rendering everywhere**: new `render_squad_pitch()` in `components/pitch_view.py` (generic kits-on-pitch with price/stat/fixture labels). Used by pages 16 (replay shows **opponent + actual GW pts** under every player), 18 (draft team sheet), 09 (wildcard).
- **Wildcard overhauled** (design system + exact MILP for the selected GW + off-season hand-off state). Fixed its inverted shirt-suffix bug.
- **Playbook page (`19_playbook.py`)** + `analytics/playbook.py` · data answers: best-XI formation counts (3-5-2/4-5-1 dominate; 5-4-1 won once), DEF points share 29→35% post-DEFCON (all in the £4.0-5.5 bracket), defender archetype grid (top-team attacking FBs 137 avg pts / 27.9 ppm), pen-taker uplift (+20 median pts, worse ppm), predictiveness (form ρ=.29 > xGI .20 > fixture ease .14), fixture horizon (no cliff; 5-6 GWs sensible), team value (GW1 template LOST £1.6m in 25-26; risers gained ~£0.5m each; sell rule = half the rise).

### Session 8 continued (2) · curated defender roles, finishing-luck scatter, fixes
- **Curated CB/FB role map** at `assets/defender_roles_2025_26.json` (all 128 defenders ≥900 mins hand-labelled; `uncertain: true` flags hybrids · Eoin can edit, Playbook reloads). **This flipped the Q3 finding**: with Gabriel/Senesi/Guéhi correctly CB-labelled, top/mid-team CBs are the DEFCON kings (120 avg pts, 24.8 ppm, ~22 defcon pts vs FBs' 4–7). Refresh per season.
- **xG page**: new "Finishing Luck · Both Tails" section (G−xG diverging scatter, labelled extremes both directions, distribution histogram + % within ±1 goal).
- **Understat SSL fix**: macOS framework Python lacked root certs → `aiohttp.TCPConnector(ssl=certifi context)` in `understat.py`. Was silently killing the xG page.
- **Hit-capped scenario solver fix**: monolithic CBC cannot escape the warm start under hard hit caps (0 improvement in 1500s; bound 4683 vs incumbent 3098). `solve_rolling_horizon()` added to `analytics/perfect_season.py` (10-GW windows, commit 4, state carry: squad/bank/FTs/chips/hit-budget, ε-penalty on FT burn). `run_perfect_season.py` auto-routes capped scenarios to rolling.

### Session 8 continued (3) · full-league xG, minutes intensity, hits doctrine, Start Kit
- **Full-league xG coverage fix**: Understat name-merge was matching only 31/537 players who played. Fix at universe level (`player_stats.py`): FPL Opta season totals (`fpl_xg`/`fpl_xa`, new in `get_players_df` along with stable `code`) backfill wherever Understat misses → 537/537 covered. `xg_gap` recomputed vs FPL goals.
- **Playbook Q8 rebuilt** (Eoin's correction): per-match vs per-90 test among regulars (20+ apps). Full-90 players: 3.50 pts/match vs 2.30 for <65-min; per-90 efficiency is FLAT-to-falling (4.46 → 3.56) · **exposure effect, not quality**. `minutes_intensity()` in playbook.py.
- **Playbook Q9 (hits)**: unlimited (141 hits, 4682) vs nohits (0 hits, 4348) = **+2.4 net pts per hit with perfect foresight** → negative-EV for humans. 47% of perfect play's hits were within 1 GW of a chip. Triggers: forced / chip amplification / projected 5-6 GW gain ≥8 pts.
- **Season Start Kit** section atop the Playbook: budget blueprint (GKP 10.0 / DEF 26.5 / MID 35.5 / FWD 27.5 from SAF), shopping criteria, red flags, first-5-GWs plan.
- **Scenario results**: nohits (rolling horizon, all windows Optimal) = **4,348 grand**; FH GW12 +72 / GW25 +70. `limited` (≤1/GW, ≤6 total) re-run in flight.

### Perfect Season scoreboard (cached JSONs in data/cache/)
| Scenario | Grand total |
|---|---|
| Unlimited hits (141) | 4,682 |
| Realistic hits ≤6 (used all 6) | 4,357 |
| No hits | 4,348 |
| Set & forget | 3,098 |
| Global winner | 2,582 |
| Eoin | 2,155 |

### Still open from this session
- Optional: `brew install highs` and re-run the MILP for a tighter bound / proven optimum.
- Phase 5 continues: next overhaul candidates `13_free_hit` (MILP-power like Wildcard), `01_dashboard`, `12_predictions`.
- After FPL 2026-27 launches: flip Draft page to "vs actual" diff mode, add promoted-club players.
- Phase 5: legacy page overhauls (dashboard, planner, wildcard→MILP, free hit→MILP, etc.).

## Session 7 (2026-04-22) · UI/UX overhaul

### Data-layer bugs fixed
- **Understat season hardcoded to `2024`** → replaced with `_current_season()` that derives from `date.today()` (cutover at July). Same fix in FBRef fetcher (`2024-2025` → dynamic `YYYY-YYYY`). Stale xG data was root cause of "xG underperformers not working".
- **`team_code` missing from player universe** · only existed on squad DF. Added `team_code` + `team_short` to `get_players_df()` in `fpl_api.py`. Root cause of every player rendering as Arsenal outfield kit on Transfer Suggestions / Captain / etc.
- **Kit URL suffix inverted.** FPL CDN uses `_1` suffix for **goalkeepers**, no suffix for outfield. Previous code did the opposite → outfield players wore GK shirts, GKs had no image. Fixed in `components/pitch_view.py` and `pages/06_captain_picker.py`.
- **Cache purged** so fresh Understat and bootstrap data load on first request.

### Analytics improvements
- **Differentials rewritten** (`analytics/differentials.py`) · old `ceiling / (ownership+1)` replaced with multi-signal composite: `diff_score = haul_ceiling × momentum × minutes_factor × rank_upside` (scaled 0–10). Momentum = recent form / season PPG. Rank upside = logistic on ownership (steep <10%, flat >20%). Adds **qualitative tags**: Template Breaker, Hot Run, Nailed-On Starter, Set-Piece Threat, Underlying Burst, Dream Fixtures, Rising.
- **Captain scoring re-balanced** · fixture now weighted stronger. Full picker page: `fixture 0.50, form 0.30, xGI 0.20` (was form-heavy 0.45/0.30/0.25). My Team inline pick: `0.60 fixture + 0.40 form`, scaled 0–10 for display.
- **My Team edit mode** · axe a player → replacement picker (filtered to position + affordable) → scribble SVG overlay animation → pending swaps list with undo.

### Components / modules added
- **`components/animations.py`** · global CSS keyframes (`fade-in-up`, `pop-in`, `pulse-gold`, `shake-x`, `scribble-draw`, `x-mark`, `overlay-fade`, `confetti-fall`), utility classes, `scribble_swap_overlay()`, `confetti_burst()`.
- **`assets/prem_symbol.jpg`** · Premier League lion image. Base64-embedded in app hero via cached `_pl_logo_data_url()` helper.

### UI overhauls (this session)
- **Landing (`app.py`)** · dropped paragraph descriptions on nav cards, grouped into `Your Squad / Transfers & Chips / Analytics / Season`, live-pulse row (Best form / Most in / Most out / Unavailable), hero with GW + deadline countdown pill + PL lion right-side visual.
- **Transfer Suggestions (`pages/02_transfer_suggestions.py`)** · hero card (shirt + identity + stat block + 42px score), podium (3-card layout when close), Top Targets card grid (replacing dense dataframe), tabbed deeper analysis. All numbers 2dp.
- **Differentials (`pages/04_differentials.py`)** · summary strip · card grid with tag pills · ownership/form scatter.
- **xG Underperformers (`pages/05_xg_underperformers.py`)** · summary tiles · card grid with "due goals" gradient bar · scatter.
- **My Team (`pages/00_my_team.py`)** · 4-section layout: hero identity with 5 stat tiles · **This Week's Decisions** 3-card panel (Captain/Sell/Opportunity) with deep-links · Squad tabs with edit mode + scribble · Season Trend with inline summary + bar chart.
- **Mini-League** · private (`c`) leagues first, `Include public/region leagues` toggle off by default.
- **Theme** · slight lift from `#0e0e18` to `#151922` base; `#1e2430` secondary. Still dark.

### Bugs fixed this session
- **`TypeError: First argument must be a String, HTMLElement...`** on My Team swap · caused by explicit `st.rerun()` calls inside button handlers (buttons already trigger rerun; double-rerun raced with SVG overlay mount). Removed 5 redundant `st.rerun()` calls, moved scribble overlay emission to page root.

## Architecture

### Stack
- Streamlit + Plotly (plot backgrounds always transparent)
- Python 3.8 · **always use `List`, `Dict`, `Optional`, `Union` from `typing`**. No `list[x]` / `dict[x]`.
- No database. JSON cache with TTL on disk + Streamlit `@st.cache_data` in-memory.
- All weights and thresholds in `config.py`.

### Data sources
| Source | What | Status |
|--------|------|--------|
| FPL Public API | Prices, ownership, fixtures, GW stats, squad picks, Opta xG per90 | ✅ Working |
| Understat | Player xG/xA, team xGC/xGA · **dynamic season** | ✅ Integrated |
| vaastav GitHub | Rolling xGI last 4 GWs | ✅ Integrated |
| football-data.co.uk | Historical PL results → Dixon-Coles team ratings | ✅ Integrated |
| FBRef | Progressive passes/carries, key passes · **dynamic season** | 🔧 `pip install soccerdata` to activate |
| Fantasy Football Hub | Per-GW AI xP predictions | ⏳ Awaiting credentials · keys already in `.env` template (`FFH_EMAIL`, `FFH_PASSWORD`) |

### Data freshness
- FPL bootstrap: 4h · Fixtures: 24h · Understat players: 24h · Understat teams: 6h · vaastav rolling: 6h · Dixon-Coles: 24h
- Sidebar "🔄 Refresh Data" button forces immediate full refresh.
- Cache lives in `data/cache/` · safe to delete.

### xG priority chain (score_players / estimate_ceiling)
1. FPL Opta (`fpl_xg_per90`, `fpl_xa_per90`, `fpl_xgi_per90`) · always present
2. vaastav rolling (`rolling_xgi` · last 4 GWs)
3. Understat season (`xg_per90`, `xa_per90`)
4. FPL form / PPG · always-available fallback

### Composite FDR
- Attackers (MID/FWD): opponent xGC (high = easy)
- Defenders (DEF/GKP): opponent xGA (high = hard)
- Blend: 50% Dixon-Coles + 50% Understat xGC/xGA when DC ratings available; else 35% raw FDR + 65% Understat
- DGW / BGW multipliers: +15% / -25%

## Team
- Default team ID **38148** ("Vicario Kart")
- Manager: Eoin Houstoun
- Current GW **33** (per bootstrap at time of writing)
- Private mini-league only · public `Spurs & Ireland` type leagues are `league_type='s'` and are hidden by default in the mini-league page.

## Next Priorities
1. **FFHub integration** · biggest single accuracy upgrade. Fetcher placeholder at `data/fetchers/ffhub.py`. When creds arrive:
   - Build `fetch_ffhub_predictions()` with 6h cache
   - Wire into `build_player_universe()` via `_merge_ffhub()`
   - Update `estimate_season_points()` to prefer FFHub over naive PPG × games
   - Add FFHub `xP` as a scoring signal in `score_players()`
2. **Remaining page overhauls** · user will call the next section. Likely order: Dashboard → Captain → Buy/Sell → Injuries → others.
3. **Wildcard Planner UI** · biggest non-landing page still old.
4. **Small wins**:
   - Projected GW xP total on My Team hero (sum `ep_next` across XI)
   - "Apply swaps to FPL" action (needs `FPL_EMAIL`/`FPL_PASSWORD`)
   - Form sparklines in squad table

## Key config (tunable in `config.py`)
- `TRANSFER_WEIGHTS` · weekly adjustment
- `FIXTURE_LOOKAHEAD` · default 6 GWs
- `DIFFERENTIAL_MAX_OWNERSHIP` · default 10%
- `XG_MIN_THRESHOLD` / `XG_GAP_THRESHOLD` · xG flag thresholds
- `HAUL_THRESHOLD` / `TWENTY_PLUS_THRESHOLD` · ceiling flags
- `TRANSFER_CLOSE_MARGIN` · when to show podium instead of hero (default 0.04)
- `FPL_GOAL_PTS` / `FPL_CS_PTS` · scoring system by position

## Project Structure
```
FF/
├── app.py                          # Router · st.navigation (6 sections) + shared data load; sole set_page_config
├── pages/home.py                   # Home · GW command center (team-ID + captain/transfer/chip/risk cards) + hero + pulse
├── config.py
├── requirements.txt
├── .env                            # Gitignored · FPL + FFH credentials
├── .env.example
├── .streamlit/config.toml          # Lighter dark theme
├── assets/
│   └── prem_symbol.jpg             # Premier League lion · used in app hero
├── pages/                          # 16 pages · see status table above
├── components/
│   ├── animations.py               # Global CSS + scribble overlay + confetti
│   ├── pitch_view.py               # FPL-style pitch, captain pulse, correct kits
│   ├── player_table.py             # Styled DF, 2dp throughout
│   ├── fixture_ticker.py
│   └── badges.py                   # Set-piece / DEFCON badges
├── data/
│   ├── fetchers/
│   │   ├── fpl_api.py              # team_code + team_short now propagated
│   │   ├── understat.py            # dynamic season
│   │   ├── fbref.py                # dynamic season
│   │   ├── vaastav.py
│   │   ├── dixon_coles.py
│   │   └── ffhub.py                # placeholder
│   ├── processors/
│   │   ├── player_stats.py         # Central merge
│   │   └── fixture_difficulty.py
│   ├── cache/                      # Auto-generated
│   └── models/player.py
├── analytics/
│   ├── transfer_engine.py
│   ├── differentials.py            # New multi-signal model + tags
│   └── xg_divergence.py
└── docs/
    └── WORKFLOW.md                 # This file
```

## Rules that prevent UI/UX drift
1. **Never `st.rerun()` in a button handler** (causes animation overlay race).
2. **Never invent a new colour or spacing** · use the tokens in CLAUDE.md.
3. **No duplicate sections** · if a dedicated page exists, link to it.
4. **2dp on every number.**
5. **Short names** · truncate with ellipsis, no wrapping in cards.
6. **Real images over emoji** when we have them.

---
_Read `CLAUDE.md` for the design-system reference. Start each new session here for full context._

## Session 2026-07-12 (evening) · Pitch planner, nav slim, graph audit
- **My Team pitch = the planner.** Timeline scrubs into simulated future GWs
  (SIM_HORIZON=5 · GW1-5 fixtures replay as GW39-43). Permanent ✕ on every kit
  (transfer out), kit tap opens a Player Intel dialog. Working moves persist as
  disk drafts (analytics/squad_planner.py · pitch links full-reload the page).
  Save promotes draft to plan. FT banking 1/week +1 banked cap 5, −4/extra with
  a red badge; strip shows transfers/free/bank/net-xP/saved state.
- **Nav slimmed 21→19 pages, 6→5 groups.** Deleted 01_dashboard (generic
  charts, better versions in Transfers/Value Lab) and 03_transfer_planner
  (superseded by the pitch planner + Buy/Sell verdicts). New groups: This Week ·
  Transfers · Chips · Scouting · Data Science Lab.
- **Graph audit (all ~50 charts).** Every remaining chart maps to a decision;
  removed the Free Hit position donut (adjacent grouped bars carry the same
  answer with numbers); added the Net xP chip to the planner strip.
- **Bug fixed:** animation/theme CSS was injected once per session, so every
  rerun after the first dropped hover/count-up styling. Now injected per run.

## Sessions 2026-07-13 → 07-16 · Super-tool build-out + spotless polish
- **Fluid planner:** whole Pitch View tab in a fragment; pitch clicks go
  through components/pitch_click (bidirectional component · never use
  ?query-param links, they full-reload and wipe session). Multi-axe queue,
  full-width Transfer Desk table (sortable, column chooser, pinned kit+name,
  📊 per-column top-ten dialogs with GW-window slider), per-week captain +
  chips, Optimise (suggest_plan) + Analyse (analyse_plan) dialogs.
- **Shared engines:** xp_engine (per-GW horizon), model_store (disk bundle +
  startup pre-warm thread → Predictions/Free Hit render in seconds),
  price_radar, plan_optimizer.
- **Playbook Q10-Q12** (premium captaincy incl. ten-season icon-vs-field
  8/10 + armband pricing ~25 pts/£m; bench doctrine; DEFCON carry 3-4).
- **Faces everywhere:** face_html + with_image_labels + image scatter
  symbols; intel popup (with per-GW history table) opens from kits on every
  pitch mode and via intel_lookup on scouting pages.
- **Fixes:** Buy/Sell unique targets (was pairing everyone with one player);
  bootstrap defensive_contribution is raw ACTIONS → "DEF acts"; off-season
  squad form=0 override; nested-expander crash on Injuries; CSS must
  re-inject every rerun; None cells coerced.
- Launch app with `nohup streamlit run app.py --server.port 8510 &`.

## Session 2026-07-24 · 2026-27 season rollover + Value Board planning suite

Branch `season-rollover-2026-27` (15 commits, not yet merged to main).

**Phase 1 · rollover to live 2026-27.** FPL API flipped to the new season
(555 players, GW1 deadline 2026-08-21). `get_season_phase` auto-reads
"preseason", so the GW39 off-season sim stands down on its own. Added
Coventry (COV) + Hull (HUL) to `config.TEAM_COLORS` (only two clubs missing).
`scripts/verify_rollover.py` is the acceptance harness (phase/GW1/prices/colours).
Seeded `assets/defender_roles_2026_27.json` from last season (100 stayers).
**Preseason has zero played GWs** → fixed 2 hard crashes (Predictions, Free Hit:
the points model backtests an empty test set) + noisy model pre-warm; shared
guard `ui/preseason.stop_if_preseason()` gives honest empty-states on the 8
squad/model pages. Team ID updated to **45595** in `.env`.

**Phase 2 · the Value Board (the big build).** The 26/27 Draft is now a live
**Value Board**: actual prices vs archive-projected points, bucketed by
`analytics/value_verdicts.py` (Necessity / Value / Overpriced / Fair / Scout).
Key signal `pricing_surprise = predicted − actual` (FPL bargain vs tax). Shared
builder `ui/value_board.py:build_board()` (cached) feeds the Draft AND the
Playbook 26/27 read. `solve_draft()` runs the optimal squad on real prices.

**Projection realism (the model can't know these · encoded by hand):**
- `analytics/projection_overrides.py` + `assets/player_overrides_2026_27.json`:
  fitness/role/regression overrides (Isak/Palmer/Havertz/Mosquera minutes up,
  Dubravka benched, Fernandes/Thiago haircut, Anderson Forest→City haircut).
  `minutes` recomputes points from the per-90 rate; `pts_mult` haircuts.
- Live club/status/set-piece order come from the LIVE bootstrap inside the
  verdict engine, so transfers self-correct (Senesi→Spurs, Isak→Liverpool).
- `analytics/projection_confidence.py`: High/Medium/Low tier + honest range
  (proj_lo..proj_hi) from last-season minutes sample; **overrides, fullbacks,
  and new-club players are knocked down a tier**. Isak dialled to 151, Low.

**Optimiser rules (Eoin's, in `analytics/squad_milp.optimize_squad`):**
`max_attackers_per_club=1` (DEFCON mids exempt via
`assets/defcon_players_2026_27.json`), `max_defenders_per_club=1`,
`force_codes`/`exclude_codes`. `solve_draft` also does a **risk-aware objective**
(`risk` 0-1 blends mean vs floor) and an **opening-fixtures weight** (`opening`
0-1, GW1-6 ease via `OPENING_FIXTURES`), plus a per-player veto.

**Draft UI:** 4 strategies (Optimal value / Safe Haaland+Fernandes /
Punt Fernandes-only / Bench Boost GW1), risk + opening + budget sliders,
"don't trust" veto multiselect, verdict lanes with confidence dots + ranges +
set-piece + injury + override notes, and a **player inspector** (25/26 evidence:
goals/xGI/DEFCON/minutes + position-rank chart).

**Chip Planner** rebuilt (`analytics/chip_timing.py` + `views/14_chip_planner.py`):
first-half only (GW1-19, since 26/27 gives two chip sets and set one expires at
GW19), runs on a chosen draft, recommends BB (with GW1 no-prep callout) / TC / FH
by fixture ease.

**Gotcha (bit us twice):** Streamlit escapes st.markdown HTML if an interpolated
placeholder leaves a whitespace-only line. Always collapse card HTML to one line:
`"".join(s.strip() for s in html.splitlines())`.

**Still open:** Wildcard fixture-swing timing; Value Lab 26/27 lens; merge the
branch to main.

---

## 2026-08-01 · Consensus projections, expected minutes, and a pitch-first Draft

### New data source · Fantasy Football Hub predicted points
`data/cache/ffh_predictions_2026_27.csv` (gitignored, 409 players). A **manual,
one-shot** snapshot of the Hub's `/predictions` tool taken from Eoin's own
logged-in session: per-player predicted points for GW1-4, **expected minutes per
gameweek**, points per gameweek, ownership and each fixture. Never polled or
scheduled · same rules as the Scout snapshot.

Loader: `data/fetchers/ffhub.py` · `load_snapshot`, `per_gw_frame` (long form),
`per_gw_by_code` (joined to the stable FPL `code`), `match_to_board`. Club names
match FPL's exactly, so the join is name + club (name alone collides across
clubs and silently hands one player another's projection).

### Consensus engine · `analytics/consensus.py`
Blends three independent reads into one number plus an honest spread:
ours (carryover, Spearman ~0.4) · Scout (season model) · Hub (match model).

- **Scale first.** The models disagree on what a season is worth (ours runs
  ~0.73x Scout, ~0.61x the Hub). `robust_scale` puts everything on our scale via
  a median ratio before anything is compared, or the ranking is just the offset.
- **Season weights** 0.35 ours / 0.40 Scout / 0.25 Hub, renormalised per row so a
  player only one model can see keeps that model's number.
- **Two zero-handling rules that matter.** A Hub zero means "no minutes in the
  window", not "no points this season" · Saliba at 0 would otherwise drag a real
  starter to a third of what the season models say. Anything under
  `MIN_NAILEDNESS_FOR_SEASON` (0.5, i.e. 45 mins a game) is excluded from the
  SEASON blend and surfaced as `ffh_no_early_minutes` instead. It still drives
  the per-gameweek view, where "he is not playing" IS the answer.
- **Disagreement is the confidence signal.** `model_spread` (coefficient of
  variation) → High/Medium/Low. Two models agreeing caps at Medium; "High" means
  three independent reads landed together.
- New columns: `consensus_points`, `consensus_lo/hi`, `consensus_confidence`,
  `model_spread`, `n_models`, `src_ours/src_scout/src_ffh`, `ffh_nailedness`,
  `ffh_exp_mins_next/mean`, `ffh_mins_volatility`, `points_scale_to_match`.
- `biggest_disagreements()` is the shortlist worth a human read.

### Per-gameweek projections · `analytics/gw_projection.py`
Replaces "season / 38 x fixture ease" with the Hub's real per-fixture forecast
where the window covers it, and falls back to the old shape beyond it, rescaled
so the two never sit side by side in different units. `source()` reports which
produced each cell so the UI can label it. Also holds `best_xi()` (the XI for
THIS gameweek, formation-legal) and `bench_boost_value()` (what the chip is
actually worth, plus dead bench slots).

**The old model was hiding a real problem.** With minutes ignored, the optimiser
drafted Rice and Garner, whom the match model expects to play **15 and 30
minutes** in GW1 (World Cup returnees). A GW1 Bench Boost was worth 8.4 points
with Rice a dead slot. Hence the new **"Weight early minutes"** dial on the draft
(default 0.5), which scales the objective by `ffh_nailedness`.

### `views/18_draft_2026_27.py` rebuilt around the pitch
The pitch IS the planner. Each shirt carries the **next three fixtures as
FDR-coloured chips** and **that gameweek's expected points**; a red `!` marks
anyone under 45 expected minutes. `x` marks a player for replacement, `↓` forces
him to the bench, the kit opens his card. Below the pitch sits ONE table: the
affordable, club-legal replacements when someone is marked, otherwise the pool.
Swaps are a tick in a `Swap in` column (`st.data_editor`) · row-selection on
`st.dataframe` is a canvas grid and could not be verified reliably.

Everything else moved behind five tabs (Verdicts · Where the models disagree ·
Wildcard · Chip route · All players) so the planner owns the screen.

Player card tabs: **Model agreement** (one bar per model + what the spread
means), **Minutes** (expected minutes per gameweek, the only stated minutes
forecast in the app), **Opening run** (green = real match forecast, faded =
fixture shape), **Last season**.

State: `draft_swaps` (out → in), `draft_axe`, `draft_bench`, re-applied every
rerun so the optimiser stays the starting point rather than the last word.

**Gotcha:** `st.metric` truncates its label and value to a couple of characters
inside `st.dialog`. Use the HTML tile helper (which CLAUDE.md already mandates
for heroes) everywhere in dialogs.

### Football context captured as a skill
`.claude/skills/fpl-football-lens.md` · Eoin's football-first reasoning for
26/27: the scoring asymmetries (a mid has three routes to points, a forward
one), guaranteed points over exciting points, why carryover breaks on new
managers, the current club-by-club reads, template risk as a cost rather than an
obligation, and the coupled Bench Boost / Wildcard / goalkeeper-trap decision.
Read it before ranking players or writing optimiser rules.

**Still open:** wire the same per-gameweek model into the Chip Planner (it still
uses the fixture-shape model); Value Lab 26/27 lens; mobile widths.

---

## 2026-08-01 (later) · Light mode, custom tables, and comparison

### Theme system · `ui/theme.py` rewritten
Two palettes, one set of `--ff-*` variable names. Every surface reads
`var(--ff-...)` rather than a literal, so switching is a CSS swap with nothing to
re-render. `theme_toggle()` sits under the sidebar wordmark.

**The distinction that makes light mode readable:** two accent families.
`--ff-mint` is an INK colour, safe as text on the current ground (bright mint in
dark, a deeper `#00874A` in light). `--ff-mint-v` is a VIVID FILL for chips that
carry black text, nearly identical in both themes because a chip supplies its own
ground. Mixing them up is what makes a naive light mode unreadable.

`app.py`'s hard-coded dark CSS block is GONE · it lived at equal specificity and
would have fought the palette. Do not re-add it.

Charts: `ui/charts.py` builds every option against the dark palette in ~20
places. Rather than touch every call site, `render()` remaps a known set of
literals on the way out (`_LIGHT_SWAP` + `_retheme`). The chart key gets a
`_lt` suffix in light mode, or Streamlit reuses the mounted chart and keeps the
old colours.

Component iframes do not inherit the host's custom properties, so
`component_css()` hands the palette to the pitch and the tables explicitly.

### `components/ff_table.py` · tables we actually control
Streamlit's dataframe is a canvas grid: it cannot be styled with CSS, it paints
against Streamlit's configured base theme (so it stayed dark in light mode), and
its row hit testing is opaque to automation. Replaced with a real HTML table
behind a small bidirectional component. Buys the app's own look, rich cells
(faces, coloured chips, inline bars, FDR fixture runs, action buttons) and clicks
reported exactly like the pitch reports them. Declarative column specs:
`col_face`, `col_player`, `col_num`, `col_bar`, `col_chip`, `col_run`,
`col_action`, `col_html`. `build_html` is pure, so it unit tests without a browser.

**Callers MUST dedupe on the returned nonce**, same as the pitch. `_click()` in
the draft page is the shared helper.

### `analytics/head_to_head.py` · the two "which one" questions
**Player vs player.** Every axis is given three ways, because totals flatter
whoever is expensive: per season, per £m, per 90. Axes are scaled across the
compared players only, since the question is never "is he good" but "is he
better than the alternative I can afford".

Two scores, on purpose: `totals` (mean of the 0-1 scaled axes) drives the radar,
while `edges` (mean RELATIVE difference vs the field) drives the verdict. With
two players every axis scales to exactly 0 or 1, so `totals` would call a 4% edge
a landslide. **Alderete vs Ballard comes out 1% apart, which the verdict now
reports as noise rather than a win.**

**Draft vs draft.** `score_draft` re-picks the XI every gameweek, doubles the
captain, and pays the bench in the Bench Boost week, so "Bench Boost GW1" and
"Bench Boost GW2" are genuinely different plans rather than the same squad twice.
`compare_drafts` returns a verdict plus the reasons: which chip week was worth
more, captaincy over the window, the biggest single-week swings, budget left
over, and a warning when a boosted bench contains someone not expected to play.

### Draft page · pitch-first, laptop-first
- Gameweek **stepper** (◀ ▶) replaced the slider.
- **Compact** pitch mode: smaller kits, price and projection on one line, tighter
  rows. Pitch height 797px → 662px.
- Hero shrunk to one line and the controls moved into a **popover beside it**, so
  the pitch now starts at y=222 instead of y=446. Readout tiles moved BELOW the
  pitch: the pitch is what you look at, the numbers are what you check after.
- New tabs: **Compare players** (radar + per-gameweek lines + a metric table with
  ◆ on the better number and a column saying why the row matters) and
  **Compare drafts** (A/B with its own chip plan, weekly lines, a per-week
  difference bar, and the reasons behind the gap).
- Player card: a **keep-or-not verdict** built from minutes, points per £m rank
  within his price band, and model agreement · not from the headline projection.

**Bug worth remembering: Streamlit gives a declared component's iframe a 300px
default width.** The pitch and tables size themselves from their container, so at
300px they wrapped into a tall cramped column and reported that height back. The
fix is CSS on `[data-testid="stCustomComponentV1"]`, in `ui/theme.py`.

**Also:** `st.metric` truncates its label and value to a couple of characters
inside `st.dialog`. Use the HTML tile helper there.

**Measuring layout in a browser: never trust `getBoundingClientRect` while
`document.body.style.zoom` is set.** It cost a detour chasing a "tiles are half
width" bug that did not exist.

**Still open:** wire the per-gameweek model into the Chip Planner (it still uses
the fixture-shape model); convert the remaining pages' inline literals to
`var(--ff-*)` so light mode is complete app-wide (Draft, tables, pitch, charts
and chrome are done); Value Lab 26/27 lens.

---

## 2026-08-01 (evening) · Saved drafts and a simulated comparison

### `analytics/drafts.py` · drafts are recipes, not squads
A saved draft stores the RECIPE (strategy, locks, vetoes, budget/risk/opening/
minutes dials, chip plan), not the fifteen players. That keeps a saved draft
correct when prices move or a projection updates, which is the whole point of
comparing them in early August.

Squad and chip plan are independent on purpose, which is what lets "Optimal" and
"Optimal, BB GW2 into WC GW4" be two comparable drafts built on the same fifteen.

Nine presets seeded on first run: three squads (Optimal · +Mosquera+Haaland ·
+Fernandes+Mosquera+Haaland) across three chip plans (none · BB2→WC4 · BB1→WC4).
A `_seeded` marker means a deleted preset stays deleted instead of reappearing.
Stored in `data/cache/saved_drafts.json` (gitignored).

### Monte Carlo comparison · `simulate_drafts` in `analytics/head_to_head.py`
Two point estimates always differ, so the question "is this gap real" needs a
spread, not a subtraction. Two sources of uncertainty:

- **rate** · how good the player actually is. ONE draw per player for the whole
  window, because being wrong about Isak in GW1 means being wrong in GW8 too.
  Width comes from how far the three models disagree (`consensus_lo/hi`).
- **match** · week-to-week variance, drawn fresh each gameweek, overdispersed
  (variance ≈ 2.4x mean) because football is lumpy.

**Both draws are SHARED between drafts.** If two squads have twelve players in
common those twelve cancel in the difference, and the comparison narrows to the
picks that actually differ. Simulating each draft independently would drown the
signal in variance neither draft owns. This is the thing that makes the verdict
trustworthy.

`significance()` is deliberately conservative: anything inside 65/35 is reported
as a coin flip, because a projection validating at Spearman 0.4 does not earn
finer resolution. `build_phases()` splits a draft at its Wildcard so the second
half is a squad rebuilt on the fixtures that follow the reset.

Live result: all nine presets are within noise of each other on chip plan, and
locking Fernandes + Mosquera + Haaland costs about 4 points against pure Optimal
over GW1-8, which is inside the spread. Chip timing separates the drafts far
more than the premium locks do.

### Comparison UI
- Verdict states the ACTION first ("Pick Base BB2 → WC4" / "Too close to call").
- **Range bands are hand-drawn HTML, not ECharts.** A floating bar (lo to hi with
  a tick at the mean) is awkward to encode in a charting library and was silently
  rendering the spans at the wrong width. Absolute positioning makes overlap
  exact, which is the entire point of the chart.
- Colour carries the decision: leader mint, anyone still in the fight (beats it
  in ≥35% of sims) gold, everyone clearly behind grey. Nine drafts in nine
  colours is a rainbow, not a shortlist.
- Chart labels abbreviate the SQUAD and keep the CHIP PLAN, because the chip is
  usually what differs and a middle-truncated name hides it.
- The head-to-head grid only renders at six drafts or fewer.

### Substitution rules · `_legal_swaps` in the draft page
A legal XI is exactly one keeper plus at least three defenders, two midfielders
and one forward. Tapping ⇅ arms a swap and lights ONLY the players who can
legally come on, so the formation rule is taught by the interface rather than
enforced by an error. Verified: a keeper only swaps with the other keeper; with
four defenders any position can come on; with three, only another defender can.

Player names in every table are now the click target for the card.

**Not done yet, next up:** the per-gameweek transfer ledger (transfers made at
GW2+, free-transfer accrual capped at 5, hits at -4, and a summary-of-changes
panel), plus the budget/FT strip at the top of the planner. The typography and
icon pass across the draft page is also outstanding. Note that the light/dark
choice lives in session state, so it resets on a full page reload.

### One definition of a draft (2026-08-01, follow-up)
The strategy picker at the top of the Draft page was still the old hardcoded
`DRAFT_STRATEGIES` list, so the page offered bespoke premium modes ("Safe ·
Haaland + Fernandes", "Punt · Fernandes, no Haaland") that the saved drafts knew
nothing about. Two definitions of "a draft" that disagreed.

The picker is now the SAVED DRAFTS. Selecting one loads its recipe into the
dials, and the dials are overrides from there (keyed on the draft id so they
re-read when you switch). A premium call is expressed as a LOCK, which is why
there is no no-Haaland mode any more: that is Optimal without him locked.

`DRAFT_STRATEGIES` is trimmed to the three that change the solver's OBJECTIVE
(Optimal value, Bench Boost GW1, BB GW2 → WC4) · the bench-weighting arms cannot
be expressed as locks. `solve_draft` still understands the removed names so a
stale saved draft keeps working. The Chip Planner shares the list and picked the
change up for free.

**Preset bug fixed at the same time:** the BB presets carried a chip plan but
still solved with `⚖️ Optimal value`, so they planned a Bench Boost on a bench
built not to play. Each chip plan now carries the strategy that builds a squad
capable of it.

### More routes, and a walkthrough of the one you picked (2026-08-01)
Four route experiments added to the presets, all on the Optimal squad because the
chip question is largely separable from the squad question and varying it on one
squad answers it without tripling the picker:

- **BB1 → WC6** · same boost, carry the all-playing fifteen two weeks longer
- **BB3 → WC6** · let the openers settle, boost into a known-good week
- **WC4, no Boost** · the control arm for "is the Boost worth it at all"
- **BB1, no Wildcard** · the control arm for "is the reset worth it"

Thirteen presets total. The Draft page now lands on **Optimal · BB1 → WC4**,
since that is the route under active consideration.

`walk_route()` in `analytics/head_to_head.py` answers what a route name cannot:
what the Boost returns in the week it is played, what the bench is worth in a
normal week, how many players the Wildcard changes and what the reset is worth
over the six weeks that follow it, and how many free transfers are banked by the
time you get there. Rendered at the top of the Chip route tab for the selected
draft, with a week-by-week table marking the chip weeks and flagging any benched
player not expected to play.

**A metric I wrote and then removed:** the first version computed a "carry cost"
as the mean bench points in non-boost weeks and derived a break-even from it.
That is not what carrying an all-playing fifteen costs · the real cost is XI
strength given up by spending on the bench, which needs a second solve and is
already done properly in `season_opener.bb_dilution`. The cheap version produced
"break-even 0.6 gameweeks", which is nonsense. It now reports the bench in a
normal week alongside the boost week and uses the difference to answer the
TIMING question instead, which is what the cheap numbers can honestly support.

Live read on BB1 → WC4: the Boost returns 14.9 against a normal-week bench of
15.0, so the timing is neutral, and the GW4 reset is worth only +2.1 over GW4-9
with 3 transfers banked. On this squad the Wildcard is not buying much.

### Brighter surfaces, better charts, saving from the planner (2026-08-01)

**The app was too black.** Every dark surface lifted a step and warmed toward
blue (`bg` #0B0E13 → #10141F, `s1` #151922 → #1B2131), lines from 0.08 to 0.11
alpha, and a third gradient added to the ground. The tiers now read as separate
planes instead of one black field. Contrast is unaffected: text on bg is 16.2:1.

**Light-mode greys were too thin** for small text: `muted` 0.60 → 0.68 and
`muted2` 0.40 → 0.52. All six light accents now clear 4.6:1 on white (measured,
not eyeballed).

**Buttons.** The kit badges were flat circles with a bare glyph, which read as a
stray dot on a busy pitch · now rounded squares with a lit top edge, a real
shadow and a hover/press state. The table swap control went from a bare "+" to a
labelled "Swap in" pill. Dialog buttons use Material icons
(`:material/swap_horiz: Replace him`) instead of glyph-prefixed text.

**Two new chart types in `ui/charts.py`:**
- `fixture_run_option` · the opening run as bars **coloured by fixture
  difficulty**, opponent on the axis under the gameweek, value on top, and an
  optional expected-minutes line on a second axis. Colour carries the WHY, so
  the run reads without a legend or a tooltip, and a tall bar sitting on thin
  minutes (the trap) is visible immediately. Only the minutes line is legended:
  the bars are individually coloured, so one swatch for them would be a lie.
- `model_spread_option` · the three models as points on ONE axis with a
  connecting rule and the blend as a diamond. Three separate bars make you
  compare heights; one axis makes the SPREAD the thing you see, which is the
  question being asked.

**Player card rebuilt** around four tabs: Opening run, Model agreement, Value for
money, Last season. The new one is **Value for money**: a radar against the
median player of the same position within £0.5m of his price. The filter that
makes it honest is `>= 40` projected points · without it the baseline is dragged
down by two hundred squad players who never start and everyone looks like a
bargain. Haaland correctly reports "too few comparable players" at £15.5m.

**Saving moved to where drafts are built.** The Controls popover now has a name
field, chip pickers and "Save as a new draft", and selects the new draft
immediately. The Compare drafts tab keeps the manage/delete list.

### Graded stats, per-gameweek availability, side-by-side squads (2026-08-01)

**Every number in the player card is now graded**, because "108 projected points"
means nothing on its own. Two kinds of grade for two kinds of number:
- **RANK** against every player in his position that the models rate (points,
  per £m, per 90). Top 10% green, top third amber, the rest red, and each tile
  shows the rank: "2nd of 114 DEF".
- **THRESHOLD** against a bar the rules define. DEFCON per 90 is green at or
  above the bar (10 CBIT for a defender, 12 for a midfielder), amber within 20%
  of it, red below.

**Note a conflict to resolve with Eoin:** he asked for a defender threshold of
20, but his own worked example (10.8 per 90 shown green) matches the bar of 10
that FPL actually uses and that `_defcon_per90` already scores against. The code
uses 10/12; if 20 is right, `DEFCON_THRESHOLD` is the one place to change.

**`miss_gws` · per-gameweek unavailability.** A season minutes cut cannot say
"Garner plays no part in GW1-2", because missing the opening two weeks says
nothing about April. The override schema takes a `miss_gws` list, applied in
`gw_projection` (new source `SRC_MANUAL`), so those cells are zero and everything
downstream (XI selection, Bench Boost value, the simulation) sees it.

Football overrides added from Eoin's reads: Garner out GW1-2; Porro the only
certain Spurs defender; Senesi, Van de Ven and Van Hecke all haircut because the
centre-back pairing is genuinely unknown; Tonali and Fernandes nailed; Maddison
and Kudus lifted to 2400 minutes.

**Pitch:** the axe and swap controls are smaller (17px) and moved OFF the shirt
to its top corners; a gold P sits low-right on a penalty taker and the
low-minutes warning low-left, so nothing collides.

**Comparison:** two squads can now be lined up side by side at any gameweek in
the window, with players unique to each draft marked and sorted to the top ·
the shared players are not the argument.

**Gotcha worth remembering: `st.cache_resource` holds the LIVE object across code
edits.** Adding a method to `GwProjection` gave `AttributeError` on a method
plainly present in the file, because the cached instance predated it. `_projector`
now takes a `_PROJ_VERSION` in its key; bump it when the class changes.

### Optimiser maths corrected, and no more light grey (2026-08-01)

**Two real bugs in how "optimal" was found**, both found from Eoin asking why
Garner kept being drafted while showing 0 expected points:

1. **A missing match-model row was treated as a nailed starter.**
   `ffh_nailedness` is NaN for 148 of 535 players (the Hub simply has no row for
   them) and the minutes gate filled that with 1.0 · so the LEAST certain players
   got the largest benefit of the doubt. Kroupi.Jr on a 0.39 minutes share was
   scored as fully nailed. It now falls back to our own fitted `mins_share`.
2. **A hand-entered absence never reached the solver.** `miss_gws` only applied
   per gameweek, so the season objective happily drafted a player the same
   codebase had scored at zero for the opening weeks. There is now a haircut
   proportional to the share of the OPENING WINDOW missed, not of the season: a
   draft is built for the start.

Effect: Garner 112.1 → 65.7 as the solver sees him, and he leaves the fifteen.
Kroupi.Jr 107.2 → 74.5. Haaland is untouched at 0.944 nailedness.

**No light grey.** Eoin cannot read it: *"I never find light grey writing useful,
I prefer white font on black and black font on white."* `--ff-muted` went 0.64 →
0.86 and `--ff-muted2` 0.46 → 0.66 in dark (0.68 → 0.86 and 0.52 → 0.68 in
light). Measured on a card: muted is now 10.8:1 dark and 11.8:1 light, muted2 is
6.9:1 and 6.1:1. Written up as a user-level skill at
`~/.claude/skills/no-light-grey-text/SKILL.md`, which also covers what to use
INSTEAD of grey for hierarchy (weight, size, space, meaningful colour).

**DEFCON confirmed:** the bar is 10 for defenders and 12 for midfielders, and
clearing it pays a flat 2 points. That is why the card grades on hit rate as well
as the per-90 average · a player who averages 11 by spiking once earns the bonus
far less often than the mean implies.

**Heatmap labels** were being clipped by a guessed 70px gutter. The grid now uses
`containLabel`, column labels rotate 30 degrees when names are long, row labels
truncate at a set width rather than overflowing, and each cell prints its value.

### Saving a team you built, and Hub's season weight (2026-08-01)

**A draft can now carry an explicit fifteen.** The old save stored only the
RECIPE (strategy, locks, dials), so the thing you built by hand on the pitch and
the thing that got saved were different objects · the recipe re-solves to
something else tomorrow. `BASE` gains a `squad` field (15 player codes); when
present the planner uses it verbatim and `build_phases` skips the solve, so the
comparison scores the squad you actually chose.

**Save moved onto the planner**, beside the team it saves: a name box and a
button under the pitch. Saving the same name UPDATES that draft rather than
making a second one, and the button reads "Update" once you are on your own
draft. That is the loop Eoin described: name it, build it, save, tweak, save
again.

**Axing a player now adds his sale price to the money strip.** "In the bank"
becomes "To spend" and reads `£X banked + £Y freed`, because the number you shop
with is the sum, not the leftover.

**Hub's season weight cut 0.25 → 0.15** (ours 0.35 → 0.40, Scout 0.40 → 0.45).
Eoin's read, and it is right: the Hub deliberately does not look far ahead, so
its season figure is a four-gameweek window extrapolated to 38. This changes
nothing about the per-gameweek numbers, where it remains the primary source and
the only stated minutes forecast.

Note `changed_club` already flagged Anderson's move (Forest to Man City) and an
override was already recording the rotation and DEFCON risk that comes with it.

### The draft selector, redesigned (2026-08-01)
The draft is the primary object on the page and it was a plain dropdown hidden
inside a settings popover · you had to open a menu to find out what you had
picked. It is now a row of pills directly under the title:

- **An icon says what KIND of draft it is** · bookmark for a fifteen you saved,
  lock for a premium call, flask for a chip-route experiment, scales for the
  plain optimum. That is information a name alone cannot carry.
- **Labels are shortened to the distinguishing part** and keep the chip plan
  intact, because the chip is usually what differs between two drafts.
- **Your own drafts sort first.** A preset is a starting point; the one you built
  is the one you came back for.
- **One scrolling line, not four wrapped rows.** Fourteen drafts wrapped to 182px
  and pushed the pitch off a laptop screen; the row is now 39px and scrolls.
  The wrap lives on the inner `[role=radiogroup]`, not on `stButtonGroup` ·
  styling the outer element does nothing.
- Selected pill takes the accent as a **fill**, not a tint. Targets are
  `[data-testid^="stBaseButton-pills"]` and `stBaseButton-pillsActive`.

Under the pills, one line states what the selection IS: a kind chip, the full
name, and the facts (locks, chip plan). The cost-of-conviction readout folded
into a single line with it and is colour-graded, which is how we can now see at
a glance that locking Fernandes + Mosquera + Haaland costs **-52 projected XI
points** against the free optimum.

Net effect: the pitch moved from y=664 to y=500.

### Sidebar, navigation and comparison identity (2026-08-01)

**Sidebar.** The FPL purple against near-black was the harshest edge on the
screen. It is now blue-slate in dark (`#1A2740`) and light blue in light
(`#E7F0FB`), driven by four new tokens (`side`, `side2`, `side-ink`,
`side-line`) so it follows the theme like everything else. Sidebar ink measures
13.1:1 dark and 13.7:1 light, and the sidebar-to-content luminance ratio dropped
to 2.88, which is what removes the slab effect. Nav links gained a resting hover
and a real selected state (mint inset rule) instead of relying on contrast.

**Navigation regrouped** from six sections to four by INTENT: Play (this week),
Plan (draft, transfers, chips), Stats (research), History. Nineteen links at once
was a directory, not navigation.

**Gotcha:** Streamlit sets `visibility: hidden` on `[data-testid="stNavSectionHeader"]`
when `st.navigation(..., expanded=False)`. The categories ARE the navigation
here, so the CSS forces them visible; without that the groups render as unlabelled
gaps.

**Draft identities.** Comparing drafts by name meant the same long string in five
places, truncated differently each time, in a green multiselect box that read as
a tag rather than a selection. Each compared draft now gets a stable identity ·
a LETTER, a colour and a shape · used by the key row, the ranked table, the
range bands, the cumulative lines, the win bars, the head-to-head grid and the
squad columns. The shape matters as much as the colour: it keeps the comparison
readable in greyscale and for a colour-blind reader.

The setup is now numbered (1 choose, 2 window, then run), and the run button is
primary and disabled until two drafts are picked.

**Side-by-side squads gained a Pitch view**, the same compact pitch the planner
uses, with players unique to that draft ringed in mint. A list is right for
scanning numbers; a pitch is right for seeing a team.

**Foden override added**: 2400 minutes, on Eoin's read that he starts the opening
weeks under the new City manager. His 25/26 rate was 5.67 per 90, so the rate was
never the question · only the minutes. Season projection 94.5 → 113.7.

### Pitch cards, top-three picks, richer filters (2026-08-01)

**Every player sits on a card now.** A light translucent panel with a defined
edge, a lit top border and a soft shadow, so the kit and its numbers read as one
object instead of floating on grass. That edge is what lets the cards pack
tighter (68px wide compact, gaps down to 5px) without the rows blurring into
each other · and it lifts the text off a busy background, so the nameplate lost
its black slab and now uses a text shadow.

**Sidebar is light blue in BOTH themes** by request, with near-black ink (13.2:1
dark, 14.1:1 light) and a deep-green accent for the selected page and the
category headers. This is the one surface that deliberately does not follow the
theme.

**Axing a player now answers the question.** The top three affordable
replacements appear as ranked cards (rank badge, face, price delta, next three
fixtures, points over the next four gameweeks, expected minutes) with a one-click
"Bring in" under each, above the full 22-row list. Twenty-two rows is a research
tool; three cards is an answer, and an answer is what you want the moment you
take someone out. Ranked on the horizon, not on the single gameweek.

**Pool filters rebuilt:** position as a segmented control (four options should
never need typing), a name search, a club picker, a max-price slider, and the
important one · **a horizon slider (default 4)** that re-ranks the whole table on
expected points over the next N gameweeks from the one you are viewing. "Best
next week" and "best over the next eight" are different questions and the table
now answers whichever you are asking, with a matching column.

**Still open · the big one:** making the side-by-side comparison INTERACTIVE ·
stepping gameweeks inside it, making trial transfers and swaps on either squad,
and having each side track its own budget, transfers used and chips. That is a
feature in its own right, not a tweak, and it is the next thing to build.

### Gameweek stepping in the comparison, glossier sidebar (2026-08-01)

**The side-by-side steps through gameweeks.** A prev/next stepper with a live
readout of each draft's XI points for that week, beside its letter badge. The
squads barely change week to week but the FIXTURES do, and that is what moves
the numbers · stepping GW1 to GW2 re-picks both best elevens (formation went
4-4-2 to 4-3-3, the keeper changed) and repaints every fixture chip.

**The run is cached against `(picks, window, sims, board)`.** Without it every
gameweek step re-solved up to nine MILPs and re-ran 1500 simulations, which made
the stepper unusable. It reuses the stored `entries` and `sim` unless the button
is pressed again or the inputs change.

**Sidebar is a brighter, glossier light blue:** `#EAF6FF` to `#BFE1FF` with a
white sheen over the top fifth, an inset highlight down the right edge and a soft
outer shadow. Ink stays at 12:1 against the darkest part of the gradient.

**Still open:** trial transfers and swaps INSIDE the comparison, with each side
tracking its own budget, transfers used and chips. Stepping the weeks is done;
editing the squads in place is the remaining half.

### Review response · three P0s fixed, compare-all added (2026-08-01)

Acted on `docs/DRAFT_PAGE_IMPROVEMENT_PLAN.md` after verifying its claims rather
than taking them on trust. Three were real and are fixed:

1. **`_one_line` was eating words** · it joined stripped lines with "", so any
   prose that wrapped in the source welded together ("costs 0.6 pts a" +
   "gameweek" -> "pts agameweek"). This was MY helper and the bug was systemic,
   not one card. Fixed to insert a space only where a word meets a word or a
   word meets an inline tag, so chips stay flush. Six join cases tested.
2. **A recipe-only save wiped a saved fifteen** · `save_draft` rebuilt the entry
   from `BASE`, so any save without a `squad` nulled one. Now it starts from the
   stored entry and only an explicit non-None value overrides.
3. **`_write` was not atomic** · a truncated write left `saved_drafts.json`
   empty, `_read` returned {} and `load_drafts` re-seeded presets over the top,
   destroying every user draft. Now writes a temp file, fsyncs and `os.replace`s.

Also added the **compare-all shortcuts** Eoin asked for (all / just mine / clear)
and extended `_ID_LETTERS` to A-Z, since "compare all" passes fourteen drafts and
a repeated identity letter is worse than none.

Note the plan predates this session's caching work: P1-1 (cache the Monte Carlo)
was already done via `_ab_cache`, and the gameweek stepper in P2-3 already exists.

## 2026-08-01 (evening) · Draft-page hardening pass

Worked the improvement plan end to end on branch `draft-page-hardening`.
Tests went 75 → 184.

**Two football findings that changed the model.**

*DEFCON is a player property, not a manager system.* Tested Eoin's hypothesis
that Iraola's move to Liverpool makes Van Dijk a DEFCON asset. Variance
decomposition on 2025-26 defenders: only **16.4% between-club**, 83.6% within.
Player rate persists year to year at r = 0.79-0.80, club rate at 0.55-0.56.
Bournemouth's own defenders under one manager ran 11.50 (Senesi) to 5.15
(Smith). The direct test he asked for cannot be run: the archive has **no
CBIT data at all for 2019-20 to 2024-25**, because FPL's API only exposed
defensive actions in the early era and again from 2025-26.

*Promoted clubs DO lift their defenders.* +5.6% defensive actions pooled over
the three seasons that carry action counts, and 8 of 9 promoted club-seasons
finished above the league median (binomial p = 0.02). **Midfielders show
nothing** (p = 0.96). Turning that into points needs the threshold: a
multiplicative lift on an integer match count changes nothing, since 9 x 1.056
is still under 10, so the lift goes on the underlying rate. Through a negative
binomial fitted to the observed overdispersion it is worth about **+2.5 season
points**, which COV/HUL/IPS defenders now receive. See `analytics/promoted.py`.

**Bugs found and fixed.**

- **Archive 2024-25 had `team_name = ""` on all 27,283 rows.**
  `master_team_list.csv` stops at 2023-24 and the fallback was an empty map, so
  the season was invisible to every club-level query. Per-season `teams.csv`
  covers the gap with identical club naming.
- **Cross-draft state bleed.** Transfers, axed player, manual XI and viewed
  gameweek were global, so switching preset carried the previous draft's
  transfers onto the new fifteen. Now scoped by draft id.
- **Ties in the Monte Carlo.** Win probability used a strict `>`, but shared
  draws mean identical squads produce identical totals, so each reported
  "beats the other 0%" instead of a dead heat. Ties now count as half.
- **Caches keyed on `len(board)`.** A snapshot refresh changes numbers, not row
  count, so the stale projection survived the edit meant to change it. Now a
  content stamp (`analytics/freshness.py`).
- **Light mode**: the squad header hardcoded white and vanished on the white
  page background.
- **Two different "XI GW1" numbers** on one screen · the tile doubled the
  captain, the pitch summed the cards.

**Claims in the plan that did NOT survive checking.** `draft_bench` is not a
dead session key (used twice). `solve_draft` and `_routes` were already
`cache_data` and the planner was already a fragment, so a pool keystroke was
never rebuilding the route MILPs.

**Not done, deliberately.** FPL-5 price-rise timing and FPL-6 fixture-swing
view; ENG-2 extracting `planner()` and `tab_ab` into `ui/draft/` (a ~1,200-line
move that would freeze the layout while the design is still changing weekly);
DS-4 the calibration harness, which needs real gameweeks to log against.
Also still open: the light/dark choice resets on hard reload, and the tab
scroll position resets on tab change.
