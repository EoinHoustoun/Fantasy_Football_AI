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

# "Cover from this club" groups the pitch into the two things a club result
# actually pays out on: a clean sheet (keeper + defenders) and goals
# (midfielders + forwards).
COVER_POSITIONS = {"def": ("GKP", "DEF"), "att": ("MID", "FWD")}


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
    gw_pts_cols: Optional[List[str]] = None,
    boost_col: Optional[str] = None,
    min_club_cover: Optional[List] = None,
    max_from_club: Optional[List] = None,
) -> Optional[Dict]:
    """
    Pick the optimal 15 (2-5-5-3, ≤3 per club, budget), best legal XI and
    captain, maximizing XI points + captain points + bench_weight × bench
    points. Returns dict with squad/lineup/captain DataFrames + totals,
    or None if infeasible.

    `force_codes` · player `code`s that MUST be in the 15 (e.g. Haaland).
    `exclude_codes` · player `code`s that must NOT be picked. Both no-op if the
    frame has no `code` column.

    **`gw_pts_cols` changes what is being optimised.** Without it there is ONE
    lineup for the whole window, so the objective is really "the fifteen whose
    window totals sum highest". That cannot see complementary fixtures. Take two
    pairs over three gameweeks:

        A:  8, 2, 8   and   1, 7, 1     window totals 18 + 9  = 27
        B:  5, 7, 5   and   5, 5, 7     window totals 17 + 17 = 34

    Summing totals picks B. But you only field one of each pair, and starting
    the better one each week gives A 8+7+8 = 23 against B's 5+7+7 = 19. Pair A
    is the better buy and a fixed-lineup model will never choose it.

    Pass one column per gameweek and the eleven is chosen PER GAMEWEEK, which is
    what actually happens: the same fifteen, subbed weekly. `boost_col` names
    the gameweek where all fifteen score, so a Bench Boost is priced exactly
    rather than through the `bench_weight` fudge.

    The cost is a start variable per player per gameweek. The captain variables
    are left continuous on purpose · the objective is maximising and captaincy
    is capped at one per week, so the LP relaxation lands on the best starter
    anyway, and it halves the binary count.
    """
    if gw_pts_cols:
        missing = [c for c in gw_pts_cols if c not in players.columns]
        if missing:
            raise ValueError("gw_pts_cols not on the frame: %s" % missing)
        if boost_col is not None and boost_col not in gw_pts_cols:
            raise ValueError("boost_col %r must be one of gw_pts_cols" % boost_col)
        return _optimize_multi_week(
            players, budget=budget, gw_pts_cols=gw_pts_cols, boost_col=boost_col,
            captain=captain, time_limit=time_limit, bench_budget=bench_budget,
            min_club_cover=min_club_cover, max_from_club=max_from_club,
            force_codes=force_codes, exclude_codes=exclude_codes,
            max_attackers_per_club=max_attackers_per_club, defcon_codes=defcon_codes,
            max_defenders_per_club=max_defenders_per_club)
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

    # "I want cover from this club" · at least N of a side of the pitch from one
    # team. Locking a NAMED player says who; this says only that you want the
    # exposure and lets the optimiser pick the cheapest way to get it, which is
    # usually a better trade than guessing the right name yourself.
    #
    # Defensive cover is GKP+DEF because a keeper and a centre-back both pay out
    # on the same clean sheet · they are one bet, not two. Attacking cover is
    # MID+FWD for the same reason on goals.
    if min_club_cover and "team_id" in df.columns:
        for team_id, kind, n in min_club_cover:
            wanted = COVER_POSITIONS.get(str(kind))
            if not wanted or int(n) <= 0:
                continue
            c_idx = [i for i in idx
                     if int(df.loc[i, "team_id"] or 0) == int(team_id)
                     and df.loc[i, "position"] in wanted]
            if c_idx:
                prob += pulp.lpSum(squad[i] for i in c_idx) >= int(n)

    # "No more than N from this club" · tighter than FPL's own limit of three.
    # In the model rather than enforced by re-solving with a player banned:
    # banning explores ONE branch and can miss the optimum, while this is exact
    # and still returns a proven optimum.
    if max_from_club and "team_id" in df.columns:
        for team_id, n in max_from_club:
            t_idx = [i for i in idx if int(df.loc[i, "team_id"] or 0) == int(team_id)]
            if t_idx:
                prob += pulp.lpSum(squad[i] for i in t_idx) <= int(n)

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


