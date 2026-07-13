# FPL Analytics App · Claude Onboarding

Fantasy Premier League analytics web app. Data-driven transfer, captain, and team-selection decisions. Streamlit + Python 3.8.

**Read `docs/WORKFLOW.md` for current session history, architecture depth, data sources, and known bugs.** This file is the short briefing.

## Run
```bash
streamlit run app.py                       # http://localhost:8501
streamlit run app.py --server.port 8510    # the user's current dev port
```

## How to work on this project

The user wants the app at **10/10 quality**. Three expert hats, always:

1. **Product Designer** · simple, scannable UIs. Less words, more visuals. Strong hierarchy.
2. **Data Scientist** · real signal, real numbers. Verify the math. Flag when data is stale or wrong.
3. **AI / Full-stack Engineer** · clean Streamlit patterns, no flaky components, reproducible fixes.

### Priorities, in order
1. **Fix things that are broken.** Broken numbers > ugly UI. Always triage this first.
2. **Aesthetics second.** Use the design system below · never invent a one-off style.
3. **Real assets.** When adding imagery, use kits, team crests, PL logo (in `assets/prem_symbol.jpg`). No stock emoji-only fluff when a real image exists.

### Working cadence
- **Section by section.** The user redesigns one page at a time · don't parallel-rewrite the whole app.
- **Overhauls are allowed to be big.** When the user asks for an overhaul, commit fully: drop redundant sections, restructure, don't patch.
- **Ask before destructive changes.** But within aesthetic/layout scope, make the call · the user prefers confident direction over checklist questions.

## Design system

This is binding. If you invent a new colour or spacing, you're drifting · stop and re-use tokens below.

### Colours
```
Background         #151922   (primary)
Secondary BG       #1e2430
Card BG            rgba(22,26,34,0.85)
Card border        rgba(255,255,255,0.08)
Text primary       #eef1f5
Text muted         rgba(255,255,255,0.5)
Text very muted    rgba(255,255,255,0.4)

Accents:
  Mint (primary)   #00FF87   · positive, captain-not, "score" numbers
  Gold             #FFD700   · captain, premium, top-pick emphasis
  Cyan             #04f5ff   · secondary info, xP / xGI
  Red              #FF4B4B   · danger, sell, high FDR 5
  Orange           #FF8C42 / #FFA500 · warnings, FDR 4
  Magenta          #e90052   · MID position, highlights
  FWD Orange       #FF7B00

Position chips   GKP #00FF87 · DEF #04f5ff · MID #e90052 · FWD #FF7B00
FDR colours      1/2 green · 3 yellow #FFD60A · 4 orange #FF8C42 · 5 red #FF4B4B
```

### Typography
- Font: `'Inter','SF Pro Display',sans-serif`
- Hero title: **40–48px, weight 900, letter-spacing -1.2px**
- Section heading (underline style): **11px, weight 800, letter-spacing 0.22em, uppercase**
- Stat number: **18–28px, weight 900**
- Stat label: **10–11px, weight 800, letter-spacing 0.1–0.18em, uppercase**
- Body: **13–14px, line-height 1.5**

### Cards
- Base: `rgba(22,26,34,0.85)` + `1px solid rgba(255,255,255,0.08)` + radius **10–18px**
- Padding: **16–28px** depending on card size
- Accent strategy: top-border 3px in the accent colour (nav tiles, decision cards) OR left-border 3px (alert cards)
- Hover lift via `.fplh-card-hover` utility (defined in `components/animations.py`)

### Layout
- Section headers use a **muted underline** treatment: 11px uppercase tracked label + flex-grow hairline divider
- Responsive card grid: `grid-template-columns:repeat(auto-fill,minmax(320–340px,1fr)); gap:14px`
- Stat strips inside hero: flex gap 10px, min-width 120px per tile
- Never use `st.metric` for a custom hero · build tiles as HTML to match the system

