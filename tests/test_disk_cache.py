"""Derived frames survive a restart instead of being rebuilt from scratch.

`build_board` costs 3.9 seconds and `build_player_universe` 2.8. Both are pure
functions of inputs the app already stamps, so paying that on every cold start,
and on every override edit, is waste. This caches the RESULT to disk under the
stamp, which turns a rebuild into a parquet read.

The danger is obvious and is what these tests are for: a cache that serves the
wrong stamp, or that survives a corrupt file by crashing the page.
"""
import pandas as pd
import pytest

from data import disk_cache


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_cache, "STORE", tmp_path)


def _frame(n=3):
    return pd.DataFrame({"code": range(n), "pts": [1.5] * n, "name": ["a"] * n})


def test_the_builder_runs_on_a_cold_cache():
    calls = []
    out = disk_cache.cached("board", "stamp-1", lambda: (calls.append(1), {"df": _frame()})[1])
    assert calls == [1]
    assert out["df"].equals(_frame())


def test_the_builder_does_not_run_again_for_the_same_stamp():
    disk_cache.cached("board", "stamp-1", lambda: {"df": _frame()})
    calls = []
    out = disk_cache.cached("board", "stamp-1", lambda: (calls.append(1), {"df": _frame()})[1])
    assert calls == [], "second call rebuilt instead of reading the cache"
    assert out["df"].equals(_frame())


def test_a_new_stamp_rebuilds():
    disk_cache.cached("board", "stamp-1", lambda: {"df": _frame(3)})
    out = disk_cache.cached("board", "stamp-2", lambda: {"df": _frame(5)})
    assert len(out["df"]) == 5


def test_dtypes_and_values_survive_the_round_trip():
    df = pd.DataFrame({"code": pd.Series([1, 2], dtype="int64"),
                       "pts": pd.Series([1.25, 2.5], dtype="float64"),
                       "ok": pd.Series([True, False], dtype="bool"),
                       "name": ["x", "y"]})
    disk_cache.cached("t", "s", lambda: {"df": df})
    got = disk_cache.cached("t", "s", lambda: {"df": None})["df"]
    pd.testing.assert_frame_equal(got, df)


def test_non_frame_values_round_trip_too():
    payload = {"df": _frame(), "meta": {"model": "xgb", "mae": 0.17}, "n": 4}
    disk_cache.cached("t", "s", lambda: payload)
    got = disk_cache.cached("t", "s", lambda: {"df": None})
    assert got["meta"] == {"model": "xgb", "mae": 0.17}
    assert got["n"] == 4


def test_a_corrupt_cache_rebuilds_rather_than_crashing():
    disk_cache.cached("t", "s", lambda: {"df": _frame()})
    for p in disk_cache.STORE.rglob("*.parquet"):
        p.write_bytes(b"not a parquet file")
    calls = []
    out = disk_cache.cached("t", "s", lambda: (calls.append(1), {"df": _frame()})[1])
    assert calls == [1], "a corrupt cache must fall back to building"
    assert out["df"].equals(_frame())


def test_a_None_frame_round_trips_as_None():
    # build_board legitimately returns None for a missing scout snapshot.
    disk_cache.cached("t", "s", lambda: {"df": _frame(), "scout": None})
    got = disk_cache.cached("t", "s", lambda: {"df": None})
    assert got["scout"] is None
