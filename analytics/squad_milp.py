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
from typing import Dict, List, Optional

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
    bench_budget: Optional[float] = None,
    force_codes: Optional[List] = None,
    exclude_codes: Optional[List] = None,
    max_attackers_per_club: Optional[int] = None,
    defcon_codes: Optional[List] = None,
    max_defenders_per_club: Optional[int] = None,
    bench_pts_col: Optional[str] = None,
) -> Optional[Dict]:
    """
    Pick the optimal 15 (2-5-5-3, ≤3 per club, budget), best legal XI and
    captain, maximizing XI points + captain points + bench_weight × bench
    points. Returns dict with squad/lineup/captain DataFrames + totals,
    or None if infeasible.

    `force_codes` · player `code`s that MUST be in the 15 (e.g. Haaland).
    `exclude_codes` · player `code`s that must NOT be picked. Both no-op if the
    frame has no `code` column.
    """
    df = players.dropna(subset=[pts_col, "price", "position"]).reset_index(drop=True)
    if exclude_codes and "code" in df.columns:
        df = df[~df["code"].isin(exclude_codes)].reset_index(drop=True)
    idx = list(df.index)
    limits = PERFECT_SEASON["squad_limits"]
    lineup_min = PERFECT_SEASON["lineup_min"]

    prob = pulp.LpProblem("squad", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("squad", idx, cat="Binary")
    lineup = pulp.LpVariable.dicts("lineup", idx, cat="Binary")
    cap = pulp.LpVariable.dicts("cap", idx, cat="Binary")

    pts = df[pts_col].astype(float)

    # What a benched player is actually worth.
    #
    # `bench_weight` is a fudge: it says a bench player is worth some fraction
    # of a starter, which is true of nothing in particular. When you know you
    # will play a Bench Boost, the truth is exact · in that ONE gameweek every
    # one of the fifteen scores, and in the others only the eleven do. Pass
    # `bench_pts_col` holding each player's points in the boost week and the
    # objective becomes the plan itself rather than a proxy for it.
    #
    # This matters because chasing a bench POINTS TARGET is a constraint, not
    # an objective, and optimising against it can build a worse fifteen: you
    # end up buying bench quality that never earns its price in the ten weeks
    # you are not boosting.
    if bench_pts_col is not None and bench_pts_col in df.columns:
        bench_pts = df[bench_pts_col].astype(float)
        prob += pulp.lpSum(
            pts[i] * (lineup[i] + cap[i] * (1 if captain else 0))
            + bench_pts[i] * (squad[i] - lineup[i])
            for i in idx
        )
    else:
        prob += pulp.lpSum(
            pts[i] * (lineup[i] + cap[i] * (1 if captain else 0)
                      + bench_weight * (squad[i] - lineup[i]))
            for i in idx
        )

    prob += pulp.lpSum(squad[i] for i in idx) == 15
    prob += pulp.lpSum(lineup[i] for i in idx) == 11
    prob += pulp.lpSum(cap[i] for i in idx) == (1 if captain else 0)
    prob += pulp.lpSum(df.loc[i, "price"] * squad[i] for i in idx) <= budget
    if bench_budget is not None:
        # Playbook Q11 doctrine: bench money is dead money · cap what the four
        # non-starters may cost so the surplus is forced into the XI.
        prob += pulp.lpSum(df.loc[i, "price"] * (squad[i] - lineup[i])
                           for i in idx) <= bench_budget

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

    # Attack-correlation cap · at most N attack-correlated (MID/FWD) players per
    # club. DEFCON mids (Garner) are exempt · their points don't ride the team's
    # attack, so a same-club defcon+attacker pair stays legal.
    if max_attackers_per_club is not None and "team_id" in df.columns:
        defcon = set(defcon_codes or [])
        has_code = "code" in df.columns
        for team in df["team_id"].dropna().unique():
            a_idx = [i for i in idx
                     if df.loc[i, "team_id"] == team
                     and df.loc[i, "position"] in ("MID", "FWD")
                     and not (has_code and df.loc[i, "code"] in defcon)]
            if a_idx:
                prob += pulp.lpSum(squad[i] for i in a_idx) <= max_attackers_per_club

    # Defender diversification · at most N defenders per club (clean sheets are a
    # team event, so two DEF from one club is a doubled bet on the same outcome).
    if max_defenders_per_club is not None and "team_id" in df.columns:
        for team in df["team_id"].dropna().unique():
            d_idx = [i for i in idx
                     if df.loc[i, "team_id"] == team and df.loc[i, "position"] == "DEF"]
            if d_idx:
                prob += pulp.lpSum(squad[i] for i in d_idx) <= max_defenders_per_club

    for i in idx:
        prob += lineup[i] <= squad[i]
        prob += cap[i] <= lineup[i]

    if force_codes and "code" in df.columns:
        for c in force_codes:
            f_idx = [i for i in idx if df.loc[i, "code"] == c]
            if f_idx:
                prob += pulp.lpSum(squad[i] for i in f_idx) == 1

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))
    label = pulp.LpStatus[status]
    if label not in ("Optimal", "Not Solved"):
        logger.warning("squad MILP status: %s", label)
        return None

    # "Optimal" is CBC PROVING no better squad exists under these constraints.
    # "Not Solved" means the time limit bit first and the answer is merely the
    # best found so far · still usable, but it is no longer an optimum and the
    # page must not present it as one. Validated by brute force: on reduced
    # pools where every legal squad can be enumerated, this model returns the
    # exact same objective as exhaustive search.
    proven = label == "Optimal"
    if not proven:
        logger.warning("squad MILP hit the %ss limit · returning the best found, "
                       "which is not proven optimal", time_limit)

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
        "solver_status": label,
        "proven_optimal": proven,
    }


def diagnose_infeasible(players: pd.DataFrame, budget: float = 100.0,
                        pts_col: str = "pts", **kw) -> str:
    """Say WHY no squad could be built, by relaxing one rule at a time.

    A solver that returns None teaches the user nothing and reads as a broken
    model. It is almost never "you cannot afford it" · far more often a squad
    rule bites in a way nobody had in mind. Two forced Man Utd midfielders
    against a one-attacker-per-club rule is not a budget problem, and saying
    "infeasible" invites exactly the wrong fix.

    Relaxations are tried in order of how often they are the real cause.
    """
    if optimize_squad(players, budget=budget, pts_col=pts_col, **kw):
        return ""

    trials = [
        ("max_attackers_per_club",
         "the max-attackers-per-club rule · two of your forced players are "
         "attackers at the same club"),
        ("max_defenders_per_club",
         "the max-defenders-per-club rule · two of your forced players are "
         "defenders at the same club"),
        ("exclude_codes", "your vetoes · too many players are ruled out"),
        ("force_codes", "your locked players · they cannot fit together"),
    ]
    for key, why in trials:
        if kw.get(key) in (None, (), []):
            continue
        relaxed = dict(kw)
        relaxed[key] = None
        if optimize_squad(players, budget=budget, pts_col=pts_col, **relaxed):
            return why

    for extra in (5.0, 20.0):
        if optimize_squad(players, budget=budget + extra, pts_col=pts_col, **kw):
            return ("the budget · this needs about £%.0fm more than you have"
                    % extra)
    return ("the pool · after the vetoes there are not enough players left to "
            "fill a legal fifteen")
