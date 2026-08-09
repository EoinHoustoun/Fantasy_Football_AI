"""Chip timing must read the same per-gameweek numbers as everything else.

`chip_windows` spread a season projection over 38 and scaled it by fixture
difficulty. That is a fixture SHAPE, not a forecast: it cannot see that a player
is on 15 minutes because he came back late from a tournament, and its average is
wrong for anyone whose scoring is lumpy, which is every premium. CLAUDE.md is
explicit that per-gameweek points go through `analytics/gw_projection`, never a
local `season / 38 * ease` again. The Chip Planner was the last page still doing
its own.

Passing a projector also makes the page agree with the Draft page about the same
squad, which it previously could not.
"""
import pandas as pd

from analytics.chip_timing import chip_windows


class FakeProj(object):
    """A projector with an opinion the fixture-shape model cannot have."""

    def __init__(self, table):
        self.table = table          # {(code, gw): points}

    def points(self, code, gw):
        return float(self.table.get((int(code), int(gw)), 0.0))


SQUAD = pd.DataFrame([
    {"code": 1, "web_name": "Star", "team_id": 10, "pts": 200.0, "in_xi": True},
    {"code": 2, "web_name": "Sub", "team_id": 10, "pts": 100.0, "in_xi": False},
])
FIX = pd.DataFrame([
    {"gameweek": 1, "home_team_id": 10, "away_team_id": 20, "home_fdr": 2, "away_fdr": 4},
    {"gameweek": 2, "home_team_id": 20, "away_team_id": 10, "home_fdr": 3, "away_fdr": 3},
])


def test_it_uses_the_projector_when_given_one():
    # The bench player is worthless in GW1 and excellent in GW2. Only a real
    # per-gameweek forecast knows that; a season average never will.
    proj = FakeProj({(1, 1): 5.0, (1, 2): 5.0, (2, 1): 0.0, (2, 2): 12.0})
    w = chip_windows(SQUAD, FIX, 1, 2, proj=proj)
    bb = {r["gw"]: r["bench_pts"] for r in w["bench_boost"]}
    assert bb[2] > bb[1]
    assert bb[1] == 0.0


def test_the_triple_captain_week_follows_the_projector():
    proj = FakeProj({(1, 1): 3.0, (1, 2): 20.0, (2, 1): 1.0, (2, 2): 1.0})
    w = chip_windows(SQUAD, FIX, 1, 2, proj=proj)
    assert w["triple_captain"][0]["gw"] == 2
    assert w["triple_captain"][0]["captain"] == "Star"


def test_without_a_projector_it_still_works():
    """The old fixture-shape path stays available · other callers rely on it."""
    w = chip_windows(SQUAD, FIX, 1, 2)
    assert len(w["bench_boost"]) == 2
    assert all("bench_pts" in r for r in w["bench_boost"])


def test_a_blank_gameweek_scores_nothing_either_way():
    proj = FakeProj({(1, 1): 5.0, (2, 1): 5.0})
    w = chip_windows(SQUAD, FIX, 1, 3, proj=proj)
    gw3 = [r for r in w["free_hit"] if r["gw"] == 3][0]
    assert gw3["blanks"] == 2


def test_free_hit_finds_the_squad_s_worst_week():
    proj = FakeProj({(1, 1): 20.0, (2, 1): 20.0, (1, 2): 1.0, (2, 2): 1.0})
    w = chip_windows(SQUAD, FIX, 1, 2, proj=proj)
    assert w["free_hit"][0]["gw"] == 2