def _squad_rules(prob, df, idx, squad, budget, bench_budget_vars,
                 force_codes, max_attackers_per_club, defcon_codes,
                 max_defenders_per_club, min_club_cover=None,
                 max_from_club=None):
    """The constraints on the FIFTEEN · identical whichever objective is used.

    Pulled out so the single-week and per-gameweek models cannot drift apart.
    A squad rule that held in one and not the other would show up as the two
    solvers disagreeing about a squad, which is exactly the class of bug the
    single `solve_opening` path was introduced to kill.
    """
    limits = PERFECT_SEASON["squad_limits"]
    prob += pulp.lpSum(squad[i] for i in idx) == 15
    prob += pulp.lpSum(df.loc[i, "price"] * squad[i] for i in idx) <= budget

    for pos, n in limits.items():
        prob += pulp.lpSum(squad[i] for i in idx
                           if df.loc[i, "position"] == pos) == n

    if "team_id" in df.columns:
        for team in df["team_id"].dropna().unique():
            t_idx = [i for i in idx if df.loc[i, "team_id"] == team]
            prob += pulp.lpSum(squad[i] for i in t_idx) <= PERFECT_SEASON["max_per_club"]

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

    if max_defenders_per_club is not None and "team_id" in df.columns:
        for team in df["team_id"].dropna().unique():
            d_idx = [i for i in idx
                     if df.loc[i, "team_id"] == team and df.loc[i, "position"] == "DEF"]
            if d_idx:
                prob += pulp.lpSum(squad[i] for i in d_idx) <= max_defenders_per_club

    if min_club_cover and "team_id" in df.columns:
        for team_id, kind, n in min_club_cover:
            wanted = COVER_POSITIONS.get(str(kind))
            if not wanted or int(n) <= 0:
                continue
            c_idx = [i for i in idx
                     if int(df.loc[i, "team_id"] or 0) == int(team_id)
                     and df.loc[i, "position"] in wanted]
            if c_idx:
                prob += pulp.lpSum(squad[i] for i in c_idx) >= int(n)

    if force_codes and "code" in df.columns:
        for c in force_codes:
            f_idx = [i for i in idx if df.loc[i, "code"] == c]
            if f_idx:
                prob += pulp.lpSum(squad[i] for i in f_idx) == 1

    # Same cap the single-week path applies · kept here so the two models cannot
    # disagree about a squad, which is the class of bug this shared function
    # exists to prevent.
    if max_from_club and "team_id" in df.columns:
        for team_id, n in max_from_club:
            t_idx = [k for k in idx if int(df.loc[k, "team_id"] or 0) == int(team_id)]
            if t_idx:
                prob += pulp.lpSum(squad[k] for k in t_idx) <= int(n)

