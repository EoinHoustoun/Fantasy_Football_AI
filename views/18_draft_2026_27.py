"""
2026-27 Draft · predicted start prices, projected points, optimal GW1 squad.

Pre-launch mode: everything is a projection from the 10-season archive.
Once FPL launches the 2026-27 game (~July), the page becomes a diff view
vs actual prices (badge flips automatically when new bootstrap appears).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.animations import inject_global_animations
from components.team_identity import team_dot
from config import LAST_COMPLETE_SEASON, NEXT_SEASON
from ui import charts

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
POS_ORDER = ["GKP", "DEF", "MID", "FWD"]
MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:14px 18px;")


# ── Scout layer: tailored questions + cards for the Target Board ────────────────

def _scout_questions(row: pd.Series) -> list:
    """1-2 scouting prompts tailored to a player's signals. A projection can't
    know the new-season depth chart · these are the human reads to make before
    prices drop."""
    qs = []
    sr    = row.get("starts_ratio")
    price = float(row.get("predicted_start_price") or 0)
    share = float(row.get("mins_share") or 0)
    dpr   = float(row.get("price_delta") or 0)

    if pd.notna(sr) and sr < 0.8:
        starts = int(row.get("starts_total") or 0)
        games  = int(row.get("games_played") or 0)
        qs.append(f"Started {starts}/{games} in 25/26 · nailed now, or still rotated?")
    elif share < 0.6:
        qs.append("Model sees patchy minutes · will he lock down a starting spot?")

    if dpr >= 1.0:
        qs.append(f"Projected +£{dpr:.1f}m · is the hype backed by minutes, or a trap?")

    if price >= 9.0:
        qs.append("Premium anchor · does he own pens/set-pieces to justify the price?")
    elif price <= 4.5:
        qs.append("Cheap starter? Confirm he starts GW1 before locking him in.")

    qs.append("Any new signing or backup who could eat his minutes?")
    return qs[:2]


def _scout_card(row: pd.Series, accent: str) -> str:
    pos   = str(row.get("position", ""))
    pc    = POS_COLORS.get(pos, "#888")
    code  = int(row.get("team_code", 1) or 1)
    name  = str(row.get("web_name", "?"))
    team  = str(row.get("team_name", ""))
    price = float(row.get("predicted_start_price") or 0)
    pts   = float(row.get("projected_points") or 0)
    pmin  = int(row.get("projected_minutes") or 0)
    vscr  = float(row.get("value_score") or 0)
    share = max(0.0, min(1.0, float(row.get("mins_share") or 0)))

    q_html = "".join(
        f'<li style="margin-bottom:3px;line-height:1.3;">{q}</li>' for q in _scout_questions(row)
    )
    stat = lambda v, l, c="#fff": (
        f'<div style="text-align:center;"><div style="font-size:15px;font-weight:900;color:{c};">{v}</div>'
        f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,0.4);">{l}</div></div>'
    )
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
  </div>
  <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:8px;">
    {stat(f"£{price:.1f}", "Pred price")}
    {stat(f"{pts:.0f}", "Proj pts", "#00FF87")}
    {stat(f"{pmin:,}", "Proj mins", "#04f5ff")}
    {stat(f"{vscr:.1f}", "Pts/£m", "#FFD700")}
  </div>
  <div style="height:5px;border-radius:3px;background:rgba(255,255,255,0.08);overflow:hidden;margin-bottom:10px;">
    <div style="height:100%;width:{share*100:.0f}%;background:{accent};"></div>
  </div>
  <ul style="margin:0;padding-left:16px;font-size:11px;color:rgba(255,255,255,0.62);">{q_html}</ul>
</div>
"""


