"""
How old are the hand-refreshed model inputs, and has anything changed?

Two jobs that want the same facts:

1. **Cache correctness.** Several caches keyed on `len(board)`. A snapshot
   refresh or an overrides edit almost never changes the row COUNT, so a stale
   projection was served for the full six-hour TTL after the very edit that was
   meant to change it. `board_stamp` keys on content instead.

2. **Honesty in the UI.** The Scout and Hub snapshots are manual one-shot files.
   A six-week-old Hub export silently drives the whole per-gameweek view, and
   nothing on screen says so. `sources` returns each file's age so the page can.
"""

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# A snapshot older than this is stale enough that the per-gameweek view is
# probably describing a squad that has since changed. Gameweeks are a week long,
# so a fortnight is two gameweeks of drift.
STALE_AFTER_DAYS = 14
AGEING_AFTER_DAYS = 7


def _mtime(path) -> Optional[float]:
    try:
        return os.path.getmtime(str(path))
    except OSError:
        return None


def _paths() -> Dict[str, object]:
    """The hand-refreshed inputs, resolved lazily so an import cannot fail."""
    out = {}
    try:
        # Named for what it still SUPPLIES, not for its provider. Since Scout's
        # GW1-38 table took over the points, this file only backfills minutes,
        # goals and clean sheets · so a chip reading "Scout 5d ago" was telling
        # Eoin his projections were five days old when they were an hour old.
        from analytics.scout_projections import SNAPSHOT_PATH as SCOUT
        out["Scout stats"] = SCOUT
    except Exception:
        pass
    try:
        from data.fetchers.ffhub import SNAPSHOT_PATH as FFH
        out["Hub"] = FFH
    except Exception:
        pass
    try:
        # Scout's per-gameweek table · the heaviest voice in the per-gameweek
        # blend. Left out of this list it would refresh on disk and change
        # nothing on screen, because the projector is cached on this stamp.
        from analytics.scout_rmt import SNAPSHOT_PATH as RMT
        out["Scout GW"] = RMT
    except Exception:
        pass
    try:
        # Scout's GW1-38 table · the season POINTS every consensus blend starts
        # from. Same trap as "Scout GW" below it: absent from this list the file
        # refreshes on disk and nothing on screen moves, because every cache
        # downstream is keyed on this stamp.
        from analytics.scout_rmt import SEASON_PATH as RMTS
        out["Scout season"] = RMTS
    except Exception:
        pass
    try:
        from analytics.projection_overrides import overrides_path
        out["Overrides"] = overrides_path()
    except Exception:
        pass
    try:
        # NOT hand-refreshed, and watched anyway. The bootstrap carries live
        # prices, availability status and team news, and both the board and the
        # universe are built from it · so without this a refresh changed nothing
        # on screen. That was survivable while every cache died with the
        # process. `data.disk_cache` now persists a build across restarts, so a
        # key blind to the bootstrap could serve yesterday's injury flags for as
        # long as the snapshots happened not to move.
        from config import CACHE_DIR
        out["Bootstrap"] = Path(CACHE_DIR) / "fpl_bootstrap.json"
    except Exception:
        pass
    return out


def inputs_stamp() -> str:
    """A digest of the hand-refreshed FILES only · no board required.

    `board_stamp` cannot key the function that BUILDS the board, so the board
    was cached on nothing at all and served a six-hour-old view of files that
    had changed minutes earlier. This is the key for that function.
    """
    h = hashlib.blake2b(digest_size=8)
    for name, path in sorted(_paths().items()):
        h.update(name.encode())
        h.update(repr(_mtime(path)).encode())
    return h.hexdigest()


def board_stamp(board: Optional[pd.DataFrame] = None,
                points_col: str = "consensus_points") -> str:
    """A short content stamp for cache keys.

    Combines every input mtime with a digest of the board's projection column,
    so ANY change that could move a number invalidates the cache · including the
    ones that leave the row count untouched, which is every interesting one.
    """
    h = hashlib.blake2b(digest_size=8)
    for name, path in sorted(_paths().items()):
        h.update(name.encode())
        h.update(repr(_mtime(path)).encode())

    if board is not None and not board.empty:
        h.update(str(len(board)).encode())
        col = points_col if points_col in board.columns else None
        if col is None:
            for c in ("consensus_points", "projected_points"):
                if c in board.columns:
                    col = c
                    break
        if col is not None:
            vals = pd.to_numeric(board[col], errors="coerce").round(3)
            h.update(pd.util.hash_pandas_object(vals, index=False).values.tobytes())
    return h.hexdigest()


def frame_stamp(df: Optional[pd.DataFrame], *cols: str) -> str:
    """A content stamp for any frame handed to a cached function.

    `board_stamp` knows about the 26/27 board's projection columns. This is the
    general case: pass the columns whose values decide the result, and the
    stamp moves when they do. Use it wherever a DataFrame argument carries a
    leading underscore, so the thing Streamlit refuses to hash is described by
    something it will.
    """
    h = hashlib.blake2b(digest_size=8)
    if df is None or getattr(df, "empty", True):
        return h.hexdigest()
    h.update(str(len(df)).encode())
    for c in cols:
        if c in df.columns:
            h.update(c.encode())
            vals = pd.to_numeric(df[c], errors="coerce").round(3)
            h.update(pd.util.hash_pandas_object(vals, index=False).values.tobytes())
    return h.hexdigest()


def sources(now: Optional[float] = None) -> List[Dict]:
    """Each manual input with its age, newest first.

    `state` is one of fresh / ageing / stale / missing. Missing matters: a
    snapshot that never loaded is not the same as one that is merely old, and
    the difference decides whether a whole club is absent from the pool.
    """
    import time
    now = time.time() if now is None else now
    out = []
    for name, path in _paths().items():
        mt = _mtime(path)
        if mt is None:
            out.append({"name": name, "days": None, "state": "missing"})
            continue
        days = (now - mt) / 86400.0
        state = ("stale" if days >= STALE_AFTER_DAYS
                 else "ageing" if days >= AGEING_AFTER_DAYS else "fresh")
        out.append({"name": name, "days": days, "state": state})
    return sorted(out, key=lambda r: (r["days"] is None, r["days"] or 0))


def age_label(days: Optional[float]) -> str:
    """Human age, never a bare timestamp."""
    if days is None:
        return "missing"
    if days < 1 / 24:
        return "just now"
    if days < 1:
        return "%dh ago" % max(1, int(days * 24))
    if days < 14:
        return "%dd ago" % int(days)
    return "%dw ago" % int(days / 7)


def worst_state(rows: Optional[List[Dict]] = None) -> str:
    """The state the UI should colour the whole chip by."""
    rows = sources() if rows is None else rows
    order = ["missing", "stale", "ageing", "fresh"]
    for s in order:
        if any(r["state"] == s for r in rows):
            return s
    return "fresh"
