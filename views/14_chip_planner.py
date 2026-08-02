"""
Chip Planner · first half (GW1-19).

2026/27 gives two of every chip and the first set (Wildcard, Free Hit, Bench
Boost, Triple Captain) must be spent by GW19, so this only plans the first half.
It runs on a chosen draft (no live squad needed in preseason) and the released
fixtures, and recommends the best GW1-19 week for each chip · with GW1 always
shown for Bench Boost, since playing it there needs no transfer or wildcard prep.
"""
import streamlit as st

from components.animations import inject_global_animations
from ui import charts
from analytics import freshness as _freshness
from ui.value_board import build_board, solve_draft, DRAFT_STRATEGIES
from analytics.chip_timing import chip_windows
from config import CHIP_TIMING

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

GOLD, MINT, CYAN, RED, MUTED = "#FFD700", "#00FF87", "#04f5ff", "#FF6B6B", "rgba(255,255,255,0.5)"


def _hero(title: str, gw: int, metric: str, sub: str, color: str, note: str = "") -> str:
    note_html = (f'<div style="font-size:12px;color:{GOLD};margin-top:8px;">⚡ {note}</div>'
                 if note else "")
    html = f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
     border-top:4px solid {color};border-radius:12px;padding:22px 24px 18px;">
  <div style="font-size:12px;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;">{title}</div>
  <div style="font-size:44px;font-weight:900;color:{color};line-height:1;">GW{gw}</div>
  <div style="font-size:20px;font-weight:700;color:#fff;margin-top:6px;">{metric}</div>
  <div style="font-size:13px;color:rgba(255,255,255,0.5);margin-top:6px;">{sub}</div>
  {note_html}
</div>"""
    return "".join(s.strip() for s in html.splitlines())


# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='padding:18px 0 4px;'>"
    f"<div style='font-size:34px;font-weight:900;color:{GOLD};letter-spacing:-0.5px;'>🎯 Chip Planner</div>"
    f"<div style='font-size:14px;color:{MUTED};margin-top:4px;'>"
    f"First-half chips (GW1-19) · the best week to play each, on a chosen draft.</div></div>",
    unsafe_allow_html=True,
)
st.info("2026/27 gives **two of every chip**. The first set (WC · FH · BB · TC) must be used "
        "**by GW19**, so this plans the first half only. Timings are fixture-based best guesses · "
        "doubles and blanks firm up during the season.")

board, scout, _, _ = build_board(_freshness.inputs_stamp())
if board is None:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

c1, c2 = st.columns([3, 1])
with c1:
    strategy = st.radio("Squad", DRAFT_STRATEGIES, horizontal=True, label_visibility="collapsed")
with c2:
    budget = st.slider("Budget (£m)", 95.0, 105.0, 100.0, 0.5, key="chip_budget")

res = solve_draft(board, strategy, budget)
if res is None:
    st.error("Solver found no feasible squad · change strategy or budget.")
    st.stop()
squad = res["squad"]

# Fixtures (session cache, else fetch)
fixtures_df = st.session_state.get("fixtures_df")
if fixtures_df is None:
    from data.fetchers.fpl_api import get_fixtures_df, fetch_fixtures, fetch_bootstrap
    fixtures_df = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())

GW_HI = CHIP_TIMING["first_batch_gw_hi"]
w = chip_windows(squad, fixtures_df, 1, GW_HI)

bb = w["bench_boost"]
tc = w["triple_captain"]
fh = w["free_hit"]
bb_best = bb[0]
bb_gw1 = next((x for x in bb if x["gw"] == 1), {"gw": 1, "bench_pts": 0.0})
tc_best = tc[0]
fh_best = fh[0]
bench_names = " · ".join(squad[~squad["in_xi"]]["web_name"].tolist())

# ── Recommendations ────────────────────────────────────────────────────────────
st.markdown("### Best week for each first-half chip")
h1, h2, h3 = st.columns(3)
with h1:
    gw1_note = (f"GW1 also strong ({bb_gw1['bench_pts']:.0f} pts) · no prep needed"
                if bb_best["gw"] != 1 else "GW1 · no transfer/wildcard prep needed")
    st.markdown(_hero("Bench Boost", bb_best["gw"], f"{bb_best['bench_pts']:.0f} bench pts",
                      f"Bench: {bench_names}", CYAN, gw1_note), unsafe_allow_html=True)
with h2:
    st.markdown(_hero("Triple Captain", tc_best["gw"], f"+{tc_best['extra_pts']:.0f} extra pts",
                      f"Captain: {tc_best['captain']}", GOLD), unsafe_allow_html=True)
with h3:
    blanks = fh_best.get("blanks", 0)
    fh_sub = (f"{blanks} of your 15 blank that week" if blanks
              else "your squad's weakest fixture week")
    st.markdown(_hero("Free Hit", fh_best["gw"], f"{fh_best['squad_pts']:.0f} squad pts",
                      fh_sub, MINT), unsafe_allow_html=True)

st.caption(f"Squad: {strategy} · £{res['squad_cost']:.1f}m. Bench Boost wants a full, well-fixtured "
           f"bench; Triple Captain wants your best player's softest week; Free Hit rescues your worst week.")

# ── Charts over GW1-19 ─────────────────────────────────────────────────────────
tab_bb, tab_tc = st.tabs(["📊 Bench Boost by GW", "👑 Triple Captain by GW"])

with tab_bb:
    st.caption("Projected bench points each week · higher = better Bench Boost. GW1 highlighted.")
    by_gw = sorted(bb, key=lambda x: x["gw"])
    colors = [GOLD if r["gw"] == bb_best["gw"] else (MINT if r["gw"] == 1 else CYAN) for r in by_gw]
    opt = charts.bar_option(x=[r["gw"] for r in by_gw],
                            y=[r["bench_pts"] for r in by_gw], colors=colors)
    opt["tooltip"]["formatter"] = "GW{b}: {c} bench pts"
    charts.render(opt, height="300px", key="chip_bb")

with tab_tc:
    st.caption("Extra points from tripling your best captain each week · higher = better Triple Captain.")
    by_gw = sorted(tc, key=lambda x: x["gw"])
    colors = [GOLD if r["gw"] == tc_best["gw"] else CYAN for r in by_gw]
    opt = charts.bar_option(x=[r["gw"] for r in by_gw],
                            y=[r["extra_pts"] for r in by_gw], colors=colors)
    opt["tooltip"]["formatter"] = "GW{b}: +{c} pts"
    charts.render(opt, height="300px", key="chip_tc")

st.markdown(
    f"<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-top:14px;'>"
    f"Per-GW points = each player's season projection / 38, scaled by that week's fixture difficulty "
    f"(a blank scores 0, a double stacks both). It's a fixture read, not a live xP · re-check once "
    f"line-ups and any doubles/blanks are confirmed. Wildcard timing lives on its own page.</div>",
    unsafe_allow_html=True)
