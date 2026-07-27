"""Season Opener · fixture reads, Bench Boost break-even, and route scoring."""
import pandas as pd
import pytest

from analytics.season_opener import (
    bb_dilution, compare_routes, fixture_swing, opening_ease, opening_factors,
    squad_frame)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _fixtures(rows):
    """rows: (gw, home_id, away_id, home_fdr, away_fdr)."""
    return pd.DataFrame([
        {"gameweek": gw, "home_team_id": h, "away_team_id": a,
         "home_fdr": hf, "away_fdr": af}
        for gw, h, a, hf, af in rows])


def test_opening_ease_means_are_exact():
    fx = _fixtures([(1, 1, 2, 2.0, 4.0), (2, 2, 1, 2.0, 4.0)])
    out = opening_ease(fx, 1, 2).set_index("team_id")
    # team 1: 2.0 home then 4.0 away · mean 3.0. team 2: 4.0 then 2.0 · mean 3.0.
    assert out.loc[1, "fdr"] == pytest.approx(3.0)
    assert out.loc[2, "fdr"] == pytest.approx(3.0)
    assert out.loc[1, "home"] == 1
    assert out.loc[1, "n"] == 2


def test_opening_ease_window_excludes_later_gameweeks():
    fx = _fixtures([(1, 1, 2, 2.0, 4.0), (9, 1, 2, 5.0, 5.0)])
    out = opening_ease(fx, 1, 6).set_index("team_id")
    assert out.loc[1, "fdr"] == pytest.approx(2.0)   # GW9 must not leak in


def test_opening_ease_empty_window_returns_empty_frame():
    fx = _fixtures([(30, 1, 2, 2.0, 4.0)])
    assert opening_ease(fx, 1, 6).empty


def test_easy_fixtures_score_above_one_hard_below():
    fx = _fixtures([(1, 1, 2, 2.0, 4.0)])
    fac = opening_factors(fx, {"gw_hi": 6, "fdr_slope": 0.28, "factor_floor": 0.4})
    assert fac[1] > 1.0     # FDR 2 is easier than average
    assert fac[2] < 1.0     # FDR 4 is harder


def test_fixture_swing_sign_says_which_way_the_run_turns():
    # team 1 easy early then hard late · team 2 the reverse.
    fx = _fixtures([(1, 1, 2, 2.0, 4.0), (2, 1, 2, 2.0, 4.0),
                    (7, 1, 2, 5.0, 2.0), (8, 1, 2, 5.0, 2.0)])
    sw = fixture_swing(fx, early=(1, 2), late=(7, 8)).set_index("team_id")
    assert sw.loc[1, "swing"] == pytest.approx(3.0)    # 2.0 -> 5.0, gets harder
    assert sw.loc[2, "swing"] == pytest.approx(-2.0)   # 4.0 -> 2.0, gets easier
    # sorted hardest-turning first
    assert fixture_swing(fx, early=(1, 2), late=(7, 8)).iloc[0]["team_id"] == 1


# ── squad helpers ─────────────────────────────────────────────────────────────

def _squad(xi_pts, bench_pts, team_ids=None):
    """Fake an `optimize_squad` result: {"squad": df with in_xi}."""
    n_xi, n_b = len(xi_pts), len(bench_pts)
    team_ids = team_ids or ([1] * (n_xi + n_b))
    return {"squad": pd.DataFrame({
        "pts": list(xi_pts) + list(bench_pts),
        "team_id": team_ids,
        "in_xi": [True] * n_xi + [False] * n_b})}


def test_squad_frame_returns_none_for_infeasible_solve():
    assert squad_frame(None) is None
    assert squad_frame({"squad": pd.DataFrame()}) is None


# ── Bench Boost break-even ────────────────────────────────────────────────────

def test_bb_dilution_reports_break_even_in_gameweeks():
    boost = _squad([100.0] * 11, [80.0] * 4)      # XI 1100, bench 320
    normal = _squad([110.0] * 11, [20.0] * 4)     # XI 1210, bench 80

    def solve_fn(board, all_must_play, bench_price_cap=None, **kw):
        return boost if all_must_play else normal

    out = bb_dilution(pd.DataFrame(), solve_fn)
    # dilution (1210-1100)/38 = 2.894 per GW · gain (320-80)/38 = 6.3 once
    arm = out["arms"][0]
    assert arm["dilution_per_gw"] == pytest.approx(2.89, abs=0.01)
    assert arm["bb_gain"] == pytest.approx(6.3, abs=0.05)
    assert arm["break_even_gws"] == pytest.approx(2.2, abs=0.05)


