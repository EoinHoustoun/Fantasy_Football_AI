"""A manager-change correction has to reach the per-gameweek layer.

`pts_mult` scales the SEASON projection. The opening-window objective reads
per-fixture match cells instead, so a season haircut never touches it · the same
trap that left Foden reading as a substitute after his minutes were fixed.

`gw_pts_mult` is the per-gameweek twin: it scales whatever the match model says
for that player, in every week, without freezing a number that goes stale the
next time a snapshot lands.
"""
import pandas as pd

from analytics.gw_projection import GwProjection

BOARD = pd.DataFrame([
    {"code": 1, "team_id": 10, "consensus_points": 190.0},
    {"code": 2, "team_id": 10, "consensus_points": 190.0},
])
FIX = {(10, 1): [("OPP", True, 3.0)], (10, 2): [("OPP", False, 3.0)]}
LONG = pd.DataFrame([
    {"code": 1, "gw": 1, "pts": 6.0, "exp_mins": 90},
    {"code": 1, "gw": 2, "pts": 4.0, "exp_mins": 90},
    {"code": 2, "gw": 1, "pts": 6.0, "exp_mins": 90},
])


def _proj(**kw):
    return GwProjection(BOARD, FIX, ffh_long=LONG, **kw)


# Asserted as RATIOS against the un-multiplied projection. The class rescales
# match cells on the way in (the Hub runs hot and is damped), so an absolute
# expectation would be testing that rescale, not this multiplier.

def test_the_multiplier_scales_every_gameweek_for_that_player():
    base, up = _proj(), _proj(gw_pts_mult={1: 1.10})
    assert round(up.points(1, 1) / base.points(1, 1), 3) == 1.10
    assert round(up.points(1, 2) / base.points(1, 2), 3) == 1.10


def test_it_touches_nobody_else():
    base, up = _proj(), _proj(gw_pts_mult={1: 1.10})
    assert up.points(2, 1) == base.points(2, 1)


def test_a_hand_set_score_still_wins():
    # `gw_points` is the most explicit statement there is · a blanket rate
    # correction must not quietly rescale a number set for one fixture.
    p = _proj(gw_pts_mult={1: 1.10}, gw_points={1: {1: 9.0}})
    assert p.points(1, 1) == 9.0


def test_a_missed_gameweek_stays_zero():
    p = _proj(gw_pts_mult={1: 1.10}, miss_gws={1: [1]})
    assert p.points(1, 1) == 0.0
