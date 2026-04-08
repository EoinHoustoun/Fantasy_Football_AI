"""
Vaastav FPL historical data fetcher.

Pulls season-long historical FPL data from the vaastav/Fantasy-Premier-League
GitHub repository. This gives us:
- Historical player prices and ownership
- GW-by-GW points history
- Season summaries going back to 2016/17

GitHub: https://github.com/vaastav/Fantasy-Premier-League

Data is read directly from raw GitHub URLs — no scraping needed.
Cached locally for 48 hours.
"""

import json
import logging
import time
from typing import Optional

import pandas as pd
import requests

from config import CACHE_DIR

logger = logging.getLogger(__name__)

VAASTAV_BASE   = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master"
CACHE_TTL      = 48 * 3600   # 48 hours
CURRENT_SEASON = "2025-26"   # ← update each season


def _cache_path(key: str) -> str:
    return str(CACHE_DIR / f"vaastav_{key}.parquet")


def _is_fresh(key: str) -> bool:
    from pathlib import Path
    p = Path(_cache_path(key))
    if not p.exists():
        return False
    return (time.time() - p.stat().st_mtime) < CACHE_TTL


def _fetch_csv(url: str) -> Optional[pd.DataFrame]:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        from io import StringIO
        return pd.read_csv(StringIO(resp.text))
    except Exception as e:
        logger.warning(f"Vaastav fetch failed for {url}: {e}")
        return None


def fetch_current_season_summary(season: str = CURRENT_SEASON) -> Optional[pd.DataFrame]:
    """
    Fetch current season player summary from vaastav.

    Returns one row per player with: name, total_points, goals, assists,
    clean_sheets, minutes, bonus, bps, price history.

    Note: vaastav is updated periodically, not in real-time.
    FPL API is more current for live data.
    """
    key = f"season_{season.replace('-', '_')}"
    if _is_fresh(key):
        return pd.read_parquet(_cache_path(key))

    url = f"{VAASTAV_BASE}/data/{season}/players_raw.csv"
    df = _fetch_csv(url)
    if df is None:
        return None

    df["name_key"] = (df.get("first_name", "") + " " + df.get("second_name", "")).str.lower().str.strip()
    df.to_parquet(_cache_path(key))
    logger.info(f"Vaastav: {len(df)} players fetched for {season}")
    return df


def fetch_gw_history(season: str = CURRENT_SEASON) -> Optional[pd.DataFrame]:
    """
    Fetch gameweek-by-gameweek data for all players in a season.

    Useful for form analysis, price change tracking, and ownership trends.
    Returns long-format DataFrame: one row per (player, gameweek).
    """
    key = f"gw_history_{season.replace('-', '_')}"
    if _is_fresh(key):
        return pd.read_parquet(_cache_path(key))

    url = f"{VAASTAV_BASE}/data/{season}/gws/merged_gw.csv"
    df = _fetch_csv(url)
    if df is None:
        return None

    df.to_parquet(_cache_path(key))
    logger.info(f"Vaastav GW history: {len(df)} rows for {season}")
    return df


