"""Playbook Q13-Q15 · shape and method guards on synthetic seasons.

These run on hand-built archives rather than the real parquet, so they stay fast
and assert the METHOD (which comparisons are legal) rather than the answers.
"""
import numpy as np
import pandas as pd
import pytest

from analytics.playbook import (early_bench_boost, opening_fixture_signal,
                                wildcard_decay)

POSITIONS = [("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]


def _archive(seasons=("2024-25",), gws=36, n_per_pos=14, seed=0):
    """A synthetic archive rich enough for a 15-man MILP to be feasible."""
    rng = np.random.default_rng(seed)
    rows = []
    code = 0
    for season in seasons:
        for pos, _ in POSITIONS:
            for i in range(n_per_pos):
                code += 1
                team = code % 10 + 1
                strength = rng.uniform(1.0, 6.0)
                for gw in range(1, gws + 1):
                    rows.append({
                        "season": season, "code": code, "position": pos,
                        "team_id": team, "gw": gw,
                        "opponent_team": (team % 10) + 1,
                        "total_points": float(max(0, rng.normal(strength, 1.5))),
                        "minutes": 90 if strength > 2.0 else 20,
                    })
    return pd.DataFrame(rows)


def _summary(arch):
    rng = np.random.default_rng(1)
    rows = []
    for (season, code), g in arch.groupby(["season", "code"]):
        rows.append({"season": season, "code": code,
                     "web_name": "P%d" % code,
                     # a price spread wide enough that a bench cap is satisfiable
                     "start_price": float(rng.choice([4.0, 4.5, 5.0, 5.5, 6.5, 8.0]))})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def data():
    arch = _archive()
    return arch, _summary(arch)


def test_early_bench_boost_returns_expected_columns(data):
    arch, summ = data
    out = early_bench_boost(arch, summ)
    assert not out.empty
    for col in ("season", "dilution_per_gw", "bb_gain", "break_even_gws"):
        assert col in out.columns


def test_early_bench_boost_break_even_present_when_there_is_a_tradeoff(data):
    """Exact arithmetic is pinned in test_season_opener on controlled numbers ·
    here the reported columns are rounded, so only the invariant is testable."""
    arch, summ = data
    out = early_bench_boost(arch, summ)
    for _, r in out.iterrows():
        if r["dilution_per_gw"] > 0:
            assert r["break_even_gws"] is not None
            assert r["break_even_gws"] > 0
        else:
            # no cost to carrying the Boost squad · no break-even to report
            assert r["break_even_gws"] is None


def test_early_bench_boost_boost_bench_outscores_cheap_bench(data):
    """The whole premise: an all-playing bench must beat fodder, or the chip is moot."""
    arch, summ = data
    out = early_bench_boost(arch, summ)
    assert (out["bench_boost"] >= out["bench_cheap"]).all()


def test_wildcard_decay_never_scores_an_overlapping_build(data):
    """The whole method rests on build windows closing before the scored window."""
    arch, summ = data
    out = wildcard_decay(arch, summ, eval_starts=[13], ages=[0, 3, 6], horizon=5)
    assert not out.empty
    # freshest legal build for eval starting 13 with horizon 5 closes at GW12
    assert out["build_gw"].max() <= 12
    for _, r in out.iterrows():
        assert r["build_gw"] + 5 < 13


def test_wildcard_decay_age_matches_build_position(data):
    arch, summ = data
    out = wildcard_decay(arch, summ, eval_starts=[13], ages=[0, 3], horizon=5)
    for _, r in out.iterrows():
        assert r["build_gw"] == 12 - 5 - r["age_gws"]


def test_wildcard_decay_baseline_is_per_evaluation_window(data):
    """Comparing across windows would confound staleness with scoring rate."""
    arch, summ = data
    out = wildcard_decay(arch, summ, eval_starts=[13, 19], ages=[0, 3], horizon=5)
    for ev, g in out.groupby("eval_start"):
        assert g["loss_vs_fresh"].min() == 0.0     # each window has its own zero


def test_opening_fixture_signal_returns_two_correlations(data):
    arch, _ = data
    out = opening_fixture_signal(_archive(seasons=("2023-24", "2024-25")))
    assert out["predict_r"] is not None
    assert out["persist_r"] is not None
    assert -1.0 <= out["predict_r"] <= 1.0
    assert -1.0 <= out["persist_r"] <= 1.0


def test_opening_fixture_signal_handles_empty_archive():
    out = opening_fixture_signal(pd.DataFrame(
        columns=["season", "team_id", "gw", "total_points", "opponent_team"]))
    assert out["predict_r"] is None
