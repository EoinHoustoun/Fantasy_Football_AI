"""Weeks from different models must be put on one scale before they compete.

Measured on the real board: GW1-6 come entirely from the Hub's match forecasts
and total 56-59 for a squad, while GW7-19 come entirely from the fixture-shape
fallback and total 68-75. A 23% step at exactly the source boundary.

Left alone, that decides every chip: anything wanting a low week lands in GW1-6
and anything wanting a high week lands in GW7-19, regardless of the fixtures.
This is the same trap as ranking players on a raw model gap when one model runs
hot · the offset gets read as signal.
"""
import pandas as pd

from analytics.chip_timing import level_by_source


def _rows(match_lvl, shape_lvl):
    """Six match weeks then six shape weeks, flat within each region."""
    return ([{"gw": g, "squad_pts": match_lvl, "source": "match"} for g in range(1, 7)]
            + [{"gw": g, "squad_pts": shape_lvl, "source": "shape"} for g in range(7, 13)])


def test_a_step_between_the_two_regions_is_removed():
    out = level_by_source(_rows(56.0, 72.0), key="squad_pts")
    vals = [r["squad_pts"] for r in out]
    assert max(vals) - min(vals) < 0.01


def test_shape_within_a_region_survives():
    rows = _rows(56.0, 72.0)
    rows[2]["squad_pts"] = 70.0          # one genuinely good match week
    out = {r["gw"]: r["squad_pts"] for r in level_by_source(rows, key="squad_pts")}
    assert out[3] > out[1], "a real difference inside a region was flattened"


def test_it_does_nothing_when_there_is_only_one_source():
    rows = [{"gw": g, "squad_pts": 50.0 + g, "source": "match"} for g in range(1, 7)]
    out = level_by_source(rows, key="squad_pts")
    assert [r["squad_pts"] for r in out] == [50.0 + g for g in range(1, 7)]


def test_the_match_region_is_the_anchor():
    """Match cells are a real forecast; the shape is the approximation, so the
    shape moves onto the forecast, not the other way round."""
    out = {r["gw"]: r["squad_pts"] for r in level_by_source(_rows(56.0, 72.0), key="squad_pts")}
    assert abs(out[1] - 56.0) < 0.01


def test_a_zero_mean_region_is_left_alone_rather_than_dividing_by_zero():
    rows = ([{"gw": g, "squad_pts": 0.0, "source": "match"} for g in range(1, 7)]
            + [{"gw": g, "squad_pts": 5.0, "source": "shape"} for g in range(7, 13)])
    out = level_by_source(rows, key="squad_pts")
    assert all(r["squad_pts"] == r["squad_pts"] for r in out)   # no NaN
