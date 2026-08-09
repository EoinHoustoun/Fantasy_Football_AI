"""Charts must survive light mode.

`render()` calls `_retheme` whenever the light palette is active, and `_retheme`
referenced `_LIGHT_SWAP`, a name defined nowhere in the codebase. So every chart
in the app raised NameError in light mode · silently, because Streamlit catches
it into a red box at the bottom of the page and the rest still renders.

Caught while rebuilding the Chip Planner, which is the first page I opened in
light mode.
"""
import pytest

from ui import charts


def test_retheme_is_callable_on_a_realistic_option():
    opt = {"series": [{"type": "bar", "data": [1, 2],
                       "itemStyle": {"color": "#00FF87"}}],
           "xAxis": {"axisLabel": {"color": "#eef1f5"}},
           "tooltip": {"formatter": "GW{b}: {c}"}}
    out = charts._retheme(opt)
    assert isinstance(out, dict)
    assert out["series"][0]["type"] == "bar"


def test_it_leaves_structure_and_numbers_alone():
    opt = {"a": [1, 2.5, None], "b": {"c": True}}
    assert charts._retheme(opt) == {"a": [1, 2.5, None], "b": {"c": True}}


def test_a_dark_literal_becomes_something_renderable():
    """The point of the swap · a near-white label on a white page is invisible."""
    out = charts._retheme({"color": "#eef1f5"})
    assert isinstance(out["color"], str) and out["color"].startswith("#")


def test_an_unknown_colour_is_passed_through_untouched():
    assert charts._retheme({"color": "#123456"})["color"] == "#123456"


@pytest.mark.parametrize("node", ["plain", 5, 5.5, None, True, [], {}])
def test_it_handles_every_node_type(node):
    charts._retheme(node)
