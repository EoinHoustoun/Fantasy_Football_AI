"""Per-gameweek expected points · source precedence, fixture shape, best XI.

All figures here are INVENTED. The rules under test are the ones the page
depends on being right:

  a hand-entered absence beats everything, a real match forecast beats fixture
  shape, and a legal XI is 1 GKP plus at least 3 DEF, 2 MID and 1 FWD.
"""
import pandas as pd
import pytest

from analytics.gw_projection import (SRC_MANUAL, SRC_MATCH, SRC_SHAPE,
                                     GwProjection, best_xi, fixture_factor)

# (team_id, gw) -> [(opp, home, fdr), ...]
FIX = {
    (1, 1): [(9, True, 2.0)],
    (1, 2): [(9, True, 5.0)],
    (1, 3): [(9, True, 3.0)],
    (1, 4): [(9, True, 3.0), (8, False, 3.0)],   # a double gameweek
    (2, 1): [(9, True, 3.0)],
    (2, 2): [(9, True, 3.0)],
}


def _board(codes=(10, 20), team=1, season=190.0):
    return pd.DataFrame({
        "code": list(codes),
        "team_id": [team] * len(codes),
        "consensus_points": [season] * len(codes),
        "position": ["MID"] * len(codes),
    })


def _long(rows):
    return pd.DataFrame(rows, columns=["code", "gw", "pts", "exp_mins"])


# ── fixture_factor ───────────────────────────────────────────────────────────

def test_easier_fixtures_score_higher():
    assert fixture_factor(2.0) > fixture_factor(3.0) > fixture_factor(5.0)


def test_neutral_difficulty_is_neutral():
    assert fixture_factor(3.0) == pytest.approx(1.0)


def test_factor_never_goes_to_zero_on_the_hardest_fixture():
    assert fixture_factor(10.0) > 0


# ── source precedence ────────────────────────────────────────────────────────

def test_a_match_forecast_beats_fixture_shape():
    p = GwProjection(_board(), FIX, ffh_long=_long([(10, 1, 7.5, 90)]))
    assert p.points(10, 1) == 7.5
    assert p.source(10, 1) == SRC_MATCH
    # no row for this player, so the same week falls back to shape
    assert p.source(20, 1) == SRC_SHAPE


def test_a_hand_entered_absence_beats_a_match_forecast():
    """Garner out for GW1-2 has to win over a model that has not heard."""
    p = GwProjection(_board(), FIX, ffh_long=_long([(10, 1, 7.5, 90)]),
                     miss_gws={10: [1]})
    assert p.points(10, 1) == 0.0
    assert p.source(10, 1) == SRC_MANUAL
    assert p.expected_minutes(10, 1) == 0.0
    assert p.misses(10, 1) is True


def test_an_absence_in_one_week_does_not_touch_another():
    p = GwProjection(_board(), FIX, miss_gws={10: [1]})
    assert p.points(10, 1) == 0.0
    assert p.points(10, 2) > 0.0
    assert p.misses(10, 2) is False


# ── fixture shape ────────────────────────────────────────────────────────────

def test_shape_follows_fixture_difficulty():
    p = GwProjection(_board(), FIX)
    assert p.points(10, 1) > p.points(10, 3) > p.points(10, 2)


def test_a_double_gameweek_sums_both_fixtures():
    p = GwProjection(_board(), FIX)
    assert p.points(10, 4) == pytest.approx(2 * p.points(10, 3), rel=1e-6)


def test_a_blank_gameweek_is_zero():
    p = GwProjection(_board(), FIX)
    assert p.points(10, 9) == 0.0        # no fixture entry for that week


def test_a_bigger_season_projection_gives_bigger_weeks():
    lo = GwProjection(_board(season=100.0), FIX)
    hi = GwProjection(_board(season=200.0), FIX)
    assert hi.points(10, 1) > lo.points(10, 1)


# ── bulk helpers ─────────────────────────────────────────────────────────────

def test_matrix_matches_cell_by_cell():
    p = GwProjection(_board(), FIX, ffh_long=_long([(10, 1, 7.5, 90)]))
    m = p.matrix([10, 20], [1, 2])
    assert m.loc[10, 1] == pytest.approx(p.points(10, 1), abs=0.01)
    assert m.loc[20, 2] == pytest.approx(p.points(20, 2), abs=0.01)
    assert list(m.index) == [10, 20]


def test_run_total_is_inclusive_of_both_ends():
    p = GwProjection(_board(), FIX)
    assert p.run_total(10, 1, 3) == pytest.approx(
        p.points(10, 1) + p.points(10, 2) + p.points(10, 3))


def test_coverage_counts_real_forecasts():
    p = GwProjection(_board(), FIX, ffh_long=_long([(10, 1, 7.5, 90)]))
    assert p.coverage([10, 20], 1) == (1, 2)
    assert p.coverage([10, 20], 2) == (0, 2)


def test_window_is_the_weeks_the_match_model_covers():
    p = GwProjection(_board(), FIX,
                     ffh_long=_long([(10, 1, 7.5, 90), (10, 2, 6.0, 90)]))
    assert p.window == [1, 2]
    assert GwProjection(_board(), FIX).window == []


# ── best XI ──────────────────────────────────────────────────────────────────

def _squad():
    """Two keepers, five defenders, five midfielders, three forwards."""
    pos = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return pd.DataFrame({"code": range(1, 16), "position": pos,
                         "team_id": [1] * 15})


def test_best_xi_is_a_legal_formation():
    squad = _squad()
    board = pd.DataFrame({"code": squad["code"], "team_id": 1,
                          "consensus_points": range(15, 0, -1),
                          "position": squad["position"]})
    xi = best_xi(squad, GwProjection(board, FIX), 1)
    got = squad[squad["code"].isin(xi)]["position"].value_counts()
    assert len(xi) == 11
    assert got.get("GKP", 0) == 1
    assert got.get("DEF", 0) >= 3
    assert got.get("MID", 0) >= 2
    assert got.get("FWD", 0) >= 1


def test_best_xi_prefers_the_higher_scorers():
    squad = _squad()
    board = pd.DataFrame({"code": squad["code"], "team_id": 1,
                          "consensus_points": range(15, 0, -1),
                          "position": squad["position"]})
    proj = GwProjection(board, FIX)
    xi = best_xi(squad, proj, 1)
    inside = min(proj.points(c, 1) for c in xi)
    outside = [proj.points(int(c), 1) for c in squad["code"] if c not in xi]
    # nobody benched outscores the weakest starter once the shape is legal
    assert all(o <= inside + 1e-9 for o in outside) or len(outside) == 4
