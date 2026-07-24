"""
2026-27 Value Board · actual launch prices vs projected points.

FPL has published the real 2026-27 prices, so this page is no longer a
projection of prices · it is the value read on the ones that shipped. Each
player's projected points (fitted on the 2025-26 archive) is set against their
actual price and bucketed by `analytics/value_verdicts.py`:

  Necessity · Value (under-priced) · Overpriced · Fair · Scout (no history)

The optimal GW1 squad is solved on the ACTUAL prices, so it is a squad you can
literally build. Promoted-club and new-signing players have no history and are
shown as Scout cards, not given fake numbers.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.animations import inject_global_animations
from components.team_identity import team_dot
from config import LAST_COMPLETE_SEASON, NEXT_SEASON
from analytics.value_verdicts import VERDICTS
from ui import charts

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
POS_ORDER = ["GKP", "DEF", "MID", "FWD"]
MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:14px 18px;")

# verdict → (accent colour, emoji, one-line meaning)
VERDICT_META = {
    VERDICTS.NECESSITY: ("#FFD700", "🥇", "Elite projection, template-owned. Build around them."),
    VERDICTS.VALUE:     ("#00FF87", "🟢", "FPL priced them below their projected return. Load up."),
    VERDICTS.OVERPRICED: ("#FF4B4B", "🔴", "Big tag, pedigree, but the projection doesn't earn it."),
    VERDICTS.FAIR:      ("rgba(255,255,255,0.5)", "⚪", "Priced about right."),
    VERDICTS.SCOUT:     ("#04f5ff", "🔍", "No 25/26 history. Scout the depth chart before committing."),
}


# ── Scout layer: tailored questions per player ─────────────────────────────────

def _scout_questions(row: pd.Series) -> list:
    """1-2 human reads a projection can't make · depth chart, fitness, role."""
    qs = []
    sr    = row.get("starts_ratio")
    price = float(row.get("actual_price") or 0)
    share = float(row.get("mins_share") or 0)
    surp  = float(row.get("pricing_surprise") or 0)

    if pd.notna(sr) and sr < 0.8:
        starts = int(row.get("starts_total") or 0)
        games  = int(row.get("games_played") or 0)
        qs.append(f"Started {starts}/{games} in 25/26 · nailed now, or still rotated?")
    elif share < 0.6:
        qs.append("Projection sees patchy minutes · will he lock down a starting spot?")

    if surp <= -1.0:
        qs.append(f"FPL priced £{-surp:.1f}m over the model · reputation tax, or a bigger role?")
    if price >= 9.0:
        qs.append("Premium anchor · does he own the pens / set-pieces to justify it?")
    elif price <= 4.5:
        qs.append("Cheap starter? Confirm he starts GW1 before locking him in.")

    qs.append("Any new signing or backup who could eat his minutes?")
    return qs[:2]


def _verdict_card(row: pd.Series) -> str:
    verdict = str(row.get("verdict", VERDICTS.FAIR))
    accent, emoji, _ = VERDICT_META.get(verdict, VERDICT_META[VERDICTS.FAIR])
    pos   = str(row.get("position", ""))
    pc    = POS_COLORS.get(pos, "#888")
    name  = str(row.get("web_name", "?"))
    team  = str(row.get("team_name", "") or "")
    price = float(row.get("actual_price") or 0)
    pts   = float(row.get("projected_points") or 0)
    vscr  = float(row.get("value_score") or 0)
    own   = float(row.get("ownership") or 0)
    surp  = float(row.get("pricing_surprise") or 0)
    reason = str(row.get("verdict_reason", "") or "")
    share = max(0.0, min(1.0, float(row.get("mins_share") or 0)))
    is_scout = verdict == VERDICTS.SCOUT

    surp_col = "#00FF87" if surp > 0 else "#FF4B4B" if surp < 0 else MUTED
    surp_txt = (f"+£{surp:.1f}m under model" if surp > 0
                else f"£{-surp:.1f}m over model" if surp < 0 else "at model price")

    q_html = "".join(
        f'<li style="margin-bottom:3px;line-height:1.3;">{q}</li>' for q in _scout_questions(row)
    )
    stat = lambda v, l, c="#fff": (
        f'<div style="text-align:center;"><div style="font-size:15px;font-weight:900;color:{c};">{v}</div>'
        f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,0.4);">{l}</div></div>'
    )
    # Scout cards have no projection · show price + ownership only.
    if is_scout:
        mid = f'{stat(f"£{price:.1f}", "Price")}{stat(f"{own:.1f}%", "Owned", "#04f5ff")}'
        bar = ""
    else:
        mid = (f'{stat(f"£{price:.1f}", "Price")}{stat(f"{pts:.0f}", "Proj pts", "#00FF87")}'
               f'{stat(f"{vscr:.1f}", "Pts/£m", "#FFD700")}{stat(f"{own:.1f}%", "Owned", "#04f5ff")}')
        bar = (f'<div style="height:5px;border-radius:3px;background:rgba(255,255,255,0.08);'
               f'overflow:hidden;margin-bottom:8px;"><div style="height:100%;width:{share*100:.0f}%;'
               f'background:{accent};"></div></div>'
               f'<div style="font-size:10px;color:{surp_col};font-weight:700;margin-bottom:8px;">{surp_txt}</div>')

    return f"""
<div class="fplh-card-hover" style="background:rgba(22,26,34,0.85);
     border:1px solid rgba(255,255,255,0.08);border-top:3px solid {accent};
     border-radius:12px;padding:14px 16px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
    {team_dot(row.get("team_short"), size=14)}
    <div style="min-width:0;flex:1;">
      <div style="font-size:15px;font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;
           text-overflow:ellipsis;">{name}</div>
      <div style="font-size:11px;color:rgba(255,255,255,0.45);">{team}</div>
    </div>
    <span style="background:{pc};color:#000;border-radius:4px;padding:1px 7px;font-size:10px;
          font-weight:900;flex-shrink:0;">{pos}</span>
    <span style="font-size:14px;flex-shrink:0;" title="{verdict}">{emoji}</span>
  </div>
  <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:8px;">{mid}</div>
  {bar}
  <div style="font-size:11px;color:rgba(255,255,255,0.7);margin-bottom:8px;line-height:1.35;">{reason}</div>
  <ul style="margin:0;padding-left:16px;font-size:11px;color:rgba(255,255,255,0.55);">{q_html}</ul>
</div>
"""


