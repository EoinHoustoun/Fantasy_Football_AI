"""
Build the fifteen that scores most across an actual plan.

The usual squad optimiser maximises one scoring vector and treats the bench as
a fraction of a starter (`bench_weight`). That fraction is a fudge · it is true
of nothing in particular, and it quietly encourages buying bench quality that
never earns its price.

When the plan is known the truth is exact. Over an opening window with a Bench
Boost in one gameweek:

    boost week   all fifteen score
    other weeks  only the eleven score, and the captain doubles

So a player's value depends on whether he starts, and the two cases are
different numbers rather than one number scaled. That is expressible in the
existing MILP, which already carries separate `squad` and `lineup` variables:

    counted when starting   his points across EVERY week of the window
    counted when benched    his points in the BOOST week only

Both cases are then exactly right, and the approximation only bites for a
player who starts some weeks and not others · which is what a bench is for.

The other thing this fixes is a target masquerading as an objective. "Get the
bench over 15" is a constraint. Optimising for it can build a WORSE fifteen,
because points spent on a bench that plays once are points not spent on the
eleven that play every week. This module never targets a bench score; it just
counts the boost week honestly and lets the total decide.
"""

import logging
from typing import Dict, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# A Boost must beat NOT playing one by more than this to be worth burning the
# chip. Ties, and anything inside the noise, keep the chip.
TIE_MARGIN = 0.5


def plan_vectors(board: pd.DataFrame, proj, gws: Sequence[int],
                 boost_gw: Optional[int]) -> pd.DataFrame:
    """Add `plan_start` and `plan_bench` columns for this window and chip plan.

    `plan_start` · what he returns if he is in the eleven all window.
    `plan_bench` · what he returns if he never starts, which is his boost-week
    score, or nothing at all when no Boost is planned.
    """
    d = board.copy()
    codes = [int(c) for c in d["code"]]
    mat = proj.matrix(codes, list(gws))

    d["plan_start"] = d["code"].astype(int).map(mat.sum(axis=1)).fillna(0.0).round(2)
    if boost_gw is not None and int(boost_gw) in list(gws):
        d["plan_bench"] = (d["code"].astype(int)
                           .map(mat[int(boost_gw)]).fillna(0.0).round(2))
    else:
        # No Boost · a benched player scores nothing, and the optimiser should
        # feel that rather than being told a bench is 10% of a starter.
        d["plan_bench"] = 0.0
    return d


def best_boost_week(board: pd.DataFrame, proj, gws: Sequence[int],
                    solve, candidates: Optional[Sequence[int]] = None) -> Dict:
    """Try each candidate Boost week and keep the plan that scores most.

    `solve(frame) -> result_dict_or_None` does the actual optimisation, so this
    stays independent of which constraints the caller wants applied.

    Returns {boost_gw, total, squad, per_week, tried}. `boost_gw` may be None
    when carrying no Boost beats every week of playing one, which is a real
    answer and worth surfacing rather than forcing a chip in.
    """
    tried = []
    best = None
    # `None` first, so a Boost has to BEAT carrying the chip rather than merely
    # matching it. A chip that gains nothing should stay in your pocket.
    for bb in [None] + list(candidates or list(gws)):
        frame = plan_vectors(board, proj, gws, bb)
        res = solve(frame)
        if not res:
            tried.append({"boost_gw": bb, "total": None})
            continue
        total = _plan_total(res["squad"], proj, gws, bb)
        tried.append({"boost_gw": bb, "total": round(total, 1)})
        if best is None or total > best["total"] + TIE_MARGIN:
            best = {"boost_gw": bb, "total": total, "squad": res["squad"],
                    "result": res}
    if best is None:
        return {"boost_gw": None, "total": 0.0, "squad": None, "tried": tried}
    best["per_week"] = _per_week(best["squad"], proj, gws, best["boost_gw"])
    best["tried"] = tried
    best["total"] = round(best["total"], 1)
    return best


def _per_week(squad: pd.DataFrame, proj, gws: Sequence[int],
              boost_gw: Optional[int]) -> List[Dict]:
    """What the plan scores each week, and whether the Boost is on."""
    from analytics.gw_projection import best_xi
    codes = [int(c) for c in squad["code"]]
    out = []
    for g in gws:
        xi = best_xi(squad, proj, g)
        cap = max(xi, key=lambda c: proj.points(c, g)) if xi else None
        starters = sum(proj.points(c, g) for c in codes if c in xi)
        bench = sum(proj.points(c, g) for c in codes if c not in xi)
        boosted = boost_gw is not None and int(g) == int(boost_gw)
        out.append({
            "gw": int(g), "boosted": boosted,
            "xi": round(starters, 1), "bench": round(bench, 1),
            "captain": round(proj.points(cap, g), 1) if cap is not None else 0.0,
            "total": round(starters + (proj.points(cap, g) if cap is not None else 0.0)
                           + (bench if boosted else 0.0), 1),
        })
    return out


def _plan_total(squad: pd.DataFrame, proj, gws: Sequence[int],
                boost_gw: Optional[int]) -> float:
    return float(sum(w["total"] for w in _per_week(squad, proj, gws, boost_gw)))
