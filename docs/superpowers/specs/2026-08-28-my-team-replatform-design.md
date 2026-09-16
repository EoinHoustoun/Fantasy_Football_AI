# My Team · re-platform the forward planner onto the Draft stack

Date: 2026-08-28 · Branch: `draft-page-hardening` (or a fresh branch off it)
Status: approved approach (option A), spec for review

## 1. Goal

When Eoin scrubs My Team forward to a future gameweek, the page answers
**"what is the best move this week?"** with the same engine the 26/27 Draft
uses, so one expected-points number, one transfer ledger, one player card and
one "is the gap real" test exist in the app.

Today My Team runs a private stack (`analytics/xp_engine.py`,
`analytics/plan_optimizer.py`, its own FT ledger in `squad_planner.py`, a raw
`st.dataframe` replacement panel, a hand-rolled head-to-head and a second
player dialog). None of the Draft's summer work reaches it.

## 2. Non-goals (first pass)

- Chip placement. The Chip Planner owns it; My Team only records the chip
  chosen for a week, as it does now.
- The greedy multi-week optimiser ("Optimise my next 5 weeks"). It is removed
  in this pass and returns in phase 2 rewritten on the new projector.
- The hero, the history scrub (past GWs), the Lineup tab, the Squad Table tab
  and the Season Trend section are untouched, except where they must read the
  new plan schema.
- Any change to the Draft page's behaviour. It only loses code to shared
  modules.

## 3. Architecture

Three layers, the top one being the only Streamlit-aware one.

### 3.1 `analytics/team_plan.py` (new, pure Python, fully unit-tested)

Owns the plan state for a REAL team, keyed by player `code` (the stable FPL
identity the Draft already uses; `fpl_id` is season-local).

```python
Entry = {"swaps": {out_code: in_code}, "captain": code|None, "chip": str|None}
Plans = {gw: Entry}                        # saved
Drafts = {gw: Entry}                       # working, overrides saved for that gw

load(team_id) -> (plans, drafts)           # reads data/cache/squad_plans.json
save_plan / save_draft / clear_draft / clear_all(team_id, gw, entry)
migrate_v1(entry, code_by_fpl_id) -> Entry # legacy {transfers:[{out_id,in_id..}]}
effective_codes(start_codes, plans, drafts, up_to_gw) -> List[code]
      # replays every saved week <= up_to_gw, then the draft for up_to_gw;
      # a Free Hit week applies for that week only and reverts after
ledger(plans, drafts, up_to_gw, start_codes, first_gw) -> Dict
      # thin wrapper over squad_rules.transfer_ledger with the real season's
      # rules: FTs accrue from first_gw (the first planning week), 1 per
      # week, banked to FT_CAP=5, oldest spent first, rest at -4;
      # WC/FH weeks unlimited and accrue nothing; net moves against the
      # week's opening squad (buy-back is free)
bank_after(base_bank_m, price_by_code, plans, drafts, up_to_gw) -> float
```

`squad_planner.py` keeps its file path and the v1 loader for migration; the
duplicated ledger functions (`free_transfers_for`, `hit_cost`, `total_hits`)
are deleted once no caller remains.

### 3.2 `ui/live_projection.py` (new, extracted from the Draft view)

The cached builders the Draft currently keeps inline (`_projector`,
`_FIX`, `BOARD_STAMP`, `_module_stamp`, `_fixtures_for`, `_club_fixtures`)
move here unchanged, with the same cache-key discipline (underscore only on
`_board`/`_fix`, stamps hashed). Both pages call:

```python
projection(stamp) -> (board, PROJ, fixtures_by_gw, match_window)
fixtures_for(team_id, gw, n=3) -> List[fixture dict]      # FDR-coloured run
```

This is the one refactor of the Draft page in scope. It is mechanical and
the Draft's tests must pass unchanged afterwards.

### 3.3 `views/00_my_team.py` planner fragment (rewritten)

The forward-week branch of the pitch tab (`_planner_fragment`, currently
lines 1414-1801) is replaced. Everything else on the page stays.

Bridging the real squad to the board: `get_team_squad` gains a `code`
column (from `bootstrap["elements"]`), and the squad joins the board on
`code`. A player in the squad but not on the board (should not happen in
season; guarded anyway) renders with points 0 and a "no projection" chip.

## 4. What the planner shows for a future week

Top to bottom, mirroring the Draft's `planner()` so the two pages feel like
one product:

1. **Money strip** from `team_plan.ledger`: free now · banked · moves this
   week · hits (−4 each) · bank after · squad value. Red badge on hits.
