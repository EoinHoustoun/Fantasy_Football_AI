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
