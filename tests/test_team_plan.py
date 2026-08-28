"""Plan state for the REAL team, keyed by player code like the Draft."""
import json

import pytest

from analytics import team_plan as tp
from analytics import squad_planner as sp


@pytest.fixture(autouse=True)
def tmp_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "PLANS_PATH", tmp_path / "squad_plans.json")
    yield


START = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


def test_normalize_v1_transfers_map_ids_to_codes():
    v1 = {"transfers": [{"out_id": 501, "in_id": 502, "out_name": "A", "in_name": "B"}],
          "captain": 501, "chip": None}
    e = tp.normalize(v1, code_by_fpl_id={501: 9001, 502: 9002})
    assert e == {"swaps": {9001: 9002}, "captain": 9001, "chip": None}


def test_normalize_drops_unknown_ids_and_bare_lists():
    e = tp.normalize([{"out_id": 1, "in_id": 2}], code_by_fpl_id={1: 10})
    assert e == {"swaps": {}, "captain": None, "chip": None}


def test_round_trip_and_schema_tag():
    tp.save_draft(45595, 3, {"swaps": {3: 30}, "captain": 30, "chip": None})
    tp.save_plan(45595, 2, {"swaps": {1: 21}, "captain": None, "chip": "BB"})
    plans, drafts = tp.load(45595)
    assert plans == {2: {"swaps": {1: 21}, "captain": None, "chip": "BB"}}
    assert drafts == {3: {"swaps": {3: 30}, "captain": 30, "chip": None}}
    raw = json.loads(sp.PLANS_PATH.read_text())
    assert raw["schema"] == 2


def test_save_plan_clears_the_draft_for_that_week():
    tp.save_draft(45595, 2, {"swaps": {1: 21}, "captain": None, "chip": None})
    tp.save_plan(45595, 2, {"swaps": {1: 21}, "captain": None, "chip": None})
    _, drafts = tp.load(45595)
    assert 2 not in drafts


def test_effective_codes_replays_saved_weeks_then_draft():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": None},
             3: {"swaps": {2: 22}, "captain": None, "chip": None}}
    drafts = {3: {"swaps": {2: 23}, "captain": None, "chip": None}}
    assert tp.effective_codes(START, plans, drafts, 2)[:2] == [21, 2]
    assert tp.effective_codes(START, plans, drafts, 3)[:2] == [21, 23]   # draft wins for gw3
    assert tp.effective_codes(START, plans, {}, 3)[:2] == [21, 22]
    assert tp.effective_codes(START, plans, drafts, 4)[:2] == [21, 23]   # draft for 3 still applies at 4


def test_free_hit_week_reverts_afterwards():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": "FH"}}
    assert tp.effective_codes(START, plans, {}, 2)[0] == 21
    assert tp.effective_codes(START, plans, {}, 3)[0] == 1


def test_swaps_upto_and_wildcard_gw():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": "WC"},
             4: {"swaps": {5: 55}, "captain": None, "chip": None}}
    assert tp.swaps_upto(plans, {}, 3) == {2: {1: 21}}
    assert tp.wildcard_gw(plans, {}, 5) == 2
    assert tp.chip_at(plans, {}, 4) is None


def test_migration_v1_to_v2_with_mapping():
    """Migration write-back when code_by_fpl_id is supplied: v1 transfers convert to swaps, schema is updated."""
    # Seed schema-less v1 file
    sp._write({"plans": {"45595": {"2": {"transfers": [{"out_id": 501, "in_id": 502}], "captain": 501, "chip": "BB"}}},
               "drafts": {}})
    # Load WITH mapping
    plans, drafts = tp.load(45595, code_by_fpl_id={501: 9001, 502: 9002})
    # Verify in-memory result is migrated v2
    assert plans == {2: {"swaps": {9001: 9002}, "captain": 9001, "chip": "BB"}}
    # Verify file on disk now has schema == 2 with migrated swaps (JSON keys are strings)
    raw = json.loads(sp.PLANS_PATH.read_text())
    assert raw["schema"] == 2
    assert raw["plans"]["45595"]["2"]["swaps"]["9001"] == 9002
    assert raw["plans"]["45595"]["2"]["captain"] == 9001
    assert raw["plans"]["45595"]["2"]["chip"] == "BB"


def test_migration_v1_without_mapping_leaves_file_untouched():
    """Loading schema-less v1 WITHOUT code_by_fpl_id returns empty swaps but does NOT write to disk."""
    # Seed schema-less v1 file
    original = {"plans": {"45595": {"2": {"transfers": [{"out_id": 501, "in_id": 502}], "captain": 501, "chip": "BB"}}},
                "drafts": {}}
    sp._write(original)
    # Load WITHOUT mapping
    plans, drafts = tp.load(45595)
    # In-memory: transfers drop because no mapping, so swaps are empty
    assert plans == {2: {"swaps": {}, "captain": None, "chip": "BB"}}
    # File on disk: unchanged (no schema key added, v1 transfers still there)
    raw = json.loads(sp.PLANS_PATH.read_text())
    assert "schema" not in raw
    assert raw == original


def test_empty_schema_less_file_stays_unwritten():
    """Loading an empty schema-less file does not write to disk."""
    # Seed empty schema-less file
    sp._write({"plans": {}, "drafts": {}})
    # Load
    plans, drafts = tp.load(45595)
    # In-memory: empty
    assert plans == {} and drafts == {}
    # File on disk: still has no schema (no write happened)
    raw = json.loads(sp.PLANS_PATH.read_text())
    assert "schema" not in raw


def test_ledger_banks_and_charges_like_the_draft():
    plans = {3: {"swaps": {1: 21, 2: 22, 3: 23}, "captain": None, "chip": None}}
    led = tp.ledger(plans, {}, 3, START, first_gw=2, banked_now=1)
    w = {x["gw"]: x for x in led["weeks"]}
    assert w[2]["used"] == 0 and w[2]["available_before"] == 1
    assert w[3]["available_before"] == 2 and w[3]["used"] == 3
    assert w[3]["hits"] == 1 and led["points_cost"] == 4


def test_ledger_respects_transfers_already_banked():
    plans = {2: {"swaps": {1: 21, 2: 22}, "captain": None, "chip": None}}
    led = tp.ledger(plans, {}, 2, START, first_gw=2, banked_now=2)
    assert led["hits"] == 0


def test_ledger_buy_back_is_free():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": None},
             3: {"swaps": {21: 1}, "captain": None, "chip": None}}
    led = tp.ledger(plans, {}, 3, START, first_gw=2)
    assert led["hits"] == 0


def test_ledger_wildcard_week_is_unlimited():
    plans = {2: {"swaps": {1: 21, 2: 22, 3: 23, 4: 24}, "captain": None, "chip": "WC"}}
    led = tp.ledger(plans, {}, 2, START, first_gw=2)
    assert led["hits"] == 0 and led["wildcard_gw"] == 2


def test_bank_after_prices_moves():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": None}}
    prices = {1: 5.0, 21: 6.5}
    assert tp.bank_after(2.0, prices, START, plans, {}, 2) == pytest.approx(0.5)