def _lane(df: pd.DataFrame, accent: str) -> None:
    if df.empty:
        st.info("No players match this filter with the current projections.")
        return
    cards = "".join(_scout_card(r, accent) for _, r in df.iterrows())
    st.markdown(
        f'<div class="fplh-stagger" style="display:grid;'
        f'grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">{cards}</div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=24 * 3600, show_spinner="Training price model + projections…")
def _build_draft_universe():
    from data.processors.archive import load_gw_archive, load_season_summary
    from analytics.price_predictor import train_price_model, predict_next_season_prices
    from analytics.season_projection import project_season, validate_projection

    summary = load_season_summary()
    if summary is None:
        return None, None, None

    trained = train_price_model(summary)
    prices = predict_next_season_prices(summary, trained)
    proj = project_season(summary, LAST_COMPLETE_SEASON)
    validation = validate_projection(summary)

    arch = load_gw_archive()
    teams = (arch[arch["season"] == LAST_COMPLETE_SEASON]
             .groupby("code")["team_id"].last().reset_index())

    uni = (proj.merge(prices[["code", "predicted_start_price", "price_2025_26_end"]],
                      on="code")
           .merge(teams, on="code"))

    # shirt codes from the archived final bootstrap (player code → team code)
    import json as _json
    from config import CACHE_DIR as _CD
    bs_path = _CD / "archive" / "fpl_bootstrap_2025_26_final.json"
    if bs_path.exists():
        with open(bs_path) as f:
            bs = _json.load(f)
        tc_map = {int(e["code"]): int(e["team_code"]) for e in bs["elements"]}
        uni["team_code"] = uni["code"].map(tc_map).fillna(1).astype(int)
        ts_map = {int(e["code"]): e.get("team") for e in bs["elements"]}
        short_by_id = {int(t["id"]): t["short_name"] for t in bs["teams"]}
        uni["team_short"] = uni["code"].map(ts_map).map(short_by_id)
    else:
        uni["team_code"] = 1
        uni["team_short"] = None
    uni["value_score"] = (uni["projected_points"] / uni["predicted_start_price"]).round(2)

    # Nailed-ness signals: model-implied minutes share + last-season starts share.
    ss = (summary[summary["season"] == LAST_COMPLETE_SEASON]
          [["code", "starts_total", "games_played"]].copy())
    uni = uni.merge(ss, on="code", how="left")
    uni["mins_share"] = (uni["projected_minutes"] / 3420.0).clip(0, 1).round(2)
    uni["starts_ratio"] = (uni["starts_total"] / uni["games_played"]).round(2)
    uni["price_delta"] = (uni["predicted_start_price"] - uni["price_2025_26_end"]).round(1)

    bt = dict(trained["backtest"][trained["winner"]])
    bt["model"] = trained["winner"]
    return uni, bt, validation


@st.cache_data(ttl=24 * 3600, show_spinner="Solving optimal draft (exact MILP)…")
def _solve_draft(uni: pd.DataFrame, budget: float, bench_weight: float,
                 bench_budget: float = 18.5):
    from analytics.squad_milp import optimize_squad
    d = uni.rename(columns={"predicted_start_price": "price",
                            "projected_points": "pts"})
    return optimize_squad(d, budget=budget, bench_weight=bench_weight,
                          time_limit=90, bench_budget=bench_budget)


uni, price_bt, validation = _build_draft_universe()
if uni is None:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:14px;">
    <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">
      📋 {NEXT_SEASON} Draft</div>
    <span style="background:rgba(255,215,0,0.12);border:1px solid rgba(255,215,0,0.4);
      color:#FFD700;font-size:10px;font-weight:800;letter-spacing:0.12em;padding:4px 10px;
      border-radius:20px;text-transform:uppercase;">Pre-launch projection</span>
  </div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    Predicted GW1 prices + projected points → the optimal value squad, before anyone else has it
  </div>
</div>""",
    unsafe_allow_html=True,
)

worst_pair = min(validation.values(), key=lambda v: v["spearman"])
best_pair = max(validation.values(), key=lambda v: v["spearman"])
st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;">'
    + "".join([
        (f'<div style="{CARD}flex:1;min-width:160px;">'
         f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};text-transform:uppercase;">{lab}</div>'
         f'<div style="font-size:24px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
         f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>')
        for lab, val, sub, acc in [
            ("Price model", f"±£{price_bt['mae']:.2f}m",
             f"{price_bt['exact_bucket']:.0%} exact · {price_bt['within_half_m']:.0%} within £0.5 "
             f"({price_bt['model']})", "#00FF87"),
            ("Points signal", f"ρ {best_pair['spearman']:.2f}",
             f"{worst_pair['spearman']:.2f} in the DEFCON rule-change year", "#04f5ff"),
            ("Universe", f"{len(uni)}", "2025-26 players · promoted clubs excluded", "#FFD700"),
        ]])
    + "</div>",
    unsafe_allow_html=True,
)

# ── Controls + solve ──────────────────────────────────────────────────────────
c1, c2, _ = st.columns([1, 1, 2])
with c1:
    budget = st.slider("Budget (£m)", 95.0, 105.0, 100.0, 0.5)
with c2:
    bench_weight = st.slider("Bench weighting", 0.0, 0.5, 0.1, 0.05,
                             help="How much bench points matter vs pure XI.")
    bench_budget = st.slider(
        "Bench budget cap (£m)", 16.5, 25.0, 18.5, 0.5,
        help="Playbook Q11: bench money is dead money. The cap forces the "
             "solver to spend on the eleven who score · ~£18.5 funds one "
             "playing DEFCON defender as first sub plus fodder.")

res = _solve_draft(uni, budget, bench_weight, bench_budget)
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

_sec(f"Optimal squad · £{res['squad_cost']:.1f}m · {res['xi_points']:.0f} projected XI pts (incl. captain)")

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

# ── Target Board · who to want when prices drop ────────────────────────────────
_sec("🎯 Target board · who to want when prices drop")
st.markdown(
    f'<div style="font-size:13px;color:{MUTED};margin:-2px 0 12px;">'
    f'Minutes-first, per your Playbook (minutes ↔ points, ρ≈0.98). Bar = projected '
    f'minutes share of a full season. Each pick comes with the reads to check once the '
    f'{NEXT_SEASON} game is live and depth charts are known.</div>',
    unsafe_allow_html=True,
)

# Meaningful graph: the whole thesis in one view · minutes drive points.
_mp_groups = []
for pos in POS_ORDER:
    d = uni[uni["position"] == pos]
    _mp_groups.append((pos, POS_COLORS[pos], [
        {"x": int(r["projected_minutes"]), "y": round(float(r["projected_points"]), 1),
         "name": str(r["web_name"]), "size": 7,
         "tip": (f"{r['web_name']} · {r['team_name']}<br/>"
                 f"{int(r['projected_minutes']):,} mins → {r['projected_points']:.0f} pts"
                 f" · £{r['predicted_start_price']:.1f}m")}
        for _, r in d.iterrows()
    ]))
charts.render(
    charts.multi_scatter_option(_mp_groups, x_name="Projected minutes 26/27",
                                y_name="Projected points"),
    height="340px", key="draft_min_pts",
)

lane_nailed  = uni[(uni["projected_minutes"] >= 2400) & (uni["predicted_start_price"] <= 7.0)] \
                  .sort_values("value_score", ascending=False).head(12)
lane_premium = uni[uni["predicted_start_price"] >= 9.0] \
                  .sort_values("projected_points", ascending=False).head(10)
lane_risk    = uni[(uni["predicted_start_price"] >= 6.0) & (uni["mins_share"] < 0.6)] \
                  .sort_values("predicted_start_price", ascending=False).head(12)
lane_enabler = uni[(uni["predicted_start_price"] <= 4.5) & (uni["projected_minutes"] >= 1800)] \
                  .sort_values("projected_minutes", ascending=False).head(12)

t_nailed, t_prem, t_risk, t_enab = st.tabs([
    f"💚 Nailed value ({len(lane_nailed)})",
    f"⭐ Premium anchors ({len(lane_premium)})",
    f"⚠️ Rotation risks ({len(lane_risk)})",
    f"🪙 Enablers ({len(lane_enabler)})",
])
with t_nailed:
    st.caption("High projected minutes for ≤ £7.0m · the value engine room.")
    _lane(lane_nailed, "#00FF87")
with t_prem:
    st.caption("£9.0m+ anchors by projected points · sanity-check they're nailed and on set-pieces.")
    _lane(lane_premium, "#FFD700")
with t_risk:
    st.caption("Priced ≥ £6.0m but projected under 60% of a season's minutes · be careful.")
    _lane(lane_risk, "#FF4B4B")
with t_enab:
    st.caption("≤ £4.5m and still projected to play · the bench that actually starts.")
    _lane(lane_enabler, "#04f5ff")

# ── Full price-prediction table ───────────────────────────────────────────────
_sec("Every predicted price")
tab_all, tab_risers = st.tabs(["All players", "Biggest repricings"])

table = uni[["web_name", "position", "team_name", "price_2025_26_end",
             "predicted_start_price", "projected_points", "projected_minutes",
             "value_score", "last_season_points"]].copy()
table.columns = ["Player", "Pos", "Team", "End 25/26 (£m)", "Pred 26/27 (£m)",
                 "Proj pts", "Proj mins", "Pts/£m", "25/26 pts"]
table = table.round(2)

with tab_all:
    st.dataframe(table.sort_values("Proj pts", ascending=False),
                 use_container_width=True, height=420, hide_index=True)
with tab_risers:
    table["Δ price"] = (table["Pred 26/27 (£m)"] - table["End 25/26 (£m)"]).round(1)
    st.dataframe(table.reindex(table["Δ price"].abs().sort_values(ascending=False).index)
                 .head(40), use_container_width=True, height=420, hide_index=True)

st.markdown(
    f'<div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:18px;">'
    f'Projections trained on 9 historical season-pairs. Promoted-club players and new '
    f'signings have no FPL history and are excluded · re-check after the {NEXT_SEASON} '
    f'game launches. Points signal is honest, not heroic: season-to-season FPL is noisy.</div>',
    unsafe_allow_html=True)
