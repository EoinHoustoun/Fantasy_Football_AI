# Agent handoff · everything a new session needs

Read `CLAUDE.md` first (architecture, design system, gotchas). This file is the
judgement layer: how Eoin works, what has been decided and why, and the traps that
have already cost time. Written 2026-07-27.

---

## 1. Safety, before anything else

**The repo is public.** Never commit Fantasy Football Scout data (paid membership),
`.env`, or any credential. Do not reproduce real Scout figures even in tests or
markdown. See the "THIS REPO IS PUBLIC" section of `CLAUDE.md`.

**Browser automation drives Eoin's own logged-in Chrome.** Targeted reads only,
manual local snapshots, never bulk-harvest, never bypass a paywall or bot check.
See "Browser automation safety" in `CLAUDE.md`.

---

## 2. How Eoin works

- **Three hats at once**: product designer, data scientist, AI engineer. He wants
  the reasoning, not just the output.
- **Fixes before aesthetics.** Broken numbers outrank a pretty page.
- **Confident direction over checklists.** Within aesthetic and layout scope, make
  the call. Ask only when the answer changes what gets built.
- **He is a strong domain thinker.** His football reads have repeatedly been right
  where the model was wrong (Canvot's DEFCON, Vuskovic's CBIT, fullbacks not
  earning DEFCON, Semenyo's overperformance, Kinsky taking the Spurs gloves).
  **Treat his football instinct as evidence, then go and test it.** Several of the
  best findings in this app started as "I think..." from him.
- **He wants to be told when he is wrong**, with the number that shows it.
- No em dashes, anywhere. No AI attribution in commits. Personal GitHub only.

## 3. Working method that has worked

1. **Check the claim against data before building on it.** Almost every request
   here contains a testable assertion.
2. **Two arms, one constraint apart.** The house method for any "is X worth it"
   question: build two hindsight-optimal squads differing in exactly one
   constraint and read the DIFFERENCE. Levels are optimistic, the gap is honest.
3. **Verify in the browser, not just in pytest.** Multiple bugs (missing import,
   popup nonce, wrapped button labels) only appeared when the page was loaded.
4. **Say what you did not finish.** Half-built features are worse than absent ones.

---

## 4. Decisions already made · do not relitigate

| Decision | Why |
|---|---|
| **Wildcard timed by the Bench Boost clock and fixture swing, NOT by squad staleness** | Q14: staleness saturates after ~3 GWs (14 pts lost, then only 3 more over 9 weeks) |
| **BB GW1-2, Wildcard GW5-7** | BB break-even is 3.5 GWs over 10 seasons, 7.2 in the DEFCON season |
| **Haaland is optional, not compulsory** | Force-in vs exclude: net ≈ +8 pts a season. Own him for differential risk, not points |
| **Opening-fixtures slider is a tie-breaker** | Q15: predicts at r = −0.38 and weakening; team quality persists at r = +0.53 |
| **Rank DEFCON on HIT RATE, never the mean** | It is a threshold (10 DEF / 12 MID). A mean built on spikes does not pay |
| **Full-backs are not DEFCON assets** | CBs clear the bar 37% of starts, FBs 10%, and FBs did not out-score them |
| **Hand overrides beat the Scout fallback** | Eoin's knowledge is not in any model |
| **ECharts only, never Plotly** | Standing rule |

## 5. Traps that already cost time · do not repeat

- **`pitch_click` replays its last value on EVERY rerun.** Dedupe on `nonce` or
  popups fire at random. Documented in `CLAUDE.md` rule 4b.
- **Two models are not on the same scale.** Ours runs ~0.72× Scout's. Ranking by
  raw points gap ranks by that offset, not disagreement. Use the residual.
- **A ZERO-MINUTES row is worse than no row.** It keeps a player out of the
  no-history backfill while the model scores him on an empty sample (Vuskovic: 8.2
  pts). `override_no_evidence` handles it.
- **Promoted clubs were silently absent from the optimiser** because they have no
  carryover projection. Backfilled from Scout. Re-check after any board change.
- **Squad decay cannot be measured by rebuilding at GW k.** That measures window
  OVERLAP and hindsight, not staleness. Only compare builds that CLOSE before the
  scored window. Both dead ends are in `wildcard_decay`'s docstring.
- **Player photo CDN path is `premierleague25` and stays that way** · `26` and `24`
  both 502. Plain code, no `p` prefix.
- **`st.markdown` escapes HTML if an interpolated line is whitespace-only.**
  Collapse card HTML to one line.
- **Faces on a scatter pile up** in the high-minutes corner. Cap at ~10. Bars are safe.
- **Truncating a captured dataset loses players silently.** The Scout snapshot was
  first saved with a 40+ point cut, which dropped Bobby Thomas and the cheap
  Coventry defenders. Capture everything or state the cut.

---

## 6. Where things stand

**Branch `season-rollover-2026-27`.** Suite: 75 tests.

Built: Season Opener (coupled BB+WC route comparator), Playbook Q13-Q17, Scout
second opinion with scale correction, the 26/27 Draft as a planning surface
(locks priced, vetoes, 2-attackers toggle, gameweek stepper, per-gameweek bench,
shirt-click player cards, Scout fixture ticker, replacement finder, wildcard
planner, chip routes).

**Next, in order:**
1. **Planner handoff.** The draft should hand its squad to the EXISTING My Team
   planner (`analytics/squad_planner.py` has FT banking, hit costs, named draft
   persistence, `effective_squad`). Do NOT build a second planner · two that can
   disagree about the squad is the failure mode. This unlocks ✕-swap on the pitch,
   named saved drafts, and the per-week in/out summary Eoin asked for.
2. **Real per-gameweek projections.** Current per-GW figure is season ÷ 38 scaled
   by fixture ease · a fixture SHAPE, not a match forecast. Opponent-adjusted
   rates and rotation risk would make it real.
3. Value Lab 26/27 lens; merge this branch to `main`; mobile responsiveness.

**Open questions Eoin is weighing:** Fernandes vs Mbeumo (£4m apart, Mbeumo has
the better underlying and underperformed); whether to take both premiums; Forest
defence under Glasner (Milenkovic best on DEFCON, but the run is not a clean-sheet
run); Senesi's move risk against a 52-DEFCON-point floor.
