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
