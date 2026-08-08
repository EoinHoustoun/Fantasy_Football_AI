# Optimise Squad · letting the dials rebuild a saved fifteen

Design doc · 2026-08-08 · branch `draft-page-hardening`

## Problem

The 26/27 Draft page has an exact squad optimiser that already does what the user
wants, and no way to ask it. `views/18_draft_2026_27.py:1552`:

```python
res = None
if _SAVED_SQUAD is None:
    res = solve_opening(_LIVE_SPEC)
```

Once a draft carries a saved fifteen, the solver never runs. Every dial in the
tuning panel (budget, risk, opening weight, minutes gate, chip weeks, locks,
club rules) moves nothing, because the page short-circuits to the squad on disk.

That freeze is deliberate and the reasoning at line 1500 is sound: a squad built
by hand must not silently rebuild under the user. But the only escape hatch ever
built is a **veto**. Banning a player forces a full re-solve. There is no way to
say "just optimise it" without banning someone the user actually wants, and the
page's other sixteen buttons offer nothing closer. "↺ Reset squad" clears manual
swaps and benchings only.

The user's report: "we are missing an optimise squad button ... it can make
unlimited changes, taking into account our settings in the tuning".

## What already works and is NOT in scope to build

`solve_opening` (line 1389) covers most of the request today, once it is allowed
to run. None of this needs writing:

| Requirement | Where it already lives |
|---|---|
| Unlimited changes driven by the live dials | `_LIVE_SPEC` (line 1527), which already carries `"squad": None` |
| Optimal over GW1-3 | `OPT_WINDOW = (1, wildcard_gw - 1)` (line 1481) |
| Bench Boost GW1 priced in | `bench_pts_col` / `boost_col`, in the **objective**, not a post-hoc weight (line 1535) |
| A weekly XI, not one fixed lineup | `OPLAN.solve_window` (line 1461) |
| Exact rather than heuristic | `analytics/squad_milp.optimize_squad`, PuLP/CBC |
| Honest about optimality | `_PROVEN` / `proven_optimal` (line 1609) |
| Budget reallocation on a veto | line 1505, whole-squad re-solve by design |

Because `_LIVE_SPEC["squad"]` is already `None`, `solve_opening(_LIVE_SPEC)`
re-solves from the dials and ignores the save. **No change to any analytics or
optimiser module is required.** The work is entirely in the page.

### The budget-reallocation behaviour, restated

The user raised this specifically: vetoing a £5.5m player must not swap in
another £5.5m player. It must free the money and re-solve all fifteen, so the
answer can be "buy a £9.0m forward and downgrade two defenders to pay for it"
when that scores more over the window. This is existing behaviour. It gets a
regression test here (section 6) because nothing currently pins it.

## Scope

One button, a confirmation dialog, and the tests that hold both in place.

Explicitly **out** of scope, agreed with the user: searching the chip calendar
(trying Bench Boost and Wildcard at every plausible week and ranking whole
routes). `analytics/season_opener.compare_routes` already does part of that and
it is a separate piece of work.

## Design

### 1. The button

Sits in the tuning panel beside "Keep these settings", labelled with the window
it will solve so the horizon is never implicit:

```
[ ✨ Optimise for GW1-3 ]     [ 💾 Keep these settings ]
```

Rendered only when `_SAVED_SQUAD is not None`. With no saved fifteen the page
already auto-solves on every rerun, so the button would be a no-op and showing
it would imply the dials were not already live.

On click: solve inside `components.loading.fpl_loader(LINES_SOLVER)` so the
2-5s MILP shows the themed overlay rather than a bare Streamlit spinner.

```python
res = solve_opening(_LIVE_SPEC)   # _LIVE_SPEC["squad"] is already None
```

### 2. Propose, then confirm · never overwrite on click

The result goes to session state as a proposal and opens an `@st.dialog`. It
does not touch the saved draft until the user accepts. This mirrors the page's
existing "Best Boost week" flow, which proposes and waits for "Use GW N"
(line 1721), so the page stays consistent with itself.

