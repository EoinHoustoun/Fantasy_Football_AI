# 2026-27 Season Rollover · Design Spec

**Date:** 2026-07-24
**Status:** Approved (design), pending implementation plan
**Scope:** Phase 1 of a two-phase effort. Phase 2 (value-verdict engine) gets its own spec once Phase 1 lands.

## Context

The FPL API has flipped to 2026-27: 20 teams, 555 players, real prices set
(Haaland 15.5, B.Fernandes 12.0, Palmer/Saka 9.5), GW1 deadline 2026-08-21.
`is_current` is empty, `is_next` is GW1, nothing finished. The app already
classifies this as **preseason** via `get_season_phase()`, which means the
off-season GW39 sandbox is designed to stand down automatically and projections
"firm up with real data".

The app fetches players, prices, fixtures live from the FPL API. Player faces
and jerseys are CDN-keyed by player `code` and `team_code`, so they follow
automatically once the new bootstrap is loaded and team identity is complete.
The 2025-26 season is already archived in `data/cache/archive/` (the one-shot
harvest the API wiped at launch) and must be preserved verbatim.

So the rollover is not a rebuild. It is a controlled cache refresh plus closing
three concrete gaps, then a verification pass.

## Goal

The app runs live on real 2026-27 data. 2025-26 is preserved intact as the
archive and its tools (Perfect Season, GW History, Value Lab) still read it.
Every page renders with real prices, correct clubs, faces and jerseys, and no
crashes in the zero-gameweeks-played preseason state.

## Non-goals

- The value-verdict engine (under-priced / necessity / overpriced). That is
  Phase 2, its own spec.
- Any new nav page or visual redesign.
- Confirmed 2026-27 line-ups or minutes (unknowable pre-season).

## Units of work

### 1. Cold cache refresh
The disk cache (`data/fetchers/fpl_api.py` `_fetch`) is TTL-gated and the
off-season `fpl_bootstrap.json` / `fpl_fixtures.json` copies are stale, so a
refetch is expected on next load. To make it deterministic:

- Delete `data/cache/fpl_bootstrap.json` and `data/cache/fpl_fixtures.json`.
- **Do not touch `data/cache/archive/`** (irreplaceable 2025-26 harvest) or the
  `vaastav_*` / `*.parquet` / model bundles (10-season archive).
- Restart the app (or clear the Streamlit `@st.cache_data`) so `load_bootstrap`
  picks up the fresh disk fetch.

**Acceptance:** `get_season_phase(bootstrap)['phase'] == 'preseason'`, live=True,
`next_deadline` = 2026-08-21, `get_current_gameweek()` returns 1, and the Home
banner shows the preseason state.

### 2. Two new clubs
`config.TEAM_COLORS` covers 28 historical clubs but is missing the two 2026-27
promoted sides not seen recently: **COV (Coventry City)** and **HUL (Hull
City)**. Everything else in the 20-team set is already keyed.

- Add `COV` and `HUL` to `TEAM_COLORS` with real primary/secondary club colours,
  matching the existing entry shape.

**Acceptance:** for all 20 clubs, `team_color`/`team_dot` return a real colour
(no green fallback), and shirts/faces render on a page that lists players from
Coventry and Hull.

### 3. Off-season sim stands down
In preseason, `app.py` only shows the `🧪 Simulate GW39` toggle when
`phase == 'offseason'`, so it should disappear on its own and `simulate_gw`
stays `None`.

- Verify the toggle is gone and `st.session_state.current_gw == 1`.
- Grep for any hard-coded GW39 / `simulate_gw=39` outside the off-season guard
  and neutralise it.

**Acceptance:** no GW39 sim toggle in preseason; universe fixtures are the real
GW1+ fixtures, not cloned GW39s.

### 4. Preseason degradation (primary risk)
Preseason has **zero gameweeks played**: `form` is 0 for everyone, there is no
gw-history parquet for 2026-27 yet, and live per-GW xP has no matches to lean on.

- Confirm `build_player_universe` builds cleanly with no played GWs (the
  form -> points_per_game fallback already exists; verify it triggers).
- Walk the history/xP-dependent surfaces (My Team xP, Predictions, GW History,
  Captain) and confirm each shows an honest empty-state or archive-based view,
  never a crash or a misleading zero.

**Acceptance:** every page loads; any surface that genuinely needs played
gameweeks says so plainly instead of erroring.

### 5. Defender roles
The loader `analytics/playbook._load_defender_roles(season)` already reads
`assets/defender_roles_{season}.json` per season, so no code change is needed,
only the data file.

- Create `assets/defender_roles_2026_27.json` seeded from the 2025-26 file for
  players who stayed, flagged as provisional; leave it user-editable and refine
  as line-ups confirm. Loader must tolerate a missing/partial file (returns
  empty, no crash).
- Update the two copy references in `views/19_playbook.py` that name the
  2025-26 file.

**Acceptance:** Playbook loads with the 2026-27 roles file; missing entries
degrade to the stat-based fallback, not an error.

### 6. Verification pass
Load the app on port 8510 and walk: Home, My Team, 26/27 Draft, Predictions,
Value Lab, Perfect Season, GW History, Playbook.

**Acceptance:** real 2026-27 prices show, all 20 clubs render correctly with
faces/jerseys/dots, archive tools still read 2025-26, no tracebacks.

## Data preservation contract

Untouched by this work: `data/cache/archive/**`, every `vaastav_*` and
`*.parquet` file, `points_model_bundle.pkl`, `xgb_tuned_params.joblib`,
`perfect_season_2025_26*.json`. Only the live `fpl_bootstrap.json` and
`fpl_fixtures.json` caches are refreshed.

## Risks

- **Stale Streamlit cache masks the refresh.** Mitigation: delete disk caches
  AND restart / clear `@st.cache_data`.
- **External sources (Understat/FBRef) empty in preseason.** Expected; they must
  degrade to FPL-only universe, not block the load. Verify in unit 4.
- **A page assumes >=1 played GW.** Caught in unit 4/6; fix with an empty-state.

## Phase 2 preview (not built here)

`analytics/value_verdicts.py` joins actual 2026-27 price with archive-based
projected points to bucket players: Value (under-priced), Necessity (must-have),
Overpriced (pedigree but too dear), Fair, and Scout/unknown (no history,
flagged, no invented numbers). `views/18_draft_2026_27.py` upgrades into the
live Value Board. Separate spec.
