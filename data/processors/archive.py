"""
Multi-season FPL historical archive (2016-17 → 2025-26).

Normalizes vaastav per-GW data (plus the FPL-API harvest for 2025-26,
where the vaastav repo is permanently stale at GW29) into two tidy
parquet files under data/cache/archive/:

  gw_archive.parquet      one row per (player, fixture appearance)
  season_summary.parquet  one row per (player, season)

Cross-season player identity uses the FIFA-stable `code` column from
players_raw.csv (verified present in every season), joined per season
via merged_gw.element → players_raw.id → code. Names from players_raw,
never from merged_gw (older seasons mangle them: "Aaron_Cresswell_454").

Schema drift handled here (verified empirically):
  2016-19   no xP/xG/position/team-name cols; HAS old CBIT + recoveries
  2019-20   COVID: GWs labelled 1-29 then 39-47 → remapped to 1-38
  2020-22   xP + position/team appear; still no xG
  2022-24   xG/xA/xGI/xGC + starts appear
  2024-25   element_type 5 "assistant managers" must be filtered out
  2025-26   CBIT + defensive_contribution; rows come from the API harvest
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import CACHE_DIR, POSITIONS
from data.fetchers.vaastav import (
    SEASONS,
    fetch_gw_history,
    fetch_master_team_list,
    fetch_players_raw,
)

logger = logging.getLogger(__name__)

ARCHIVE_DIR = CACHE_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

GW_ARCHIVE_PATH = ARCHIVE_DIR / "gw_archive.parquet"
SEASON_SUMMARY_PATH = ARCHIVE_DIR / "season_summary.parquet"
HARVEST_SEASON = "2025-26"   # served by the API harvest, not vaastav

# Canonical archive schema. Nullable stats (xg, cbit, …) stay NaN for
# seasons that lack them · never zero-filled.
CANONICAL_COLS = [
    "season", "code", "element", "player_name", "web_name", "position",
    "team_id", "team_name", "gw", "fixture", "kickoff_time", "was_home",
    "opponent_team", "minutes", "total_points", "goals_scored", "assists",
    "clean_sheets", "goals_conceded", "own_goals", "penalties_saved",
    "penalties_missed", "saves", "yellow_cards", "red_cards", "bonus",
    "bps", "starts", "xp", "xg", "xa", "xgi", "xgc", "cbi", "tackles",
    "recoveries", "cbit", "defensive_contribution", "value", "price",
    "selected", "transfers_in", "transfers_out",
]

# merged_gw source column → canonical name (applied when present)
GW_RENAME = {
    "GW": "gw",
    "round": "gw",
    "xP": "xp",
    "expected_goals": "xg",
    "expected_assists": "xa",
    "expected_goal_involvements": "xgi",
    "expected_goals_conceded": "xgc",
    "clearances_blocks_interceptions": "cbi",
}

NULLABLE_FLOATS = ["starts", "xp", "xg", "xa", "xgi", "xgc", "cbi",
                   "tackles", "recoveries", "cbit", "defensive_contribution"]


def _element_lookup(season: str) -> Optional[pd.DataFrame]:
    """element id → code, names, position, team_id for one season."""
    raw = fetch_players_raw(season)
    if raw is None:
        return None
    raw = raw[raw["element_type"].isin(POSITIONS)].copy()   # drops 2024-25 managers
    raw["position"] = raw["element_type"].map(POSITIONS)
    raw["player_name"] = (
        raw["first_name"].fillna("").str.strip() + " " +
        raw["second_name"].fillna("").str.strip()
    ).str.strip()
    if "web_name" not in raw.columns:
        raw["web_name"] = raw["second_name"]
    return raw[["id", "code", "player_name", "web_name", "position", "team"]].rename(
        columns={"id": "element", "team": "team_id"}
    )


def _team_names(season: str) -> Dict[int, str]:
    master = fetch_master_team_list()
    if master is None:
        return {}
    rows = master[master["season"] == season]
    return dict(zip(rows["team"].astype(int), rows["team_name"]))


def _normalize_vaastav_season(season: str) -> Optional[pd.DataFrame]:
    gw_df = fetch_gw_history(season)
    lookup = _element_lookup(season)
    if gw_df is None or lookup is None:
        logger.error(f"Archive: missing source data for {season}")
        return None

    df = gw_df.copy()
    # some seasons carry both GW and round · keep GW, drop the duplicate source
    if "GW" in df.columns and "round" in df.columns:
        df = df.drop(columns=["round"])
    df = df.rename(columns=GW_RENAME)
    # drop merged_gw identity cols · players_raw is authoritative
    df = df.drop(columns=[c for c in ("name", "position", "team") if c in df.columns])

    # inner join also filters element_type-5 manager rows (absent from lookup)
    df = df.merge(lookup, on="element", how="inner")

    df["gw"] = pd.to_numeric(df["gw"], errors="coerce")
    df = df[df["gw"].notna()].copy()
    df["gw"] = df["gw"].astype(int)
    if season == "2019-20":
        # COVID restart: GWs 39-47 are really 30-38
        df.loc[df["gw"] >= 39, "gw"] -= 9

    team_map = _team_names(season)
    df["team_name"] = df["team_id"].map(team_map).fillna("")

    df["season"] = season
    for col in CANONICAL_COLS:
        if col not in df.columns:
            df[col] = np.nan

    for col in df.columns.intersection(
        [c for c in CANONICAL_COLS if c not in
         ("season", "player_name", "web_name", "position", "team_name",
          "kickoff_time", "was_home")]
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["price"] = df["value"] / 10.0
    if df["cbi"].notna().any():
        df["cbit"] = df["cbi"].fillna(0) + df["tackles"].fillna(0)

    return df[CANONICAL_COLS]


def _load_harvest_season(season: str = HARVEST_SEASON) -> Optional[pd.DataFrame]:
    path = ARCHIVE_DIR / f"fpl_gw_{season.replace('-', '_')}.parquet"
    if not path.exists():
        logger.error(f"Archive: harvest parquet missing for {season} · "
                     f"run scripts/harvest_2025_26.py first")
        return None
    df = pd.read_parquet(path)
    for col in CANONICAL_COLS:
        if col not in df.columns:
            df[col] = np.nan
    return df[CANONICAL_COLS]


def build_gw_archive(seasons: Optional[List[str]] = None,
                     force: bool = False) -> Optional[pd.DataFrame]:
    """Build (or load) the full per-GW archive across all seasons."""
    if GW_ARCHIVE_PATH.exists() and not force:
        return pd.read_parquet(GW_ARCHIVE_PATH)

    seasons = seasons or SEASONS
    frames = []
    for season in seasons:
        part = (_load_harvest_season(season) if season == HARVEST_SEASON
                else _normalize_vaastav_season(season))
        if part is None or part.empty:
            logger.warning(f"Archive: skipping {season} (no data)")
            continue
        logger.info(f"Archive: {season} · {len(part)} rows, "
                    f"{part['code'].nunique()} players, max GW {int(part['gw'].max())}")
        frames.append(part)

    if not frames:
        return None
    archive = pd.concat(frames, ignore_index=True)
    archive.to_parquet(GW_ARCHIVE_PATH)
    logger.info(f"Archive built: {len(archive)} rows → {GW_ARCHIVE_PATH}")
    return archive


def _defcon_points(g: pd.DataFrame) -> float:
    """
    2025-26 Defensive Contribution points for one player-season.
    DEF/GKP: CBIT >= 10 → +2 · MID/FWD: CBIT + recoveries >= 12 → +2.
    NaN for seasons without CBIT data.
    """
    if g["cbit"].isna().all():
        return np.nan
    pos = g["position"].iloc[0]
    if pos in ("DEF", "GKP"):
        stat, thr = g["cbit"].fillna(0), 10
    else:
        stat, thr = g["cbit"].fillna(0) + g["recoveries"].fillna(0), 12
    played = g["minutes"] > 0
    return float(2 * int((stat[played] >= thr).sum()))


def build_season_summary(gw_archive: Optional[pd.DataFrame] = None,
                         force: bool = False) -> Optional[pd.DataFrame]:
    """One row per (player, season): start/end price, totals, per-90 rates."""
    if SEASON_SUMMARY_PATH.exists() and not force:
        return pd.read_parquet(SEASON_SUMMARY_PATH)

    if gw_archive is None:
        gw_archive = build_gw_archive()
    if gw_archive is None:
        return None

    rows = []
    for (season, code), g in gw_archive.groupby(["season", "code"]):
        g = g.sort_values("gw")
        priced = g[g["price"].notna()]
        if priced.empty:
            continue
        minutes = float(g["minutes"].fillna(0).sum())
        played = g[g["minutes"] > 0]
        per90 = (lambda x: round(x / minutes * 90, 3)) if minutes > 0 else (lambda x: 0.0)

        first_gw = int(priced["gw"].iloc[0])
        rows.append({
            "season": season,
            "code": int(code),
            "player_name": g["player_name"].iloc[-1],
            "web_name": g["web_name"].iloc[-1],
            "position": g["position"].iloc[-1],
            "team_name": g["team_name"].iloc[-1],
            "start_price": float(priced["price"].iloc[0]),
            "end_price": float(priced["price"].iloc[-1]),
            "price_change": round(float(priced["price"].iloc[-1] - priced["price"].iloc[0]), 1),
            "joined_late": first_gw > 1,
            "first_gw": first_gw,
            "total_points": float(g["total_points"].fillna(0).sum()),
            "minutes": minutes,
            "games_played": int(len(played)),
            "starts_total": float(g["starts"].sum()) if g["starts"].notna().any() else np.nan,
            "ppg": round(float(played["total_points"].mean()), 2) if len(played) else 0.0,
            "pp90": per90(float(g["total_points"].fillna(0).sum())),
            "goals": float(g["goals_scored"].fillna(0).sum()),
            "assists": float(g["assists"].fillna(0).sum()),
            "goals_per90": per90(float(g["goals_scored"].fillna(0).sum())),
            "assists_per90": per90(float(g["assists"].fillna(0).sum())),
            "xg": float(g["xg"].sum()) if g["xg"].notna().any() else np.nan,
            "xa": float(g["xa"].sum()) if g["xa"].notna().any() else np.nan,
            "xgi": float(g["xgi"].sum()) if g["xgi"].notna().any() else np.nan,
            "xgc": float(g["xgc"].sum()) if g["xgc"].notna().any() else np.nan,
            "xg_per90": per90(float(g["xg"].sum())) if (g["xg"].notna().any() and minutes > 0) else np.nan,
            "clean_sheets": float(g["clean_sheets"].fillna(0).sum()),
            "bonus": float(g["bonus"].fillna(0).sum()),
            "bps": float(g["bps"].fillna(0).sum()),
            "cbit_total": float(g["cbit"].sum()) if g["cbit"].notna().any() else np.nan,
            "defcon_points": _defcon_points(g),
            "saves": float(g["saves"].fillna(0).sum()),
            "selected_end": float(g["selected"].iloc[-1]) if g["selected"].notna().any() else np.nan,
            "pts_per_million": round(float(g["total_points"].fillna(0).sum()) /
                                     float(priced["price"].iloc[0]), 2),
        })

    summary = pd.DataFrame(rows)
    summary.to_parquet(SEASON_SUMMARY_PATH)
    logger.info(f"Season summary built: {len(summary)} player-seasons → {SEASON_SUMMARY_PATH}")
    return summary


def load_gw_archive() -> Optional[pd.DataFrame]:
    return pd.read_parquet(GW_ARCHIVE_PATH) if GW_ARCHIVE_PATH.exists() else None


def load_season_summary() -> Optional[pd.DataFrame]:
    return pd.read_parquet(SEASON_SUMMARY_PATH) if SEASON_SUMMARY_PATH.exists() else None


def build_optimizer_input(season: str = HARVEST_SEASON) -> Optional[pd.DataFrame]:
    """
    Per-(player, GW) table for the Perfect Season MILP.

    Aggregates DGW fixtures (points summed · captaincy doubles the whole GW),
    forward-fills price across blank GWs so players stay holdable, and
    carries the per-GW team id for the 3-per-club constraint.

    Returns wide-ish long format: code, gw, player_name, web_name, position,
    team_id, team_name, points, price, played.
    """
    archive = load_gw_archive()
    if archive is None:
        return None
    df = archive[archive["season"] == season].copy()
    if df.empty:
        return None

    agg = (df.groupby(["code", "gw"])
             .agg(points=("total_points", "sum"),
                  price=("price", "last"),
                  minutes=("minutes", "sum"),
                  team_id=("team_id", "last"),
                  team_name=("team_name", "last"),
                  player_name=("player_name", "last"),
                  web_name=("web_name", "last"),
                  position=("position", "last"))
             .reset_index())

    max_gw = int(agg["gw"].max())
    full = []
    for code, g in agg.groupby("code"):
        g = g.set_index("gw").reindex(range(int(g["gw"].min()), max_gw + 1))
        g["code"] = code
        for col in ("price", "team_id", "team_name", "player_name", "web_name", "position"):
            g[col] = g[col].ffill()
        g["points"] = g["points"].fillna(0)        # blank GW → 0 pts, still holdable
        g["minutes"] = g["minutes"].fillna(0)
        full.append(g.reset_index().rename(columns={"index": "gw"}))

    out = pd.concat(full, ignore_index=True)
    out["played"] = out["minutes"] > 0
    return out
