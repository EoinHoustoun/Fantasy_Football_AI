# FF Overhaul Plan · "Fantasy football, data-science-grade"

Goal: make FF the most visual, fluid, interactive, and *simple-to-use* FPL app
anyone has · a data scientist's app for winning fantasy football, with a UI that
is genuinely impressive. Big overhaul, committed fully, but sequenced so nothing
gets built twice.

## Locked decisions (2026-07-12)
- **Pitch model:** ONE unified *timeline* pitch (scrub past ↔ future).
- **Charts:** Apache **ECharts** via `streamlit-echarts` (free/MIT) · one shared theme.
- **Visual direction:** *Elevate the current identity* · keep dark `#151922` + mint
  `#00FF87` DNA, add real depth (glass, gradient mesh, subtle 3D/parallax, glow,
  football loading screens). On-brand, but a clear step up.
- **Start:** Foundations first.

## Guiding principles (apply to every screen)
- **Never too much on one screen. Never too much writing.** Brief labels, no
  paragraphs, one idea per section. Numbers over sentences.
- **The pitch never scrolls** · the full XI + bench fit one screen.
- **Simple to use** · obvious primary action per screen; progressive disclosure for depth.
- Respect + extend the design system; consolidate inline CSS into one theme module.
- Everything data-honest (2dp, stale-data flags) · the data-scientist promise.

---

## Phase 1 · Foundations (visual language + structure)

### 1.1 Jersey HD fix (quick win, root cause found)
Shirts load `shirt_{code}-66.png` (66px source) but render at 72px+ → upscaled blur.
CDN also serves `-110` and `-220` (verified 200 OK; `-220` ≈ 30KB). Fix: render the
`-220` variant and let the browser *downscale* (crisp even on retina).
- File: `components/team_identity.py` (`_SHIRT_BASE`/`shirt_url`, add a `size` arg,
  default 220). `shirt_html` + `pitch_view.py` inherit automatically.

### 1.2 Design-system refresh → one theme module
Create `ui/theme.py` (or `components/theme.py`): all tokens + a single global-CSS
injector; migrate the scattered inline CSS in `app.py`/pages to reference it.
- **Colour evolution (additive, non-breaking):** keep base + mint/gold/cyan/red;
  ADD surface tiers (`surface-1/2/3`), `glass` (blur + translucent), `glow`
  (mint/gold outer glows), gradient-mesh backgrounds, depth shadow scale.
- **Type:** keep Inter for body; add a free display face for heroes/big numbers
  (e.g. Space Grotesk / Archivo). Lock the scale (hero / section / stat / label /
  body), min 0.78rem. Codify a short **writing-style** guide (verb-first, ≤N words
  per card, no sub-captions on tiles).
- **Motion/3D:** extend `components/animations.py` · card tilt-on-hover (3D
  transform), parallax hero, staggered reveals, count-up numbers, and upgraded
  **football-themed loading screens** (build on `components/loading.py`).

### 1.3 Navigation regroup · 20 pages → 5 top-level tabs
Sub-navigate within each via `st.tabs` or a section selector. Proposed mapping:
1. **Home** · command center + Gaffer's Briefing.
2. **My Team** · the unified timeline pitch (absorbs *Captain*; captaincy lives on the pitch).
3. **Transfers** · Suggestions · Planner · Buy/Sell · Chips (Wildcard, Free Hit, Chip Planner).
4. **Analysis** · Dashboard · Differentials · xG Tracker · Predictions · Ownership · Injuries.
5. **Season Lab** · GW History · Mini-League · Perfect Season · Value Lab · 26/27 Draft · Playbook.
- File: `app.py` `st.navigation` structure; no page logic moves, only grouping + a
  sub-nav layer.

---

## Phase 2 · The Unified Pitch (centrepiece)

### 2.1 Pitch visual redesign
- **Order GK → DEF → MID → FWD, top to bottom** (flip current FWD-first order).
- **Fit one screen** · responsive card/shirt sizing so XI + bench never scroll.
- **Impressive background** · stadium-depth: mown-grass gradient + vignette + soft
  stadium-light glow + subtle perspective, replacing the flat green stripes. HD kits.

