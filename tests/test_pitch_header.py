"""The squad header above the pitch · total, bench and squad score.

All figures here are INVENTED.
"""
from components.pitch_view import _formation_bar


def test_the_squad_score_sits_beside_the_total():
    h = _formation_bar("4-5-1", "2026-27 · GW1", 79.7, "SQUAD GW1", 15.8,
                       score_pct=117.2, score_colour="#00FF87")
    assert "79.7" in h and "bench 15.8" in h and "117%" in h


def test_no_score_means_no_chip():
    """A week with no ceiling must not render an empty percentage."""
    h = _formation_bar("4-4-2", "", 60.0, "XI GW3", 12.0)
    assert "%" not in h.split("Formation")[0]


def test_a_boosted_week_can_exceed_one_hundred():
    """The ceiling is eleven players; a Boost plays fifteen."""
    h = _formation_bar("3-4-3", "", 96.0, "SQUAD GW2", 18.0, score_pct=134.0)
    assert "134%" in h


def test_the_score_is_rounded_to_whole_percent():
    h = _formation_bar("4-4-2", "", 60.0, "XI GW3", 12.0, score_pct=93.47)
    assert "93%" in h and "93.4" not in h


def test_the_header_still_renders_without_a_total():
    h = _formation_bar("4-4-2", "Draft", None)
    assert "Formation" in h and "4-4-2" in h
