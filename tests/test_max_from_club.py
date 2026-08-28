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


# ── attack-cap exemption ──────────────────────────────────────────────────────

def _two_club_pool():
    """Nine clubs of cheap fodder plus two strong attackers at club 1.

    Nine, not six: a squad needs eight attackers (5 MID + 3 FWD), so with a
    one-attacker-per-club cap fewer than eight clubs is infeasible before the
    rule under test even gets a say.
    """
    import pandas as pd
    rows = []
    code = 100
    for club in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        for pos, n, pts in (("GKP", 2, 3.0), ("DEF", 3, 3.0),
                            ("MID", 3, 3.0), ("FWD", 2, 3.0)):
            for k in range(n):
                code += 1
                rows.append({"code": code, "web_name": "p%d" % code,
                             "position": pos, "team_id": club, "price": 4.0,
                             "pts": pts})
    # Two standout attackers at club 1 · the cap is the only reason to split them
    for i, pos in enumerate(("MID", "FWD")):
        code += 1
        rows.append({"code": code, "web_name": "star%d" % i, "position": pos,
                     "team_id": 1, "price": 4.5, "pts": 30.0})
    return pd.DataFrame(rows)


def test_attack_cap_blocks_two_attackers_from_one_club():
    from analytics.squad_milp import optimize_squad
    res = optimize_squad(_two_club_pool(), budget=100.0, pts_col="pts",
                         max_attackers_per_club=1)
    assert res is not None
    picked = res["squad"]
    club1_att = picked[(picked["team_id"] == 1)
                       & (picked["position"].isin(["MID", "FWD"]))]
    assert len(club1_att) <= 1


def test_exempting_a_club_lets_both_attackers_in():
    """The point of the exemption · same pool, same cap, one club released."""
    from analytics.squad_milp import optimize_squad
    res = optimize_squad(_two_club_pool(), budget=100.0, pts_col="pts",
                         max_attackers_per_club=1, attack_cap_exempt=[1])
    assert res is not None
    picked = res["squad"]
    club1_att = picked[(picked["team_id"] == 1)
                       & (picked["position"].isin(["MID", "FWD"]))]
    assert len(club1_att) >= 2, "both stars should be affordable and legal now"


def test_exemption_does_not_leak_to_other_clubs():
    import pandas as pd
    from analytics.squad_milp import optimize_squad
    pool = _two_club_pool()
    # Give club 2 two standouts as well, but exempt only club 1.
    extra = pd.DataFrame([
        {"code": 9001, "web_name": "s2a", "position": "MID", "team_id": 2,
         "price": 4.5, "pts": 29.0},
        {"code": 9002, "web_name": "s2b", "position": "FWD", "team_id": 2,
         "price": 4.5, "pts": 29.0}])
    res = optimize_squad(pd.concat([pool, extra], ignore_index=True),
                         budget=100.0, pts_col="pts",
                         max_attackers_per_club=1, attack_cap_exempt=[1])
    assert res is not None
    picked = res["squad"]
    club2_att = picked[(picked["team_id"] == 2)
                       & (picked["position"].isin(["MID", "FWD"]))]
    assert len(club2_att) <= 1


def test_max_price_band_caps_the_cheapest_defenders():
    """Only ever one £4.0m defender · the solver picks which, not which names."""
    import pandas as pd
    from analytics.squad_milp import optimize_squad

    rows = []
    code = 500
    for club in range(1, 11):
        for pos, n, price, pts in (("GKP", 2, 4.5, 3.0), ("DEF", 2, 4.0, 6.0),
                                   ("DEF", 2, 5.5, 5.0), ("MID", 3, 5.0, 5.0),
                                   ("FWD", 2, 5.0, 5.0)):
            for _ in range(n):
                code += 1
                rows.append({"code": code, "web_name": "p%d" % code,
                             "position": pos, "team_id": club,
                             "price": price, "pts": pts})
    pool = pd.DataFrame(rows)

    free = optimize_squad(pool, budget=100.0, pts_col="pts")
    cheap_free = free["squad"][(free["squad"]["position"] == "DEF")
                               & (free["squad"]["price"] == 4.0)]
    assert len(cheap_free) > 1, "without the rule the cheap band is attractive"

    capped = optimize_squad(pool, budget=100.0, pts_col="pts",
                            max_price_band=[("DEF", 4.0, 1)])
    assert capped is not None
    cheap = capped["squad"][(capped["squad"]["position"] == "DEF")
                            & (capped["squad"]["price"] == 4.0)]
    assert len(cheap) <= 1
    assert len(capped["squad"]) == 15
