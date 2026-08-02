"""Optimising the PLAN, not a proxy for it.

All figures here are INVENTED.

The point: a benched player is worth his boost-week score and nothing else, so
the objective should say that rather than calling him a fixed fraction of a
starter. Chasing a bench points TARGET is a constraint, and optimising against
a constraint can build a worse fifteen.
"""
import pandas as pd

from analytics.opening_plan import best_boost_week, plan_vectors


class FakeProj:
    """points(code, gw) = code * gw, so weeks differ and players differ."""

    def __init__(self, scale=1.0):
        self.scale = scale

    def points(self, code, gw):
        return float(code) * float(gw) * self.scale

    def matrix(self, codes, gws):
        return pd.DataFrame({g: [self.points(c, g) for c in codes] for g in gws},
                            index=pd.Index([int(c) for c in codes], name="code"))


def _board(n=6):
    return pd.DataFrame({"code": range(1, n + 1),
                         "web_name": ["P%d" % i for i in range(1, n + 1)],
                         "position": ["MID"] * n, "team_id": range(1, n + 1)})


# ── the two vectors ──────────────────────────────────────────────────────────

def test_start_value_is_the_whole_window():
    d = plan_vectors(_board(), FakeProj(), [1, 2, 3], boost_gw=2)
    # player 1 scores 1+2+3
    assert d.loc[d.code == 1, "plan_start"].iloc[0] == 6.0


def test_bench_value_is_the_boost_week_only():
    d = plan_vectors(_board(), FakeProj(), [1, 2, 3], boost_gw=2)
    # player 1 scores 2 in GW2
    assert d.loc[d.code == 1, "plan_bench"].iloc[0] == 2.0


def test_no_boost_means_a_benched_player_is_worth_nothing():
    """Not 10% of a starter · nothing. That is what actually happens."""
    d = plan_vectors(_board(), FakeProj(), [1, 2, 3], boost_gw=None)
    assert (d["plan_bench"] == 0.0).all()


def test_a_boost_outside_the_window_is_ignored():
    d = plan_vectors(_board(), FakeProj(), [1, 2, 3], boost_gw=9)
    assert (d["plan_bench"] == 0.0).all()


def test_bench_value_never_exceeds_start_value():
    d = plan_vectors(_board(), FakeProj(), [1, 2, 3], boost_gw=3)
    assert (d["plan_bench"] <= d["plan_start"] + 1e-9).all()


# ── choosing the week ────────────────────────────────────────────────────────

def _solver(board):
    """Take the whole (small) board as the squad, so the plan maths is exposed."""
    def solve(frame, bench_col=None):
        return {"squad": frame.copy(), "bench_col": bench_col}
    return solve


def test_it_picks_the_week_the_bench_scores_most():
    """With points rising in gw, the latest week should win."""
    b = _board(15)
    out = best_boost_week(b, FakeProj(), [1, 2, 3], _solver(b), candidates=[1, 2, 3])
    assert out["boost_gw"] == 3


def test_a_boost_that_gains_nothing_keeps_the_chip():
    """A chip you should not play is a real finding, not a failure. With every
    player scoring zero there is nothing to boost, so it stays in the pocket."""
    b = _board(15)
    out = best_boost_week(b, FakeProj(scale=0.0), [1, 2, 3], _solver(b),
                          candidates=[1, 2])
    assert out["boost_gw"] is None


def test_a_boost_must_beat_carrying_the_chip_not_merely_match_it():
    from analytics.opening_plan import TIE_MARGIN
    assert TIE_MARGIN > 0


def test_every_candidate_is_reported():
    b = _board(15)
    out = best_boost_week(b, FakeProj(), [1, 2, 3], _solver(b), candidates=[1, 2])
    assert {t["boost_gw"] for t in out["tried"]} == {1, 2, None}


def test_per_week_marks_only_the_boosted_gameweek():
    b = _board(15)
    out = best_boost_week(b, FakeProj(), [1, 2, 3], _solver(b), candidates=[2])
    boosted = [w for w in out["per_week"] if w["boosted"]]
    assert len(boosted) == 1
    assert boosted[0]["gw"] == out["boost_gw"]