### Images / assets
- **Club visuals go through `components/team_identity.py`** · `shirt_html(team_code, is_gkp, width)` (the standard shirt+crest block), `shirt_url`, `badge_url(team_code)` (PL crest CDN `resources.premierleague.com/premierleague/badges/50/t{code}.png`), and `team_color`/`team_color_pair` (palette in `config.TEAM_COLORS`, keyed by `team_short`). Never re-declare a local shirt helper · import from here. Render badges with `onerror` hide so a CDN hiccup degrades gracefully.
- **Gotcha: analytics engines whitelist columns.** Crests need `team_code` and colours need `team_short` on the rendered row. Several engines prune columns (`differentials.get_differentials`, `xg_divergence`, `transfer_engine.get_transfer_targets`, `points_model` predictions) · both `team_code` and `team_short` are now in those whitelists. If crests all show one club or colours fall back to green, a new/edited engine dropped those columns.
- PL lion logo lives at `assets/prem_symbol.jpg`. Loaded via `_pl_logo_data_url()` in `pages/home.py` (base64 cached).
- Player shirts served from FPL CDN: **outfield** `shirt_{code}-66.png`, **goalkeeper** `shirt_{code}_1-66.png`. Helper in every page that renders players. *Do not invert the suffix* · the `_2` suffix does not exist and was the source of the "everyone in a keeper kit" bug.
- When the user gives us new imagery (team kits, player headshots), drop into `assets/` and base64-embed via a cached helper · don't rely on Streamlit static serving.

### Animations (module: `components/animations.py`)
Call `inject_global_animations()` at the top of every page. Provides:
- `.fplh-animate-in` · fade-in-up entrance
- `.fplh-stagger > *` · staggered children entrance (use on grid wrappers)
- `.fplh-card-hover` · lift + green border on hover
- `.fplh-captain-pulse` · infinite gold glow (captain badge)
- `.fplh-pop` · scale-in pop
- `scribble_swap_overlay(out, in)` · full-screen SVG scribble shown on squad swaps
- `confetti_burst()` · celebration overlay (not wired yet; use for captain-confirm moments)

### Rules that prevent UI drift
1. **Rounded everything to 2dp.** Every numeric column on every page.
2. **Short names.** Players truncated with ellipsis, no wrapping. 10–12 chars cap on cards.
3. **Less text.** No paragraph descriptions on nav tiles. Section purpose explained by the section title + section content, not a sub-caption.
4. **No duplicate sections.** If a dedicated page exists (e.g., Transfers, Captain), link to it · don't re-render a smaller copy inside another page.
5. **Never call `st.rerun()` in a button handler.** Streamlit already reruns on click. Double-rerun caused a race with the animation overlay SVG mount (TypeError).
6. **Streamlit strips `style` attributes that contain only CSS custom properties.** `<span style="--x:5">` arrives with no style attribute at all. Carry custom-property values in a per-instance `<style>` rule instead (see `animations.count_up`).
7. **No em dashes anywhere.** UI copy, comments, commit messages. Use the mid-dot `·`, a comma, or a full stop.

## Stack
- **Python 3.8** · always use `List`, `Dict`, `Optional`, `Union` from `typing`. Never `list[x]` or `dict[x]`.
- **Streamlit + Apache ECharts** (`streamlit-echarts`) for UI/charts · every chart goes through the shared helpers in `ui/charts.py` (one dark theme, transparent grounds). Plotly is gone — do not reintroduce it.
- **No database.** JSON cache with TTL in `data/cache/` · safe to delete for cold fetch.
- **All weights, thresholds, scoring constants → `config.py`.**