```
OPTIMISE · GW1-3 · BB GW1 · WC GW4              ✓ proven optimal

OUT                          IN
Gabriel      £6.0m    →      Saliba      £6.5m
Wissa        £7.0m    →      Watkins     £9.0m
...

Spend  £99.5m → £100.0m        Bank £0.5m → £0.0m
GW1-3  108.2  → 115.6          +7.4

              [ Use this fifteen ]   [ Keep mine ]
```

Both point totals come from `OPLAN.plan_total(squad, PROJ, _plan_gws, bb)`, the
same function the planner already uses, so the dialog and the page cannot
disagree. The diff is computed on `code`, never on name, per the repo's standing
join rule.

`proven_optimal` is surfaced in the dialog header using the existing `_PROVEN`
logic rather than a second honesty check. When CBC times out the header reads
"best found, not proven" and the accept button still works.

Accept path: write the fifteen codes into the draft spec's `squad` field and
persist with `DR.save_draft`, then `st.rerun()`. That call is sanctioned twice
over by the CLAUDE.md rule (inside a dialog, and after a disk write).

### 3. Horizon stays coupled to the wildcard week

The user asked to set the horizon in tuning. It already is set there, indirectly:
the wildcard selector at GW4 derives `OPT_WINDOW = (1, 3)`, and the banner at
line 1489 already states it.

A second widget owning the same value is rejected. Two controls for one number
is how they drift apart, and this page has already paid for that once: the
planner and the comparison built squads differently until `solve_opening` was
written to make them share a path. An independent horizon dial also has no
defensible answer when horizon 3 meets a wildcard at GW8, because that is a
squad optimised for a window the user does not own.

Instead the derived horizon becomes a plain line under the wildcard selector:

```
Wildcard    [ GW4 ▾ ]
            Plan horizon · 3 gameweeks (GW1-3)
```

One number, two readouts, no possible contradiction.

### 4. Failure path

An infeasible solve must not open an empty dialog. The button routes a `None`
result through `analytics.squad_milp.diagnose_infeasible`, already wired at line
1576, which relaxes one constraint at a time and names the binding one. The user
sees "the binding constraint is the one-defender-per-club rule", not silence.

## What could go wrong

- **Solving on a stale board.** The button must read `SOLVE_BOARD` / `_LIVE_SPEC`
  as constructed on the current rerun, not a cached copy keyed on something that
  does not change. This is the underscore-prefixed-cache-key trap that already
  cost a debugging round on this page.
- **A silently dropped player.** If a saved code is missing from the board the
  diff must show it as an explicit OUT with a reason, not omit the row. Silent
  disappearance is the failure class recorded in the invisible-bugs notes.
- **Double rerun racing the dialog.** The accept handler sets state and reruns at
  app scope. A fragment-scoped rerun leaves the dialog open.

## Testing

All offline, no solver run in CI beyond a small pinned pool.

1. `solve_opening` with a spec whose `squad` is `None` re-solves and returns a
   fifteen, even when a saved draft exists on disk.
2. `solve_opening` with a spec carrying 15 valid codes returns those codes
   verbatim (the freeze still holds for the auto path).
3. Window derivation: `wildcard_gw = 4` gives `(1, 3)`; no wildcard gives `None`.
4. Bench Boost at GW1 inside the window reaches the objective as `boost_col`.
5. **Budget reallocation:** on a pinned pool where the better answer requires
   moving more than one slot, vetoing a mid-price player produces a squad that
   differs in more than one position. Pins the line-1505 behaviour the user asked
   about.
6. Accept path writes exactly 15 codes to the draft store.
7. Infeasible settings return a named binding constraint rather than `None`
   reaching the dialog.

## Estimated shape

Roughly 60 lines in `views/18_draft_2026_27.py`, one new test module. No new
modules, no changes to `analytics/`, no changes to `consensus.py` or the xP
engine.

## Not in this work

- Chip-calendar route search (BB week × WC week), deferred by agreement.
- The Betfair market-lens work scoped earlier the same day, parked until the user
  creates a Betfair delayed app key. Written up in
  `2026-08-08-market-lens-design.md`.