2. **Pitch** via `render_squad_pitch` (dict API, `interactive=True`): each
   shirt carries the next three fixtures (`fixtures_for`), that week's
   consensus points (`PROJ.points(code, gw)`) and expected minutes. XI is
   `gw_projection.best_xi`; captain = highest projected among players with
   ≥45 expected minutes (the Draft's rule) unless the entry sets one. Bench
   Boost adds the bench, Triple Captain triples. Total label shows XI points
   with the `head_to_head.week_band` 80% interval and the coverage chip
   ("11/15 on match forecasts").
3. **Axe queue and replacement desk.** ✕ on a shirt pushes to the axe list
   (multi-axe kept). The candidate table is `components/ff_table` with the
   Draft's `_pool_cols` (face, name, club, price, fixture run, this-week
   points, window points, expected minutes, confidence chip, spread, swap
   action), filtered to position and pooled budget, excluding owned codes.
   `legal_swaps` glow says who may legally come on. Signing writes
   `drafts[gw].swaps[out] = in`.
4. **Player card**: the Draft's `_player_dialog` (graded tiles, this week,
   fixtures, last season, model agreement, value) becomes
   `ui/player_card_dialog.py` and both pages open it. "Replace him" pushes
   to the axe queue; the My Team version adds "⭐ Captain for GWn".
5. **Compare**: "⚖ vs the axed player" opens `head_to_head.compare_players`
   + `verdict` (radar off `totals`, verdict off `edges`), replacing the
   hand-rolled `_h2h_dialog`.
6. **Is the gap real?** Before "Save GW plan": `simulate_drafts` over
   [current squad with no further moves] vs [squad after this week's
   drafts], window `gw .. gw+4`, shared noise, 1500 sims. Renders the
   Draft's significance line (coin flip / lean / real) with the mean gap.
   Nothing is blocked; it is information next to the save button.
7. **Save / Reset / Clear this week** as today, on `team_plan`.

Stepping the scrubber back into a saved future week shows the squad as it
was after that week's saved moves (`effective_codes`), matching the Draft's
`_current_squad(gw)` semantics.

## 5. Data flow

```
bootstrap + picks (fpl_api)  ──> squad_df (+code)
build_board(stamp) ──> board ──┐
fixtures ──────────────────────┴─> live_projection.projection() ──> PROJ
squad_plans.json ──> team_plan.load ──> plans, drafts
                                       └─> effective_codes(gw) ──> pitch rows
                                       └─> ledger(gw) ──> money strip
PROJ.points / expected_minutes / best_xi / week_band ──> pitch + totals
board ∖ owned ──> ff_table candidates ──> sign ──> save_draft
simulate_drafts(now vs draft) ──> significance ──> save row
```

All expensive pieces are cached with content stamps: the projector on
`board_stamp`, candidates on `(gw, position, budget, owned_stamp)`, the
Monte Carlo on `(gw, tuple(sorted(codes_now)), tuple(sorted(codes_after)))`.

## 6. Migration and error handling

- `squad_plans.json` v1 entries (`transfers:[{out_id,in_id,...}]`) are
  converted on load with the bootstrap's `id → code` map; a v1 transfer whose
  id no longer exists is dropped with a logged warning. The file is written
  back as v2 with `"schema": 2`. It is currently empty, so this is cheap
  insurance rather than a live migration.
- If the board or projector is unavailable (archive not built), the planner
  shows the same `st.error` the Draft shows and stops; the rest of My Team
  still renders.
- Preseason and "too few gameweeks" guards are unchanged.
- The Draft page's session keys are namespaced by draft id; My Team's are
  namespaced by team id (`_sk(name) = f"{name}::team{team_id}"`) so the two
  pages cannot collide on `draft_axe`, `_pitch_nonce` and friends.

## 7. Testing

- `tests/test_team_plan.py`: v1→v2 migration, effective squad replay across
  saved and draft weeks, Free Hit revert, ledger against the Draft's rules
  (bank to 5, oldest first, net moves, WC week), bank arithmetic.
- `tests/test_live_projection.py`: the extracted builders return the same
  projector the Draft built (snapshot a small board; assert identical
  `points()` for a handful of codes).
- Draft page tests unchanged and green after the extraction.
- Cache-key static test (`tests/test_cache_keys.py` or equivalent) covers the
  new modules.
- Browser pass: scrub to GW3, axe two players, sign replacements, read the
  ledger, compare, run the Monte Carlo, save, step back to GW2, forward to
  GW4, reload the page and confirm persistence.

## 8. Delivery phases

1. **Foundations**: `team_plan.py` + tests; `live_projection.py` extraction
   with the Draft green; `code` on `get_team_squad`.
2. **Planner rewrite**: pitch, money strip, axe/replace desk on `ff_table`,
   shared player card, compare dialog, save/reset.
3. **Gap test**: Monte Carlo on the save row.
4. **Cleanup**: delete `xp_engine.py`, `plan_optimizer.py`, the duplicated
   ledger functions, `_replacement_panel`, `_h2h_dialog`; update CLAUDE.md
   (the "xp comes from xp_engine" paragraph and the stale `_scored_universe`
   note).

Phase 2 follow-up (separate spec): multi-week greedy optimiser on `PROJ`
with the real ledger, replacing "Optimise my next 5 weeks".
