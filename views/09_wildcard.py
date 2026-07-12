"""
Wildcard Planner · overhauled.

When to play the Wildcard, and what the squad should be.

Timing: every remaining GW is scored by the projected points of its best
possible 15-man squad (greedy scan · fast, relative ranking is what
matters). The selected GW's squad is then solved EXACTLY with the MILP
(analytics/squad_milp.py) and rendered on a pitch with kits.

Off-season: shows a friendly hand-off to the 26/27 Draft page.
"""

import numpy as np
import pandas as pd
import streamlit as st

from components.loading import LINES_GENERIC, fpl_loader
from typing import Dict, List

from ui import charts

from components.animations import inject_global_animations
from components.pitch_view import render_squad_pitch

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:14px 18px;")

SQUAD_LIMITS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


# ── Data ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_data():
    from data.fetchers.fpl_api import (fetch_bootstrap, fetch_fixtures,
                                       get_current_gameweek, get_fixtures_df)
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    bs = fetch_bootstrap()
    players = build_player_universe(bootstrap=bs,
                                    understat_df=fetch_understat_players())
    fixtures_df = get_fixtures_df(fetch_fixtures(), bs)
    return players, bs, fixtures_df, get_current_gameweek(bs)


def _gw_fdr_map(fixtures_df: pd.DataFrame, gw: int) -> Dict[int, List[float]]:
    gw_fix = fixtures_df[fixtures_df["gameweek"] == gw]
    fdr_map: Dict[int, List[float]] = {}
    for _, row in gw_fix.iterrows():
        for side in ("home", "away"):
            tid = int(row["home_team_id"] if side == "home" else row["away_team_id"])
            fdr = float(row["home_fdr"] if side == "home" else row["away_fdr"])
            fdr_map.setdefault(tid, []).append(fdr)
    return fdr_map


def _project_gw(players_df: pd.DataFrame, fdr_map: Dict[int, List[float]]) -> pd.DataFrame:
    df = players_df[players_df["status"] == "a"].copy()
    df["gw_fdr_list"] = df["team_id"].map(lambda t: fdr_map.get(int(t), []))
    df["n_fixtures"] = df["gw_fdr_list"].apply(len)

    def _pts(r):
        if not r["gw_fdr_list"]:
            return 0.0
        ppg = float(r.get("points_per_game", 0) or 0)
        ease = np.mean([1.0 + (3.0 - f) * 0.15 for f in r["gw_fdr_list"]])
        return ppg * ease * len(r["gw_fdr_list"])

    df["projected_gw"] = df.apply(_pts, axis=1)
    return df


def _greedy_squad_total(df: pd.DataFrame, budget: float) -> Dict:
    """Fast relative score for GW ranking (exact MILP runs on the pick)."""
    selected, pos_counts, cost, teams_in = [], {p: 0 for p in SQUAD_LIMITS}, 0.0, {}
    for _, row in df.sort_values("projected_gw", ascending=False).iterrows():
        pos, c, tid = str(row.get("position", "")), float(row.get("price", 0) or 0), int(row.get("team_id", 0) or 0)
        if pos not in pos_counts or pos_counts[pos] >= SQUAD_LIMITS[pos]:
            continue
        if cost + c > budget or teams_in.get(tid, 0) >= 3 or len(selected) >= 15:
            continue
        selected.append(row)
        pos_counts[pos] += 1
        cost += c
        teams_in[tid] = teams_in.get(tid, 0) + 1
    squad = pd.DataFrame(selected) if selected else pd.DataFrame()
    return {
        "total_pts": float(squad["projected_gw"].sum()) if not squad.empty else 0.0,
        "n_dgw": int((squad["n_fixtures"] >= 2).sum()) if not squad.empty else 0,
        "n_bgw": int((squad["n_fixtures"] == 0).sum()) if not squad.empty else 0,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def scan_gameweeks(players_df: pd.DataFrame, fixtures_df: pd.DataFrame,
                   current_gw: int, budget: float) -> pd.DataFrame:
    rows = []
    for gw in range(current_gw + 1, 39):
        proj = _project_gw(players_df, _gw_fdr_map(fixtures_df, gw))
        rows.append({"gw": gw, **_greedy_squad_total(proj, budget)})
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner="Solving exact optimal squad…")
def exact_squad_for_gw(players_df: pd.DataFrame, fixtures_df: pd.DataFrame,
                       gw: int, budget: float):
    from analytics.squad_milp import optimize_squad
    proj = _project_gw(players_df, _gw_fdr_map(fixtures_df, gw))
    proj = proj.rename(columns={"projected_gw": "pts"})
    res = optimize_squad(proj, budget=budget, bench_weight=0.05, time_limit=60)
    return res, proj


# ── Page ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">
    🃏 Wildcard Planner</div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    When to burn it, and exactly what the squad should be · solved, not guessed
  </div>
