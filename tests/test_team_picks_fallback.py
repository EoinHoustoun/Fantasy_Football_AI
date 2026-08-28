"""Between a finished gameweek and the next deadline, FPL's picks endpoint
404s for the upcoming GW. The app plans against the NEXT gameweek, so every
squad page asked for picks that do not exist yet and showed "Couldn't load
that squad". The fetcher must fall back to the latest GW that has picks and
layer on any transfers already made for the requested one."""
import requests

from data.fetchers import fpl_api


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code}")
            err.response = self
            raise err

    def json(self):
        return self._payload


GW1 = {"picks": [{"element": 10, "position": 1, "is_captain": False,
                  "is_vice_captain": False, "multiplier": 1},
                 {"element": 11, "position": 2, "is_captain": True,
                  "is_vice_captain": False, "multiplier": 2}],
       "entry_history": {"event": 1, "points": 86}}


def _router(transfers):
    def get(url, headers=None, timeout=None):
        if url.endswith("/event/2/picks/"):
            return _Resp(404)
        if url.endswith("/event/1/picks/"):
            return _Resp(200, GW1)
        if url.endswith("/transfers/"):
            return _Resp(200, transfers)
        raise AssertionError(url)
    return get


def test_falls_back_to_latest_gw_with_picks(monkeypatch):
    monkeypatch.setattr(fpl_api.requests, "get", _router([]))
    data = fpl_api.fetch_team_picks(45595, 2)
    assert [p["element"] for p in data["picks"]] == [10, 11]
    assert data["entry_history"]["event"] == 1
    assert data["picks_gw"] == 1 and data["requested_gw"] == 2


def test_applies_transfers_already_made_for_requested_gw(monkeypatch):
    transfers = [{"event": 2, "element_out": 11, "element_in": 99},
                 {"event": 1, "element_out": 5,  "element_in": 10}]   # older, ignored
    monkeypatch.setattr(fpl_api.requests, "get", _router(transfers))
    data = fpl_api.fetch_team_picks(45595, 2)
    elems = {p["position"]: p["element"] for p in data["picks"]}
    assert elems == {1: 10, 2: 99}
    assert data["picks"][1]["is_captain"] is False      # captaincy does not carry over


def test_direct_hit_is_untouched(monkeypatch):
    def get(url, headers=None, timeout=None):
        assert url.endswith("/event/1/picks/")
        return _Resp(200, GW1)
    monkeypatch.setattr(fpl_api.requests, "get", get)
    data = fpl_api.fetch_team_picks(45595, 1)
    assert data["picks_gw"] == 1 and data["requested_gw"] == 1


def test_gives_up_when_no_gw_has_picks(monkeypatch):
    monkeypatch.setattr(fpl_api.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(404))
    try:
        fpl_api.fetch_team_picks(45595, 3)
    except requests.HTTPError:
        return
    raise AssertionError("expected HTTPError")
