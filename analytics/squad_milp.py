"""
Single-period 15-man squad MILP (PuLP/CBC).

Exact replacement for the greedy knapsack in points_model.py · picks the
provably optimal squad + starting XI + captain for one scoring vector.

Used by:
  - the Perfect Season Free Hit post-pass (actual GW points)
  - the 2026-27 Optimal Value Draft (projected points, predicted prices)
  - anywhere the wildcard/free-hit pages want an exact answer

Input: DataFrame with columns  code (or any id col), position, price, pts
       plus team_id for the 3-per-club constraint.
"""

import logging
from typing import Dict, Optional

import pandas as pd
import pulp

from config import PERFECT_SEASON

logger = logging.getLogger(__name__)


def optimize_squad(
    players: pd.DataFrame,
    budget: float = 100.0,
    pts_col: str = "pts",
    bench_weight: float = 0.1,
    captain: bool = True,
    time_limit: int = 60,
) -> Optional[Dict]:
    """
    Pick the optimal 15 (2-5-5-3, ≤3 per club, budget), best legal XI and
    captain, maximizing XI points + captain points + bench_weight × bench
    points. Returns dict with squad/lineup/captain DataFrames + totals,
    or None if infeasible.
    """
    df = players.dropna(subset=[pts_col, "price", "position"]).reset_index(drop=True)
    idx = list(df.index)
    limits = PERFECT_SEASON["squad_limits"]
    lineup_min = PERFECT_SEASON["lineup_min"]

    prob = pulp.LpProblem("squad", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("squad", idx, cat="Binary")
    lineup = pulp.LpVariable.dicts("lineup", idx, cat="Binary")
    cap = pulp.LpVariable.dicts("cap", idx, cat="Binary")

    pts = df[pts_col].astype(float)
    prob += pulp.lpSum(
        pts[i] * (lineup[i] + cap[i] * (1 if captain else 0)
                  + bench_weight * (squad[i] - lineup[i]))
        for i in idx
    )

    prob += pulp.lpSum(squad[i] for i in idx) == 15
    prob += pulp.lpSum(lineup[i] for i in idx) == 11
    prob += pulp.lpSum(cap[i] for i in idx) == (1 if captain else 0)
    prob += pulp.lpSum(df.loc[i, "price"] * squad[i] for i in idx) <= budget

    for pos, n in limits.items():
        pos_idx = [i for i in idx if df.loc[i, "position"] == pos]
        prob += pulp.lpSum(squad[i] for i in pos_idx) == n
        lo = lineup_min[pos]
        prob += pulp.lpSum(lineup[i] for i in pos_idx) >= lo
        if pos == "GKP":
            prob += pulp.lpSum(lineup[i] for i in pos_idx) == 1

    if "team_id" in df.columns:
        for team in df["team_id"].dropna().unique():
            t_idx = [i for i in idx if df.loc[i, "team_id"] == team]
            prob += pulp.lpSum(squad[i] for i in t_idx) <= PERFECT_SEASON["max_per_club"]

    for i in idx:
        prob += lineup[i] <= squad[i]
        prob += cap[i] <= lineup[i]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))
    if pulp.LpStatus[status] not in ("Optimal", "Not Solved"):
        logger.warning(f"squad MILP status: {pulp.LpStatus[status]}")
        return None

    picked = [i for i in idx if squad[i].value() and squad[i].value() > 0.5]
    if len(picked) != 15:
        return None
    started = [i for i in picked if lineup[i].value() and lineup[i].value() > 0.5]
    cap_i = next((i for i in started if cap[i].value() and cap[i].value() > 0.5), None)

    squad_df = df.loc[picked].copy()
    squad_df["in_xi"] = squad_df.index.isin(started)
    squad_df["is_captain"] = squad_df.index == cap_i

    xi_pts = float(pts[started].sum()) + (float(pts[cap_i]) if cap_i is not None else 0.0)
    return {
        "squad": squad_df.sort_values(["in_xi", pts_col], ascending=[False, False]),
        "xi_points": round(xi_pts, 2),
        "squad_cost": round(float(squad_df["price"].sum()), 1),
        "captain_idx": cap_i,
        "solver_status": pulp.LpStatus[status],
    }