def _lane(df: pd.DataFrame, accent: str) -> None:
    if df.empty:
        st.info("No players in this bucket right now.")
        return
    cards = "".join(_verdict_card(r) for _, r in df.iterrows())
    st.markdown(
        f'<div class="fplh-stagger" style="display:grid;'
        f'grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">{cards}</div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=6 * 3600, show_spinner="Solving optimal squad on actual prices (exact MILP)…")
def _solve_draft(board: pd.DataFrame, budget: float, bench_weight: float):
    from analytics.squad_milp import optimize_squad
    d = board.rename(columns={"actual_price": "price", "projected_points": "pts"})
    return optimize_squad(d, budget=budget, bench_weight=bench_weight, time_limit=90)


from ui.value_board import build_board
board, scout, price_bt, validation = build_board()
if board is None:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
    <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">
      📋 {NEXT_SEASON} Value Board</div>
    <span style="background:rgba(0,255,135,0.12);border:1px solid rgba(0,255,135,0.4);
      color:#00FF87;font-size:10px;font-weight:800;letter-spacing:0.12em;padding:4px 10px;
      border-radius:20px;text-transform:uppercase;">● Live · actual prices in</span>
  </div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    Real launch prices vs projected points · who came in under price, who's a necessity, who's too dear
  </div>
</div>""",
    unsafe_allow_html=True,
)

# verdict counts + model tiles
counts = board["verdict"].value_counts().to_dict()
worst_pair = min(validation.values(), key=lambda v: v["spearman"])
best_pair = max(validation.values(), key=lambda v: v["spearman"])
tiles = [
    ("Necessity", str(counts.get(VERDICTS.NECESSITY, 0)), "template must-haves", "#FFD700"),
    ("Value", str(counts.get(VERDICTS.VALUE, 0)), "priced under projection", "#00FF87"),
    ("Overpriced", str(counts.get(VERDICTS.OVERPRICED, 0)), "pay up, get less", "#FF4B4B"),
    ("Scout", str(len(scout)), "new · no 25/26 history", "#04f5ff"),
    ("Points signal", f"ρ {best_pair['spearman']:.2f}",
     f"{worst_pair['spearman']:.2f} in a rule-change year", "#04f5ff"),
]
st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;">'
    + "".join(
        (f'<div style="{CARD}flex:1;min-width:150px;">'
         f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};text-transform:uppercase;">{lab}</div>'
         f'<div style="font-size:24px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
         f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>')
        for lab, val, sub, acc in tiles)
    + "</div>",
    unsafe_allow_html=True,
)

# ── Controls + solve on ACTUAL prices ──────────────────────────────────────────
c1, c2, _ = st.columns([1, 1, 2])
with c1:
    budget = st.slider("Budget (£m)", 95.0, 105.0, 100.0, 0.5)
with c2:
    bench_weight = st.slider("Bench weighting", 0.0, 0.5, 0.1, 0.05,
                             help="How much bench points matter vs the XI. Planning a "
                                  "Bench Boost in GW1? Push this up so the solver builds a "
                                  "bench that actually plays.")

res = _solve_draft(board, budget, bench_weight)
if res is None:
    st.error("Solver found no feasible squad · widen the budget.")
    st.stop()

squad = res["squad"]

_sec = lambda t: st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:26px 0 10px;">'
    f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;'
    f'color:{MUTED};white-space:nowrap;">{t}</div>'
    f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>',
    unsafe_allow_html=True)

_sec(f"Optimal squad · £{res['squad_cost']:.1f}m real spend · {res['xi_points']:.0f} projected XI pts (incl. captain)")

from components.pitch_view import render_squad_pitch

render_squad_pitch(
    [{
        "web_name": r["web_name"],
        "position": r["position"],
        "team_code": int(r.get("team_code", 1) or 1),
        "on_bench": not r["in_xi"],
        "is_captain": bool(r["is_captain"]),
        "stat": float(r["pts"]),
        "price": float(r["price"]),
    } for _, r in squad.iterrows()],
    stat_label="proj", title_right=NEXT_SEASON)

# ── Verdict lanes ──────────────────────────────────────────────────────────────
_sec("🎯 The verdict · who to want, who to swerve")
st.markdown(
    f'<div style="font-size:13px;color:{MUTED};margin:-2px 0 12px;">'
    f'Projected points come from last season, so injury returnees look cheap in points '
    f'until minutes are confirmed · use the scout reads on each card.</div>',
    unsafe_allow_html=True,
)

n_nec = board[board["verdict"] == VERDICTS.NECESSITY].sort_values("projected_points", ascending=False)
n_val = board[board["verdict"] == VERDICTS.VALUE].sort_values("value_score", ascending=False).head(18)
n_over = board[board["verdict"] == VERDICTS.OVERPRICED].sort_values("actual_price", ascending=False)
n_scout = scout.head(18)

t_nec, t_val, t_over, t_scout = st.tabs([
    f"🥇 Necessity ({len(n_nec)})",
    f"🟢 Value ({len(board[board['verdict'] == VERDICTS.VALUE])})",
    f"🔴 Overpriced ({len(n_over)})",
    f"🔍 Scout · new ({len(scout)})",
])
with t_nec:
    st.caption(VERDICT_META[VERDICTS.NECESSITY][2])
    _lane(n_nec.head(18), "#FFD700")
with t_val:
    st.caption(VERDICT_META[VERDICTS.VALUE][2])
    _lane(n_val, "#00FF87")
with t_over:
    st.caption(VERDICT_META[VERDICTS.OVERPRICED][2])
    _lane(n_over, "#FF4B4B")
with t_scout:
    st.caption(VERDICT_META[VERDICTS.SCOUT][2])
    _lane(n_scout, "#04f5ff")

# ── Minutes → points thesis, coloured by verdict ───────────────────────────────
_sec("Minutes drive points · the whole thesis in one view")
_groups = []
for verdict, acc, _e, _m in [(k,) + v for k, v in VERDICT_META.items() if k != VERDICTS.SCOUT]:
    d = board[board["verdict"] == verdict]
    if d.empty:
        continue
    _groups.append((verdict, acc, [
        {"x": int(r["projected_minutes"]), "y": round(float(r["projected_points"]), 1),
         "name": str(r["web_name"]), "size": 7,
         "tip": (f"{r['web_name']} · {r['team_name']}<br/>£{r['actual_price']:.1f}m · "
                 f"{int(r['projected_minutes']):,} mins → {r['projected_points']:.0f} pts")}
        for _, r in d.iterrows()
    ]))
charts.render(
    charts.multi_scatter_option(_groups, x_name="Projected minutes 26/27", y_name="Projected points"),
    height="340px", key="board_min_pts",
)

# ── Full table ─────────────────────────────────────────────────────────────────
_sec("Every price · every verdict")
tab_all, tab_surprise = st.tabs(["All players", "Biggest bargains & taxes"])

table = board[["web_name", "position", "team_name", "verdict", "price_2025_26_end",
               "actual_price", "pricing_surprise", "projected_points", "value_score",
               "ownership", "last_season_points"]].copy()
table.columns = ["Player", "Pos", "Team", "Verdict", "End 25/26 (£m)", "Price 26/27 (£m)",
                 "vs model (£m)", "Proj pts", "Pts/£m", "Owned %", "25/26 pts"]
table = table.round(2)

with tab_all:
    st.dataframe(table.sort_values("Proj pts", ascending=False),
                 use_container_width=True, height=420, hide_index=True)
with tab_surprise:
    st.caption("Positive vs model = FPL priced them below the model (bargain). Negative = tax.")
    st.dataframe(table.reindex(table["vs model (£m)"].abs().sort_values(ascending=False).index).head(40),
                 use_container_width=True, height=420, hide_index=True)

st.markdown(
    f'<div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:18px;">'
    f'Projections fitted on 9 historical season-pairs; points signal is honest, not heroic. '
    f'Promoted-club and new-signing players have no FPL history · they are in the Scout tab, '
    f'not force-ranked. Re-check minutes and set-piece roles once {NEXT_SEASON} line-ups firm up.</div>',
    unsafe_allow_html=True)
