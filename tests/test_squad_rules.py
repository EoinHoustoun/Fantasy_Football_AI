"""Formation legality and free-transfer accounting · FPL's rules, tested.

These lived inside a Streamlit view where nothing could reach them.
"""
from analytics.squad_rules import (HIT_COST, formation_of, is_legal_xi,
                                   legal_swaps, transfer_ledger)

# 2 keepers, 5 defenders, 5 midfielders, 3 forwards · a standard fifteen.
POS = {}
POS.update({c: "GKP" for c in (1, 2)})
POS.update({c: "DEF" for c in (3, 4, 5, 6, 7)})
POS.update({c: "MID" for c in (8, 9, 10, 11, 12)})
POS.update({c: "FWD" for c in (13, 14, 15)})
SQUAD = list(range(1, 16))


def _xi(*codes):
    return set(codes)


# ── formation ────────────────────────────────────────────────────────────────

def test_formation_counts_by_position():
    assert formation_of([1, 3, 4, 8, 13], POS) == {"GKP": 1, "DEF": 2,
                                                   "MID": 1, "FWD": 1}


def test_unknown_codes_are_ignored():
    assert formation_of([1, 999], POS)["GKP"] == 1


# ── legality ─────────────────────────────────────────────────────────────────

def test_a_standard_343_is_legal():
    assert is_legal_xi(_xi(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15), POS)


def test_a_541_is_legal():
    assert is_legal_xi(_xi(1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13), POS)


def test_eleven_players_is_required():
    assert not is_legal_xi(_xi(1, 3, 4, 5, 8, 9, 10, 11, 13, 14), POS)


def test_exactly_one_keeper():
    assert not is_legal_xi(_xi(1, 2, 3, 4, 5, 8, 9, 10, 11, 13, 14), POS)
    assert not is_legal_xi(_xi(3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 15), POS)


def test_minimum_three_defenders():
    # two defenders, five midfielders, three forwards
    assert not is_legal_xi(_xi(1, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15), POS)


def test_minimum_one_forward():
    assert not is_legal_xi(_xi(1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12), POS)


# ── swaps ────────────────────────────────────────────────────────────────────

