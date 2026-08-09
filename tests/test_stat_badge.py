"""The stat badge · a number, what it means, and how good it is.

Pure HTML builder so it can be tested without a browser, same shape as
`ff_table.build_html`. The percentile bar is the point: 6.7 DEFCON per 90 means
nothing on its own, and "better than 84% of defenders" means everything.
"""
import re

from components.stat_badge import badge_html, badges_row


def test_it_shows_the_label_and_the_value():
    h = badge_html("DEFCON / 90", "6.7")
    assert "DEFCON / 90" in h and "6.7" in h


def test_a_percentile_renders_a_bar_and_reads_in_words():
    h = badge_html("DEFCON / 90", "6.7", percentile=84)
    assert "84" in h
    assert "width:84%" in h.replace(" ", "")


def test_no_percentile_means_no_bar():
    h = badge_html("Points", "184")
    assert "ff-badge-bar" not in h


def test_a_sub_line_is_shown_when_given():
    assert "2025/26" in badge_html("Points", "184", sub="2025/26")


def test_the_html_is_one_line():
    # st.markdown stops passing raw HTML through when a line is whitespace-only,
    # and then renders the rest as literal text. Bit this repo before.
    h = badge_html("Points", "184", sub="2025/26", percentile=50)
    assert "\n" not in h


def test_a_row_renders_every_badge():
    h = badges_row([{"label": "A", "value": "1"}, {"label": "B", "value": "2"}])
    assert "A" in h and "B" in h and "\n" not in h


def test_an_empty_row_is_empty_not_broken():
    assert badges_row([]) == ""


def test_a_missing_value_shows_a_dash_rather_than_None():
    assert "None" not in badge_html("Points", None)


def _bar_pct(html):
    """The bar's own width · `min-width` on the card would match a naive split."""
    m = re.search(r"height:3px;width:(\d+)%", html.replace(" ", ""))
    return int(m.group(1)) if m else None


def test_percentile_is_clamped_to_the_bar():
    for p in (-20, 0, 130):
        assert 0 <= _bar_pct(badge_html("x", "1", percentile=p)) <= 100


def test_the_bar_matches_the_percentile():
    assert _bar_pct(badge_html("x", "1", percentile=84)) == 84


# ── a probability is not a rank ──────────────────────────────────────────────
# A 39% clean-sheet chance rendered as "Top 61%", which is meaningless: it is
# not a position in a distribution, it is the chance of the thing happening.
# Both draw a bar, so `bar` exists to draw one WITHOUT the rank wording.

def test_a_plain_bar_draws_without_rank_wording():
    h = badge_html("Clean sheet", "39%", bar=39)
    assert "height:3px;width:39%" in h.replace(" ", "")
    assert "Top" not in h


def test_a_percentile_still_says_top():
    assert "Top" in badge_html("Points", "143", percentile=91)


def test_bar_and_percentile_are_not_both_needed():
    # If both arrive, the explicit rank wins · it is the more specific claim.
    h = badge_html("x", "1", percentile=80, bar=20)
    assert "height:3px;width:80%" in h.replace(" ", "")
