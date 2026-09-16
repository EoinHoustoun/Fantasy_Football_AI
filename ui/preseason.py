"""Preseason guards.

Between the new season's launch (prices set, GW1 deadline announced) and the
first kickoff, there are no manager squads and no gameweeks played yet. Tools
that need a live squad or this-season gameweek data have nothing to work with,
so they show an honest notice instead of a fake number or a traceback.
"""
from typing import Dict

import streamlit as st


def is_preseason() -> bool:
    """True when the live season is set up but no gameweek has been played yet.

    Reads the season phase the router stores in session_state on every run.
    """
    phase: Dict = st.session_state.get("season_phase") or {}
    return phase.get("phase") == "preseason"


def stop_if_preseason(need: str = "This tool") -> None:
    """In preseason, render an honest empty-state and halt the page.

    `need` names what is unavailable, e.g. "GW predictions" or "Your squad".
    No-op in every other phase, so in-season behaviour is untouched.
    """
    if not is_preseason():
        return
    st.info(
        f"🌱 {need} returns once the 2026-27 season kicks off · there are no "
        "played gameweeks yet. Prices are already set, so plan your opener with "
        "the 26/27 Draft, Scouting and Value Lab in the sidebar."
    )
    st.stop()


def finished_gameweeks() -> int:
    """How many gameweeks are final (finished AND data_checked) in the live season."""
    bs: Dict = st.session_state.get("bootstrap") or {}
    return sum(1 for e in bs.get("events", [])
               if e.get("finished") and e.get("data_checked"))


def stop_if_too_few_gameweeks(need: str, min_gws: int) -> None:
    """Early in the season, halt tools that train on this-season gameweek data.

    The points model needs a few finished gameweeks per player before it has a
    single training row. Until then, say so rather than fit on nothing.
    """
    if is_preseason():
        stop_if_preseason(need)
    played = finished_gameweeks()
    if played >= min_gws:
        return
    st.info(
        f"⏳ {need} needs {min_gws} finished gameweeks of 2026-27 data to train "
        f"on · {played} so far. Until then use the consensus projections on the "
        "26/27 Draft, Captain and Transfers pages."
    )
    st.stop()