def test_a_keeper_can_only_be_swapped_for_the_other_keeper():
    xi = _xi(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
    assert legal_swaps(1, xi, SQUAD, POS) == [2]


def test_the_third_defender_can_only_be_replaced_by_a_defender():
    """Taking off a third defender with exactly three on means only another
    defender keeps the eleven legal · the rule the interface teaches."""
    xi = _xi(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
    got = legal_swaps(3, xi, SQUAD, POS)
    assert set(got) == {6, 7}
    assert all(POS[c] == "DEF" for c in got)


def test_a_spare_defender_can_be_replaced_by_anyone_on_the_bench():
    """Five defenders on, so dropping one still leaves four · every bench
    outfielder becomes legal."""
    xi = _xi(1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13)
    got = set(legal_swaps(3, xi, SQUAD, POS))
    assert {12, 14, 15} <= got
    assert 2 not in got                       # never the spare keeper


def test_nobody_on_the_bench_means_no_swaps():
    assert legal_swaps(3, set(SQUAD[:11]), SQUAD[:11], POS) == []


# ── the transfer ledger ──────────────────────────────────────────────────────

def test_gw1_is_free_and_never_appears():
    led = transfer_ledger({1: {1: 2, 3: 4}}, upto_gw=1)
    assert led["weeks"] == []
    assert led["points_cost"] == 0


def test_one_free_transfer_a_week():
    led = transfer_ledger({2: {1: 2}}, upto_gw=2)
    assert led["weeks"][0]["free_used"] == 1
    assert led["weeks"][0]["hits"] == 0
    assert led["points_cost"] == 0


def test_a_second_transfer_in_one_week_costs_four():
    led = transfer_ledger({2: {1: 2, 3: 4}}, upto_gw=2)
    assert led["weeks"][0]["hits"] == 1
    assert led["points_cost"] == HIT_COST


def test_transfers_bank_when_unused():
    led = transfer_ledger({}, upto_gw=4)
    assert led["available_now"] == 3          # GW2, GW3, GW4


def test_the_bank_is_capped():
    led = transfer_ledger({}, upto_gw=30, ft_cap=5)
    assert led["available_now"] == 5


def test_a_bank_absorbs_a_multi_transfer_week():
    """Three saved, three spent, no hit."""
    led = transfer_ledger({5: {1: 2, 3: 4, 6: 7}}, upto_gw=5)
    wk = [w for w in led["weeks"] if w["gw"] == 5][0]
    assert wk["available_before"] == 4
    assert wk["hits"] == 0
    assert led["points_cost"] == 0


def test_spending_past_the_bank_costs_per_extra_transfer():
    led = transfer_ledger({3: {1: 2, 3: 4, 5: 6, 7: 8}}, upto_gw=3)
    wk = led["weeks"][-1]
    assert wk["available_before"] == 2
    assert wk["hits"] == 2
    assert led["points_cost"] == 2 * HIT_COST


def test_the_bank_cannot_go_negative():
    led = transfer_ledger({2: {i: i + 100 for i in range(6)}}, upto_gw=3)
    assert led["available_now"] >= 0


def test_empty_swaps_is_free():
    led = transfer_ledger(None, upto_gw=6)
    assert led["points_cost"] == 0
    assert led["hits"] == 0


# ── net transfers · the user's undo ──────────────────────────────────────────

START = list(range(1, 16))


def test_selling_and_buying_back_costs_nothing():
    """Anyone who starts the week in the squad and ends it there was never
    transferred, whatever route he took. This is how a user undoes a change of
    mind, so charging for it would be charging for nothing."""
    led = transfer_ledger({2: {1: 99, 99: 1}}, upto_gw=2, start_codes=START)
    wk = led["weeks"][0]
    assert wk["used"] == 0
    assert led["points_cost"] == 0
    assert led["available_now"] == 1        # the free transfer is still there


def test_a_real_transfer_still_counts():
    led = transfer_ledger({2: {1: 99}}, upto_gw=2, start_codes=START)
    wk = led["weeks"][0]
    assert wk["used"] == 1
    assert wk["moves"] == {"out": [1], "in": [99]}


def test_a_chain_through_a_third_player_counts_once():
    """1 out for 99, then 99 out for 77. One player left, one arrived."""
    led = transfer_ledger({2: {1: 99, 99: 77}}, upto_gw=2, start_codes=START)
    wk = led["weeks"][0]
    assert wk["used"] == 1
    assert wk["moves"] == {"out": [1], "in": [77]}


def test_two_genuine_transfers_on_one_free_still_takes_a_hit():
    led = transfer_ledger({2: {1: 99, 2: 98}}, upto_gw=2, start_codes=START)
    assert led["weeks"][0]["used"] == 2
    assert led["points_cost"] == HIT_COST


def test_a_revert_in_a_LATER_week_is_a_real_transfer():
    """Undo is per gameweek. Buying a player back next week is a new transfer,
    because the squad that started that week did not contain him."""
    led = transfer_ledger({2: {1: 99}, 3: {99: 1}}, upto_gw=3, start_codes=START)
    assert [w["used"] for w in led["weeks"]] == [1, 1]


def test_without_start_codes_it_falls_back_to_counting_entries():
    led = transfer_ledger({2: {1: 99, 99: 1}}, upto_gw=2)
    assert led["weeks"][0]["used"] == 2


# ── the Wildcard week ────────────────────────────────────────────────────────

def test_the_wildcard_week_costs_nothing_however_many_moves():
    led = transfer_ledger({4: {1: 101, 2: 102, 3: 103, 4: 104, 5: 105, 6: 106}},
                          upto_gw=4, wildcard_gw=4)
    wk = [w for w in led["weeks"] if w["gw"] == 4][0]
    assert wk["hits"] == 0 and wk["cost"] == 0
    assert led["points_cost"] == 0


def test_the_wildcard_week_grants_no_free_transfer():
    """Three banked going into a GW4 Wildcard is still three in GW5 · you
    played the chip that week instead of taking the transfer."""
    plain = transfer_ledger({}, upto_gw=4)
    wild = transfer_ledger({}, upto_gw=4, wildcard_gw=4)
    assert plain["available_now"] == 3          # GW2, GW3, GW4
    assert wild["available_now"] == 2           # GW2, GW3 only


def test_the_bank_survives_the_wildcard_untouched():
    """Unlimited transfers that week must not eat the saved ones."""
    led = transfer_ledger({4: {1: 101, 2: 102}}, upto_gw=5, wildcard_gw=4)
    # GW2 +1, GW3 +1, GW4 none (wildcard), GW5 +1 = 3
    assert led["available_now"] == 3


def test_the_wildcard_week_is_flagged():
    led = transfer_ledger({}, upto_gw=4, wildcard_gw=4)
    assert [w["gw"] for w in led["weeks"] if w["wildcard"]] == [4]


def test_weeks_around_the_wildcard_still_charge_normally():
    led = transfer_ledger({3: {1: 101, 2: 102, 3: 103}}, upto_gw=4, wildcard_gw=4)
    wk3 = [w for w in led["weeks"] if w["gw"] == 3][0]
    assert wk3["used"] == 3 and wk3["hits"] == 1     # 2 banked, 3 made


def test_no_wildcard_behaves_exactly_as_before():
    a = transfer_ledger({3: {1: 101}}, upto_gw=5)
    b = transfer_ledger({3: {1: 101}}, upto_gw=5, wildcard_gw=None)
    assert a["available_now"] == b["available_now"]
    assert a["points_cost"] == b["points_cost"]


# ── accent-blind search ──────────────────────────────────────────────────────

def test_accents_fold_so_a_plain_keyboard_finds_the_player():
    from analytics.squad_rules import fold_accents as f
    assert f("Šeško") == "sesko"
    assert f("Dúbravka") == "dubravka"
    assert f("João Pedro") == "joao pedro"


def test_letters_that_do_not_decompose_are_mapped():
    """ø and đ have no combining form to strip, so NFD alone leaves them."""
    from analytics.squad_rules import fold_accents as f
    assert f("Højlund") == "hojlund"
    assert f("Ødegaard") == "odegaard"


def test_a_plain_name_is_only_lower_cased():
    from analytics.squad_rules import fold_accents as f
    assert f("Haaland") == "haaland"


def test_empty_input_is_safe():
    from analytics.squad_rules import fold_accents as f
    assert f("") == "" and f(None) == ""


def test_the_turkish_dotless_i_folds():
    """It is its own letter, not an accented one, so NFD leaves it alone."""
    from analytics.squad_rules import fold_accents as f
    assert f("Kadıoğlu") == "kadioglu"
