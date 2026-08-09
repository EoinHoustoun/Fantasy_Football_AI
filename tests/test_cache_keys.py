"""A cached function whose key is wrong serves yesterday's answer forever.

This is a STATIC check over the whole app, not a behaviour test, because the
failure is invisible at runtime: nothing errors, nothing logs, the page simply
keeps showing a number that stopped being true. It cost a day twice · once when
a hand-set Foden override would not appear, and once when the pitch showed the
Spurs Fernandes at 4.8 in GW1 against a correct 2.99.

Two rules, both learned the hard way:

1. **Streamlit does not hash an argument whose name starts with `_`.** Naming a
   content stamp `_stamp` makes it decorative. `_projector` had all five
   parameters underscored, so its key was empty and one projector was built per
   process and reused for the life of it.

2. **A cached function with no arguments has a constant key.** `build_board()`
   cached for six hours however recently a snapshot had been refreshed, and
   every other Draft cache keys off the board.

The allowlists below are the deliberate exceptions. Adding to one is a claim
you have to be able to defend: for rule 1, that a hashed `stamp` beside it fully
describes the unhashed frame; for rule 2, that the function reads only sources
which cannot change inside a session.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Large frames that an adjacent HASHED stamp argument already describes.
# The key is "<file stem>::<function>::<param>".
UNHASHED_OK = {
    "18_draft_2026_27::_projector::_board",
    "18_draft_2026_27::_projector::_fix",
    "18_draft_2026_27::_window_board::_base",
    "18_draft_2026_27::_lane_html::_df",
    "18_draft_2026_27::_routes::_board",
    "00_my_team::_xp_horizon_cached::_players",
    "00_my_team::_xp_horizon_cached::_bootstrap",
    "00_my_team::_scored_universe::_players",
}

# Functions that read only sources which cannot change within a session · a
# live API behind its own TTL, or the immutable historical archive.
NO_ARGS_OK = {
    "app::load_bootstrap", "app::load_fixtures",
    # Captain Picker, Buy/Sell and Injuries used to sit here with their own
    # per-page copies of the universe build. They now call the shared, stamped
    # loader in `data/universe.py`, so they need no exception.
    "09_wildcard::load_data",
    "10_ownership_trend::load_gw_history", "10_ownership_trend::load_universe",
    "11_gw_history::load_bootstrap", "15_mini_league::fetch_global_avg",
    "16_perfect_season::_load_all", "16_perfect_season::_replay_lookup",
    "17_value_lab::_summary", "home::_pl_logo_data_url",
    "18_draft_2026_27::_club_fixtures", "18_draft_2026_27::_defcon_per90",
    "18_draft_2026_27::_last_season_stats",
    # A constant key is the POINT here · this returns the process-wide store the
    # weekly-ceiling solver writes into from a background thread. A page script
    # re-executes top to bottom on every rerun, so a plain module-level dict was
    # recreated each time and the thread wrote into an object nobody would read
    # again. It holds no derived data, only solver results already keyed by
    # (gameweek, budget, board stamp), so it cannot go stale the way a cached
    # projection can.
    "18_draft_2026_27::_ceiling_store",
}


def _cached_functions():
    """(file stem, FunctionDef) for every @st.cache_data / @st.cache_resource."""
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {".venv", "tests"}:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any("cache_data" in ast.unparse(d) or "cache_resource" in ast.unparse(d)
                   for d in node.decorator_list):
                yield path.stem, node


def _args(node):
    return [a.arg for a in node.args.args + node.args.kwonlyargs]


def test_no_accidental_unhashed_cache_arguments():
    """Rule 1 · an underscore means "do not hash me", so it must be deliberate."""
    offenders = []
    for stem, node in _cached_functions():
        for arg in _args(node):
            if arg.startswith("_") and "%s::%s::%s" % (stem, node.name, arg) not in UNHASHED_OK:
                offenders.append("%s.%s(%s) is not hashed" % (stem, node.name, arg))
    assert not offenders, (
        "Streamlit skips hashing underscore-prefixed arguments, so each of these "
        "is silently absent from its cache key:\n  " + "\n  ".join(offenders))


def test_every_unhashed_frame_has_a_hashed_stamp_beside_it():
    """An allowlisted frame is only safe because something else describes it."""
    for stem, node in _cached_functions():
        args = _args(node)
        if not any(a.startswith("_") for a in args):
            continue
        hashed = [a for a in args if not a.startswith("_")]
        assert hashed, (
            "%s.%s takes only unhashed arguments, so its cache key is empty and "
            "it will be computed once per process and never again." % (stem, node.name))


def test_no_new_cached_function_without_a_key():
    """Rule 2 · no arguments means one constant key for the whole TTL."""
    offenders = [
        "%s.%s()" % (stem, node.name)
        for stem, node in _cached_functions()
        if not _args(node) and "%s::%s" % (stem, node.name) not in NO_ARGS_OK
    ]
    assert not offenders, (
        "These cache on a constant key, so nothing on disk can invalidate them:\n  "
        + "\n  ".join(offenders))


@pytest.mark.parametrize("name", sorted(UNHASHED_OK | NO_ARGS_OK))
def test_allowlists_have_no_dead_entries(name):
    """A stale allowlist entry hides the next real offender behind a name that
    no longer exists · so the exceptions have to be kept honest too."""
    stem, func = name.split("::")[0], name.split("::")[1]
    assert any(s == stem and n.name == func for s, n in _cached_functions()), (
        "%s is allowlisted but no longer exists · remove it" % name)
