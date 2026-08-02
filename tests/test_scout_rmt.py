"""Scout's Rate My Team per-gameweek snapshot, and the two-source blend.

All figures here are INVENTED · the real snapshot is paid third-party data and
is never reproduced in this repo.
"""
import numpy as np
import pandas as pd

from analytics import scout_rmt as RMT
from analytics.gw_projection import RMT_WEIGHT, HUB_WEIGHT, _blend_match_sources


def _board():
    return pd.DataFrame({
        "code": [1, 2], "web_name": ["Alpha", "M.Beta"],
        "team_short": ["ARS", "TOT"], "position": ["MID", "DEF"]})


def _snap():
    return pd.DataFrame({
        "name": ["Alpha", "Beta"], "team": ["Arsenal", "Spurs"],
        "pos": ["M", "D"], "gw1": [5.0, 3.0], "gw2": [4.0, 2.0],
        "gw3": [6.0, 4.0]})


# ── the snapshot ─────────────────────────────────────────────────────────────

def test_clubs_map_to_the_board_short_code():
    df = RMT.load_snapshot.__wrapped__ if hasattr(RMT.load_snapshot, "__wrapped__") else None
    s = _snap().copy()
    s["team_short"] = s["team"].map(RMT.CLUB_TO_SHORT)
    assert list(s["team_short"]) == ["ARS", "TOT"]


def test_positions_map_to_fpl_names():
    assert RMT.POS_TO_FPL["G"] == "GKP" and RMT.POS_TO_FPL["F"] == "FWD"


def test_a_surname_only_row_still_joins():
    """FPL writes a clash as "M.Beta"; Scout drops the initial."""
    s = _snap()
    s["team_short"] = s["team"].map(RMT.CLUB_TO_SHORT)
    s["pos"] = s["pos"].map(RMT.POS_TO_FPL)
    long = RMT.per_gw_by_code(s, _board())
    assert set(long["code"]) == {1, 2}


def test_long_frame_is_one_row_per_player_gameweek():
    s = _snap()
    s["team_short"] = s["team"].map(RMT.CLUB_TO_SHORT)
    s["pos"] = s["pos"].map(RMT.POS_TO_FPL)
    long = RMT.per_gw_by_code(s, _board())
    assert len(long) == 6 and set(long["gw"]) == {1, 2, 3}


# ── the blend ────────────────────────────────────────────────────────────────

def _hub(pts, mins=80.0):
    return pd.DataFrame({"code": [1], "gw": [1], "pts": [pts], "exp_mins": [mins]})


def _rmt(pts):
    return pd.DataFrame({"code": [1], "gw": [1], "pts": [pts]})


def test_scout_carries_the_bigger_weight():
    assert RMT_WEIGHT > HUB_WEIGHT and abs(RMT_WEIGHT + HUB_WEIGHT - 1.0) < 1e-9


def test_where_only_scout_has_a_view_scout_is_used():
    out = _blend_match_sources(None, _rmt(5.0))
    assert float(out.iloc[0]["pts"]) == 5.0


def test_where_only_the_hub_has_a_view_the_hub_survives():
    hub = _hub(4.0)
    out = _blend_match_sources(hub, pd.DataFrame(columns=["code", "gw", "pts"]))
    assert float(out.iloc[0]["pts"]) == 4.0


def test_the_blend_lands_between_the_two():
    out = _blend_match_sources(_hub(4.0), _rmt(6.0))
    v = float(out.iloc[0]["pts"])
    assert 4.0 < v < 6.0 and v > 5.0      # Scout-weighted, so nearer 6


def test_expected_minutes_come_from_the_hub():
    """Scout's table has no minutes column · the Hub is the only source that
    states them, and the early-minutes gate runs on that."""
    out = _blend_match_sources(_hub(4.0, mins=72.0), _rmt(6.0))
    assert float(out.iloc[0]["exp_mins"]) == 72.0


def test_a_small_overlap_does_not_rescale():
    """A scale ratio from a handful of players is noise, not a calibration."""
    hub = pd.DataFrame({"code": [1], "gw": [1], "pts": [4.0], "exp_mins": [80.0]})
    out = _blend_match_sources(hub, _rmt(4.0))
    assert abs(float(out.iloc[0]["pts"]) - 4.0) < 1e-6
