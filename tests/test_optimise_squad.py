"""The Optimise button · the window it solves, and the diff it shows.

The 26/27 Draft page froze its optimiser whenever a draft carried a saved
fifteen, so every tuning dial moved nothing. The button that unfreezes it needs
two pure pieces the view cannot be trusted to hold: which gameweeks the squad is
being built for, and what actually changed when the solver comes back.
"""
import pandas as pd

from analytics.squad_milp import optimize_squad
from analytics.squad_rules import plan_window, squad_diff


# ── the window the squad is built for ────────────────────────────────────────
# You own the opening squad until you wildcard, so that is the window worth
# optimising. Scoring it over a season you are going to tear up rewards players
# who pay off in weeks you will not own them.

def test_a_wildcard_at_gw4_builds_for_the_first_three_weeks():
    assert plan_window(4) == (1, 3)


def test_no_wildcard_means_no_window():
    assert plan_window(None) is None


def test_a_wildcard_in_gw1_leaves_nothing_to_build_for():
    assert plan_window(1) is None


def test_the_week_survives_arriving_as_a_string():
    assert plan_window("4") == (1, 3)


# ── what actually changed ────────────────────────────────────────────────────
# Joined on code, never on name · a name join is what silently lost the second
# opinions, and a diff that quietly drops a player is worse than no diff.

PRICES = {1: 4.5, 2: 6.0, 3: 7.0, 4: 9.0, 5: 5.5, 6: 6.5}


def test_a_player_who_left_is_reported_out():
    d = squad_diff([1, 2, 3], [1, 2, 4], PRICES)
    assert d["out"] == [3]


def test_a_player_who_arrived_is_reported_in():
    d = squad_diff([1, 2, 3], [1, 2, 4], PRICES)
    assert d["in"] == [4]


def test_players_who_stayed_are_in_neither_list():
    d = squad_diff([1, 2, 3], [1, 2, 4], PRICES)
    assert 1 not in d["out"] + d["in"]
    assert 2 not in d["out"] + d["in"]


def test_an_unchanged_squad_has_an_empty_diff():
    d = squad_diff([1, 2, 3], [3, 2, 1], PRICES)
    assert d["out"] == [] and d["in"] == []


def test_spend_is_totalled_on_both_sides():
    d = squad_diff([1, 2, 3], [1, 2, 4], PRICES)
    assert d["spend_before"] == 17.5   # 4.5 + 6.0 + 7.0
    assert d["spend_after"] == 19.5    # 4.5 + 6.0 + 9.0


def test_the_biggest_move_is_listed_first():
    # 4 is the expensive arrival, 5 the cheap one · the eye should meet the
    # move that spent the money, not whichever code sorted lowest.
    d = squad_diff([1, 2], [4, 5], PRICES)
    assert d["in"] == [4, 5]


def test_a_player_missing_from_the_board_is_still_reported_out():
    # The saved fifteen can name a code the board no longer carries. Omitting
    # the row makes a player vanish from the squad with nothing said, which is
    # the silent-drop failure this diff exists to prevent.
    d = squad_diff([1, 999], [1, 2], PRICES)
    assert 999 in d["out"]


def test_a_missing_price_does_not_corrupt_the_total():
    d = squad_diff([1, 999], [1, 2], PRICES)
    assert d["spend_before"] == 4.5
    assert d["unpriced"] == [999]


# ── vetoing a player reallocates the whole budget ────────────────────────────
# Eoin's question, and the behaviour `views/18_draft_2026_27.py:1505` claims but
# nothing tested: banning a player must not slot in another at the same price.
# It frees the money and re-solves all fifteen, so the answer can be "buy the
# expensive one and downgrade someone else to pay for it".
#
# The pool below makes that the only good answer. Every player scores (bench
# weight 1.0, no captain), so the maths is a clean knapsack:
#
#   core 15 slots cost 52.0 and leave 12.0 for one DEF slot and one MID slot
#   dHigh 6.5/12  dLow 3.0/5   X 5.5/40   mCheap 5.5/10   mStar 9.0/30
#
#   with X:     dHigh + X      = 12.0 ✓  52 pts   ← the optimum
#   vetoed:     dHigh + mCheap = 12.0 ✓  22 pts   ← the like-for-like swap
#               dLow  + mStar  = 12.0 ✓  35 pts   ← the reallocation, and better

def _reallocation_pool():
    rows = []
    tid = 0

    def add(code, pos, price, pts):
        nonlocal tid
        tid += 1
        rows.append({"code": code, "position": pos, "price": price,
                     "pts": pts, "team_id": tid})

    for i in range(2):                      # keepers · exactly enough
        add(10 + i, "GKP", 4.0, 5)
    for i in range(3):                      # forwards · exactly enough
        add(20 + i, "FWD", 4.0, 6)
    for i in range(4):                      # the flat defensive core
        add(30 + i, "DEF", 4.0, 6)
    for i in range(4):                      # the flat midfield core
        add(40 + i, "MID", 4.0, 6)

    add(50, "DEF", 6.5, 12)                 # dHigh
    add(51, "DEF", 3.0, 5)                  # dLow
    add(60, "MID", 5.5, 40)                 # X · the player Eoin vetoes
    add(61, "MID", 5.5, 10)                 # mCheap · the like-for-like swap
    add(62, "MID", 9.0, 30)                 # mStar · only affordable if dHigh goes

    return pd.DataFrame(rows)


def _solve(exclude=None):
    out = optimize_squad(_reallocation_pool(), budget=64.0, bench_weight=1.0,
                         captain=False, exclude_codes=exclude or [])
    assert out is not None, "the pool should always admit a legal fifteen"
    return [int(c) for c in out["squad"]["code"]]


def test_the_vetoed_player_starts_in_the_optimal_squad():
    assert 60 in _solve()


def test_a_veto_removes_the_player():
    assert 60 not in _solve(exclude=[60])


def test_a_veto_moves_more_than_the_vetoed_slot():
    before, after = _solve(), _solve(exclude=[60])
    prices = dict(zip(_reallocation_pool()["code"],
                      _reallocation_pool()["price"]))
    d = squad_diff(before, after, prices)
    # One change out would mean a like-for-like substitution at the same price,
    # which is the behaviour this must never regress to.
    assert len(d["out"]) > 1, d


def test_the_money_goes_where_it_buys_most():
    after = _solve(exclude=[60])
    assert 62 in after, "the expensive midfielder should be bought"
    assert 50 not in after, "the better defender should be sold to pay for him"
