"""Shared, disk-persisted points-model bundle + background pre-warm.

The Random Forest pipeline (vaastav fetch → features → tune → train →
predict) costs minutes on a cold start. Before this module, Predictions and
Free Hit each trained their OWN copy behind separate st.cache_data entries,
and every app restart paid the full cost again on first click.

Now:
  · one bundle {predictions, metrics, current_gw, trained_at} lives at
    data/cache/points_model_bundle.pkl (gitignored via *.pkl)
  · pages read the bundle instantly when it is fresh (<6h, same GW)
  · app.py kicks prewarm_async() once per process · a daemon thread trains
    the bundle in the background while the user is still on Home, so the
    first click on Predictions is fast
  · a lock file stops two trainers running at once

No Streamlit imports here · the thread must not touch script-run context.
Python 3.8 typing.
"""

from __future__ import annotations

import logging
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import CACHE_DIR

logger = logging.getLogger(__name__)

BUNDLE_PATH = Path(CACHE_DIR) / "points_model_bundle.pkl"
LOCK_PATH = Path(CACHE_DIR) / "points_model_bundle.lock"
MAX_AGE_S = 6 * 3600
LOCK_STALE_S = 15 * 60

_PREWARM_STARTED = False


# ── Bundle I/O ─────────────────────────────────────────────────────────────────

def load_bundle(current_gw: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The saved bundle, or None when missing, stale, or for another GW."""
    try:
        with open(BUNDLE_PATH, "rb") as f:
            b = pickle.load(f)
    except (OSError, pickle.PickleError, EOFError, AttributeError):
        return None
    if time.time() - float(b.get("trained_at", 0)) > MAX_AGE_S:
        return None
    if current_gw is not None and int(b.get("current_gw", -1)) != int(current_gw):
        return None
    return b


def save_bundle(predictions, metrics, current_gw: int) -> None:
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = BUNDLE_PATH.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"predictions": predictions, "metrics": metrics,
                     "current_gw": int(current_gw),
                     "trained_at": time.time()}, f)
    os.replace(tmp, BUNDLE_PATH)


# ── Training (lock-guarded · used by pages and by the warm thread) ─────────────

def _lock_active() -> bool:
    try:
        return time.time() - LOCK_PATH.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return False


def train_and_store(players_df, current_gw: int,
                    fdr_map: Optional[Dict[int, float]] = None) -> Dict[str, Any]:
    """Run the full pipeline and persist the bundle. Returns the fresh bundle."""
    from analytics.points_model import run_pipeline
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.touch()
    try:
        predictions, metrics = run_pipeline(players_df, current_gw, fdr_map=fdr_map)
        save_bundle(predictions, metrics, current_gw)
    finally:
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    return {"predictions": predictions, "metrics": metrics,
            "current_gw": int(current_gw), "trained_at": time.time()}


# ── Background pre-warm ────────────────────────────────────────────────────────

def _warm() -> None:
    """Build everything the pipeline needs from the RAW fetchers (no st.*),
    then train + store if the bundle is stale. Failures are logged, never
    raised · the pages fall back to training on demand with their loader."""
    try:
        from data.fetchers.fpl_api import (fetch_bootstrap, fetch_fixtures,
                                           get_current_gameweek, get_fixtures_df)
        from data.fetchers.understat import fetch_understat_players
        from data.processors.player_stats import build_player_universe

        bs = fetch_bootstrap()
        current_gw = get_current_gameweek(bs)
        if load_bundle(current_gw) is not None or _lock_active():
            return
        players_df = build_player_universe(
            bootstrap=bs, understat_df=fetch_understat_players())
        fixtures_df = get_fixtures_df(fetch_fixtures(), bs)
        captain_gw = next((e["id"] for e in bs["events"] if e.get("is_next")),
                          current_gw + 1)
        gw_fix = fixtures_df[fixtures_df["gameweek"] == captain_gw]
        fdr_map = {}
        for _, row in gw_fix.iterrows():
            fdr_map[int(row["home_team_id"])] = float(row["home_fdr"])
            fdr_map[int(row["away_team_id"])] = float(row["away_fdr"])
        logger.info("Pre-warming points model (GW%s)…", current_gw)
        train_and_store(players_df, current_gw, fdr_map=fdr_map)
        logger.info("Points model bundle warm.")
    except Exception:  # noqa: BLE001 · warm-up is best-effort by design
        logger.exception("Model pre-warm failed · pages will train on demand")


def prewarm_async() -> None:
    """Kick the warm thread once per process. Cheap to call every rerun."""
    global _PREWARM_STARTED
    if _PREWARM_STARTED or load_bundle() is not None or _lock_active():
        _PREWARM_STARTED = True
        return
    _PREWARM_STARTED = True
    threading.Thread(target=_warm, name="ff-model-prewarm", daemon=True).start()
