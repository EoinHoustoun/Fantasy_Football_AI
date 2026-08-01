"""Promoted-club DEFCON bonus · detection, targeting, and the refusal guards.

All figures here are INVENTED. The point of these tests is the RULES: defenders
only, promoted clubs only, and a refusal to guess when the inputs look wrong.
"""
import pandas as pd

from analytics.promoted import (PROMOTED_DEF_DEFCON_BONUS, apply_defcon_bonus,
                                promoted_clubs)

LAST = {"Arsenal", "Chelsea", "Everton", "Fulham"}


def _live(names):
    return pd.DataFrame({"name": names, "id": range(1, len(names) + 1)})


# ── detection ────────────────────────────────────────────────────────────────

def test_promoted_is_the_set_difference():
    live = _live(["Arsenal", "Chelsea", "Everton", "Newtown", "Oldford"])
    assert promoted_clubs(live, LAST) == {"Newtown", "Oldford"}


def test_no_promoted_when_nothing_changed():
    assert promoted_clubs(_live(sorted(LAST)), LAST) == set()


def test_refuses_when_too_many_look_promoted():
    """A naming mismatch would make every club look promoted. Applying a bonus
    to the whole league is far worse than applying none."""
    live = _live(["AFC Arsenal", "FC Chelsea", "Everton FC", "Fulham FC", "Newtown"])
    assert promoted_clubs(live, LAST) == set()


def test_missing_inputs_return_empty_not_a_guess():
    assert promoted_clubs(None, LAST) == set()
    assert promoted_clubs(pd.DataFrame(), LAST) == set()
    assert promoted_clubs(_live(["Newtown"]), set()) == set()


# ── targeting ────────────────────────────────────────────────────────────────

def _board():
    return pd.DataFrame({
        "web_name": ["PromoDef", "PromoMid", "PromoFwd", "StayDef", "PromoDef2"],
        "team_name": ["Newtown", "Newtown", "Newtown", "Arsenal", "Oldford"],
        "position": ["DEF", "MID", "FWD", "DEF", "DEF"],
        "consensus_points": [60.0, 90.0, 70.0, 100.0, 55.0],
    })


def test_bonus_hits_promoted_defenders_only():
    out = apply_defcon_bonus(_board(), {"Newtown", "Oldford"},
                             points_col="consensus_points")
    got = dict(zip(out["web_name"], out["consensus_points"]))
    assert got["PromoDef"] == 60.0 + PROMOTED_DEF_DEFCON_BONUS
    assert got["PromoDef2"] == 55.0 + PROMOTED_DEF_DEFCON_BONUS
    # midfielders measured at -0.3% (p=0.96) · they get nothing
    assert got["PromoMid"] == 90.0
    assert got["PromoFwd"] == 70.0
    assert got["StayDef"] == 100.0


def test_bonus_is_recorded_per_row_for_audit():
    out = apply_defcon_bonus(_board(), {"Newtown"}, points_col="consensus_points")
    rec = dict(zip(out["web_name"], out["promoted_defcon_bonus"]))
    assert rec["PromoDef"] == PROMOTED_DEF_DEFCON_BONUS
    assert rec["PromoMid"] == 0.0
    assert rec["StayDef"] == 0.0


def test_no_promoted_clubs_is_a_no_op():
    board = _board()
    out = apply_defcon_bonus(board, set(), points_col="consensus_points")
    assert out["consensus_points"].tolist() == board["consensus_points"].tolist()
    assert (out["promoted_defcon_bonus"] == 0).all()


def test_missing_points_column_does_not_raise():
    board = _board().drop(columns=["consensus_points"])
    out = apply_defcon_bonus(board, {"Newtown"}, points_col="consensus_points")
    assert (out["promoted_defcon_bonus"] == 0).all()


def test_nan_projection_becomes_the_bonus_not_nan():
    board = _board()
    board.loc[0, "consensus_points"] = None
    out = apply_defcon_bonus(board, {"Newtown"}, points_col="consensus_points")
    assert out.loc[0, "consensus_points"] == PROMOTED_DEF_DEFCON_BONUS


def test_does_not_mutate_the_caller_frame():
    board = _board()
    before = board["consensus_points"].tolist()
    apply_defcon_bonus(board, {"Newtown"}, points_col="consensus_points")
    assert board["consensus_points"].tolist() == before


def test_bonus_size_matches_the_documented_derivation():
    """+5.6% action rate through a negative-binomial threshold model is worth
    about +2.5 season points. Guard against a silent edit to the constant."""
    assert 2.0 <= PROMOTED_DEF_DEFCON_BONUS <= 3.0
