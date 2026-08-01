"""Player comparison verdict · better, worse, or the same, and what to DO.

All figures here are INVENTED.

The case worth protecting is the third one: a player who is genuinely a little
better but meaningfully dearer is NOT a reason to spend. Inside the noise of a
model that ranks at about 0.4 correlation, the money is the only real
difference, so the cheaper player is the pick.
"""
import pytest

from analytics.grading import band_of, points_cuts
from analytics.head_to_head import compare_players, verdict


def _p(name, price, run, per_gw, mins, per_m, per90, dc, ag=0.9, pos="DEF"):
    return dict(name=name, price=price, run=run, per_gw=per_gw, exp_mins_pg=mins,
                season=run * 6.3, per_m=per_m, per_90=per90, defcon=dc,
                fixtures=1.0, agreement=ag, position=pos, code=1,
                team="X", team_code=1, team_short="X")


def _v(a, b):
    return verdict(compare_players([a, b]), [a, b])


# ── the same ─────────────────────────────────────────────────────────────────

def test_near_identical_players_pick_the_cheaper_one():
    v = _v(_p("Dear", 6.0, 26.0, 4.33, 85, 5.1, 0.30, 0.42),
           _p("Cheap", 4.5, 25.6, 4.27, 84, 5.2, 0.30, 0.41))
    assert v["call"] == "same"
    assert v["pick"] == "Cheap"
    assert "1.5" in v["detail"]          # names the saving


def test_a_small_edge_that_costs_real_money_is_still_the_cheaper_pick():
    """Three points better over six gameweeks and three million dearer. The
    points are inside the noise; the money is not."""
    v = _v(_p("Dearer", 7.5, 28.0, 4.7, 86, 3.7, 0.33, 0.45),
           _p("Value", 4.5, 25.0, 4.2, 84, 5.6, 0.31, 0.40))
    assert v["pick"] == "Value"
    assert "3.0" in v["detail"]


def test_same_price_and_same_output_says_it_comes_down_to_belief():
    v = _v(_p("A", 5.0, 26.0, 4.33, 85, 5.2, 0.30, 0.42),
           _p("B", 5.0, 25.7, 4.28, 85, 5.1, 0.30, 0.41))
    assert v["call"] == "same"
    assert v["pick"] is None
    assert "minutes you believe" in v["detail"]


# ── one is better ────────────────────────────────────────────────────────────

def test_a_clear_winner_is_called_clearly():
    v = _v(_p("Star", 6.0, 38.0, 6.3, 88, 6.3, 0.45, 0.60),
           _p("Weak", 4.5, 18.0, 3.0, 60, 4.0, 0.22, 0.20))
    assert v["call"] == "clear"
    assert v["pick"] == "Star"
    assert "worth it" in v["detail"]


def test_the_verdict_names_what_it_won_on():
    v = _v(_p("Star", 6.0, 38.0, 6.3, 88, 6.3, 0.45, 0.60),
           _p("Weak", 4.5, 18.0, 3.0, 60, 4.0, 0.22, 0.20))
    assert " on " in v["headline"]


def test_one_player_cannot_be_compared():
    v = verdict(compare_players([]), [])
    assert v["call"] == "unclear"
    assert v["pick"] is None


# ── the bars ─────────────────────────────────────────────────────────────────

def test_cuts_are_position_relative():
    """Keepers cluster and forwards spread, so the same score is not the same
    quality. A flat cut looks decisive and is quietly wrong."""
    cuts = points_cuts({
        "GKP": [3.5 + i * 0.02 for i in range(60)],     # tight
        "FWD": [1.0 + i * 0.12 for i in range(60)],     # wide
    })
    assert cuts["GKP"][1] < cuts["FWD"][1]


def test_band_of_respects_the_cuts():
    cuts = {"DEF": (3.5, 4.1)}
    assert band_of(4.8, "DEF", cuts) == "green"
    assert band_of(3.8, "DEF", cuts) == "amber"
    assert band_of(2.9, "DEF", cuts) == "red"


def test_a_missing_score_is_not_quietly_green():
    assert band_of(None, "DEF", {"DEF": (3.5, 4.1)}) == "red"


def test_a_thin_sample_falls_back_rather_than_fitting_to_noise():
    cuts = points_cuts({"FWD": [4.0, 4.1, 4.2]})
    assert cuts["FWD"] == (3.5, 4.3)
