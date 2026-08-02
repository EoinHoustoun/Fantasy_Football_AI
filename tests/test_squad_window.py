"""The eleven is re-picked every gameweek, so complementary fixtures count.

A fixed-lineup optimiser maximises the sum of fifteen window totals, which is
the wrong objective: only eleven of them score in any given week. Two players
whose good weeks alternate are worth more than their totals suggest, because
you start whichever one has the fixture. Eoin's example, and the reason this
exists:

    A:  8, 2, 8   and   1, 7, 1     totals 18 + 9  = 27, fielded 8+7+8 = 23
    B:  5, 7, 5   and   5, 5, 7     totals 17 + 17 = 34, fielded 5+7+7 = 19

Summing totals prefers B by 7. Playing the fixtures prefers A by 4.
"""

import pandas as pd
import pytest

from analytics.squad_milp import optimize_squad

GWS = ["gw1", "gw2", "gw3"]


def _filler(start_id, position, n, price, per_gw, team_offset=0):
    """Players who are identical every week, to pad a legal squad out."""
    return [{"code": start_id + i, "position": position, "price": price,
             "team_id": 100 + team_offset + i,
             "gw1": per_gw, "gw2": per_gw, "gw3": per_gw}
            for i in range(n)]


def _pool():
    """A legal universe where exactly one MID slot is contested.

    Everything else is deliberately flat, so any difference in the answer comes
    from the contested slot and nothing else.
    """
    rows = []
    rows += _filler(1, "GKP", 4, 4.0, 3.0, 0)
    rows += _filler(11, "DEF", 8, 4.0, 3.0, 10)
    rows += _filler(31, "FWD", 6, 4.0, 3.0, 30)
    # Four MIDs that always start, plus the contested pair below.
    rows += _filler(41, "MID", 4, 4.0, 4.0, 40)

    # The contested pair · same price, same club-independence, different shape.
    # Only ONE of them can make the eleven each week (the squad takes both).
    rows += [
        {"code": 200, "position": "MID", "price": 5.0, "team_id": 200,
         "gw1": 8.0, "gw2": 2.0, "gw3": 8.0},          # spiky A1
        {"code": 201, "position": "MID", "price": 5.0, "team_id": 201,
         "gw1": 1.0, "gw2": 7.0, "gw3": 1.0},          # spiky A2, complements A1
        {"code": 300, "position": "MID", "price": 5.0, "team_id": 300,
         "gw1": 5.0, "gw2": 7.0, "gw3": 5.0},          # flat B1
        {"code": 301, "position": "MID", "price": 5.0, "team_id": 301,
         "gw1": 5.0, "gw2": 5.0, "gw3": 7.0},          # flat B2
    ]
    df = pd.DataFrame(rows)
    df["window"] = df[GWS].sum(axis=1)
    return df


def test_fixed_lineup_prefers_the_higher_totals():
    """Establishes the baseline · the old objective really does pick B."""
    res = optimize_squad(_pool(), budget=100.0, pts_col="window",
                         captain=False, bench_weight=0.0)
    assert res is not None
    got = set(res["squad"]["code"])
    assert {300, 301} <= got, "summing window totals should pick the flat pair"


def test_per_gameweek_lineup_prefers_the_complementary_pair():
    """The fix · with a weekly eleven, the spiky pair wins on what it fields."""
    res = optimize_squad(_pool(), budget=100.0, gw_pts_cols=GWS, captain=False)
    assert res is not None
    got = set(res["squad"]["code"])
    assert {200, 201} <= got, (
        "a weekly eleven should prefer 8/2/8 + 1/7/1 (fields 23) over "
        "5/7/5 + 5/5/7 (fields 19)")


def test_the_weekly_eleven_actually_rotates():
    """Not just a better squad · the plan itself has to differ week to week."""
    res = optimize_squad(_pool(), budget=100.0, gw_pts_cols=GWS, captain=False)
    xi = res["xi_by_week"]
    assert 200 in xi[0] and 200 in xi[2], "start the spiky player in his good weeks"
    assert 201 in xi[1], "and sub him for his complement in the week he blanks"
    assert 200 not in xi[1]


def test_window_points_are_what_gets_fielded_not_what_is_owned():
    res = optimize_squad(_pool(), budget=100.0, gw_pts_cols=GWS, captain=False)
    owned = float(res["squad"][GWS].sum().sum())
    assert res["window_points"] < owned, (
        "four of the fifteen sit out every week, so the fielded total must be "
        "lower than the sum of everyone's projections")


def test_a_boost_week_counts_all_fifteen():
    """With the Boost declared, the bench scores in that week and only that week."""
    plain = optimize_squad(_pool(), budget=100.0, gw_pts_cols=GWS, captain=False)
    boost = optimize_squad(_pool(), budget=100.0, gw_pts_cols=GWS,
                           boost_col="gw2", captain=False)
    assert boost["window_points"] > plain["window_points"], (
        "playing a Bench Boost cannot lower the window total")


def test_the_squad_rules_still_hold_per_gameweek():
    res = optimize_squad(_pool(), budget=100.0, gw_pts_cols=GWS, captain=False)
    sq = res["squad"]
    assert len(sq) == 15
    assert sq["position"].value_counts().to_dict() == {
        "DEF": 5, "MID": 5, "FWD": 3, "GKP": 2}
    for gw, codes in res["xi_by_week"].items():
        assert len(codes) == 11, "gameweek %s fielded %d" % (gw, len(codes))
        pos = sq.set_index("code").loc[codes, "position"]
        assert (pos == "GKP").sum() == 1
        assert (pos == "DEF").sum() >= 3
        assert (pos == "MID").sum() >= 2
        assert (pos == "FWD").sum() >= 1


def test_boost_col_must_be_one_of_the_gameweeks():
    with pytest.raises(ValueError):
        optimize_squad(_pool(), gw_pts_cols=GWS, boost_col="gw9")


def test_missing_gameweek_column_is_an_error_not_a_silent_zero():
    with pytest.raises(ValueError):
        optimize_squad(_pool(), gw_pts_cols=["gw1", "nope"])
