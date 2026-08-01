"""Template risk · the asymmetry of skipping a highly owned player.

All figures here are INVENTED.
"""
import pandas as pd

from analytics.template import (BLANK_POINTS, HAUL_POINTS, TEMPLATE_OWNERSHIP,
                                effective_ownership, punt_meter,
                                skipped_template, verdict_line)


def _board():
    return pd.DataFrame({
        "code": [1, 2, 3, 4, 5],
        "web_name": ["Big", "Mid", "Small", "Tiny", "Owned"],
        "team_short": ["AAA", "BBB", "CCC", "DDD", "EEE"],
        "ownership": [75.0, 40.0, 16.0, 3.0, 50.0],
    })


# ── who counts as template ───────────────────────────────────────────────────

def test_only_unowned_template_players_count():
    got = skipped_template(_board(), squad_codes=[5])
    assert set(got["web_name"]) == {"Big", "Mid", "Small"}   # Tiny is below the bar


def test_owning_everyone_leaves_no_risk():
    assert skipped_template(_board(), squad_codes=[1, 2, 3, 4, 5]).empty


def test_sorted_worst_first():
    got = skipped_template(_board(), squad_codes=[])
    assert list(got["web_name"])[:2] == ["Big", "Owned"]


def test_threshold_is_respected():
    got = skipped_template(_board(), squad_codes=[], threshold=45.0)
    assert set(got["web_name"]) == {"Big", "Owned"}


def test_missing_ownership_column_returns_empty_not_an_error():
    assert skipped_template(pd.DataFrame({"code": [1]}), [1]).empty
    assert skipped_template(None, [1]).empty


# ── the asymmetry ────────────────────────────────────────────────────────────

def test_downside_is_larger_than_upside():
    """The whole point: a template skip pays small and often, loses big and
    rarely. If these ever come out equal the model has lost its meaning."""
    m = punt_meter(_board(), squad_codes=[])
    assert m["downside"] > m["upside"]


def test_downside_scales_with_ownership():
    m = punt_meter(_board(), squad_codes=[])
    # 75% owned, hauling 12, costs 9 rank points
    assert any(abs(w["cost"] - 9.0) < 0.01 for w in m["worst"])


def test_owning_the_template_zeroes_the_meter():
    m = punt_meter(_board(), squad_codes=[1, 2, 3, 4, 5])
    assert m["n"] == 0
    assert m["downside"] == 0.0
    assert "no edge either" in verdict_line(m)


def test_levels_move_with_exposure():
    template = punt_meter(_board(), squad_codes=[1, 2, 5])   # only Small left out
    maverick = punt_meter(_board(), squad_codes=[])
    assert template["level"] == "template"
    assert maverick["level"] == "maverick"


def test_verdict_mentions_both_directions():
    line = verdict_line(punt_meter(_board(), squad_codes=[]))
    assert "haul" in line and "blank" in line


# ── effective ownership ──────────────────────────────────────────────────────

def test_captaincy_raises_effective_ownership():
    b = _board()
    eo = effective_ownership(b, captain_code=1)
    assert eo.iloc[0] > b["ownership"].iloc[0]
    assert eo.iloc[1] == b["ownership"].iloc[1]      # nobody else moves


def test_no_captain_leaves_ownership_alone():
    b = _board()
    assert effective_ownership(b).tolist() == b["ownership"].tolist()


def test_constants_keep_the_asymmetry():
    assert HAUL_POINTS > BLANK_POINTS
    assert 0 < TEMPLATE_OWNERSHIP < 100
