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


# ── In-season history from the live endpoint ──────────────────────────────────
#
# Vaastav's merged_gw.csv for a season appears weeks after kickoff and went
# stale at GW29 in 2025-26. For the CURRENT season the app builds the same
# schema itself: one row per (player, finished gameweek) from
# `event/{gw}/live`, joined to the bootstrap for name / position / club /
# price and to the fixture list for venue and opponent. Columns that vaastav
# records per gameweek but the live feed does not (value, selected, xP) are
# the CURRENT bootstrap values, which is what an in-season model wants anyway.

_LIVE_STAT_COLS = [
    "minutes", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
    "yellow_cards", "red_cards", "saves", "bonus", "bps", "starts",
    "influence", "creativity", "threat", "ict_index",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "expected_goals_conceded", "clearances_blocks_interceptions", "tackles",
    "recoveries", "defensive_contribution",
]

_EMPTY_COLS = ["name", "position", "team", "xP", "element", "fixture",
               "kickoff_time", "opponent_team", "round", "selected", "value",
               "was_home", "GW"] + _LIVE_STAT_COLS


def finished_gameweeks(bootstrap: dict) -> List[int]:
    """Gameweeks whose points are final (finished AND data_checked)."""
    return sorted(
        int(e["id"]) for e in bootstrap.get("events", [])
        if e.get("finished") and e.get("data_checked")
    )


def build_live_gw_history(bootstrap: dict, fixtures: List[dict],
                          live_for_gw) -> pd.DataFrame:
    """Assemble vaastav-shaped GW history for every finished gameweek.

    `live_for_gw(gw)` returns the `event/{gw}/live` payload; injected so the
    builder is testable without the network.
    """
    gws = finished_gameweeks(bootstrap)
    if not gws:
        return pd.DataFrame(columns=_EMPTY_COLS)

    teams = {t["id"]: t["name"] for t in bootstrap.get("teams", [])}
    total_players = _num(bootstrap.get("total_players")) or 11_000_000.0
    meta = {}
    for p in bootstrap.get("elements", []):
        meta[p["id"]] = {
            "name":     f"{p.get('first_name', '')} {p.get('second_name', '')}".strip(),
            "position": POSITIONS.get(p.get("element_type"), "UNK"),
            "team":     teams.get(p.get("team"), str(p.get("team"))),
            "value":    p.get("now_cost"),
            "selected": _pct_to_count(p.get("selected_by_percent"), total_players),
            "xP":       _num(p.get("ep_this")),
            "_club_id": p.get("team"),
        }
    fx_by_id = {f["id"]: f for f in fixtures}

    rows = []
    for gw in gws:
        payload = live_for_gw(gw) or {}
        for el in payload.get("elements", []):
            pid = el.get("id")
            if pid not in meta:
                continue
            stats = el.get("stats", {}) or {}
            explain = el.get("explain") or []
            fx = fx_by_id.get(explain[0].get("fixture")) if explain else None
            row = dict(meta[pid])
            club_id = row.pop("_club_id")
            row.update({
                "element": pid, "GW": gw, "round": gw,
                "fixture": fx["id"] if fx else None,
                "kickoff_time": fx.get("kickoff_time") if fx else None,
            })
            # venue: bootstrap `team` is the club id, so compare to team_h
            if fx is not None and club_id is not None:
                home = fx["team_h"] == club_id
                row["was_home"] = home
                row["opponent_team"] = fx["team_a"] if home else fx["team_h"]
            else:
                row["was_home"] = None
                row["opponent_team"] = None
            for c in _LIVE_STAT_COLS:
                row[c] = _num(stats.get(c))
            rows.append(row)

    df = pd.DataFrame(rows, columns=_EMPTY_COLS)
    return df


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct_to_count(pct, total_players: float) -> Optional[float]:
    """selected_by_percent → an absolute count on vaastav's `selected` scale."""
    p = _num(pct)
    return None if p is None else p / 100.0 * total_players


def fetch_current_season_gw_history() -> Optional[pd.DataFrame]:
    """Live GW history for the running season, built from the FPL API."""
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, fetch_live_gw
    try:
        bs = fetch_bootstrap()
        fx = fetch_fixtures()
    except Exception as exc:   # pragma: no cover · network
        logger.warning(f"Live GW history unavailable: {exc}")
        return None
    df = build_live_gw_history(bs, fx, fetch_live_gw)
    logger.info(f"Live GW history: {len(df)} rows over GW{finished_gameweeks(bs) or [0]}")
    return df