def _optimize_multi_week(
    players: pd.DataFrame,
    budget: float,
    gw_pts_cols: List[str],
    boost_col: Optional[str],
    captain: bool,
    time_limit: int,
    bench_budget: Optional[float],
    force_codes: Optional[List],
    exclude_codes: Optional[List],
    max_attackers_per_club: Optional[int],
    defcon_codes: Optional[List],
    max_defenders_per_club: Optional[int],
    min_club_cover: Optional[List] = None,
    max_from_club: Optional[List] = None,
) -> Optional[Dict]:
    """One fifteen, a fresh eleven every gameweek. See `optimize_squad`."""
    need = list(gw_pts_cols) + ["price", "position"]
    df = players.dropna(subset=need).reset_index(drop=True)
    if exclude_codes and "code" in df.columns:
        df = df[~df["code"].isin(exclude_codes)].reset_index(drop=True)
    idx = list(df.index)
    if not idx:
        return None

    lineup_min = PERFECT_SEASON["lineup_min"]
    weeks = list(range(len(gw_pts_cols)))
    P = {g: df[gw_pts_cols[g]].astype(float) for g in weeks}
    boost_g = gw_pts_cols.index(boost_col) if boost_col is not None else None

    prob = pulp.LpProblem("squad_window", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("squad", idx, cat="Binary")
    start = pulp.LpVariable.dicts("start", (idx, weeks), cat="Binary")
    # Continuous on purpose · see the note in `optimize_squad`.
    cap = pulp.LpVariable.dicts("cap", (idx, weeks), lowBound=0, upBound=1)

    # In the Boost week the four non-starters score too, so the whole fifteen
    # counts. Written as start + (squad - start) rather than plain `squad` so
    # the captain term stays attached to the eleven.
    prob += pulp.lpSum(
        P[g][i] * (start[i][g] + (cap[i][g] if captain else 0)
                   + ((squad[i] - start[i][g]) if g == boost_g else 0))
        for i in idx for g in weeks)

    _squad_rules(prob, df, idx, squad, budget, None, force_codes,
                 max_attackers_per_club, defcon_codes, max_defenders_per_club,
                 min_club_cover=min_club_cover, max_from_club=max_from_club)

    for g in weeks:
        prob += pulp.lpSum(start[i][g] for i in idx) == 11
        prob += pulp.lpSum(cap[i][g] for i in idx) == (1 if captain else 0)
        for pos, lo in lineup_min.items():
            pos_idx = [i for i in idx if df.loc[i, "position"] == pos]
            if pos == "GKP":
                prob += pulp.lpSum(start[i][g] for i in pos_idx) == 1
            else:
                prob += pulp.lpSum(start[i][g] for i in pos_idx) >= lo
        for i in idx:
            prob += start[i][g] <= squad[i]
            prob += cap[i][g] <= start[i][g]

    if bench_budget is not None:
        # Bench money is dead money, but with a rotating eleven "the bench" is
        # not a fixed four. The rule is applied to the FIRST gameweek's bench,
        # which is the one a manager actually looks at on deadline day.
        prob += pulp.lpSum(df.loc[i, "price"] * (squad[i] - start[i][0])
                           for i in idx) <= bench_budget

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))
    label = pulp.LpStatus[status]
    if label not in ("Optimal", "Not Solved"):
        logger.warning("window squad MILP status: %s", label)
        return None
    proven = label == "Optimal"
    if not proven:
        logger.warning("window squad MILP hit the %ss limit · best found is not "
                       "proven optimal", time_limit)

    picked = [i for i in idx if squad[i].value() and squad[i].value() > 0.5]
    if len(picked) != 15:
        return None

    xi_by_week, cap_by_week, total = {}, {}, 0.0
    for g in weeks:
        started = [i for i in picked if start[i][g].value() and start[i][g].value() > 0.5]
        cap_i = max(started, key=lambda i: P[g][i]) if (started and captain) else None
        xi_by_week[g] = started
        cap_by_week[g] = cap_i
        total += float(P[g][started].sum())
        if cap_i is not None:
            total += float(P[g][cap_i])
        if g == boost_g:
            total += float(P[g][[i for i in picked if i not in started]].sum())

    first, cap_i = xi_by_week[0], cap_by_week[0]
    squad_df = df.loc[picked].copy()
    squad_df["in_xi"] = squad_df.index.isin(first)
    squad_df["is_captain"] = squad_df.index == cap_i
    # `pts` keeps the shape every caller expects: what this player contributes
    # over the whole window if he starts every week.
    squad_df["pts"] = sum(P[g] for g in weeks).loc[picked]

    return {
        "squad": squad_df.sort_values(["in_xi", "pts"], ascending=[False, False]),
        "xi_points": round(float(P[0][first].sum())
                           + (float(P[0][cap_i]) if cap_i is not None else 0.0), 2),
        "window_points": round(total, 2),
        "squad_cost": round(float(squad_df["price"].sum()), 1),
        "captain_idx": cap_i,
        "xi_by_week": {g: [df.loc[i, "code"] for i in xi_by_week[g]]
                       for g in weeks} if "code" in df.columns else {},
        "solver_status": label,
        "proven_optimal": proven,
        "per_week": True,
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
