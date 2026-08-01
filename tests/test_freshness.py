"""Snapshot freshness and the content stamp that replaced len(board).

The stamp exists because caches keyed on row COUNT survived the exact edits
they were supposed to notice. These tests pin that down.
"""
import pandas as pd

from analytics import freshness as F


# ── the content stamp ────────────────────────────────────────────────────────

def test_stamp_moves_when_a_value_changes_but_the_row_count_does_not():
    """This is the whole bug. A snapshot refresh or an override edit changes
    numbers, not the number of rows."""
    a = pd.DataFrame({"consensus_points": [10.0, 20.0, 30.0]})
    b = pd.DataFrame({"consensus_points": [10.0, 20.0, 30.5]})
    assert len(a) == len(b)
    assert F.board_stamp(a) != F.board_stamp(b)


def test_stamp_is_stable_for_identical_input():
    a = pd.DataFrame({"consensus_points": [1.0, 2.0]})
    assert F.board_stamp(a) == F.board_stamp(a.copy())


def test_stamp_moves_when_rows_are_added():
    a = pd.DataFrame({"consensus_points": [1.0, 2.0]})
    b = pd.DataFrame({"consensus_points": [1.0, 2.0, 3.0]})
    assert F.board_stamp(a) != F.board_stamp(b)


def test_stamp_falls_back_to_projected_points():
    a = pd.DataFrame({"projected_points": [1.0, 2.0]})
    b = pd.DataFrame({"projected_points": [1.0, 9.0]})
    assert F.board_stamp(a) != F.board_stamp(b)


def test_stamp_handles_empty_and_none_without_raising():
    assert isinstance(F.board_stamp(None), str)
    assert isinstance(F.board_stamp(pd.DataFrame()), str)


def test_stamp_ignores_columns_that_cannot_move_a_projection():
    a = pd.DataFrame({"consensus_points": [1.0], "web_name": ["A"]})
    b = pd.DataFrame({"consensus_points": [1.0], "web_name": ["B"]})
    assert F.board_stamp(a) == F.board_stamp(b)


# ── age reporting ────────────────────────────────────────────────────────────

def test_age_label_reads_as_time_not_a_timestamp():
    assert F.age_label(None) == "missing"
    assert F.age_label(0.0) == "just now"
    assert F.age_label(0.5) == "12h ago"
    assert F.age_label(3.0) == "3d ago"
    assert F.age_label(30.0) == "4w ago"


def test_state_thresholds():
    import time
    now = time.time()
    rows = F.sources(now=now)
    for r in rows:
        if r["days"] is None:
            assert r["state"] == "missing"
        elif r["days"] >= F.STALE_AFTER_DAYS:
            assert r["state"] == "stale"
        elif r["days"] >= F.AGEING_AFTER_DAYS:
            assert r["state"] == "ageing"
        else:
            assert r["state"] == "fresh"


def test_worst_state_reports_the_most_serious():
    assert F.worst_state([{"state": "fresh"}, {"state": "stale"}]) == "stale"
    assert F.worst_state([{"state": "fresh"}, {"state": "ageing"}]) == "ageing"
    assert F.worst_state([{"state": "missing"}, {"state": "stale"}]) == "missing"
    assert F.worst_state([{"state": "fresh"}]) == "fresh"


def test_sources_returns_a_state_for_every_known_input():
    for r in F.sources():
        assert r["state"] in {"fresh", "ageing", "stale", "missing"}
        assert r["name"]
