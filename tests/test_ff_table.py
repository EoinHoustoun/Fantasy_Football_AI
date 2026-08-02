"""The shared table's markup · `build_html` is pure, so it can be pinned down.

All figures here are INVENTED.
"""
from components.ff_table import build_html, col_action, col_num, col_player

_ROW = {"code": 1, "web_name": "A", "team_short": "X", "pts": 5.0}


# ── the action column is pinned to the right ─────────────────────────────────

def test_the_action_column_is_pinned():
    """It is the only reason anyone opened the table. At a laptop width it used
    to scroll off the right while the face and the name stayed put."""
    html = build_html([_ROW], [col_player("web_name"), col_num("pts", "Pts"),
                               col_action("code", "swap", "Sign")])
    assert "pinR" in html


def test_the_pin_covers_the_header_and_the_body():
    html = build_html([_ROW], [col_player("web_name"), col_num("pts", "Pts"),
                               col_action("code", "swap", "Sign")])
    assert html.count("pinR") == 2


def test_a_table_with_no_action_column_pins_nothing_right():
    html = build_html([_ROW], [col_player("web_name"), col_num("pts", "Pts")])
    assert "pinR" not in html


def test_identity_stays_pinned_left():
    """The right-hand pin must not have displaced the left-hand one."""
    html = build_html([_ROW], [col_player("web_name"), col_num("pts", "Pts"),
                               col_action("code", "swap", "Sign")])
    assert "pin1" in html


def test_an_empty_table_still_renders():
    html = build_html([], [col_player("web_name"),
                           col_action("code", "swap", "Sign")])
    assert "pinR" not in html and "Nothing to show" in html
