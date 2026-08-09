"""A draft spec needs a stable cache key, so an unrelated click stops re-solving.

Measured on the real page: clicking a player's shirt cost 41 SECONDS, all of it
in `solve_opening`. The click does not change any dial, so the MILP was being
re-run to produce the fifteen it had just produced. Under no CPU contention the
same solve takes 161ms; the 41 seconds is that solve competing with the eight
background ceiling MILPs the page kicks off on load.

Caching needs a key that is stable across reruns and blind to dict ordering,
because Streamlit rebuilds the spec dict from widgets on every run.
"""
from analytics.squad_rules import spec_key


BASE = {"strategy": "value", "locks": ["Haaland"], "vetoes": ["Shaw"],
        "budget": 100.0, "risk": 0.3, "bench_boost_gw": 1, "wildcard_gw": 4,
        "cover": [[1, "def", 1]], "squad": None}


def test_the_same_spec_gives_the_same_key():
    assert spec_key(BASE) == spec_key(dict(BASE))


def test_key_ignores_dict_ordering():
    # Streamlit rebuilds this dict from widgets every run · insertion order is
    # not a promise, and keying on it would miss the cache every single time.
    flipped = {k: BASE[k] for k in reversed(list(BASE))}
    assert spec_key(flipped) == spec_key(BASE)


def test_a_changed_dial_changes_the_key():
    assert spec_key(dict(BASE, risk=0.6)) != spec_key(BASE)


def test_a_changed_veto_changes_the_key():
    assert spec_key(dict(BASE, vetoes=["Shaw", "Rice"])) != spec_key(BASE)


def test_veto_order_does_not_change_the_key():
    # The multiselect returns these in click order, which is not meaningful.
    assert spec_key(dict(BASE, vetoes=["Rice", "Shaw"])) == \
           spec_key(dict(BASE, vetoes=["Shaw", "Rice"]))


def test_the_saved_fifteen_is_part_of_the_key():
    assert spec_key(dict(BASE, squad=[1, 2, 3])) != spec_key(BASE)


def test_it_survives_a_value_that_is_not_json_native():
    import numpy as np
    assert isinstance(spec_key(dict(BASE, risk=np.float64(0.3))), str)
