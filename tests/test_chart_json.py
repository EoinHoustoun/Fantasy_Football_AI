"""Charts must never emit NaN · the browser rejects it and kills the card.

Python's json.dumps writes bare `NaN` without complaining, so this class of bug
cannot be caught by serialising in Python. The browser's JSON.parse refuses it
with "Unexpected token 'N'" and takes the whole chart, and the card around it,
down with it. One NaN from an empty median is enough.
"""
import json
import math

import numpy as np

from ui.charts import _json_safe, radar_compare_option


def test_python_would_happily_emit_nan():
    """The reason a guard is needed at all · this does NOT raise."""
    assert "NaN" in json.dumps({"max": float("nan")})


def test_nan_becomes_null():
    assert _json_safe({"max": float("nan")}) == {"max": None}


def test_infinity_becomes_null():
    assert _json_safe([float("inf"), float("-inf")]) == [None, None]


def test_finite_numbers_survive_untouched():
    assert _json_safe({"a": 1.5, "b": 0.0, "c": -3.25}) == {"a": 1.5, "b": 0.0, "c": -3.25}


def test_numpy_nan_is_caught_too():
    """pandas hands back numpy scalars, which are not float instances."""
    out = _json_safe({"v": np.float64("nan"), "n": np.int64(5)})
    assert out["v"] is None
    assert out["n"] == 5


def test_nested_structures_are_walked():
    opt = {"radar": {"indicator": [{"name": "x", "max": float("nan")}]},
           "series": [{"data": [1.0, float("nan")]}]}
    txt = json.dumps(_json_safe(opt))
    assert "NaN" not in txt


def test_strings_and_none_pass_through():
    assert _json_safe({"a": "text", "b": None, "c": True}) == {"a": "text", "b": None, "c": True}


def test_a_real_radar_option_with_a_nan_median_serialises():
    """The exact shape that crashed: an empty price band makes the median NaN,
    which lands in the radar's `max`."""
    opt = radar_compare_option(
        [{"name": "Season pts", "max": float("nan")}, {"name": "Per £m", "max": 12.0}],
        [("Typical", [float("nan"), 3.0], "#7a8394", 0.10),
         ("Player", [140.0, 11.0], "#00FF87", 0.26)])
    txt = json.dumps(_json_safe(opt))
    assert "NaN" not in txt
    assert json.loads(txt)["radar"]["indicator"][0]["max"] is None
