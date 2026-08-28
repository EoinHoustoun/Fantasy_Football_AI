"""The per-gameweek projector and fixture runs, shared by the Draft and My Team.

Moved out of views/18_draft_2026_27.py so the two pages build ONE projector
with ONE cache-key discipline. See the docstrings that travelled with each
function for why the keys look the way they do.
"""
import os
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

PROJ_VERSION = 3


def module_stamp(*mods) -> str:
    """mtime of each module's source · a cache key that notices a code edit."""
    bits = []
    for m in mods:
        try:
            bits.append("%s:%s" % (m.__name__, os.path.getmtime(m.__file__)))
        except Exception:
            bits.append(getattr(m, "__name__", "?"))
    return "|".join(bits)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def club_fixtures() -> Dict:
    """(team_id, gw) -> [(opponent short, is_home, fdr), ...] for 26/27.

    Difficulty comes from Fantasy Football Scout's model ratings where a ticker
    snapshot exists, because theirs vary by venue and opponent form while FPL's
    are fixed per club.
    """
    from components.fixture_ticker import load_scout_ticker
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    bs = fetch_bootstrap()
    short = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    fx = get_fixtures_df(fetch_fixtures(), bs)
    scout_fdr = load_scout_ticker() or {}
    out: Dict = {}
    for _, r in fx.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        gw = int(r["gameweek"])
        h, a = int(r["home_team_id"]), int(r["away_team_id"])
        hs, as_ = short.get(h, "?"), short.get(a, "?")
        out.setdefault((h, gw), []).append(
            (as_, True, float(scout_fdr.get((hs, gw), r["home_fdr"]))))
        out.setdefault((a, gw), []).append(
            (hs, False, float(scout_fdr.get((as_, gw), r["away_fdr"]))))
    return out


def fixtures_for(team_id: int, gw: int, n: int = 3, fix: Optional[Dict] = None) -> List[Dict]:
    fix = club_fixtures() if fix is None else fix
    out = []
    for g in range(gw, gw + n):
        fx = fix.get((int(team_id), g), [])
        if not fx:
            out.append({"opp": "BLANK", "blank": True, "fdr": 3, "home": True})
            continue
        for opp, home, fdr in fx:
            out.append({"opp": opp, "home": home, "fdr": fdr})
    return out[:n]


# `cache_resource` holds the LIVE object across code edits, so an edited class
# keeps serving the old INSTANCE. The manual version int below was meant to
# guard that and it failed exactly the way manual steps do: `gw_points` (a
# hand-set score for one gameweek) was added to GwProjection and the int was not
# bumped, so the running app served a projector with no such feature and Foden's
# GW2 stayed on the model's 1.2 instead of the 4.0 in the overrides file.
#
# So the key now carries the module's own mtime. Edit the class, get a new
# object, with nothing to remember.


@st.cache_resource(show_spinner=False)
def projector(_board: pd.DataFrame, _fix: Dict, stamp: str, version: int,
              code_stamp: str):
    """The per-gameweek projector.

    **A leading underscore tells Streamlit not to hash that argument.** Every
    parameter here used to carry one, so the cache key was EMPTY: one projector
    was built per process and reused for the life of it, whatever changed
    underneath. That is how a refreshed Scout snapshot could sit on disk while
    the pitch kept showing the numbers it was started with.

    `_board` and `_fix` keep their underscores deliberately · they are large and
    are fully described by `stamp`. The other three must not have one, because
    they ARE the key.
    """
    from analytics import gw_projection
    return gw_projection.build(_board, _fix)


def projection(inputs_stamp: str) -> Dict:
    """Everything My Team needs from the shared board + projector, one call.

    Mirrors what the Draft page does inline: build the board, pick the points
    column, stamp it, build the fixture map and the projector off that stamp.
    Returns `"proj": None` when the board itself failed to load, so a caller
    only has to check one thing.
    """
    from analytics import freshness
    from analytics import gw_projection as gwp
    from ui.value_board import build_board
    board, scout, price_bt, validation = build_board(inputs_stamp)
    if board is None:
        return {"board": None, "proj": None, "fix": {}, "pts_col": None,
                "board_stamp": "", "window": [], "scout": scout,
                "price_bt": price_bt, "validation": validation}
    pts_col = "consensus_points" if "consensus_points" in board.columns else "projected_points"
    fix = club_fixtures()
    board_stamp = freshness.board_stamp(board, pts_col)
    proj = projector(board, fix, board_stamp, PROJ_VERSION, module_stamp(gwp))
    return {"board": board, "scout": scout, "price_bt": price_bt, "validation": validation,
            "pts_col": pts_col, "fix": fix, "proj": proj, "board_stamp": board_stamp,
            "window": proj.window}
