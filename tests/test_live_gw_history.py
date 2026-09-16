"""The current season's GW history comes from the FPL API, not vaastav.

Vaastav publishes the merged_gw.csv for a season weeks after it starts (and
went stale at GW29 last season). In-season consumers (points model, rolling
xGI, DEFCON, ownership trend) must be fed from `event/{gw}/live` joined to
the bootstrap, in the same schema vaastav uses, so nothing downstream changes.
"""
import pandas as pd

from data.fetchers import fpl_history as fh


BOOT = {
    "events": [
        {"id": 1, "finished": True,  "data_checked": True},
        {"id": 2, "finished": False, "data_checked": False},
    ],
    "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"},
              {"id": 2, "name": "Hull", "short_name": "HUL"}],
    "elements": [
        {"id": 10, "first_name": "Bukayo", "second_name": "Saka", "web_name": "Saka",
         "element_type": 3, "team": 1, "now_cost": 100, "selected_by_percent": "40.5",
         "ep_this": "6.1", "code": 999},
        {"id": 11, "first_name": "Joe", "second_name": "Bloggs", "web_name": "Bloggs",
         "element_type": 2, "team": 2, "now_cost": 40, "selected_by_percent": "0.3",
         "ep_this": "1.0", "code": 998},
    ],
}
FIXTURES = [{"id": 5, "event": 1, "team_h": 2, "team_a": 1}]
LIVE = {"elements": [
    {"id": 10, "stats": {"minutes": 90, "total_points": 9, "goals_scored": 1, "assists": 0,
                         "clean_sheets": 0, "bps": 40, "starts": 1, "bonus": 3,
                         "expected_goals": "0.5", "expected_assists": "0.2",
                         "expected_goal_involvements": "0.7", "expected_goals_conceded": "1.1",
                         "clearances_blocks_interceptions": 1, "tackles": 2,
                         "defensive_contribution": 0},
     "explain": [{"fixture": 5, "stats": []}]},
    {"id": 11, "stats": {"minutes": 0, "total_points": 0, "goals_scored": 0, "assists": 0,
                         "clean_sheets": 0, "bps": 0, "starts": 0, "bonus": 0,
                         "expected_goals": "0", "expected_assists": "0",
                         "expected_goal_involvements": "0", "expected_goals_conceded": "0",
                         "clearances_blocks_interceptions": 0, "tackles": 0,
                         "defensive_contribution": 0},
     "explain": [{"fixture": 5, "stats": []}]},
]}


def test_live_history_matches_vaastav_schema():
    df = fh.build_live_gw_history(BOOT, FIXTURES, live_for_gw=lambda gw: LIVE)
    assert len(df) == 2
    assert set(df["GW"]) == {1}                      # only finished, checked GWs
    saka = df[df["element"] == 10].iloc[0]
    assert saka["name"] == "Bukayo Saka"
    assert saka["position"] == "MID" and saka["team"] == "Arsenal"
    assert saka["value"] == 100 and saka["was_home"] is False or saka["was_home"] == False
    assert saka["opponent_team"] == 2 and saka["fixture"] == 5
    assert saka["expected_goal_involvements"] == 0.7       # numeric, not str
    assert saka["clearances_blocks_interceptions"] + saka["tackles"] == 3
    for col in ("xP", "selected", "kickoff_time", "round", "starts", "bps"):
        assert col in df.columns


def test_no_finished_gameweek_returns_empty_frame():
    boot = dict(BOOT, events=[{"id": 1, "finished": False, "data_checked": False}])
    df = fh.build_live_gw_history(boot, FIXTURES, live_for_gw=lambda gw: LIVE)
    assert df.empty and "GW" in df.columns


def test_unchecked_gameweek_is_excluded():
    boot = dict(BOOT, events=[{"id": 1, "finished": True, "data_checked": False}])
    df = fh.build_live_gw_history(boot, FIXTURES, live_for_gw=lambda gw: LIVE)
    assert df.empty
