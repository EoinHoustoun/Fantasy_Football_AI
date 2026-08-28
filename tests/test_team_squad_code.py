"""The real squad must carry the season-stable `code`, because the Value Board,
projector and player card are all keyed by it. `fpl_id` changes every summer."""
from data.fetchers import fpl_api


BOOT = {
    "elements": [
        {"id": 5, "code": 99001, "web_name": "Saka", "team": 1, "element_type": 3,
         "now_cost": 100, "total_points": 9, "form": "9.0", "selected_by_percent": "40.0",
         "status": "a", "news": ""},
        {"id": 6, "code": 99002, "web_name": "Raya", "team": 1, "element_type": 1,
         "now_cost": 55, "total_points": 6, "form": "6.0", "selected_by_percent": "30.0",
         "status": "a", "news": ""},
    ],
    "teams": [{"id": 1, "name": "Arsenal", "code": 3, "short_name": "ARS"}],
}
PICKS = {"picks": [
    {"element": 6, "position": 1, "is_captain": False, "is_vice_captain": False, "multiplier": 1},
    {"element": 5, "position": 2, "is_captain": True, "is_vice_captain": False, "multiplier": 2},
], "entry_history": {"event": 1}}


def test_squad_carries_code(monkeypatch):
    monkeypatch.setattr(fpl_api, "fetch_team_picks", lambda team_id, gw: PICKS)
    df, _ = fpl_api.get_team_squad(45595, 1, bootstrap=BOOT)
    assert list(df["code"]) == [99002, 99001]
    assert df["code"].dtype.kind == "i"