### 2.2 Timeline scrubber (the unification)
One pitch, navigable across gameweeks:
- **Past GWs** → the XI as it was, with *actual points* ("how it did"), back-button
  all the way to GW1.
- **Current/future** → pick-team / upcoming (xP, fixtures, editable).
- Controls: ◀ / ▶ + a GW slider; a clear "you are here / actual vs projected" marker.
- Reuses `data/fetchers/fpl_api.py` (entry picks per GW, live points) and
  `pitch_view.py` (both `render_pitch_view` and the `_simple_card` historical path).

### 2.3 Interactions
- **Sell via ✕** on a shirt → a filter panel slides in on the right: all players,
  dropdowns for **club** and **position**, **sort** by total points / xG / xGI /
  value / form, live search. Pick a replacement → transfer completes on the pitch.
- **Deep-dive via ℹ️** on a shirt → player panel (see Phase 3.4): form, xG/xA,
  fixtures, strengths/weaknesses radar · "why this player is / isn't delivering".
- **Markers on shirts:** penalty taker, DEFCON contributor, set-piece, captain/VC,
  injury/doubt. Reuse `components/badges.py` + DEFCON stats already computed in
  `data/fetchers/vaastav.py`.
- **State model:** `st.session_state` for selected-player / sell-target / view-GW;
  `st.empty` slots for in-place updates; escalate to a custom component only if a
  native rerun can't hit the fluidity bar.

---

## Phase 3 · Charts overhaul (ECharts) + player intelligence

### 3.1 Adopt ECharts
- Add `streamlit-echarts==0.4.0` (verify on Python 3.8 before pinning).
- Build `ui/charts.py`: a shared dark ECharts theme (palette, Inter font,
  transparent bg, tooltip/legend style) + typed helpers (bar, line, scatter,
  radar, heatmap, gauge) so every chart is one call and one look.

### 3.2 Replace the ~51 Plotly charts, page by page
Swap for more *informative* + more *beautiful* ECharts equivalents; annotate the
key point on each (narrative-as-annotation). Keep plot backgrounds transparent.

### 3.3 Player deep-dive graphs (feeds Pitch ℹ️)
- Strengths/weaknesses **radar**, rolling **xG/xA** line, **form** sparkline,
  fixture-difficulty strip, points distribution. Penalty/DEFCON/set-piece flags.

---

## Phase 4 · Polish & simplicity pass
- Football loading screens everywhere slow; count-up + reveal on key numbers.
- Writing-style sweep (cut text, enforce brevity), mobile fit, final a11y/contrast.

---

## Sequencing & size
Phase 1 (foundations) → 2 (pitch) → 3 (charts + deep-dive) → 4 (polish). Each phase
ships page-by-page. Phase 1 is the enabler · the theme, jerseys, and nav that
everything else inherits. Estimated the pitch (Phase 2) is the largest single lift.

## Writing-style rulebook (binding for all UI copy)
- **Numbers over sentences.** A stat speaks louder than a description of it.
- **Verb-first actions.** Buttons say what happens ("Sell", "Set captain"), then a
  toast confirms in past tense ("Sold").
- **≤ ~8 words per card headline; no paragraphs on tiles.** A section's purpose is
  carried by its title + content, never a sub-caption.
- **One idea per section.** If a card needs two sentences to explain, it's two cards.
- **Plain English, manager's voice.** "Best captain", not "Optimal armband selection".
- **Honest data.** Show staleness/fallback flags; never imply precision we don't have.
- **Type roles:** Archivo (display) for headings + big numbers; Inter/SF stack for
  body; tabular-nums on any aligned figures; min 0.78rem.

## Open questions to resolve as we build
- Sell/filter panel: side-by-side columns vs slide-in overlay (fluidity vs simplicity).
- Player deep-dive: inline expander vs modal-style overlay.
- Whether the timeline needs a custom component for true drag-scrub, or slider is enough.
