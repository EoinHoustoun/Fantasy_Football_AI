"""The player universe, built once and shared by every page.

Six view files each carried a byte-identical `load_universe()` behind its own
`@st.cache_data`, with TTLs of 900, 1800, 3600 and 21600 seconds. Three
consequences, all bad:

  - the same 2.8-second build ran once per page you visited
  - six copies of a large frame sat in the cache at once
  - two pages could show different numbers at the same moment, because their
    TTLs expired at different times

One loader, keyed on the content stamp rather than a clock. `freshness.
inputs_stamp()` already changes when a snapshot or override moves, so a refresh
invalidates this properly instead of waiting out a timer.

Underneath sits `data.disk_cache`, so the build survives a restart and a stamp
change · measured at 2.8 seconds to build against about 15ms to read.
"""
import logging
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)


def _build_universe(stamp: str, simulate_gw: Optional[int]) -> pd.DataFrame:
    """The real work. Split out so tests can replace it without touching cache."""
    from data.fetchers.fpl_api import fetch_bootstrap
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    del stamp                                   # key only, see module docstring
    return build_player_universe(
        bootstrap=fetch_bootstrap(),
        understat_df=fetch_understat_players(),
        simulate_gw=simulate_gw)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_universe(stamp: str = "", simulate_gw: Optional[int] = None) -> pd.DataFrame:
    """Every player with stats, prices, fixtures and the nailed-ness signals.

    `simulate_gw` is part of the key on purpose. The off-season GW39 sandbox
    clones GW1 fixtures onto a synthetic gameweek, and serving the plain build
    for it would leave every fixture tool pointing at nothing.
    """
    from data import disk_cache
    key = "%s|sim=%s" % (stamp or "nostamp", simulate_gw)
    payload = disk_cache.cached(
        "universe", key, lambda: {"players": _build_universe(stamp, simulate_gw)})
    disk_cache.prune("universe")
    return payload["players"]


def load_universe_and_bootstrap(
        stamp: str = "", simulate_gw: Optional[int] = None) -> Tuple[pd.DataFrame, dict]:
    """The pair most pages actually want. Bootstrap is a cheap disk read (~25ms)
    and is already cached at the fetcher, so it is not worth persisting here."""
    from data.fetchers.fpl_api import fetch_bootstrap
    return load_universe(stamp, simulate_gw), fetch_bootstrap()