</div>""",
    unsafe_allow_html=True,
)

with fpl_loader("Reading the season state", LINES_GENERIC):
    players_df, bootstrap, fixtures_df, current_gw = load_data()

budget = st.sidebar.slider("Wildcard budget (£m)", 95.0, 110.0, 100.0, 0.5,
                           help="Your squad's selling value + bank.")

scan = scan_gameweeks(players_df, fixtures_df, current_gw, budget)

# ── Off-season state ──────────────────────────────────────────────────────────
if scan.empty or scan["total_pts"].max() <= 0:
    st.markdown(
        f'<div style="{CARD}border-top:3px solid #FFD700;max-width:640px;'
        f'margin:30px 0;padding:28px;">'
        f'<div style="font-size:22px;font-weight:900;color:#fff;">Season over 🌴</div>'
        f'<div style="font-size:13px;color:{MUTED};margin-top:8px;line-height:1.6;">'
        f'No remaining gameweeks to wildcard into. Planning for next season lives in '
        f'the <b style="color:#FFD700;">26/27 Draft</b> · predicted prices, projected '
        f'points and the optimal GW1 squad. This page wakes up when the 2026-27 '
        f'fixtures land.</div></div>',
        unsafe_allow_html=True)
    try:
        st.page_link("views/18_draft_2026_27.py", label="Open the 26/27 Draft →")
    except Exception:
        pass  # page_link only resolves inside the multipage app
    st.stop()

# ── Timing ────────────────────────────────────────────────────────────────────
best_row = scan.loc[scan["total_pts"].idxmax()]
best_gw = int(best_row["gw"])

st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;">'
    + "".join(
        f'<div style="{CARD}flex:1;min-width:150px;">'
        f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};'
        f'text-transform:uppercase;">{lab}</div>'
        f'<div style="font-size:26px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>'
        for lab, val, sub, acc in [
            ("Best wildcard window", f"GW{best_gw}",
             f"{best_row['total_pts']:.1f} projected squad pts", "#FFD700"),
            ("DGW players available", f"{int(best_row['n_dgw'])}",
             "in that optimal squad", "#00FF87"),
            ("Windows analysed", f"{len(scan)}", f"GW{current_gw + 1}–38", "#04f5ff"),
        ])
    + "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:26px 0 10px;">'
    f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;'
    f'color:{MUTED};white-space:nowrap;">Opportunity by gameweek</div>'
    f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>',
    unsafe_allow_html=True)

colors = ["#FFD700" if int(r["gw"]) == best_gw
          else "#00FF87" if r["n_dgw"] >= 3 else "rgba(4,245,255,0.55)"
          for _, r in scan.iterrows()]
opt = charts.bar_option(
    x=[str(int(g)) for g in scan["gw"]],
    y=[round(float(v), 1) for v in scan["total_pts"]],
    colors=colors,
)
for item, (_, r) in zip(opt["series"][0]["data"], scan.iterrows()):
    txt = str(int(round(r["total_pts"])))
    if r["n_dgw"] >= 2:
        txt = f"{{dgw|{int(r['n_dgw'])}×DGW}}\n{txt}"
    item["label"] = {
        "show": True, "position": "top", "formatter": txt,
        "color": "rgba(255,255,255,0.7)", "fontSize": 10,
        "rich": {"dgw": {"color": "#FFD700", "fontSize": 9, "fontWeight": "bold"}},
    }
opt["grid"]["top"] = 34
opt["tooltip"]["formatter"] = "GW{b} · {c} pts"
charts.render(opt, height="360px", key="wc_opportunity")

# ── Exact squad on the pitch ──────────────────────────────────────────────────
st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:26px 0 10px;">'
    f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;'
    f'color:{MUTED};white-space:nowrap;">The squad, solved exactly</div>'
    f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>'
    f'<div style="font-size:12px;color:rgba(255,255,255,0.4);margin-bottom:10px;">'
    f'MILP-optimal 15 for the chosen week · provably the best within budget, '
    f'3-per-club and formation rules.</div>',
    unsafe_allow_html=True)

gw_options = scan["gw"].tolist()
sel_gw = st.selectbox("Wildcard gameweek", gw_options,
                      index=gw_options.index(best_gw),
                      format_func=lambda g: f"GW{g}" + (" ⭐ best window" if g == best_gw else ""))

res, proj = exact_squad_for_gw(players_df, fixtures_df, int(sel_gw), budget)
if res is None:
    st.error("Solver found no feasible squad at this budget.")
    st.stop()

squad = res["squad"]
st.markdown(
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">'
    + "".join(f'<span style="background:rgba(255,215,0,0.1);border:1px solid '
              f'rgba(255,215,0,0.35);color:#FFD700;font-size:12px;font-weight:800;'
              f'padding:4px 12px;border-radius:20px;">{b}</span>'
              for b in [f"GW{sel_gw}", f"£{res['squad_cost']:.1f}m",
                        f"{res['xi_points']:.1f} projected XI pts (incl. captain)"])
    + "</div>", unsafe_allow_html=True)

render_squad_pitch(
    [{
        "web_name": r.get("web_name", "?"),
        "position": r.get("position", "MID"),
        "team_code": int(r.get("team_code", 1) or 1),
        "on_bench": not r["in_xi"],
        "is_captain": bool(r["is_captain"]),
        "stat": float(r["pts"]),
        "price": float(r.get("price", 0) or 0),
    } for _, r in squad.iterrows()],
    stat_label="proj", title_right=f"GW{sel_gw}")

dgw_names = squad[squad["n_fixtures"] >= 2]["web_name"].tolist() \
    if "n_fixtures" in squad.columns else []
if dgw_names:
    st.markdown(
        f'<div style="font-size:12px;color:#00FF87;margin-top:8px;">'
        f'DGW that week: {", ".join(dgw_names)}</div>', unsafe_allow_html=True)