## Key files
| File | Purpose |
|------|---------|
| `app.py` | **Router / entrypoint** · owns the sole `set_page_config`, global CSS, shared data-load into `session_state`, sidebar branding, and `st.navigation` (6 grouped sections). Calls `nav.run()`. |
| `pages/home.py` | Home landing · GW hero + deadline countdown + live-pulse strip (moved out of `app.py`) |
| `config.py` | Tunable constants (weights, thresholds, lookahead) + `TEAM_COLORS` club palette |
| `components/team_identity.py` | **Single source for club visuals** · `shirt_url`, `badge_url` (PL crest CDN), `team_color`/`team_color_pair`. Replaces the shirt helper previously copy-pasted across ~9 pages. |
| `components/loading.py` | **Themed loader** · `fpl_loader(title, messages)` context manager (rolling-football overlay + rotating status lines). Use with `@st.cache_data(show_spinner=False)` so the raw default spinner never leaks a function name. Message pools: `LINES_SQUAD/SOLVER/MODEL/GENERIC`. |
| `components/animations.py` | Global CSS + scribble overlay + confetti |
| `components/pitch_view.py` | FPL-style pitch with captain pulse |
| `components/player_table.py` | Styled DataFrame (2dp everywhere) |
| `components/badges.py` | Set-piece / DEFCON pill badges |
| `data/fetchers/fpl_api.py` | FPL API + `team_code` / `team_short` propagation |
| `data/fetchers/understat.py` | Understat with **dynamic season** (auto-derives from date) |
| `data/fetchers/fbref.py` | FBRef with **dynamic season** |
| `data/processors/player_stats.py` | Central data merge |
| `analytics/transfer_engine.py` | Transfer scoring + ceiling + recommendation |
| `analytics/differentials.py` | Smarter tagged differentials model |
| `analytics/xg_divergence.py` | xG under/overperformers |
| `data/processors/archive.py` | 10-season historical archive (gw_archive + season_summary parquet) |
| `analytics/squad_milp.py` | Exact single-period squad MILP (PuLP) · use over greedy for new work |
| `analytics/perfect_season.py` | Hindsight-optimal season MILP (set-and-forget + transfers + chips) |
| `analytics/price_predictor.py` | Next-season start-price model (XGBoost on season-pairs) |
| `analytics/season_projection.py` | Next-season points projector (fitted minutes + pp90 carryover) |
| `analytics/playbook.py` | Empirical strategy answers (formation, defenders, hits, minutes, horizons) |
| `assets/defender_roles_2025_26.json` | Curated CB/FB labels (user-editable; refresh each season) |
| `docs/WORKFLOW.md` | Session log, data source matrix, full architecture |

## Navigation & pages
Nav is **grouped via `st.navigation`** in `app.py` (Streamlit ≥1.36). Five
sidebar sections (slimmed 2026-07; Dashboard + standalone Planner deleted):
**This Week** (Home, My Team, Captain) · **Transfers** (Transfers, Buy/Sell,
Injuries) · **Chips** (Wildcard, Free Hit, Chip Planner) · **Scouting**
(Differentials, xG Tracker, Predictions, Ownership) · **Data Science Lab**
(Perfect Season, Value Lab, Playbook, 26/27 Draft, GW History, Mini-League).
The My Team pitch IS the transfer planner · do not re-add a planner page.

**Page files live in `views/`, NOT `pages/`.** `pages/` is reserved by Streamlit's
automatic multipage system and collides with `st.navigation` (symptom: doubled/broken
sidebar + a "st.navigation was called in an app with a pages/ directory" warning).
Never recreate a top-level `pages/` folder. `st.Page("views/…")` and
`st.page_link("views/…")` reference paths relative to the `app.py` entrypoint.

**Rule: pages must NOT call `st.set_page_config`** · only the `app.py` router may.
Adding it to a page raises a Streamlit error under `st.navigation`.

Page files: `home` · `00_my_team` · `02_transfer_suggestions` ·
`04_differentials` · `05_xg_underperformers` · `06_captain_picker` ·
`07_buy_sell` · `08_injuries` · `09_wildcard` (✅ MILP) · `10_ownership_trend` ·
`11_gw_history` · `12_predictions` · `13_free_hit` · `14_chip_planner` ·
`15_mini_league` · `16_perfect_season` · `17_value_lab` · `18_draft_2026_27` ·
`19_playbook`. (Deleted: `01_dashboard`, `03_transfer_planner`.)

