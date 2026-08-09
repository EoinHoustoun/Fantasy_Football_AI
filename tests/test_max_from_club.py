"""Cap how many players come from one club, inside the MILP.

Enforcing "no more than two Sunderland" by solving, spotting the violation,
banning a player and re-solving is greedy: it explores one branch and can miss
the true optimum. A constraint in the model is exact and still proves
optimality, which is the standard this repo holds itself to.
"""
import pandas as pd

from analytics.squad_milp import optimize_squad


def _pool():
    """One club (10) stacked with the best players, so an unconstrained solve
    takes far more of them than any cap would allow."""
    rows = []

    def add(code, pos, price, pts, team):
        rows.append({"code": code, "position": pos, "price": price,
                     "pts": pts, "team_id": team})

    # The stacked club · cheap and excellent at every position.
    for i, pos in enumerate(["GKP", "GKP", "DEF", "DEF", "DEF", "DEF", "DEF",
                             "MID", "MID", "MID", "MID", "MID",
                             "FWD", "FWD", "FWD"]):
        add(100 + i, pos, 4.0, 9.0, 10)
    # Everyone else · same price, clearly worse, enough to fill a legal squad.
    tid = 20
    for i, pos in enumerate(["GKP", "GKP", "DEF", "DEF", "DEF", "DEF", "DEF",
                             "MID", "MID", "MID", "MID", "MID",
                             "FWD", "FWD", "FWD"] * 2):
        tid += 1
        add(200 + i, pos, 4.0, 2.0, tid)
    return pd.DataFrame(rows)


def _from_club(res, team=10):
    return int((res["squad"]["team_id"] == team).sum())


def test_without_a_cap_the_solver_takes_all_it_is_allowed():
    """The pool is stacked, so the solver should hit FPL's own 3-per-club
    ceiling. Anything less and the cap tests below would prove nothing."""
    res = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False)
    assert _from_club(res) == 3


def test_the_squad_limit_of_three_per_club_still_applies():
    res = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False)
    assert _from_club(res) <= 3, "FPL allows at most 3 from one club"


def test_a_tighter_cap_is_respected():
    res = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False,
                         max_from_club=[(10, 2)])
    assert _from_club(res) == 2


def test_a_cap_of_zero_excludes_the_club_entirely():
    res = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False,
                         max_from_club=[(10, 0)])
    assert _from_club(res) == 0


def test_the_capped_solve_is_still_proven_optimal():
    """The whole point · a heuristic cannot claim this."""
    res = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False,
                         max_from_club=[(10, 2)])
    assert res["proven_optimal"] is True


def test_capping_one_club_leaves_others_alone():
    res = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False,
                         max_from_club=[(10, 1)])
    assert _from_club(res) == 1
    assert len(res["squad"]) == 15


def test_a_cap_on_a_club_nobody_owns_changes_nothing():
    base = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False)
    capped = optimize_squad(_pool(), budget=100.0, bench_weight=1.0, captain=False,
                            max_from_club=[(999, 1)])
    assert base["xi_points"] == capped["xi_points"]


# ── the two solvers must agree ───────────────────────────────────────────────
# `_squad_rules` exists so the single-week and per-gameweek models cannot drift
# apart. A cap that held in one and not the other is exactly the bug it prevents.

def test_the_cap_holds_in_the_per_gameweek_model_too():
    pool = _pool()
    for c in ("gw1", "gw2", "gw3"):
        pool[c] = pool["pts"]
    res = optimize_squad(pool, budget=100.0, captain=False,
                         gw_pts_cols=["gw1", "gw2", "gw3"],
                         max_from_club=[(10, 2)])
    assert int((res["squad"]["team_id"] == 10).sum()) == 2