def get_price_history(player_name: str, gw_df: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """
    Return price history for a specific player (by web_name or full name).
    Useful for showing price trend charts.
    """
    if gw_df is None:
        gw_df = fetch_gw_history()
    if gw_df is None:
        return None

    name_col = next((c for c in gw_df.columns if "name" in c.lower()), None)
    if not name_col:
        return None

    mask = gw_df[name_col].str.lower().str.contains(player_name.lower(), na=False)
    player_df = gw_df[mask].copy()

    if player_df.empty:
        return None

    if "value" in player_df.columns:
        player_df["price"] = player_df["value"] / 10

    return player_df.sort_values("GW") if "GW" in player_df.columns else player_df


import unicodedata


def _norm_name(s: str) -> str:
    """Normalise a player name: remove accents, lowercase, strip."""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def fetch_defcon_stats(
    season: str = CURRENT_SEASON,
    last_n_gws: int = 10,
    current_gw: Optional[int] = None,
    min_season_pct: float = 0.20,
    min_recent_games: int = 6,
) -> Optional[pd.DataFrame]:
    """
    Compute per-player DEFCON reliability stats from vaastav GW data.

    DEFCON = Clearances + Blocks + Interceptions + Tackles (CBIT) threshold:
      DEF/GKP: 10+ → +2 FPL pts
      MID/FWD: 12+ → +2 FPL pts

    Uses actual `clearances_blocks_interceptions` + `tackles` columns when
    available (2025-26 data). Falls back to adjusted BPS proxy for older data.

    Recency-weighted: recent games count more via exponential decay (halflife=4).
    Minimum games filter prevents small-sample perfect scores skewing the list.

    Returns one row per player with:
      defcon_cbit_per_game  — mean CBIT per game (recent, EWM-weighted)
      defcon_pct            — % of recent games hitting threshold
      defcon_consistency    — 1 - CV (rewards 9,12,10,11 over 1,18,1,20)
      defcon_monster_score  — pct × consistency
      defcon_threshold      — threshold used (position-dependent)
      defcon_games          — qualifying games in window
    """
    gw_df = fetch_gw_history(season)
    if gw_df is None:
        return None

    needed = {"minutes", "GW", "position"}
    if not needed.issubset(set(gw_df.columns)):
        logger.warning("Vaastav data missing columns for DEFCON stats")
        return None

    df = gw_df.copy()

    # Use real CBIT if available, fall back to adjusted BPS proxy
    has_real_cbit = "clearances_blocks_interceptions" in df.columns
    if has_real_cbit:
        df["cbit"] = (
            df["clearances_blocks_interceptions"].fillna(0) +
            df.get("tackles", pd.Series(0, index=df.index)).fillna(0)
        )
        logger.info("DEFCON: using real CBIT data (clearances_blocks_interceptions + tackles)")
    else:
        # BPS proxy: strip attacking returns to isolate defensive contribution
        df["cbit"] = (
            df["bps"].fillna(0)
            - df.get("goals_scored", pd.Series(0, index=df.index)).fillna(0) * 18
            - df.get("assists",      pd.Series(0, index=df.index)).fillna(0) * 9
            - df.get("clean_sheets", pd.Series(0, index=df.index)).fillna(0) * 12
            - df.get("saves",        pd.Series(0, index=df.index)).fillna(0) * 2
        ).clip(lower=0)
        logger.info("DEFCON: using adjusted BPS proxy (no CBIT columns in data)")

    # Only count games with real minutes played
    df = df[df["minutes"] > 0].copy()

    if current_gw is None:
        current_gw = int(df["GW"].max())

    # 20% season filter across whole season
    min_gws   = max(3, int(current_gw * min_season_pct))
    gw_counts = df.groupby("name")["GW"].count()
    qualified = gw_counts[gw_counts >= min_gws].index
    df = df[df["name"].isin(qualified)]

    # Use only recent games for form stats
    recent = df[df["GW"] >= current_gw - last_n_gws + 1].copy()

    def _stats(group: pd.DataFrame) -> pd.Series:
        g   = group.sort_values("GW")
        pos = str(g["position"].mode().iloc[0]).upper() if len(g) else "MID"

        # Actual FPL DEFCON thresholds
        threshold = 10 if pos in ("DEF", "GKP") else 12

        cbit = g["cbit"]
        mins = g["minutes"]
        n    = len(cbit)

        # Require minimum games in the recent window
        if n < min_recent_games:
            return pd.Series({
                "defcon_cbit_per_game":  round(float(cbit.mean()), 2) if n > 0 else 0.0,
                "defcon_pct":           0.0,
                "defcon_consistency":   0.0,
                "defcon_minutes_factor": 0.0,
                "defcon_monster_score": 0.0,
                "defcon_threshold":     threshold,
                "defcon_games":         n,
                "avg_minutes":          round(float(mins.mean()), 1),
                "position":             pos,
            })

        # Exponential recency weighting — recent games count more (halflife=4 GWs)
        weights       = pd.Series(range(n)).apply(lambda i: 0.5 ** ((n - 1 - i) / 4.0))
        weights      /= weights.sum()
        weighted_mean = float((cbit.values * weights.values).sum())

        # Minutes factor: continuous curve from 0→1 as minutes approach 90.
        # 90 mins = 1.0, 87 mins = 0.98, 75 mins = 0.83, 60 mins = 0.67, 45 mins = 0.50
        # Uses EWM-weighted average minutes so recent availability counts more.
        avg_mins        = float((mins.values * weights.values).sum())
        minutes_factor  = round(min(avg_mins / 90.0, 1.0), 3)

        mean_cbit = float(cbit.mean())
        std_cbit  = float(cbit.std()) if n > 1 else 0.0

        # Only count games with 60+ mins as DEFCON qualifying
        # (FPL standard for defensive bonus eligibility)
        qualifying = cbit[mins >= 60]
        n_qual    = len(qualifying)
        n_above   = int((qualifying >= threshold).sum())
        pct       = round(n_above / n_qual, 3) if n_qual > 0 else 0.0

        cv          = std_cbit / mean_cbit if mean_cbit > 0.5 else 1.0
        consistency = round(max(0.0, 1.0 - min(cv, 1.0)), 3)

        # Monster score: hit rate × consistency × minutes availability
        monster = round(pct * consistency * minutes_factor, 3)

        return pd.Series({
            "defcon_cbit_per_game":   round(weighted_mean, 2),
            "defcon_pct":            pct,
            "defcon_consistency":    consistency,
            "defcon_minutes_factor": minutes_factor,
            "defcon_monster_score":  monster,
            "defcon_threshold":      threshold,
            "defcon_games":          n,
            "avg_minutes":           round(avg_mins, 1),
            "position":              pos,
        })

    stats = recent.groupby("name").apply(_stats).reset_index()
    stats["name_norm"] = stats["name"].apply(_norm_name)
    stats["last_norm"] = stats["name_norm"].apply(lambda x: x.split()[-1])
    logger.info(f"DEFCON stats computed for {len(stats)} players (real CBIT: {has_real_cbit})")
    return stats


def fetch_rolling_xgi(season: str = CURRENT_SEASON, last_n_gws: int = 4) -> Optional[pd.DataFrame]:
    """
    Compute per-player rolling xGI from the last N completed GWs.

    Uses vaastav's per-GW data (expected_goals, expected_assists).
    Returns DataFrame with: name, name_norm, last_norm,
                            rolling_xg, rolling_xa, rolling_xgi, rolling_xgc
    Returns None if data unavailable.
    """
    gw_df = fetch_gw_history(season)
    if gw_df is None:
        return None

    required = {"expected_goals", "expected_assists", "expected_goal_involvements", "GW"}
    if not required.issubset(set(gw_df.columns)):
        return None

    max_gw = int(gw_df["GW"].max())
    recent = gw_df[gw_df["GW"] >= max_gw - last_n_gws + 1].copy()

    if "minutes" in recent.columns:
        recent = recent[recent["minutes"] > 0]

    agg = {
        "rolling_xg":  ("expected_goals",              "sum"),
        "rolling_xa":  ("expected_assists",             "sum"),
        "rolling_xgi": ("expected_goal_involvements",   "sum"),
    }
    if "expected_goals_conceded" in recent.columns:
        agg["rolling_xgc"] = ("expected_goals_conceded", "sum")

    rolling = recent.groupby("name").agg(**agg).reset_index()
    rolling["name_norm"] = rolling["name"].apply(_norm_name)
    rolling["last_norm"] = rolling["name_norm"].apply(lambda x: x.split()[-1])
    return rolling
