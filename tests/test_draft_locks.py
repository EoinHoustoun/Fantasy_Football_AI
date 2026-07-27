"""Draft locks · forced players, and locks beating vetoes."""
import pandas as pd
import pytest

from ui.value_board import solve_draft


def _board():
    """A feasible 26/27 board under the standing club rules.

    Those rules bite hard on a toy fixture: at most ONE attacker (MID or FWD) per
    club means the 8 attackers in a squad need 8 DISTINCT clubs, and at most one
    defender per club needs another 5. So attackers each get their own club.
    """
    rows = []
    code = 0
    plan = [("GKP", 4), ("DEF", 9), ("MID", 8), ("FWD", 6)]
    for pos, n in plan:
        for i in range(n):
            code += 1
            # attackers get a club each; defenders and keepers spread separately
            team = (i + 1) if pos in ("MID", "FWD") else (i + 1)
            if pos == "FWD":
                team = i + 9          # keep FWD clubs clear of MID clubs
            rows.append({
                "code": code, "web_name": "%s%d" % (pos, i),
                "position": pos, "team_id": team,
                "actual_price": 4.0 + (i * 0.5),
                # cheaper players are deliberately worse, so a lock on a cheap one costs
                "projected_points": 40.0 + i * 12.0,
                "proj_lo": 30.0 + i * 12.0,
                "opening_factor": 1.0,
            })
    return pd.DataFrame(rows)


def test_locked_player_is_always_in_the_squad():
    b = _board()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, (), 0.0,
                      force_names=("DEF0",))
    assert res is not None
    assert "DEF0" in set(res["squad"]["web_name"])


def test_lock_beats_veto_when_a_player_is_in_both():
    """Picking and vetoing the same player is a mistake · the explicit lock wins."""
    b = _board()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, ("DEF0",), 0.0,
                      force_names=("DEF0",))
    assert res is not None
    assert "DEF0" in set(res["squad"]["web_name"])


def test_veto_alone_still_excludes():
    b = _board()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, ("DEF6",), 0.0)
    assert res is not None
    assert "DEF6" not in set(res["squad"]["web_name"])


def test_multiple_locks_all_survive():
    b = _board()
    locks = ("DEF0", "MID0", "FWD0")
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, (), 0.0, force_names=locks)
    assert res is not None
    assert set(locks) <= set(res["squad"]["web_name"])


def test_locking_a_weak_player_costs_points_not_feasibility():
    """The whole point of the readout: a lock has a price, and we can measure it."""
    b = _board()
    free = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, (), 0.0)
    locked = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, (), 0.0,
                         force_names=("GKP0", "DEF0", "MID0"))
    assert free is not None and locked is not None
    assert locked["xi_points"] <= free["xi_points"]


def test_unknown_lock_name_is_ignored_not_fatal():
    b = _board()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.3, (), 0.0,
                      force_names=("NotAPlayer",))
    assert res is not None
