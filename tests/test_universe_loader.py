"""One universe loader, not eight copies with four different TTLs.

Six view files each defined an identical `load_universe()`, cached separately,
with TTLs of 900, 1800, 3600 and 21600 seconds. That is six cache entries of the
same 2.8-second build, and two pages could legitimately show different numbers
at the same moment because their TTLs expired at different times.
"""
import pandas as pd
import pytest

from data import universe as U


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    from data import disk_cache
    monkeypatch.setattr(disk_cache, "STORE", tmp_path)
    U.load_universe.clear()


def _fake(monkeypatch, n=3, calls=None):
    def _build(stamp, simulate_gw):
        if calls is not None:
            calls.append((stamp, simulate_gw))
        return pd.DataFrame({"code": range(n), "web_name": ["p"] * n})
    monkeypatch.setattr(U, "_build_universe", _build)


def test_it_returns_a_frame(monkeypatch):
    _fake(monkeypatch)
    assert len(U.load_universe("s1")) == 3


def test_the_same_stamp_builds_once(monkeypatch):
    calls = []
    _fake(monkeypatch, calls=calls)
    U.load_universe("s1")
    U.load_universe.clear()          # drop the in-process layer, keep disk
    U.load_universe("s1")
    assert len(calls) == 1, "second call rebuilt instead of reading disk"


def test_a_new_stamp_rebuilds(monkeypatch):
    calls = []
    _fake(monkeypatch, calls=calls)
    U.load_universe("s1")
    U.load_universe.clear()
    U.load_universe("s2")
    assert len(calls) == 2


def test_the_simulated_gameweek_is_part_of_the_key(monkeypatch):
    # GW39 sim clones GW1 fixtures · serving the un-simulated universe for it
    # would silently give every fixture tool nothing to point at.
    calls = []
    _fake(monkeypatch, calls=calls)
    U.load_universe("s1", simulate_gw=None)
    U.load_universe.clear()
    U.load_universe("s1", simulate_gw=39)
    assert len(calls) == 2, "simulate_gw must not collide with the plain build"
