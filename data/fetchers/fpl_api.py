"""
FPL Official API fetcher.

Wraps all calls to fantasy.premierleague.com/api with local file caching.
All functions return raw dicts/lists exactly as the API sends them, plus
a helper that builds a clean pandas DataFrame of all players.
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional, Union, List

import requests
import pandas as pd

from config import (
    FPL_BOOTSTRAP,
    FPL_FIXTURES,
    FPL_LIVE_GW,
    FPL_TEAM,
    CACHE_DIR,
    CACHE_TTL,
    POSITIONS,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)",
    "Accept": "application/json",
}

# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _is_fresh(path: Path, ttl: int) -> bool:
    """Return True if the cached file exists and is younger than ttl seconds."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl


def _load_cache(key: str) -> Optional[Union[dict, list]]:
    path = _cache_path(key)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(key: str, data: Union[dict, list]) -> None:
    path = _cache_path(key)
    with open(path, "w") as f:
        json.dump(data, f)


def _fetch(url: str, cache_key: str, ttl: int) -> Union[dict, list]:
    """Fetch from cache if fresh, otherwise hit the API and cache result."""
    path = _cache_path(cache_key)
    if _is_fresh(path, ttl):
        logger.debug(f"Cache hit: {cache_key}")
        return _load_cache(cache_key)

    logger.info(f"Fetching from API: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    _save_cache(cache_key, data)
    return data


# ── Public fetchers ───────────────────────────────────────────────────────────

def fetch_bootstrap() -> dict:
    """
    Fetch the FPL bootstrap-static endpoint.
    Contains: all players, all teams, current gameweek, element types.
    """
    return _fetch(FPL_BOOTSTRAP, "fpl_bootstrap", CACHE_TTL["fpl_bootstrap"])


def fetch_fixtures() -> List[dict]:
    """Fetch all fixtures for the season."""
    return _fetch(FPL_FIXTURES, "fpl_fixtures", CACHE_TTL["fpl_fixtures"])


def fetch_live_gw(gw: int) -> dict:
    """Fetch live points data for a specific gameweek."""
    url = FPL_LIVE_GW.format(gw=gw)
    return _fetch(url, f"fpl_live_gw{gw}", CACHE_TTL["fpl_live"])


def fetch_team_picks(team_id: int, gw: int) -> dict:
    """Fetch a manager's picks for a specific gameweek."""
    url = FPL_TEAM.format(team_id=team_id, gw=gw)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_team_info(team_id: int) -> dict:
    """Fetch manager profile: name, overall points, rank, bank, team value."""
    url = f"https://fantasy.premierleague.com/api/entry/{team_id}/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_transfer_history(team_id: int) -> List[dict]:
    """Fetch full transfer history for a manager."""
    url = f"https://fantasy.premierleague.com/api/entry/{team_id}/transfers/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_team_squad(team_id: int, gw: int, bootstrap: Optional[dict] = None) -> pd.DataFrame:
    """
    Return the manager's current squad as a DataFrame.

    Merges picks from the latest GW with player info from bootstrap.
    Columns: web_name, team, position, price, is_captain, is_vice_captain,
             multiplier, on_bench, total_points, form, ownership.
    """
    if bootstrap is None:
        bootstrap = fetch_bootstrap()

    picks_data = fetch_team_picks(team_id, gw)
    picks = picks_data["picks"]
    entry_history = picks_data.get("entry_history", {})

    # Build player lookup by fpl_id
    players    = {p["id"]: p for p in bootstrap["elements"]}
    teams      = {t["id"]: t["name"] for t in bootstrap["teams"]}
    team_codes = {t["id"]: t["code"] for t in bootstrap["teams"]}

    records = []
    for pick in picks:
        p = players.get(pick["element"], {})
        price = p.get("now_cost", 0) / 10
        records.append({
            "fpl_id":           pick["element"],
            "web_name":         p.get("web_name", "Unknown"),
            "team":             teams.get(p.get("team"), "?"),
            "position":         POSITIONS.get(p.get("element_type"), "?"),
            "price":            price,
            "is_captain":       pick["is_captain"],
            "is_vice_captain":  pick["is_vice_captain"],
            "multiplier":       pick["multiplier"],
            "on_bench":         pick["position"] > 11,
            "squad_position":   pick["position"],
            "total_points":     p.get("total_points", 0),
            "form":             float(p.get("form", 0) or 0),
            "ownership":        float(p.get("selected_by_percent", 0)),
            "status":           p.get("status", "a"),
            "news":             p.get("news", ""),
            "team_code":        team_codes.get(p.get("team"), 0),
            "team_id":          p.get("team", 0),
        })

    df = pd.DataFrame(records).sort_values("squad_position").reset_index(drop=True)

    return df, entry_history


# ── DataFrame builders ────────────────────────────────────────────────────────

def get_current_gameweek(bootstrap: dict) -> int:
    """
    Return the active gameweek for transfer planning purposes.

    If the 'current' event is already finished (all matches played),
    return the next event instead — so FDR/scoring windows look forward,
    not at already-played fixtures.
    """
    current = None
    for event in bootstrap["events"]:
        if event["is_current"]:
            current = event
            break

    if current is not None and not current["finished"]:
        return current["id"]

    # Current GW is finished (or missing) — use the next one
    for event in bootstrap["events"]:
        if event["is_next"]:
            return event["id"]

    # Last resort: return current even if finished
    if current is not None:
        return current["id"]
    return 1


def get_players_df(bootstrap: Optional[dict] = None) -> pd.DataFrame:
    """
    Build a clean DataFrame of all FPL players from the bootstrap data.

    Columns include: name, team, position, price, ownership, form,
    total_points, minutes, goals_scored, assists, clean_sheets, bonus,
    ict_index, points_per_game, points_per_million.

    Returns one row per player.
    """
    if bootstrap is None:
        bootstrap = fetch_bootstrap()

    # Build team ID -> name lookup
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}

    players_raw = bootstrap["elements"]
    records = []

    for p in players_raw:
        price = p["now_cost"] / 10  # FPL stores cost as integer e.g. 85 = £8.5m
        total_points = p["total_points"]
        ppm = round(total_points / price, 2) if price > 0 else 0.0

        records.append({
            "fpl_id":          p["id"],
            "name":            f"{p['first_name']} {p['second_name']}",
            "web_name":        p["web_name"],
            "team":            teams.get(p["team"], "Unknown"),
            "team_id":         p["team"],
            "position":        POSITIONS.get(p["element_type"], "UNK"),
            "price":           price,
            "ownership":       float(p["selected_by_percent"]),
            "price_change":    p.get("cost_change_event", 0) / 10,
            "form":            float(p.get("form", 0) or 0),
            "total_points":    total_points,
            "points_per_game": float(p.get("points_per_game", 0) or 0),
            "points_per_million": ppm,
            "minutes":         p.get("minutes", 0),
            "goals_scored":    p.get("goals_scored", 0),
            "assists":         p.get("assists", 0),
            "clean_sheets":    p.get("clean_sheets", 0),
            "bonus":           p.get("bonus", 0),
            "ict_index":       float(p.get("ict_index", 0) or 0),
            "transfers_in_event":  p.get("transfers_in_event", 0),
            "transfers_out_event": p.get("transfers_out_event", 0),
            "status":          p.get("status", "a"),   # a=available, d=doubt, i=injured, s=suspended
            "news":            p.get("news", ""),
            "chance_of_playing_next_round": p.get("chance_of_playing_next_round"),
            "ep_this":          float(p.get("ep_this") or 0),
            "ep_next":          float(p.get("ep_next") or 0),
            "fpl_xg_per90":     float(p.get("expected_goals_per_90") or 0),
            "fpl_xa_per90":     float(p.get("expected_assists_per_90") or 0),
            "fpl_xgi_per90":    float(p.get("expected_goal_involvements_per_90") or 0),
            "fpl_xgc_per90":    float(p.get("expected_goals_conceded_per_90") or 0),
            # Set piece roles (1 = first taker, 2 = backup, None = not a taker)
            "penalties_order":  p.get("penalties_order"),
            "corners_order":    p.get("corners_and_indirect_freekicks_order"),
            "freekicks_order":  p.get("direct_freekicks_order"),
        })

    df = pd.DataFrame(records)
    df = df.sort_values("total_points", ascending=False).reset_index(drop=True)
    return df


def get_fixtures_df(fixtures: Optional[List] = None, bootstrap: Optional[dict] = None) -> pd.DataFrame:
    """
    Build a DataFrame of all fixtures.
    Columns: gameweek, home_team, away_team, home_fdr, away_fdr, finished, home_goals, away_goals.
    """
    if fixtures is None:
        fixtures = fetch_fixtures()
    if bootstrap is None:
        bootstrap = fetch_bootstrap()

    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    records = []

    for f in fixtures:
        if f.get("event") is None:
            continue  # Unscheduled fixture
        records.append({
            "fixture_id":    f["id"],
            "gameweek":      f["event"],
            "home_team":     teams.get(f["team_h"], "Unknown"),
            "away_team":     teams.get(f["team_a"], "Unknown"),
            "home_team_id":  f["team_h"],
            "away_team_id":  f["team_a"],
            "home_fdr":      f.get("team_h_difficulty", 3),
            "away_fdr":      f.get("team_a_difficulty", 3),
            "finished":      f.get("finished", False),
            "home_goals":    f.get("team_h_score"),
            "away_goals":    f.get("team_a_score"),
        })

    return pd.DataFrame(records)
