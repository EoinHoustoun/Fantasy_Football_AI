"""Chart colour helpers must accept theme tokens, not just hex literals.

The design system says inline colours are `var(--ff-mint)` tokens. Pages pass
those into chart helpers that interpolate hex, and `diverging_colors` crashed
the Transfers page with `invalid literal for int() with base 16: 'ar'`.
"""
from ui import charts


def test_diverging_accepts_css_variable_tokens():
    out = charts.diverging_colors([1.5, 2.75, 4.0], "var(--ff-mint)", "#FFD60A",
                                  "var(--ff-red)", midpoint=2.75)
    assert len(out) == 3 and all(c.startswith("rgb(") for c in out)
    assert out[1] == "rgb(255,214,10)"          # the midpoint is the mid colour


def test_ramp_accepts_tokens_and_short_hex():
    out = charts.color_ramp([0, 1], "var(--ff-cyan)", "#fff")
    assert out[1] == "rgb(255,255,255)"
