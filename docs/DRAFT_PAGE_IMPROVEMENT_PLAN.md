# 26/27 Draft Page: Improvement Plan

Written 2026-08-01 from a live walkthrough of `http://localhost:8510/draft_2026_27`
(1440px desktop pass plus Eoin's real zoomed viewport, which renders at ~567 CSS px)
and a deep read of `views/18_draft_2026_27.py` (2,754+ lines) and every module it
imports. Another agent is actively editing, so line numbers drift; findings are
anchored to function names where possible.

---

## What is already excellent. Keep all of this.

- **The compact pitch.** Kits, venue-aware fixture chips, price + xP per card,
  penalty badges, legal-swap highlighting through `_legal_swaps`. It teaches the
  substitution rule through the interface.
- **The copy voice.** "A guess wearing a decimal point", "an expensive
  conviction", "the bottom-right corner is the trap". Honest epistemics
  (Spearman 0.4, ±38 pts in the footer; `significance()` calling 65/35 a coin
  flip). No other FPL tool talks like this. Protect it.
- **Cost of conviction** ("-52 XI pts vs the free optimum") is exactly the right
  frame for locks, straight out of the football lens.
- **The nonce-dedupe click contract** (`_click`), applied at all five
  bidirectional component call sites. Hard-won; never regress it.
- **Theme discipline**: essentially zero colour literals in the page; the
  ink/vivid split is respected.
- **`ff_table` declarative column specs** and the pure `build_html`.
- **Docstrings that record why**, including dead ends (`_range_bands`,
  `walk_route`, `ffh_season_equivalent`).

---

## P0: Correctness and data integrity (do before anything cosmetic)

1. **Cross-draft state bleed.** `draft_swaps`, `draft_axe`, `xi_override`,
   `draft_gw` are not scoped to the selected draft id (widget dials are, via
   `f"bud_{_k}"`). Switching presets carries the previous draft's transfers onto
   the new fifteen. Scope these keys by `_spec["id"]` the same way the dials are.
2. **Save-draft data loss.** Three separate save UIs (Tune popover, planner,
   compare-drafts expander) write different payloads under the same slug.
   A recipe-only save over an existing name wipes a previously saved fifteen
   (`drafts.save_draft` upserts with `squad: None` from `BASE`). Consolidate to
   one save path; never null a stored squad on a recipe-only save.
3. **Atomic draft writes.** `drafts._write` is a bare `open(..., "w")`. An
   interrupted write truncates `saved_drafts.json`; `_read` then returns `{}` and
   re-seeds, silently destroying every user draft. Write tmp file + `os.replace`.
4. **Stale-cache keys.** `_position_ranks` and `_projector` key on `len(board)`.
   A snapshot refresh or override edit that keeps the row count serves stale
   grades and projections for 6 hours. Key on a content stamp (e.g. snapshot
   mtimes + overrides mtime + a hash of `board[PTS_COL]`), and give
   `build_board` a version constant like `_PROJ_VERSION`.
5. **Silent Scout-backfill drop.** The broad `except Exception` around the Scout
   backfill in `value_board.py` can silently remove every promoted-club player
   from the pool with only a log line. Narrow the try block and surface a visible
   warning chip in the hero when a model input failed to load. Promoted-club
   coverage is strategy-critical (Bobby Thomas class picks).
6. **Copy/spacing bugs in the Bench Boost clock card** (Chip route tab, live on
   screen now): "costs 0.6 pts agameweek", "returns 2pts once", "Break-even is
   3.4 to3.4 gameweeks", "the resethas to follow". Fix the f-string spacing, and
   when lo == hi render "about 3.4 gameweeks" instead of a degenerate range.
7. **Raw exception strings leak into the UI** in the route walkthrough
   (`st.caption(f"... ({_exc})")`). Replace with a plain-language failure line.
8. **Blank minutes cells.** Pool rows for some players (e.g. Kroupi.Jr,
   Manzambi) show "·" under MINS with no explanation. Render "no forecast" in
   muted-but-readable text, and make sure the ranking treats missing minutes as
   risk rather than neutral.

## P1: Performance (the page feels heavier than it should)

1. **Cache the Monte Carlo.** `simulate_drafts` (1500 sims, deterministic seed)
   and `build_phases` re-run on every rerun once `_ab_ready` is set. This is the
   single biggest win: `st.cache_data` keyed on (picks, window, n_sims, board
   stamp).
2. **Cache `_tuned_board`.** Full board copy + JSON read from disk + per-row
   `.map(lambda)` per rerun, then again per compared draft inside `_solve`.
3. **All seven tab bodies execute on every rerun** (st.tabs renders everything).
   Combined with tab clicks resetting scroll to the top, navigation feels
   punishing. Wrap heavy tab bodies in `@st.fragment`, or gate each body on its
   tab having been opened at least once (`st.session_state` flag), so a pool
   search keystroke does not rebuild 72 verdict cards and the route MILPs.
4. **Vectorise the pool ranking loop.** `pool.assign(_k=[PROJ.run_total(...) for
   c in pool["code"]])` walks every player through a Python sum over up to 8
   gameweeks on every filter interaction, then recomputes for survivors.
   `GwProjection.matrix()` already exists and is unused; use it here and in
   `head_to_head.simulate_drafts` (same P×G dict-lookup loop) and make `best_xi`
   single-pass instead of three `iterrows` passes.
5. **Memoise verdict-card HTML** on (data stamp, theme) instead of rebuilding
   ~150 KB of markup per keystroke.

## P2: UX and product design

1. **The zoomed-viewport reality.** Eoin's actual browser renders this page at
   ~567 CSS px and it breaks: hero title clipped, preset pills and stat tiles
   run off-screen with no scroll affordance, the pitch loses half a defender.
   Decide the supported minimum width and make the top of the page survive it:
   `flex-wrap` on tile rows, horizontal scroll containers with a visible fade
   affordance for the preset rail, `clamp()` on the hero type, pitch scaling to
   container width. Test at 560, 900, 1440.
2. **Preset rail legibility.** Eleven pills of near-identical text
   ("+Fern+Mosq+Haal BB1 → WC4" vs "+Fern+Mosq+Haal BB2 → WC4") force reading
   every one. Group them visually: locks | base | routes (the icons already
   exist), a two-line pill (squad line + chip line), and a clear selected state
   beyond fill colour. Long-term: the preset list is data, so render it from
   `drafts.py` groups rather than one flat row.
3. **Gameweek stepper.** Two large empty buttons with lone glyphs above the
   heading read as dead space, and there is no direct jump. One compact control
   row: prev / "GW 1 of 19" scrubber / next, plus keyboard left/right arrows.
4. **Save flow.** One save affordance, visible only when there is something new
   to save, with a saved-state confirmation (name + time). Pairs with P0-2.
5. **Pool table depth.** The pool shows a fixed slice with no "show more" and no
   row count ("22 of 409 shown"). Add both. Blank faces (Manzambi) need a
   placeholder silhouette rather than a hole.
6. **Tab scroll reset.** After the fragment/gating work in P1-3, clicking a READ
   tab should not send the user back to the top of the page. If Streamlit still
   resets, an anchor-scroll restore in the component JS is worth it.
7. **Consistent iconography.** The sidebar and tiles use Material icons; THE
   READ tabs use emoji (⚖️ 🆚 🎯 🤝 🃏 🗺️ 📋). Pick one system (Material,
   given the sidebar) and apply it to the tabs.
8. **Verdict-card copy dedupe.** Every Necessity card repeats "Template
   must-have" and "Any new signing or backup who could eat his minutes?" The
   boilerplate dulls a genuinely good card. Vary by evidence: only print the
   question that is actually live for that player (pens ownership for premiums,
   minutes threat for defenders, role change for new signings).
9. **New-club and returnee badges.** Semenyo showing MCI and Rogers showing
   Chelsea is correct data that looks like a bug. A small "new club" chip (and
   "WC returnee, late start" where the override applies) turns a trust-breaker
   into a feature. The overrides file already knows.

## P3: Visual polish (after the above)

- **Hierarchy at the top.** Hero title, live-prices chip, Tune button, preset
  rail, preset summary, conviction line, stepper, money strip: eight stacked
  rows before the pitch. Merge the preset summary and conviction line into one
  card; consider making the money strip part of the pitch header.
- **Light mode QA pass.** The vivid yellow fixture chips and mint accents need
  checking against light backgrounds; the design system is dual-theme and this
  page was built dark-first.
- **Footer caveat contrast.** The projection-caveat footnote must respect the
  no-light-grey rule (0.66 alpha minimum on muted text).
- **Bar scales.** SEASON and GW1-4 bars use hardcoded maxima (190, 32, 110)
  that will drift; derive from the data and label the scale once in the header.
- **Motion.** One subtle entrance on the pitch cards and tile numbers
  (150-200ms, ease-out, respecting `prefers-reduced-motion`); nothing on rerun.

## Data science upgrades

1. **Uncertainty on the headline.** "52.7 expected points" is false precision
   next to a model that validates at ±38 season points. The h2h simulator
   already produces distributions: show "52.7 (p10 44, p90 61)" on the XI tile,
   and ranges instead of decimals anywhere the number is a forecast.
2. **Disagreement as a pool column.** Model agreement lives in its own tab, but
   the decision happens in the pool. Add a compact spread indicator (the
   verdict-card "Models span 154-174" collapsed to a ±) next to CONF.
3. **Snapshot freshness stamps.** Scout and Hub files are manual; the page
   should show their mtimes next to the "3 MODELS" chip and colour it once a
   file is older than a threshold. A six-week-old FFH export currently drives
   the whole per-GW view silently.
4. **Calibration harness.** Once GWs start, log projected vs actual per player
   per GW into a parquet, and add a small reliability panel (predicted vs
   realised by bucket). This is also the portfolio-grade artifact for the repo.
5. **Test the statistical core.** `consensus.py` (zero-sample masking already
   caused one live bug), `gw_projection.py` (`fixture_factor`, `best_xi`),
   `simulate_drafts` (seeded, trivially testable), `ffhub.py` joins. All
   currently at zero tests.

## FPL strategy features (the advanced-player asks)

1. **Captaincy layer.** The XI totals ignore the doubled captain. Add a
   suggested armband per GW on the pitch (highest xP with a minutes gate) and
   include 2x captain in the XI tile and in draft comparisons; captaincy swings
   routes more than most transfers.
2. **Template risk, quantified.** Ownership exists in verdicts but not where
   the decision is made. Add effective-ownership context to the pool and a
   "punt meter" on the draft summary: expected rank swing if the high-EO
   players you skipped (Haaland 75%, Fernandes 49%) haul vs blank. This is the
   asymmetry argument from the football lens made visible.
3. **DEFCON hit rate, not mean.** DEFCON is a threshold game. Show per-player
   hit rate (share of last-season GWs clearing 10/12 CBIT) as the defender/mid
   floor column in the pool, alongside clean-sheet odds for defenders.
4. **Set-piece facts in the pool.** PENS/SET-PC badges exist on verdict cards
   only. Surface them (official orders, they are facts not forecasts) as tiny
   glyphs on pool rows and pitch cards.
5. **Price-rise timing.** The lens notes an early Wildcard's under-modelled
   payoff is jumping price risers. The price model exists (`price_predictor`);
   add projected first-month price deltas to the pool and a "team value by GW6"
   line to the route comparison.
6. **Fixture-swing view.** A compact GW1-8 ticker heatmap per shortlisted club
   (venue-aware, already in `fixture_ticker.py`) under the pool, as a
   tie-breaker signal only, labelled as such per the lens.

## Engineering hygiene

1. **Commit the feature.** `consensus.py`, `gw_projection.py`,
   `head_to_head.py`, `drafts.py`, `ff_table.py`, `ffhub.py` are untracked; the
   core of the page is unversioned. Commit before any refactor.
2. **Break up the monolith.** Extract `planner()` (343 lines) and the `tab_ab`
   block (380 lines, module scope) into `ui/draft/` modules with explicit
   parameters instead of module globals (`board`, `PTS_COL`, `PROJ`, dials).
   That alone makes ~1,200 lines testable.
3. **Pure-logic extraction.** `_keep_verdict` rules, `_transfer_ledger` (FT
   accrual), `_tuned_board` corrections, `_is_legal_xi`/`_legal_swaps` are
   business rules living in a view. Move beside their analytics siblings and
   test them.
4. **Config the magic numbers** per the project's own rule: the 40-pt pool
   floor, ±0.6 price band, 0.90/0.67 grade cuts, -12/-35 conviction tiers,
   3420 season-minutes (defined three times), bar maxima, table caps.
5. **Delete dead code**: `DRAFT_STRATEGIES` import, `price_bt`/`validation`
   unpack, `charts.range_bars_option`, `gw_projection.bench_boost_value`,
   `drafts.get_draft`/`describe`, the legacy Haaland/Fernandes string-match
   branch in `value_board.solve_draft`, `views/00_my_team 2.py`, `CLAUDE 2.md`,
   the dead `draft_bench` session key.
6. **Reconcile the rerun rule.** CLAUDE.md forbids `st.rerun()` in button
   handlers; the page does it in six places (two arguably needed for dialogs).
   Either amend the rule with the sanctioned pattern or fix the call sites.

## Suggested sequencing

1. P0 items 1-3 (state bleed, save consolidation, atomic writes): correctness
   users can hit today.
2. P0 4-8 + P1 1-3: staleness, silent failures, and the two big perf caches.
3. Engineering 1-2 (commit, then extract modules) with tests landing alongside.
4. P2 UX batch (viewport, preset rail, stepper, save flow, pool depth).
5. Data science 1-3 and FPL features 1-3, one at a time, propose-then-build.
6. P3 polish and the remaining FPL features.
