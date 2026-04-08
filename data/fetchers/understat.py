"""
Understat data fetcher.

Pulls xG, xA, non-penalty xG, and shot data for all Premier League players
from understat.com using the understat Python library.

Data is cached locally for 24 hours.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict

import pandas as pd

from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

CACHE_FILE = CACHE_DIR / "understat_players.json"

UNDERSTAT_TO_FPL = {
    "Manchester City":         "Man City",
    "Manchester United":       "Man Utd",
    "Newcastle United":        "Newcastle",
    "Nottingham Forest":       "Nott'm Forest",
    "Tottenham":               "Spurs",
    "Wolverhampton Wanderers": "Wolves",
}

TEAM_STATS_CACHE = CACHE_DIR / "understat_team_stats.json"


def _is_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    return (time.time() - CACHE_FILE.stat().st_mtime) < CACHE_TTL["understat"]


async def _fetch_understat_async(season: str = "2024") -> List[dict]:
    """Async fetch from Understat for all EPL players in a season."""
    try:
        from understat import Understat
        import aiohttp
    except ImportError:
        logger.error("understat or aiohttp package not installed. Run: pip install understat aiohttp")
        return []

    async with aiohttp.ClientSession() as session:
        understat = Understat(session)
        players = await understat.get_league_players("epl", season)
        return players


def fetch_understat_players(season: str = "2024") -> Optional[pd.DataFrame]:
    """
    Fetch all EPL player xG data from Understat.

    Returns a DataFrame with columns:
        player_name, xg, xa, npxg, goals, assists, minutes, shots, key_passes
    Returns None if fetch fails.
    """
    # Check cache first
    if _is_fresh():
        logger.debug("Understat cache hit")
        with open(CACHE_FILE) as f:
            raw = json.load(f)
        return _to_dataframe(raw)

    # Fetch fresh data
    logger.info("Fetching Understat player data...")
    try:
        raw = asyncio.run(_fetch_understat_async(season))
        if not raw:
            return None

        with open(CACHE_FILE, "w") as f:
            json.dump(raw, f)

        logger.info(f"Fetched {len(raw)} players from Understat")
        return _to_dataframe(raw)

    except Exception as e:
        logger.warning(f"Understat fetch failed: {e}. Trying cache fallback.")
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                raw = json.load(f)
            return _to_dataframe(raw)
        return None


def _to_dataframe(raw: List[dict]) -> pd.DataFrame:
    """Convert raw Understat player list to a clean DataFrame."""
    records = []
    for p in raw:
        minutes = int(p.get("time", 0) or 0)
        xg = float(p.get("xG", 0) or 0)
        xa = float(p.get("xA", 0) or 0)
        npxg = float(p.get("npxG", 0) or 0)
        goals = int(p.get("goals", 0) or 0)

        records.append({
            "player_name":  p.get("player_name", ""),
            "xg":           round(xg, 3),
            "xa":           round(xa, 3),
            "npxg":         round(npxg, 3),
            "xg_per90":     round(xg / (minutes / 90), 3) if minutes >= 90 else None,
            "xa_per90":     round(xa / (minutes / 90), 3) if minutes >= 90 else None,
            "goals":        goals,
            "assists":      int(p.get("assists", 0) or 0),
            "shots":        int(p.get("shots", 0) or 0),
            "key_passes":   int(p.get("key_passes", 0) or 0),
            "minutes_us":   minutes,
        })

    df = pd.DataFrame(records)
    df["name_key"] = df["player_name"].str.lower().str.strip()
    return df


async def _fetch_league_results_async(season: str = "2024") -> list:
    try:
        from understat import Understat
        import aiohttp
    except ImportError:
        return []
    async with aiohttp.ClientSession() as session:
        understat = Understat(session)
        return await understat.get_league_results("epl", season)


def fetch_understat_team_stats(season: str = "2024", last_n: int = 6) -> Optional[pd.DataFrame]:
    """
    Compute per-team recent xGC and xGA from Understat match results.

    Returns DataFrame: team (FPL name), xgc_per_game (goals conceded), xga_per_game (goals created)
    Based on last_n completed matches per team.
    Cached for 6 hours.
    """
    cache_ttl = 6 * 3600
    if TEAM_STATS_CACHE.exists() and (time.time() - TEAM_STATS_CACHE.stat().st_mtime) < cache_ttl:
        logger.debug("Team stats cache hit")
        with open(TEAM_STATS_CACHE) as f:
            import json
            data = json.load(f)
        return pd.DataFrame(data)

    logger.info("Fetching Understat team match results...")
    try:
        raw = asyncio.run(_fetch_league_results_async(season))
        if not raw:
            return None

        team_matches: Dict[str, List[dict]] = {}
        for match in raw:
            if not match.get("isResult"):
                continue
            h_raw = match["h"]["title"]
            a_raw = match["a"]["title"]
            h_name = UNDERSTAT_TO_FPL.get(h_raw, h_raw)
            a_name = UNDERSTAT_TO_FPL.get(a_raw, a_raw)
            h_xg = float(match["xG"]["h"])
            a_xg = float(match["xG"]["a"])
            dt   = match["datetime"]

            team_matches.setdefault(h_name, []).append({"xg": h_xg, "xgc": a_xg, "dt": dt})
            team_matches.setdefault(a_name, []).append({"xg": a_xg, "xgc": h_xg, "dt": dt})

        rows = []
        for team, matches in team_matches.items():
            matches.sort(key=lambda x: x["dt"])
            recent = matches[-last_n:]
            xgc_avg = sum(m["xgc"] for m in recent) / len(recent) if recent else 1.5
            xga_avg = sum(m["xg"]  for m in recent) / len(recent) if recent else 1.2
            rows.append({
                "team":          team,
                "xgc_per_game":  round(xgc_avg, 3),
                "xga_per_game":  round(xga_avg, 3),
            })

        import json
        with open(TEAM_STATS_CACHE, "w") as f:
            json.dump(rows, f)

        logger.info(f"Fetched team stats for {len(rows)} teams")
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning(f"Understat team stats fetch failed: {e}")
        return None
