"""
European and domestic-cup fixtures for English clubs, from ESPN's public scoreboard.

FPL only knows Premier League matches, but a Thursday in Europe or a League Cup
tie changes who starts on Sunday. This pulls every Champions League, Europa
League, Conference League, League Cup and FA Cup match an English club plays,
one month per request (ESPN rejects date ranges but accepts YYYYMM), and caches
a season per file. Finished seasons are cached for good; the live one refreshes
daily.

Teams come back as ESPN display names and are mapped to FPL short codes
(`team_code`), which the archive and the live fixtures can both be joined on.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from config import CACHE_DIR

logger = logging.getLogger(__name__)

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={ym}&limit=1000"
COMPETITIONS = {
    "uefa.champions": "UCL",
    "uefa.europa": "UEL",
    "uefa.europa.conf": "UECL",
    "eng.league_cup": "EFL Cup",
    "eng.fa": "FA Cup",
}
LIVE_TTL = 24 * 3600

# ESPN display names and the FPL / vaastav spellings, all to one short code.
ALIASES = {
    "ARS": ["arsenal"], "AVL": ["aston villa"], "BOU": ["afc bournemouth", "bournemouth"],
    "BRE": ["brentford"], "BHA": ["brighton & hove albion", "brighton and hove albion", "brighton"],
    "BUR": ["burnley"], "CHE": ["chelsea"], "COV": ["coventry city", "coventry"],
    "CRY": ["crystal palace"], "EVE": ["everton"], "FUL": ["fulham"], "HUL": ["hull city", "hull"],
    "IPS": ["ipswich town", "ipswich"], "LEE": ["leeds united", "leeds"], "LEI": ["leicester city", "leicester"],
    "LIV": ["liverpool"], "LUT": ["luton town", "luton"], "MCI": ["manchester city", "man city"],
    "MUN": ["manchester united", "man utd", "man united"], "NEW": ["newcastle united", "newcastle"],
    "NFO": ["nottingham forest", "nott'm forest", "nottm forest"], "SHU": ["sheffield united", "sheffield utd"],
    "SOU": ["southampton"], "SUN": ["sunderland"], "TOT": ["tottenham hotspur", "tottenham", "spurs"],
    "WHU": ["west ham united", "west ham"], "WOL": ["wolverhampton wanderers", "wolves"],
}
_LOOKUP = {name: code for code, names in ALIASES.items() for name in names}


def team_code(name: Optional[str]) -> Optional[str]:
    """Short code for an English club name in any of the spellings we meet, else None."""
    if not name:
        return None
    key = re.sub(r"\s+", " ", str(name).strip().lower())
    return _LOOKUP.get(key)


def _months(season: str) -> List[str]:
    start = int(season[:4])
    return ["%d%02d" % (start, m) for m in range(7, 13)] + ["%d%02d" % (start + 1, m) for m in range(1, 6)]


def _fetch_month(league: str, ym: str) -> List[dict]:
    resp = requests.get(URL.format(league=league, ym=ym), timeout=20,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)"})
    if resp.status_code != 200:
        return []
    out = []
    for ev in resp.json().get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c.get("team", {}).get("displayName") for c in comp.get("competitors", [])}
        out.append({"date": ev.get("date"), "home": sides.get("home"), "away": sides.get("away"),
                    "status": comp.get("status", {}).get("type", {}).get("name")})
    return out


def fetch_season(season: str, refresh: bool = False) -> List[Dict]:
    """Every non-league match an English club plays in `season` ("2026-27").

    One row per (club, match): {team, date, comp, opponent, home, status}.
    """
    path = Path(CACHE_DIR) / ("midweek_%s.json" % season)
    live = int(season[:4]) >= time.gmtime().tm_year - (0 if time.gmtime().tm_mon >= 7 else 1)
    if path.exists() and not refresh:
        age = time.time() - path.stat().st_mtime
        if not live or age < LIVE_TTL:
            return json.loads(path.read_text())
    rows = []
    for league, label in COMPETITIONS.items():
        for ym in _months(season):
            try:
                events = _fetch_month(league, ym)
            except Exception:  # noqa: BLE001 · one bad month must not lose the season
                logger.warning("espn %s %s failed", league, ym, exc_info=True)
                continue
            for e in events:
                for side, other, home in (("home", "away", True), ("away", "home", False)):
                    code = team_code(e[side])
                    if code:
                        rows.append({"team": code, "date": e["date"], "comp": label,
                                     "opponent": e[other], "home": home, "status": e["status"]})
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["date"], r["team"])):
        k = (r["team"], r["date"][:10], r["comp"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    path.write_text(json.dumps(uniq))
    logger.info("espn fixtures %s: %d club-matches", season, len(uniq))
    return uniq
