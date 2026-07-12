"""Suggest a multi-week transfer plan · the advisor behind "Optimise my plan".

Greedy sequential optimiser over the shared xP horizon (analytics/xp_engine):
week by week it looks for the like-for-like swap that buys the most expected
points over the REST of the horizon, respecting the real rules:

  · budget (bank + sale price), like-for-like positions (formation stays legal)
  · max 3 players per club
  · free-transfer banking (1/week, +1 banked, cap 5) · a hit (−4) is only
    taken when the remaining-horizon gain clears it by a margin
  · minutes-gated candidates (no bench-fodder mirages) · Playbook doctrine:
    hits are almost never worth it, so the bar for one is high

Bench players can be upgraded but their gain is discounted (they mostly don't
score), which naturally points the budget at the XI.

Pure logic · no Streamlit. Python 3.8 typing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from analytics.squad_planner import FT_CAP, HIT_COST

MAX_MOVES_PER_WEEK = 2
FT_GAIN_THRESHOLD = 1.0      # a free move must buy at least this much xP
HIT_MARGIN = 2.0             # a hit move must clear the 4-pt cost by this much
BENCH_DISCOUNT = 0.2         # bench upgrades barely score
CANDIDATES_PER_POS = 10      # pool depth per position per week (speed)


def _club_counts(squad: List[Dict[str, Any]]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for p in squad:
        tid = int(p.get("team_id") or 0)
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def suggest_plan(base_squad: pd.DataFrame,
                 players_df: pd.DataFrame,
                 xp: pd.DataFrame,
                 first_gw: int,
                 horizon: int,
                 bank: float,
                 ft_start: int = 1,
                 ) -> Tuple[Dict[int, List[Dict[str, Any]]], List[str], Dict[str, float]]:
    """Returns ({gw: [transfer dicts]}, rationale lines, summary).

    Transfer dicts match squad_planner's schema (out_id/in_id/names/prices/
    position) so they can be written straight into drafts. summary carries
    {"xp_gain", "hits", "net"} for the headline verdict.
    """
    gws = [g for g in range(int(first_gw), int(first_gw) + int(horizon))
           if g in xp.columns]
    _summary = {"xp_gain": 0.0, "hits": 0, "net": 0.0}
    if not gws:
        return {}, ["No projected gameweeks available."], _summary

    def _xp_rest(pid: int, from_gw: int) -> float:
        cols = [g for g in gws if g >= from_gw]
        if int(pid) not in xp.index or not cols:
            return 0.0
        return float(xp.loc[int(pid), cols].sum())

    # Working squad state
    squad: List[Dict[str, Any]] = []
    for _, r in base_squad.iterrows():
        squad.append({
            "fpl_id": int(r["fpl_id"]), "web_name": str(r["web_name"]),
            "position": str(r["position"]), "price": float(r["price"]),
            "team_id": int(r.get("team_id") or 0),
            "on_bench": bool(r.get("on_bench", False)),
        })

    pool = players_df[players_df["status"] == "a"].copy()
    pool["_mins_ok"] = pd.to_numeric(pool.get("avg_minutes"),
                                     errors="coerce").fillna(0) >= 45

    plan: Dict[int, List[Dict[str, Any]]] = {}
    notes: List[str] = []
    fts = int(ft_start)
    bank = float(bank)

    for gw in gws:
        moves_this_week: List[Dict[str, Any]] = []
        for _slot in range(MAX_MOVES_PER_WEEK):
            owned = {p["fpl_id"] for p in squad}
            clubs = _club_counts(squad)

            best = None   # (net_gain, raw_gain, out_p, in_row, uses_hit)
            for out_p in squad:
                out_rest = _xp_rest(out_p["fpl_id"], gw)
                budget = bank + out_p["price"]
                cand = pool[
                    (pool["position"] == out_p["position"])
                    & (pool["price"] <= budget + 0.01)
                    & (~pool["fpl_id"].isin(owned))
                    & (pool["_mins_ok"])
                ]
                if cand.empty:
                    continue
                cand = cand.assign(
                    _rest=[_xp_rest(int(i), gw) for i in cand["fpl_id"]]
                ).sort_values("_rest", ascending=False).head(CANDIDATES_PER_POS)

                for _, c in cand.iterrows():
                    tid = int(c.get("team_id") or 0)
                    same_club = int(out_p["team_id"] == tid)
                    if clubs.get(tid, 0) - same_club + 1 > 3:
                        continue
                    gain = float(c["_rest"]) - out_rest
                    if out_p["on_bench"]:
                        gain *= BENCH_DISCOUNT
                    uses_hit = len(moves_this_week) >= fts
                    net = gain - (HIT_COST if uses_hit else 0)
                    threshold = (HIT_MARGIN if uses_hit else FT_GAIN_THRESHOLD)
                    if net < threshold:
                        continue
                    if best is None or net > best[0]:
                        best = (net, gain, out_p, c, uses_hit)

            if best is None:
                break
            net, gain, out_p, in_row, uses_hit = best
            move = {
                "out_id": int(out_p["fpl_id"]), "out_name": out_p["web_name"],
                "in_id": int(in_row["fpl_id"]), "in_name": str(in_row["web_name"]),
                "position": out_p["position"],
                "price_out": round(out_p["price"], 1),
                "price_in": round(float(in_row["price"]), 1),
            }
            moves_this_week.append(move)
            _summary["xp_gain"] += gain
            if uses_hit:
                _summary["hits"] += 1
            notes.append(
                f"GW{gw}: {out_p['web_name']} → {in_row['web_name']} · "
                f"+{gain:.1f} xP over the run"
                + (f" (−{HIT_COST} hit, net +{net:.1f})" if uses_hit else " (free)"))
            # Apply to working state
            bank += out_p["price"] - float(in_row["price"])
            squad = [p for p in squad if p["fpl_id"] != out_p["fpl_id"]]
            squad.append({
                "fpl_id": int(in_row["fpl_id"]), "web_name": str(in_row["web_name"]),
                "position": out_p["position"], "price": float(in_row["price"]),
                "team_id": int(in_row.get("team_id") or 0),
                "on_bench": out_p["on_bench"],
            })

        if moves_this_week:
            plan[gw] = moves_this_week
        fts = min(FT_CAP, max(0, fts - len(moves_this_week)) + 1)

    _summary["net"] = _summary["xp_gain"] - _summary["hits"] * HIT_COST
    if not plan:
        notes.append("No move clears the bar · your squad already tracks the "
                     "xP frontier for this horizon. Bank the transfer.")
    return plan, notes, _summary