def test_bb_dilution_returns_a_bracket_not_a_single_number():
    boost = _squad([100.0] * 11, [80.0] * 4)

    def solve_fn(board, all_must_play, bench_price_cap=None, **kw):
        if all_must_play:
            return boost
        # a capped bench is weaker, so the chip gains more against it
        return _squad([110.0] * 11, [5.0] * 4) if bench_price_cap else \
            _squad([110.0] * 11, [20.0] * 4)

    out = bb_dilution(pd.DataFrame(), solve_fn)
    assert len(out["arms"]) == 2
    assert out["break_even_lo"] < out["break_even_hi"]


def test_bb_dilution_returns_none_when_boost_squad_infeasible():
    assert bb_dilution(pd.DataFrame(), lambda *a, **k: None) is None


def test_bb_dilution_handles_a_boost_squad_that_is_not_weaker():
    """No trade-off to price · must not divide by zero or invent a break-even."""
    same = _squad([100.0] * 11, [80.0] * 4)

    def solve_fn(board, all_must_play, bench_price_cap=None, **kw):
        return same

    out = bb_dilution(pd.DataFrame(), solve_fn)
    assert out["arms"][0]["break_even_gws"] is None
    assert out["break_even_lo"] is None


# ── route comparator ──────────────────────────────────────────────────────────

def _flat_fixtures(gw_hi=19, n_teams=2):
    rows = []
    for gw in range(1, gw_hi + 1):
        rows.append((gw, 1, 2, 3.0, 3.0))
    return _fixtures(rows)


def test_compare_routes_returns_one_row_per_route():
    fx = _flat_fixtures()
    squad = _squad([100.0] * 11, [50.0] * 4)
    routes = [{"label": "A", "bb_gw": 1, "wc_gw": 3},
              {"label": "B", "bb_gw": None, "wc_gw": 7}]

    def solve_fn(board, all_must_play, bench_price_cap=None, opening_window=None):
        return squad

    out = compare_routes(pd.DataFrame(), fx, solve_fn, routes=routes)
    assert len(out) == 2
    assert set(out["label"]) == {"A", "B"}


def test_compare_routes_credits_the_bench_boost_week():
    """With identical squads, the only difference is the boosted bench week."""
    fx = _flat_fixtures()
    squad = _squad([100.0] * 11, [50.0] * 4)

    def solve_fn(board, all_must_play, bench_price_cap=None, opening_window=None):
        return squad

    out = compare_routes(pd.DataFrame(), fx, solve_fn,
                         routes=[{"label": "boost", "bb_gw": 1, "wc_gw": 3},
                                 {"label": "none", "bb_gw": None, "wc_gw": 3}])
    boost = out[out["label"] == "boost"].iloc[0]["points"]
    none = out[out["label"] == "none"].iloc[0]["points"]
    # one week of 4 bench players at 50/38 each, on FDR 3 (ease 1.0)
    assert boost - none == pytest.approx(4 * 50.0 / 38.0, abs=0.05)


def test_compare_routes_ranks_a_rigged_route_first():
    """A route whose chip lands on stacked-easy fixtures must win."""
    rows = [(gw, 1, 2, 3.0, 3.0) for gw in range(1, 20)]
    rows[0] = (1, 1, 2, 1.0, 1.0)          # GW1 is a gift
    fx = _fixtures(rows)
    squad = _squad([100.0] * 11, [50.0] * 4)

    def solve_fn(board, all_must_play, bench_price_cap=None, opening_window=None):
        return squad

    out = compare_routes(pd.DataFrame(), fx, solve_fn,
                         routes=[{"label": "BB on the gift", "bb_gw": 1, "wc_gw": 5},
                                 {"label": "BB later", "bb_gw": 4, "wc_gw": 5}])
    assert out.iloc[0]["label"] == "BB on the gift"


def test_compare_routes_empty_when_baseline_infeasible():
    out = compare_routes(pd.DataFrame(), _flat_fixtures(), lambda *a, **k: None)
    assert out.empty
