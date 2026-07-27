# Season Opener · early-season chip route, opening fixtures, and a second opinion

Design doc · 2026-07-27 · branch `season-rollover-2026-27`

## Problem

The 26/27 planning suite solves one static GW1 squad and ranks BB/TC/FH independently
over GW1-19 on that fixed squad. It cannot price the decision actually on the table:
an **early Bench Boost coupled to an early Wildcard**. Those two chips are not
independent. A Bench Boost needs fifteen playing assets, which dilutes the XI in the
weeks that matter most, and the Wildcard is the thing that repairs that dilution. The
route is one decision, not two.

Three further gaps surfaced while scoping:

1. **"Do I need Haaland" has never been costed.** Q11 `icon_vs_field` compares one
   premium against one challenger over a whole season. The real question is a squad
   opportunity cost: what does the rest of the squad lose to afford him.
2. **The opening-fixtures slider is unvalidated.** `OPENING_FIXTURES` weights GW1-6
   ease into the draft objective, but nothing has tested whether opening fixtures
   predict opening returns.
3. **The projection model has no second opinion.** Isak sits at 151 on a Low-confidence
   694-minute sample, Thiago carries a hand-applied regression haircut, Senesi is
   flagged new-club uncertain. Those are judgement calls with nothing to check them
   against.

## What the scoping analysis already established

Run against Fantasy Football Scout's independent 26/27 season projections (Chris
Atkinson's model, the engine behind Rate My Team) plus the live 380-fixture list.
Numbers below are reproduced by the prototype scripts and will be re-derived inside
the engines, not hardcoded.

- **Haaland is roughly break-even.** Forced in vs excluded, same budget and rules:
  XI projection 1888 with him against 1903 without. The armband recovers about 23.
  Net gain over a full season is around 8 points, which is noise. The real argument
  for owning him is differential risk against a high-ownership template, which is a
  different argument and should be surfaced as such.
- **The Bench Boost break-even is 2.2 to 2.8 gameweeks.** An all-play fifteen costs
  about 2.7 XI points per gameweek carried and the chip returns 5.8 to 7.5. So
  BB GW1 into WC GW3 pays, BB GW2 into WC GW4 pays, BB GW1 into WC GW5 does not.
- **There is no opening-fixture edge in 26/27.** Mean GW1-6 FDR runs from 2.83
  (NEW, MUN, LIV, EVE) to 3.67 (BOU), with eleven clubs at exactly 3.00. The spread
  is too small to build a draft around.
- **The swing does carry signal.** EVE +0.67 and MUN +0.50 get worse after GW6;
  BOU −1.00 and COV −0.50 get materially better. That argues for a GW6-7 wildcard,
  which **conflicts** with the GW3 the dilution clock implies. The tooling must model
  both rather than pick a side.

## Non-goals

- No automated scraping of Fantasy Football Scout. Bulk harvesting a paid site is
  against its terms. Scout data enters through a **manual, gitignored snapshot** the
  user refreshes when they choose (see Data below).
- No change to the live optimiser rules (1 attacker and 1 defender per club, risk
  dial, veto). Those stay as they are.
- No in-season logic. This is preseason planning for GW1-19 only, matching the
  Chip Planner's existing scope.

## Architecture

Four units, each independently testable, following the existing engine and view split.

### 1. `analytics/scout_projections.py` · the second opinion

Loads a snapshot of Scout's season projections and joins it to the value board.

- `load_snapshot(path) -> pd.DataFrame`: reads the CSV, returns tidy columns
  (`scout_name, team_short, pos, price, mins, pts, value`).
- `match_to_board(scout, board) -> pd.DataFrame`: joins on an alias map plus
  team and position. Scout writes `B.Fernandes`, `Joao Pedro`, `Thiago`, so exact
  matching will not work. Unmatched rows are **returned, not dropped**, so the UI can
  show what failed rather than silently losing players.
- `disagreements(joined, min_delta) -> pd.DataFrame`: per-player `delta = scout_pts −
  our_pts`, sorted by absolute size, annotated with our confidence tier and any
  override note. This is the Isak/Thiago/Senesi surface.

Alias map lives in `assets/scout_aliases_2026_27.json`, hand-maintained, same pattern
as `defender_roles_2026_27.json`.

### 2. `analytics/season_opener.py` · fixtures and the route comparator

- `opening_ease(fixtures, gw_lo, gw_hi) -> pd.DataFrame`: team_id to mean FDR and
  home count over a window. Generalises `ui.value_board._opening_factors`, which
  currently hardcodes GW1 to `cfg["gw_hi"]`; that helper is refactored to call this
  so there is one implementation.
- `fixture_swing(fixtures, early, late) -> pd.DataFrame`: early ease, late ease, and
  the swing between them, per club. Drives the wildcard-timing read.
- `bb_dilution(board, min_bench_mins, bench_price_cap) -> Dict`: solves the all-play
  fifteen against a cheap-bench fifteen and returns dilution per gameweek, chip gain,
  and break-even in gameweeks. Returns the bracket (free bench and capped bench), not
  a single number, because the two framings differ and both are honest.
