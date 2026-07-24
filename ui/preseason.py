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