## My Team pitch planner (2026-07)
The Pitch View timeline scrubs history (GW1..now) AND future planning weeks.
Off-season, `SIM_HORIZON` (config) future GWs are simulated: GW1..5 fixtures
replay as GW39..43. In a future week every kit gets a permanent ✕ (transfer
out) and the kit opens a Player Intel dialog. Clicks are FLUID: the pitch
renders through `components/pitch_click/` (a minimal bidirectional Streamlit
component · data-ffaction/data-ffid elements report {action, id, nonce} over
the websocket; dedupe on nonce). Never regress to `<a href="?...">` links ·
they full-reload the app and wipe session state. `?gw=41` deep links still
jump the scrubber. Working moves persist as DRAFTS on disk via
`analytics/squad_planner.py` (`data/cache/squad_plans.json`, schema
{plans, drafts}); Save promotes draft→plan. FT banking: 1/week, +1 per week
with no saved transfers, cap 5; extras cost −4 (red badge). `effective_squad()`
applies saved plans cumulatively when scrubbing forward.

**xP comes from `analytics/xp_engine.py`** (per-player, per-GW horizon:
form/ppg blend × minutes factor × per-fixture ease, DGW/BGW aware, calibrated
to ep_next's scale) · the planner pitch, Net xP chip and replacement panel all
show the VIEWED week's projection, and head-to-heads add an "xP next N GWs"
row. **"✨ Optimise my next 5 weeks"** (`analytics/plan_optimizer.py`) greedily
plans like-for-like swaps over the horizon (budget, ≤3/club, FT banking,
hits only past a margin, bench-discounted, minutes-gated) and writes the
result as timeline drafts with a summary dialog + save-all. The replacement panel
ranks by player-level signals (form 0.45 + xP 0.30 + fixtures 0.25 · club-level
FDR alone clumps the list by team); each candidate has ⚖ head-to-head vs the
axed player (fixtures, winner-highlighted stats, xP/price verdict, radar
overlay). Player radars always compare vs the ±£1m positional price band
(`ui/player_detail.price_band_baseline`).

More planner rules (2026-07-13): the whole planner runs inside `@st.fragment`
(in-fragment actions use `st.rerun(scope="fragment")` · dialogs keep app
scope). Multi-axe: ✕ queues any number of players (`plan_axes` session list,
pooled budget, radio slot picker); ✕ again un-queues. Plan entries are dicts
{transfers, captain, chip} (legacy bare lists normalise on read) · captain set
from the Player Intel dialog, chip via the per-week selectbox; WC/FH are
hit-free and don't consume FTs, FH squads revert next week, BB/TC feed the
Squad xP chip. Player photos: resources.premierleague.com/premierleague25/
photos/players/110x140/{code}.png (plain code, no 'p' prefix) with kit
fallback. `ui/player_detail.intel_lookup(universe)` is the app-wide intel
expander. Off-season the squad fetch's form is 0.0 for everyone · My Team
overrides it from the universe (self-healed) or captain scores break.

## Data gotcha · player xG
Understat matches by name and silently misses most players. `build_player_universe()` backfills `xg`/`xa` from FPL Opta season totals (joined at source, full coverage guaranteed). The stable player `code` is on the universe · always join archive data by `code`, never by name.

## Season Lab data (do NOT delete)
`data/cache/archive/` holds the one-shot 2025-26 FPL API harvest (the API wiped this data at the 2026-27 launch) plus the 10-season archive. Rebuild archive: `python scripts/build_archive.py`. Perfect Season rerun: `python scripts/run_perfect_season.py`. The generic `data/cache/` purge advice does NOT apply to `data/cache/archive/`.

## Team
- Default team ID: **38148** ("Vicario Kart"), manager Eoin Houstoun
- Track the private mini-league (not the public `Spurs & Ireland` type ones · those are league_type `s`, the user wants `c`)

## Credentials
`.env` file at project root (gitignored). Keys:
- `FPL_TEAM_ID=38148`
- `FFH_EMAIL=` / `FFH_PASSWORD=` · **awaiting user fill**. Once provided, build `data/fetchers/ffhub.py` and wire into `build_player_universe()`.
- `FPL_EMAIL=` / `FPL_PASSWORD=` · optional, unlocks private-league endpoints.

## Known data gotchas (verify against current code)
- **Season is dynamic.** `understat.py` and `fbref.py` both derive the active season from today's date. If caches look stale after season rollover, delete `data/cache/` contents.
- **`team_code` must be on `players_df`.** Fix is in `get_players_df()` · added `team_code` + `team_short` at source. Shirt rendering depends on it; without it, every player falls back to Arsenal's shirt.
- **Analytics engines whitelist output columns.** `differentials`, `xg_divergence`, `transfer_engine.get_transfer_targets`, `points_model` prune columns · `team_code` + `team_short` must stay in those lists or crests/colours break. (Fixed; watch when editing.)
- **Kit URL convention.** See Design System § Images. The `_1` suffix is **GK only**.
- **Off-season `form` is 0 for everyone.** FPL's `form` = avg points over the last 30 days; in the summer with no recent matches the API returns 0.0 for all players. Not an app bug. **Fixed:** `build_player_universe` substitutes `points_per_game` for `form` when the whole column is zero (flagged `form_is_fallback=True`); self-heals when real form returns. So all form-based ranking stays meaningful off-season.
- **Off-season has no "next gameweek".** The `🧪 Simulate GW39` sidebar toggle (in `app.py`, default on when `season_phase=='offseason'`) makes `build_player_universe(simulate_gw=39)` clone GW1 fixtures as GW39 so fixture/FDR tools work. `session_state.current_gw` stays REAL for squad fetch; only the universe fixtures are simulated. Turn off when the real season launches.

## Recent architecture (2026-07 overhaul)
- **`app.py` is a `st.navigation` router** · 6 grouped sidebar sections; page files live in **`views/`** (NOT `pages/` · reserved name collides with `st.navigation`). Pages must not call `set_page_config`.
- **`components/team_identity.py`** · `shirt_url`/`shirt_html`, `team_color`/`team_dot` (crests removed: PL crest CDN unreachable → team-colour dots instead).
- **`components/loading.py`** · `fpl_loader()` themed spinner.
- **`views/home.py`** · GW command center (captain/transfer/chip/risk cards) + honest season/sim banner.
- **`views/03_transfer_planner.py`** · real planner: sell→buy verdicts (strong/positive/lateral/negative/avoid) + multi-move plan with hit costs, reuses `transfer_engine.score_players`.
- **`views/00_my_team.py`** · "✏️ Lineup" tab (subs/captain + live xP) and enhanced "🔁 Pick Team / Transfers" edit mode (search + sort + full replacement list).
- **`views/18_draft_2026_27.py`** · Minutes-First Target Board (nailed value / premium / rotation-risk / enabler lanes + scout questions).

## Current priorities (pulled from user)
Done in the 2026-07 overhaul: grouped nav, team-identity/crest→dot visual rollout (all card pages), honest season framing, GW39 off-season sandbox, Minutes-First Target Board, Transfer Planner with verdicts, My Team Lineup editor + enhanced Pick Team transfers, fun loaders, keeper-kit + white-circle bug fixes.

Open / next up:
1. Mobile responsiveness · fixed-width HTML cards for phone viewing.
3. When 2026-27 launches: re-run Target Board with real prices + promoted clubs; refresh `defender_roles` file; turn off GW39 sim.
4. Wire FFHub once credentials arrive (biggest accuracy upgrade).
5. Mini-league: default to **private** leagues (league_type `c`), toggle for public.

## Do not
- Write Co-Authored-By / AI attribution in git commits.
- Use the work GitHub (`Eoin-Houstoun`) · this is a personal project, use `EoinHoustoun`.
- Invent new design tokens.
- Re-render dashboards that already live on a dedicated page · link instead.
- Call `st.rerun()` inside a button handler.
