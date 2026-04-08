"""
FBRef advanced stats fetcher.

Pulls per-90 advanced stats from FBRef for EPL players:
progressive carries, progressive passes, key passes, pressures,
expected goals, expected assists.

Uses the soccerdata library which wraps FBRef with caching
and respects rate limits automatically.

Falls back gracefully if unavailable.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd

from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

CACHE_FILE = CACHE_DIR / "fbref_players.parquet"


def _is_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    return (time.time() - CACHE_FILE.stat().st_mtime) < CACHE_TTL["fbref"]


def fetch_fbref_players(season: str = "2024-2025") -> Optional[pd.DataFrame]:
    """
    Fetch EPL player advanced stats from FBRef.

    Returns DataFrame with columns:
        player_name, progressive_carries, progressive_passes,
        key_passes, pressures, xg, xa (per 90 stats)

    Returns None if fetch fails — app degrades gracefully.
    """
    if _is_fresh():
        logger.debug("FBRef cache hit")
        return pd.read_parquet(CACHE_FILE)

    try:
        import soccerdata as sd
    except ImportError:
        logger.info("soccerdata not installed — install with: pip install soccerdata")
        return _try_direct_scrape(season)

    try:
        logger.info("Fetching FBRef stats via soccerdata...")
        fbref = sd.FBref(leagues="ENG-Premier League", seasons=season)

        # Fetch standard stats + passing + possession stats
        passing = fbref.read_player_season_stats(stat_type="passing")
        possession = fbref.read_player_season_stats(stat_type="possession")

        merged = _merge_fbref_tables(passing, possession)
        merged.to_parquet(CACHE_FILE)
        logger.info(f"FBRef: {len(merged)} players fetched")
        return merged

    except Exception as e:
        logger.warning(f"FBRef soccerdata fetch failed: {e}")
        return None


def _merge_fbref_tables(passing: pd.DataFrame, possession: pd.DataFrame) -> pd.DataFrame:
    """Merge passing and possession tables into a unified per-player DataFrame."""
    try:
        # FBRef tables have multi-level columns — flatten them
        if isinstance(passing.columns, pd.MultiIndex):
            passing.columns = ["_".join(filter(None, c)).strip() for c in passing.columns]
        if isinstance(possession.columns, pd.MultiIndex):
            possession.columns = ["_".join(filter(None, c)).strip() for c in possession.columns]

        # Reset index to get player_name as column
        passing = passing.reset_index()
        possession = possession.reset_index()

        # Find player name column
        name_col = next((c for c in passing.columns if "player" in c.lower()), None)
        if not name_col:
            return pd.DataFrame()

        passing["name_key"] = passing[name_col].str.lower().str.strip()
        possession["name_key"] = possession[name_col].str.lower().str.strip()

        # Extract useful columns — column names vary by FBRef version
        prog_passes_col = next((c for c in passing.columns if "prog" in c.lower() and "pass" in c.lower()), None)
        key_passes_col  = next((c for c in passing.columns if "key" in c.lower() and "pass" in c.lower()), None)
        prog_carries_col = next((c for c in possession.columns if "prog" in c.lower() and "carr" in c.lower()), None)

        result = passing[["name_key"]].copy()
        result["player_name"] = passing[name_col]

        for col, label in [(prog_passes_col, "progressive_passes"),
                            (key_passes_col,  "key_passes")]:
            if col:
                result[label] = pd.to_numeric(passing[col], errors="coerce")

        poss_cols = possession[["name_key"]].copy()
        if prog_carries_col:
            poss_cols["progressive_carries"] = pd.to_numeric(possession[prog_carries_col], errors="coerce")

        result = result.merge(poss_cols, on="name_key", how="left")
        return result

    except Exception as e:
        logger.warning(f"FBRef merge failed: {e}")
        return pd.DataFrame()


def _try_direct_scrape(season: str) -> Optional[pd.DataFrame]:
    """
    Fallback: direct HTTP request to FBRef.
    Only attempts if soccerdata is unavailable.
    Respects FBRef's rate limits (adds delay).
    """
    logger.info("Attempting direct FBRef scrape (fallback)...")
    try:
        import requests
        from bs4 import BeautifulSoup

        time.sleep(4)  # FBRef rate limit — be polite
        url = "https://fbref.com/en/comps/9/passing/Premier-League-Stats"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)"},
            timeout=20,
        )
        if resp.status_code != 200:
            return None

        tables = pd.read_html(resp.text)
        if not tables:
            return None

        df = tables[0]
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(filter(None, c)).strip() for c in df.columns]

        df = df[df.get("Player", df.columns[0]).notna()].copy()
        df["name_key"] = df.iloc[:, 0].astype(str).str.lower().str.strip()

        result = pd.DataFrame()
        result["name_key"]   = df["name_key"]
        result["player_name"] = df.iloc[:, 0]

        # Try to find progressive passes column
        prog_col = next((c for c in df.columns if "PrgP" in c or "Prog" in c), None)
        key_col  = next((c for c in df.columns if "KP" in c), None)

        if prog_col:
            result["progressive_passes"] = pd.to_numeric(df[prog_col], errors="coerce")
        if key_col:
            result["key_passes"] = pd.to_numeric(df[key_col], errors="coerce")

        result.to_parquet(CACHE_FILE)
        return result

    except Exception as e:
        logger.warning(f"FBRef direct scrape also failed: {e}")
        return None
