"""MILP: max attack-correlated players per club, with DEFCON exemption."""
from typing import List

import pandas as pd

from analytics.squad_milp import optimize_squad


def _pool() -> pd.DataFrame:
    rows: List[dict] = []
    code = 1
    team_cycle = list(range(10, 40))   # spread filler so <=3 per club holds
    ti = 0

    def add(pos, price, pts, n):
        nonlocal code, ti
        for _ in range(n):
            rows.append({"code": code, "web_name": f"{pos}{code}", "position": pos,
                         "team_id": team_cycle[ti % len(team_cycle)],
                         "price": price, "pts": pts})
            code += 1
            ti += 1

    # Plenty of cheap filler across many clubs so a legal 15 is always available.
    add("GKP", 4.5, 30, 6)
    add("DEF", 4.5, 30, 12)
    add("MID", 5.0, 30, 10)
    add("FWD", 5.0, 30, 8)
    # Team 1: two ELITE attacking mids (the optimiser wants both).
    rows.append({"code": 900, "web_name": "EliteA", "position": "MID",
                 "team_id": 1, "price": 6.0, "pts": 200})
    rows.append({"code": 901, "web_name": "EliteB", "position": "MID",
                 "team_id": 1, "price": 6.0, "pts": 195})
    return pd.DataFrame(rows)


def _team1_attackers(res):
    s = res["squad"]
    return s[(s["team_id"] == 1) & (s["position"].isin(["MID", "FWD"]))]


def test_without_cap_both_elite_mids_are_picked():
    res = optimize_squad(_pool(), budget=100.0, time_limit=20)
    assert len(_team1_attackers(res)) == 2


def test_cap_limits_same_club_attackers_to_one():
    res = optimize_squad(_pool(), budget=100.0, time_limit=20, max_attackers_per_club=1)
    assert len(_team1_attackers(res)) == 1


def test_defcon_mid_is_exempt_from_the_cap():
    pool = _pool()
    # Make the second team-1 mid a DEFCON player · both should now be allowed.
    defcon_code = int(pool[(pool["team_id"] == 1)].iloc[1]["code"])
    res = optimize_squad(pool, budget=100.0, time_limit=20,
                         max_attackers_per_club=1, defcon_codes=[defcon_code])
    assert len(_team1_attackers(res)) == 2
