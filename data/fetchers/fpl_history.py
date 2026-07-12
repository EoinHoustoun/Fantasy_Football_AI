"""
FPL full-season history harvester.

Pulls the COMPLETE season of per-player, per-fixture history straight from
the official FPL API (`element-summary/{id}/history`). Unlike the vaastav
GitHub repo (stale at GW29 for 2025-26), the API holds every finished GW -
but only until the next season's game launches (~early July), at which point
the data is wiped and replaced.

Output is an immutable snapshot in data/cache/archive/:
  fpl_gw_{season}.parquet            one row per (player, fixture)
  fpl_bootstrap_{season}_final.json  full bootstrap snapshot (codes, prices,
                                     positions, ownership at season end)

Run via scripts/harvest_2025_26.py.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from config import CACHE_DIR, FPL_BASE, POSITIONS

logger = logging.getLogger(__name__)

ARCHIVE_DIR = CACHE_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)",
    "Accept": "application/json",
}

REQUEST_SLEEP = 0.2   # be polite · ~840 requests ≈ 4 minutes
MAX_RETRIES = 3

# element-summary history fields → archive column names.
# Anything missing in the API response becomes NaN (never zero-filled).
HISTORY_FIELD_MAP = {
    "round":                            "gw",
    "fixture":                          "fixture",
    "kickoff_time":                     "kickoff_time",
    "was_home":                         "was_home",
    "opponent_team":                    "opponent_team",
    "minutes":                          "minutes",
    "total_points":                     "total_points",
    "goals_scored":                     "goals_scored",
    "assists":                          "assists",
    "clean_sheets":                     "clean_sheets",
    "goals_conceded":                   "goals_conceded",
    "own_goals":                        "own_goals",
    "penalties_saved":                  "penalties_saved",
    "penalties_missed":                 "penalties_missed",
    "saves":                            "saves",
    "yellow_cards":                     "yellow_cards",
    "red_cards":                        "red_cards",
    "bonus":                            "bonus",
    "bps":                              "bps",
    "starts":                           "starts",
    "expected_goals":                   "xg",
    "expected_assists":                 "xa",
    "expected_goal_involvements":       "xgi",
    "expected_goals_conceded":          "xgc",
    "clearances_blocks_interceptions":  "cbi",
    "tackles":                          "tackles",
    "recoveries":                       "recoveries",
    "defensive_contribution":           "defensive_contribution",
    "value":                            "value",
    "selected":                         "selected",
    "transfers_in":                     "transfers_in",
    "transfers_out":                    "transfers_out",
}

NUMERIC_COLS = [c for c in HISTORY_FIELD_MAP.values()
                if c not in ("kickoff_time", "was_home")]


def _get(url: str) -> Optional[dict]:
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"Fetch failed ({e}); retry {attempt + 1}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
    return None


def fetch_final_bootstrap(season: str) -> Optional[dict]:
    """Fetch the bootstrap and snapshot it to the archive (idempotent)."""
    snap_path = ARCHIVE_DIR / f"fpl_bootstrap_{season.replace('-', '_')}_final.json"
    if snap_path.exists():
        with open(snap_path) as f:
            return json.load(f)

    data = _get(f"{FPL_BASE}/bootstrap-static/")
    if data is None:
        return None
    with open(snap_path, "w") as f:
        json.dump(data, f)
    logger.info(f"Bootstrap snapshot saved → {snap_path}")
    return data


def _player_history_rows(element_id: int, meta: Dict, teams: Dict[int, str]) -> List[Dict]:
    """Fetch one player's per-fixture history and normalise to archive rows."""
    data = _get(f"{FPL_BASE}/element-summary/{element_id}/")
    if data is None:
        return []

    rows = []
    for h in data.get("history", []):
        row = {dst: h.get(src) for src, dst in HISTORY_FIELD_MAP.items()}
        row.update({
            "element":     element_id,
            "code":        meta["code"],
            "player_name": meta["player_name"],
            "web_name":    meta["web_name"],
            "position":    meta["position"],
            "team_id":     meta["team_id"],
            "team_name":   teams.get(meta["team_id"], ""),
        })
        rows.append(row)
    return rows


def harvest_season(season: str = "2025-26", force: bool = False) -> Optional[pd.DataFrame]:
    """
    Harvest the full season for every element in the bootstrap.

    Resumable: progress is checkpointed every 50 players to a .partial
    parquet, so a crashed run picks up where it left off. The final
    parquet is immutable · re-running with force=False returns it as-is.
    """
    season_key = season.replace("-", "_")
    final_path = ARCHIVE_DIR / f"fpl_gw_{season_key}.parquet"
    partial_path = ARCHIVE_DIR / f"fpl_gw_{season_key}.partial.parquet"

    if final_path.exists() and not force:
        logger.info(f"Harvest already complete: {final_path}")
        return pd.read_parquet(final_path)

    bootstrap = fetch_final_bootstrap(season)
    if bootstrap is None:
        logger.error("Could not fetch bootstrap · aborting harvest")
        return None

    teams = {t["id"]: t["name"] for t in bootstrap.get("teams", [])}
    # element_type 5 = 2024-25+ "assistant managers" · never part of a real squad
    elements = [e for e in bootstrap["elements"] if e["element_type"] in POSITIONS]
    logger.info(f"Harvesting {len(elements)} players for {season}")

    done_rows: List[pd.DataFrame] = []
    done_ids = set()
    if partial_path.exists() and not force:
        prev = pd.read_parquet(partial_path)
        done_rows.append(prev)
        done_ids = set(prev["element"].unique())
        logger.info(f"Resuming · {len(done_ids)} players already harvested")

    batch: List[Dict] = []
    failed: List[int] = []
    pending = [e for e in elements if e["id"] not in done_ids]

    for i, el in enumerate(pending):
        meta = {
            "code":        el["code"],
            "player_name": f"{el['first_name']} {el['second_name']}".strip(),
            "web_name":    el["web_name"],
            "position":    POSITIONS[el["element_type"]],
            "team_id":     el["team"],
        }
        rows = _player_history_rows(el["id"], meta, teams)
        if rows:
            batch.extend(rows)
        else:
            failed.append(el["id"])
        time.sleep(REQUEST_SLEEP)

        if (i + 1) % 50 == 0 or i == len(pending) - 1:
            if batch:
                done_rows.append(pd.DataFrame(batch))
                batch = []
            if done_rows:
                pd.concat(done_rows, ignore_index=True).to_parquet(partial_path)
            logger.info(f"Progress: {i + 1}/{len(pending)} players")

    if failed:
        logger.warning(f"{len(failed)} players failed after retries: {failed[:20]}")

    if not done_rows:
        return None

    df = pd.concat(done_rows, ignore_index=True)
    df["season"] = season
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["price"] = df["value"] / 10.0
    # cbit = CBI + tackles (the DEFCON counting stat)
    df["cbit"] = df["cbi"].fillna(0) + df["tackles"].fillna(0)

    df.to_parquet(final_path)
    if partial_path.exists():
        partial_path.unlink()
    logger.info(f"Harvest complete: {len(df)} rows → {final_path}")
    return df
