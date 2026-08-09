"""A player who is not playing scores nothing, whatever the points model says.

Points and minutes come from different places in the blend: Scout supplies a
per-fixture score, the Hub supplies stated expected minutes. Nothing reconciled
them, so 25 player-gameweek cells projected real points on a stated ZERO
minutes. Mac Allister came out at 3.7 for GW1 on 0 expected minutes and the
optimiser duly drafted him.

CLAUDE.md already states the intent: a Hub zero "still drives the per-gameweek
view, where not playing IS the answer". This makes that true.

Only a STATED zero counts. Unknown minutes stay unknown and change nothing.
"""
import pandas as pd

from analytics.gw_projection import GwProjection

BOARD = pd.DataFrame([{"code": 1, "team_id": 10, "consensus_points": 190.0},
                      {"code": 2, "team_id": 10, "consensus_points": 190.0}])
FIX = {(10, 1): [("OPP", True, 3.0)]}


def _proj(long, **kw):
    return GwProjection(BOARD, FIX, ffh_long=pd.DataFrame(long), **kw)


def test_a_stated_zero_minutes_scores_nothing():
    p = _proj([{"code": 1, "gw": 1, "pts": 6.0, "exp_mins": 0}])
    assert p.points(1, 1) == 0.0


def test_stated_minutes_above_zero_are_untouched():
    p = _proj([{"code": 1, "gw": 1, "pts": 6.0, "exp_mins": 60}])
    assert p.points(1, 1) > 0


def test_unknown_minutes_change_nothing():
    # No minutes cell at all is not a statement that he is out.
    p = _proj([{"code": 1, "gw": 1, "pts": 6.0}])
    assert p.expected_minutes(1, 1) is None
    assert p.points(1, 1) > 0


def test_a_hand_set_score_still_beats_a_stated_zero():
    # gw_points is the most explicit statement there is: "he plays, and this is
    # what he returns". It must overrule a stale minutes cell.
    p = _proj([{"code": 1, "gw": 1, "pts": 6.0, "exp_mins": 0}],
              gw_points={1: {1: 9.0}})
    assert p.points(1, 1) == 9.0


def test_it_does_not_leak_to_other_players():
    p = _proj([{"code": 1, "gw": 1, "pts": 6.0, "exp_mins": 0},
               {"code": 2, "gw": 1, "pts": 6.0, "exp_mins": 90}])
    assert p.points(1, 1) == 0.0 and p.points(2, 1) > 0
