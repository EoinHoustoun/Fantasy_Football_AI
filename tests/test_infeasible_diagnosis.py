"""A failed solve must say WHY · "infeasible" is not an answer.

All figures here are INVENTED.

The case that prompted this: two forced Man Utd midfielders against a
one-attacker-per-club rule. The page reported infeasible and guessed at money,
sending the user to check a budget that was never the problem.
"""
import pandas as pd

from analytics.squad_milp import diagnose_infeasible, optimize_squad


def _pool(n_per_pos=8, price=5.0):
    rows = []
    code = 1
    for pos, n in (("GKP", n_per_pos), ("DEF", n_per_pos * 3),
                   ("MID", n_per_pos * 3), ("FWD", n_per_pos * 2)):
        for i in range(n):
            rows.append({"code": code, "web_name": "%s%d" % (pos, i),
                         "position": pos, "price": price,
                         "team_id": i % 12, "pts": 50.0 + i})
            code += 1
    return pd.DataFrame(rows)


def test_a_solvable_problem_reports_nothing():
    assert diagnose_infeasible(_pool(), budget=100.0) == ""


def test_the_attacker_rule_is_named_when_it_is_the_cause():
    """Two forced attackers at one club against a one-per-club cap."""
    p = _pool()
    same_club = p[(p.position == "MID") & (p.team_id == 0)].head(2)
    codes = [int(c) for c in same_club["code"]]
    assert len(codes) == 2
    out = diagnose_infeasible(p, budget=100.0, force_codes=codes,
                              max_attackers_per_club=1)
    assert "attackers-per-club" in out


def test_relaxing_that_rule_really_does_solve_it():
    """The diagnosis must be true, not merely plausible."""
    p = _pool()
    codes = [int(c) for c in p[(p.position == "MID") & (p.team_id == 0)].head(2)["code"]]
    assert optimize_squad(p, 100.0, "pts", force_codes=codes,
                          max_attackers_per_club=1) is None
    assert optimize_squad(p, 100.0, "pts", force_codes=codes,
                          max_attackers_per_club=2) is not None


def test_a_real_budget_problem_is_named_as_one():
    p = _pool(price=9.0)
    out = diagnose_infeasible(p, budget=60.0)
    assert "budget" in out or "pool" in out


def test_an_empty_pool_is_named_as_a_pool_problem():
    p = _pool()
    out = diagnose_infeasible(p, budget=100.0,
                              exclude_codes=[int(c) for c in p["code"]])
    assert "pool" in out or "vetoes" in out
