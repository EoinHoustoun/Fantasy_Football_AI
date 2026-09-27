import pandas as pd
import pytest

from analytics.brain import availability_factor, freeze_future_features
from analytics.service import free_transfers, team_xp
from analytics.transfer_plan import selling_price, solve


def test_selling_price_keeps_half_the_rise_rounded_down():
    assert selling_price(5.5, 5.8) == 5.6
    assert selling_price(5.5, 5.6) == 5.5
    assert selling_price(7.5, 7.2) == 7.2


def test_availability_fades_after_the_next_gameweek():
    assert availability_factor("i", 0.0, 0) == 0.0
    assert availability_factor("i", 0.0, 1) == 0.5
    assert availability_factor("i", 0.0, 4) == pytest.approx(0.85)
    assert availability_factor("s", 0.0, 1) == 1.0
    assert availability_factor("u", 100.0, 3) == 0.0
    assert availability_factor("a", None, 0) == 1.0
    assert availability_factor("d", 75.0, 0) == 0.75


def test_free_transfers_replay_matches_real_history():
    # Team 45595, 2026-27: BB GW1, TC GW3, WC GW4, no transfers otherwise -> 4 FTs for GW6.
    hist = {"chips": [{"name": "bboost", "event": 1}, {"name": "3xc", "event": 3},
                      {"name": "wildcard", "event": 4}],
            "current": [{"event": g, "event_transfers": (6 if g == 4 else 0)} for g in range(1, 6)]}
    assert free_transfers(hist, 6) == 4


def test_free_transfers_cap_and_spend():
    hist = {"chips": [], "current": [{"event": g, "event_transfers": 0} for g in range(1, 9)]}
    assert free_transfers(hist, 9) == 5
    hist["current"][4]["event_transfers"] = 3   # GW5: spend 3 of 4
    assert free_transfers(hist, 7) == 3


def test_freeze_copies_player_features_but_not_fixture_features():
    f = pd.DataFrame({"code": [1, 1, 1], "season_ord": ["x"] * 3, "gw": [5, 6, 7],
                      "fixture": [1, 2, 3], "mins_last": [90.0, None, None],
                      "opp_att": [1.0, 2.0, 3.0]})
    fut = pd.Series([False, True, True])
    f.loc[1, "mins_last"] = 88.0
    out = freeze_future_features(f, fut, ["mins_last", "opp_att"])
    assert list(out["mins_last"]) == [90.0, 88.0, 88.0]
    assert list(out["opp_att"]) == [1.0, 2.0, 3.0]


def _toy():
    rows = []
    code = 1
    for pos, n in (("GKP", 3), ("DEF", 6), ("MID", 6), ("FWD", 4)):
        for k in range(n):
            rows.append({"code": code, "position": pos, "price": 5.0, "team_id": code,
                         "web_name": "%s%d" % (pos, k)})
            code += 1
    players = pd.DataFrame(rows)
    xp = pd.DataFrame({g: [1.0] * len(players) for g in (1, 2)}, index=players["code"])
    return players, xp


def test_team_xp_doubles_the_captain_and_discounts_the_bench():
    players, xp = _toy()
    squad = [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18]
    pos = dict(zip(players["code"], players["position"]))
    per = xp.copy()
    per.loc[16, 1] = 5.0
    # GW1: 11 starters at 1 + captain(5) doubled -> 10 + 5 + 5 = 20, bench 4 x 0.1
    # GW2: 11 + 1 captain = 12, bench 0.4
    assert team_xp(squad, per, pos) == pytest.approx(20.4 + 12.4)


def test_solver_makes_the_one_clear_upgrade_and_holds_otherwise():
    players, xp = _toy()
    owned = [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18]
    xp.loc[19] = [6.0, 6.0]            # an unowned forward who is much better
    res = solve(xp, players, owned, bank=0.0, free_transfers=1,
                sell_price={}, gws=[1, 2], settings={"time_limit": 20})
    w1 = res["weeks"][0]
    assert w1["in"] == [19] and len(w1["out"]) == 1
    assert res["weeks"][1]["in"] == []
    held = solve(xp, players, owned, 0.0, 1, {}, [1, 2], hold=True)
    assert held["xp_total"] < res["xp_total"]