def test_the_boosted_week_counts_the_bench_and_others_do_not():
    b = _board(15)
    out = best_boost_week(b, FakeProj(), [1, 2, 3], _solver(b), candidates=[2])
    for w in out["per_week"]:
        expected = w["xi"] + w["captain"] + (w["bench"] if w["boosted"] else 0.0)
        assert abs(w["total"] - expected) < 0.05


def test_the_solver_is_told_which_column_carries_bench_value():
    """No Boost means no bench column · the `bench_weight` fudge is the right
    tool there, because a bench you never boost is insurance, not points."""
    b = _board(15)
    seen = []

    def solve(frame, bench_col=None):
        seen.append(bench_col)
        return {"squad": frame.copy()}

    best_boost_week(b, FakeProj(), [1, 2, 3], solve, candidates=[2])
    assert seen == [None, "plan_bench"]


# ── solve_plan · declaring a Boost can never cost you points ─────────────────

def _pair_solver(bench_squad, plain_squad):
    """Return a different fifteen depending on whether a bench column was asked
    for, so the two candidates can be scored against each other."""
    def solve(frame, bench_col=None):
        codes = bench_squad if bench_col else plain_squad
        return {"squad": frame[frame["code"].isin(codes)].copy()}
    return solve


def test_solve_plan_keeps_the_squad_that_actually_scores_more():
    from analytics.opening_plan import solve_plan
    b = _board(30)
    # The "bench-aware" candidate is deliberately the WEAKER fifteen. The plan
    # score has to notice and keep the plain one.
    weak, strong = list(range(1, 16)), list(range(16, 31))
    out = solve_plan(b, FakeProj(), [1, 2, 3], 2, _pair_solver(weak, strong))
    assert set(out["squad"]["code"]) == set(strong)
    assert out["bench_aware"] is False


def test_solve_plan_prefers_the_bench_aware_squad_on_a_tie():
    from analytics.opening_plan import solve_plan
    b = _board(30)
    same = list(range(1, 16))
    out = solve_plan(b, FakeProj(), [1, 2, 3], 2, _pair_solver(same, same))
    assert out["bench_aware"] is True


def test_solve_plan_reports_the_honest_plan_total():
    from analytics.opening_plan import solve_plan, plan_total
    b = _board(30)
    squad = list(range(1, 16))
    out = solve_plan(b, FakeProj(), [1, 2, 3], 2, _pair_solver(squad, squad))
    assert out["plan_total"] == round(
        plan_total(out["squad"], FakeProj(), [1, 2, 3], 2), 1)


def test_solve_plan_without_a_boost_solves_once_and_says_so():
    from analytics.opening_plan import solve_plan
    b = _board(30)
    calls = []

    def solve(frame, bench_col=None):
        calls.append(bench_col)
        return {"squad": frame.head(15).copy()}

    out = solve_plan(b, FakeProj(), [1, 2, 3], None, solve)
    assert calls == [None]
    assert out["bench_aware"] is False


def test_solve_plan_ignores_a_boost_outside_the_window():
    from analytics.opening_plan import solve_plan
    b = _board(30)
    calls = []

    def solve(frame, bench_col=None):
        calls.append(bench_col)
        return {"squad": frame.head(15).copy()}

    solve_plan(b, FakeProj(), [1, 2, 3], 9, solve)
    assert calls == [None]


def test_solve_plan_survives_an_infeasible_arm():
    from analytics.opening_plan import solve_plan
    b = _board(30)

    def solve(frame, bench_col=None):
        return None if bench_col else {"squad": frame.head(15).copy()}

    out = solve_plan(b, FakeProj(), [1, 2, 3], 2, solve)
    assert out is not None and out["bench_aware"] is False


def test_solve_plan_returns_none_when_nothing_is_feasible():
    from analytics.opening_plan import solve_plan
    b = _board(30)
    out = solve_plan(b, FakeProj(), [1, 2, 3], 2, lambda f, c=None: None)
    assert out is None