- `compare_routes(board, fixtures, routes) -> pd.DataFrame`: the core. Each route is
  `{bb_gw, wc_gw, label}`. For each, build the squad the route implies (all-play for
  an early BB, otherwise a normal squad), score GW1-19 with the existing fixture-ease
  model from `chip_timing`, apply the chip at its gameweek, and rebuild at the
  wildcard on the post-WC fixture window. Returns net points against a
  no-early-chips baseline.

  Routes shipped by default: `BB1+WC3`, `BB2+WC4`, `BB1+WC5`, `noBB+WC7`, `noBB+WC10`.

`compare_routes` reuses `analytics.chip_timing._player_gw_points` and
`ui.value_board.solve_draft` rather than reimplementing scoring or squad selection.

### 3. Playbook Q13-Q16 · the historical evidence

Added to `analytics/playbook.py`, rendered in `views/19_playbook.py` via the existing
`_question(num, q, rule, accent)` helper. All four use the same method: two hindsight
squads differing in exactly one constraint, read the difference. Hindsight makes both
arms optimistic, but symmetrically, so the gap is honest even when the levels are not.
Every answer states that caveat inline.

- **Q13 · Does an early Bench Boost pay?** Per archive season, an all-play fifteen
  against a cheap-bench fifteen over GW1-6. Reports dilution, chip gain, break-even.
  Ten-season distribution, not a point estimate.
- **Q14 · When does a first-half Wildcard pay?** Squad decay curve: for each GW k in
  2..19, the gap between a squad re-optimised at k over GW k..k+5 and the original
  GW1 squad over the same window. The wildcard week is the first k where that gap
  exceeds the gain from the single best legal free transfer at k, measured over the
  same GW k..k+5 window. That threshold is the explicit definition, not a tuned
  constant.
- **Q15 · Do opening fixtures predict opening points?** Two parts. (a) Correlation
  between a club's GW1-6 opponent quality and its players' GW1-6 returns, per season.
  (b) Persistence: does a fast start survive past GW10, or mean-revert. Calibrates
  how much weight the opening slider deserves.
- **Q16 · Where do the models disagree, and who wins?** Not answerable historically
  (Scout snapshots only exist for 26/27), so this one is framed as a **live lens**:
  the disagreement table from `scout_projections`, sorted by size, with our confidence
  tier alongside. It asks the user to resolve each conflict deliberately rather than
  claiming a winner.

### 4. View changes

- `views/19_playbook.py`: four new question blocks, same card idiom, ECharts only.
- `views/18_draft_2026_27.py`: a route selector above the existing strategy radio.
  Selecting a route drives two squads shown side by side, the GW1 squad and the
  post-wildcard target, with the route's net-points readout from `compare_routes`.
  The existing strategy radio, risk dial, opening slider and veto stay untouched.

The opening slider gains a caption carrying Q15's finding, so a validated-as-weak
signal is not silently presented as a strong one.

## Data

Scout snapshot lands at `data/cache/scout_projections_2026_27.csv`. That path is
already covered by the `data/cache/*` gitignore rule, so it stays local and out of
git by default. It is a **snapshot with a date**, refreshed on request, never polled.
If the file is absent every Scout-dependent surface degrades to a caption saying so,
in the same way the preseason guards work today. Nothing hard-fails on its absence.

## Error handling

- Missing Scout snapshot: features render a "no snapshot loaded" caption, no crash.
- Unmatched player names: surfaced in an expander on the disagreement table, never
  silently dropped.
- Infeasible MILP: the £4.0 bench cap proved infeasible during scoping (only 19 DEF
  and 1 GK exist at that price) and CBC returned a garbage solution that parked
  Haaland on the bench. **Every solve in the new code checks
  `pulp.LpStatus[prob.status] == "Optimal"` and returns None otherwise.** The existing
  `squad_milp.optimize_squad` already does this; the new solvers must match.
- Preseason: all new surfaces work with zero played gameweeks by construction, since
  they run on fixtures and projections only.

## Testing

`tests/test_season_opener.py`:

- `opening_ease` and `fixture_swing` on a synthetic six-club fixture list with known
  FDRs, asserting exact means and swing signs.
- `bb_dilution` returns break-even in gameweeks and both bracket arms, on a small
  synthetic pool.
- `compare_routes` returns one row per route and ranks a deliberately rigged route
  first (a route whose chip week is stacked with easy fixtures).
- Every solver path asserts the infeasible case returns None rather than a bad squad.

`tests/test_scout_projections.py`:

- Alias matching for the three known-awkward cases (`B.Fernandes`, `Joao Pedro`,
  `Thiago`).
- Unmatched rows are returned rather than dropped.

Playbook Q13-Q16 are analysis over frozen archive data, covered by a smoke test that
each returns a non-empty frame with the expected columns, consistent with how Q1-Q12
are tested today.

## Build order

1. `scout_projections.py` plus alias map and tests. Smallest, unblocks Q16.
2. `season_opener.py` fixtures half (`opening_ease`, `fixture_swing`), refactoring
   `_opening_factors` to call it.
3. `season_opener.py` route half (`bb_dilution`, `compare_routes`).
4. Playbook Q13-Q15 in `analytics/playbook.py`.
5. View wiring: Playbook blocks, then the draft route selector.

Each step is independently shippable and leaves the app working.
