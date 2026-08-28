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


def _two_good_defenders_at_one_club():
    """A board where the two best defenders share a club.

    Under the old hardcoded cap the optimiser could never own both, whatever the
    numbers said. Eoin dropped that rule on 2026-08-11, so the cap has to be a
    parameter rather than a constant.
    """
    b = _board()
    b.loc[b["web_name"] == "DEF8", "team_id"] = int(
        b.loc[b["web_name"] == "DEF7", "team_id"].iloc[0])
    return b


def test_defender_cap_of_one_keeps_the_pair_apart():
    b = _two_good_defenders_at_one_club()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.0, (), 0.0,
                      max_defenders_per_club=1)
    assert res is not None
    picked = set(res["squad"]["web_name"])
    assert not {"DEF7", "DEF8"} <= picked


def test_defender_cap_of_none_lets_the_optimiser_take_both():
    b = _two_good_defenders_at_one_club()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.0, (), 0.0,
                      max_defenders_per_club=None)
    assert res is not None
    assert {"DEF7", "DEF8"} <= set(res["squad"]["web_name"])


def test_a_lock_that_matches_nobody_is_reported():
    """A vanished lock looks like a lock that was not worth taking · say so.

    The handler is attached to the module logger directly rather than using
    `caplog`, because Streamlit reconfigures logging when its cache warms up
    and the fixture's root handler stops seeing these records once it has.
    """
    import logging

    seen = []

    class _Catch(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    log = logging.getLogger("ui.value_board")
    h = _Catch(level=logging.WARNING)
    log.addHandler(h)
    try:
        res = solve_draft(_board(), "⚖️ Optimal value", 100.0, 0.3, (), 0.0,
                          force_names=("NoSuchPlayerAnywhere",))
    finally:
        log.removeHandler(h)

    assert res is not None                       # the solve still succeeds
    assert any("NoSuchPlayerAnywhere" in m for m in seen)


# ── the penalty-taker captaincy rule, inside the solver ──────────────────────

def _board_with_pens():
    """One clear best player who does NOT take penalties, and a taker below him."""
    b = _board()
    b["pens_order"] = float("nan")
    b.loc[b["web_name"] == "MID7", "pens_order"] = 1.0      # a taker, not the best
    b.loc[b["web_name"] == "FWD5", "pens_order"] = 1.0
    return b


def test_free_captaincy_picks_the_highest_scorer():
    b = _board_with_pens()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.0, (), 0.0)
    cap = res["squad"][res["squad"]["is_captain"]]["web_name"].iloc[0]
    assert cap not in ("MID7", "FWD5")


def test_pens_rule_moves_the_armband_to_a_taker():
    b = _board_with_pens()
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.0, (), 0.0,
                      captain_must_take_pens=True)
    cap = res["squad"][res["squad"]["is_captain"]]["web_name"].iloc[0]
    assert cap in ("MID7", "FWD5")


def test_a_board_with_no_takers_still_solves():
    """No pens_order anywhere is a DATA problem · it must not make every squad
    infeasible, so the rule stands down and says so."""
    b = _board()
    b["pens_order"] = float("nan")
    res = solve_draft(b, "⚖️ Optimal value", 100.0, 0.0, (), 0.0,
                      captain_must_take_pens=True)
    assert res is not None
    assert len(res["squad"]) == 15
