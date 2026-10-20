"""Two minutes bugs found 20 Oct 2026 (GW8).

1. vaastav's players_raw for the live season stopped at element 616, and the
   archive inner-joins on it, so the 52 players FPL added since (Barcola, Timber,
   Affengruber...) had no history and every one projected ~72 minutes.
2. A doubtful player who missed his last match carried that 0 into every future
   week's frozen features, and the 75% flag was then applied on top: Gibbs-White
   (6 of 6 starts at 90 minutes, then injured) read 33 expected minutes.
"""
import pandas as pd

from analytics.brain import drop_injury_gap
from data.fetchers import vaastav


# ── 1 · live-season player lookup ─────────────────────────────────────────────

def _bootstrap():
    el = lambda i, code, name: {"id": i, "code": code, "first_name": "F",
                                "second_name": name, "web_name": name,
                                "element_type": 3, "team": 1}
    return {"elements": [el(1, 1001, "Old"), el(650, 6650, "New")]}


def test_live_season_lookup_comes_from_the_bootstrap(monkeypatch):
    from data.fetchers import fpl_api
    monkeypatch.setattr(fpl_api, "fetch_bootstrap", _bootstrap)
    monkeypatch.setattr(vaastav, "_fetch_csv", lambda url: pd.DataFrame(
        {"id": [1], "code": [1001], "first_name": ["F"], "second_name": ["Old"],
         "web_name": ["Old"], "element_type": [3], "team": [1]}))
    raw = vaastav.fetch_players_raw(vaastav.CURRENT_SEASON)
    assert set(raw["id"]) == {1, 650}
    assert raw.loc[raw["id"] == 650, "code"].item() == 6650
    for col in ("id", "code", "first_name", "second_name", "web_name",
                "element_type", "team"):
        assert col in raw.columns


def test_live_season_lookup_falls_back_to_vaastav(monkeypatch):
    from data.fetchers import fpl_api

    def boom():
        raise RuntimeError("offline")
    monkeypatch.setattr(fpl_api, "fetch_bootstrap", boom)
    monkeypatch.setattr(vaastav, "_is_fresh", lambda key, season=None: False)
    monkeypatch.setattr(vaastav, "_fetch_csv", lambda url: pd.DataFrame(
        {"id": [1], "code": [1001], "element_type": [3], "team": [1]}))
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, p: None)
    raw = vaastav.fetch_players_raw(vaastav.CURRENT_SEASON)
    assert list(raw["id"]) == [1]


# ── 2 · injury gap ───────────────────────────────────────────────────────────

def _hist(minutes, starts, code=7, season="2026-27"):
    return pd.DataFrame({"code": code, "season": season,
                         "gw": range(1, len(minutes) + 1),
                         "minutes": minutes, "starts": starts})


def _players(status, code=7):
    return pd.DataFrame({"code": [code], "status": [status]})


def test_doubtful_starter_loses_his_injury_blank():
    h = _hist([90, 90, 90, 0], [1, 1, 1, 0])
    out = drop_injury_gap(h, _players("d"), "2026-27")
    assert list(out["gw"]) == [1, 2, 3]


def test_available_player_keeps_his_blank():
    # No injury flag: a blank could be a dropping, and history prices that.
    h = _hist([90, 90, 90, 0], [1, 1, 1, 0])
    assert len(drop_injury_gap(h, _players("a"), "2026-27")) == 4


def test_long_absence_is_kept():
    # Three blanks or more and a return to 90 minutes is no longer the base case.
    h = _hist([90, 90, 0, 0, 0], [1, 1, 0, 0, 0])
    assert len(drop_injury_gap(h, _players("d"), "2026-27")) == 5


def test_bench_player_blank_is_kept():
    # He was not starting before the blank, so it is not an injury gap.
    h = _hist([10, 0, 15, 0], [0, 0, 0, 0])
    assert len(drop_injury_gap(h, _players("d"), "2026-27")) == 4


def test_one_start_after_a_run_off_the_bench_is_kept():
    # Isidor, Oct 2026: five sub cameos, one start, then a knock. Dropping the
    # blank made his "last match" a 90-minute start and invented a starter.
    h = _hist([23, 26, 26, 20, 22, 90, 0], [0, 0, 0, 0, 0, 1, 0])
    assert len(drop_injury_gap(h, _players("d"), "2026-27")) == 7


def test_two_blank_gap_dropped_and_earlier_seasons_untouched():
    old = _hist([0, 0], [0, 0], season="2025-26")
    h = pd.concat([old, _hist([90, 85, 0, 0], [1, 1, 0, 0])], ignore_index=True)
    out = drop_injury_gap(h, _players("d"), "2026-27")
    assert len(out[out["season"] == "2025-26"]) == 2
    assert list(out.loc[out["season"] == "2026-27", "gw"]) == [1, 2]


def test_other_players_untouched():
    h = pd.concat([_hist([90, 0], [1, 0], code=7),
                   _hist([90, 0], [1, 0], code=8)], ignore_index=True)
    out = drop_injury_gap(h, _players("d", code=7), "2026-27")
    assert len(out[out["code"] == 8]) == 2
    assert len(out[out["code"] == 7]) == 1
