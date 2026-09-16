"""Match-odds signals · team expected goals and clean-sheet odds from the market.

The betting market prices every fixture with more information than any of our
three models: rotation news, managers, weather, everything. This module turns
a hand-refreshed odds snapshot (1X2 + over/under 2.5 per fixture) into the
two team-level facts a draft actually wants:

  · xg_for   · how many goals the market expects a team to score
  · cs_prob  · the market's clean-sheet probability for its defenders

Derivation, standard and deliberately simple: de-vig the 1X2 and totals,
solve a Poisson total from the under-2.5 price, then split it home/away so
the implied home-win probability matches the de-vigged 1X2. CS probability
is then exp(-opponent xG). Independence is assumed; that is fine at the
"which £5m defender" level this feeds.

The snapshot (`data/cache/market_odds_2026_27.json`) is manual and one-shot,
like the Scout and Hub files · it is written from F_PRED's cached odds fetch
(The Odds API, Pinnacle preferred) and NEVER polled from here. Coverage is
whatever rounds the books have priced · GW1 today, more as they open.

This module is a SIGNAL SURFACE, not a projection input: nothing in the
consensus blend reads it (that swap needs in-season validation first). It
answers "does the market agree with our draft" on demand.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Dict, List, Optional

import pandas as pd

from config import CACHE_DIR, NEXT_SEASON

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = CACHE_DIR / ("market_odds_%s.json" % NEXT_SEASON.replace("-", "_"))

# football-data club names (as F_PRED's odds cache keys them) → FPL short.
FD_TO_SHORT = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU",
    "Brentford": "BRE", "Brighton": "BHA", "Chelsea": "CHE",
    "Coventry": "COV", "Crystal Palace": "CRY", "Everton": "EVE",
    "Fulham": "FUL", "Hull": "HUL", "Ipswich": "IPS", "Leeds": "LEE",
    "Liverpool": "LIV", "Man City": "MCI", "Man United": "MUN",
    "Newcastle": "NEW", "Nott'm Forest": "NFO", "Sunderland": "SUN",
    "Tottenham": "TOT", "Wolves": "WOL", "West Ham": "WHU", "Burnley": "BUR",
}


def load_snapshot() -> Optional[dict]:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text())
    except Exception:
        logger.warning("unreadable market odds snapshot", exc_info=True)
        return None


def _devig(prices: Dict[str, float], keys: List[str]) -> Optional[Dict[str, float]]:
    try:
        inv = {k: 1.0 / float(prices[k]) for k in keys}
    except (KeyError, TypeError, ZeroDivisionError, ValueError):
        return None
    s = sum(inv.values())
    if s <= 0:
        return None
    return {k: v / s for k, v in inv.items()}


def _poisson_cdf2(lam: float) -> float:
    """P(N <= 2) for Poisson(lam)."""
    return math.exp(-lam) * (1.0 + lam + lam * lam / 2.0)


def _total_from_under(p_under: float) -> float:
    lo, hi = 0.2, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _poisson_cdf2(mid) > p_under:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _home_win_prob(mu_h: float, mu_a: float, cap: int = 12) -> float:
    """P(H > A) under independent Poissons, truncated at `cap` goals."""
    pa = [math.exp(-mu_a) * mu_a ** j / math.factorial(j) for j in range(cap)]
    ph = 0.0
    cdf_a = 0.0
    for i in range(1, cap):
        cdf_a += pa[i - 1]                      # P(A <= i-1)
        ph += math.exp(-mu_h) * mu_h ** i / math.factorial(i) * cdf_a
    return ph


def _split_total(total: float, p_home: float, p_away: float) -> float:
    """Supremacy s (home xG − away xG) matching the 1X2, by bisection."""
    target = p_home - p_away
    lo, hi = -total + 0.05, total - 0.05
    for _ in range(50):
        mid = (lo + hi) / 2.0
        mu_h, mu_a = (total + mid) / 2.0, (total - mid) / 2.0
        diff = _home_win_prob(mu_h, mu_a) - _home_win_prob(mu_a, mu_h)
        if diff < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def team_frame() -> Optional[pd.DataFrame]:
    """One row per (team_short, gw): market xg_for, xg_against, cs_prob.

    Returns None when there is no snapshot · every caller degrades to a
    caption, never an error, matching the other manual snapshots.
    """
    snap = load_snapshot()
    if not snap:
        return None
    rows = []
    for fx in snap.get("fixtures", []):
        h, a = FD_TO_SHORT.get(fx.get("home")), FD_TO_SHORT.get(fx.get("away"))
        gw = fx.get("gw")
        one_x2 = _devig(fx, ["H", "D", "A"])
        totals = _devig(fx, ["over25", "under25"])
        if not h or not a or not one_x2 or not totals:
            continue
        total = _total_from_under(totals["under25"])
        s = _split_total(total, one_x2["H"], one_x2["A"])
        mu_h, mu_a = (total + s) / 2.0, (total - s) / 2.0
        rows.append({"team_short": h, "gw": gw, "venue": "H", "opp": a,
                     "xg_for": round(mu_h, 2), "xg_against": round(mu_a, 2),
                     "cs_prob": round(math.exp(-mu_a), 3)})
        rows.append({"team_short": a, "gw": gw, "venue": "A", "opp": h,
                     "xg_for": round(mu_a, 2), "xg_against": round(mu_h, 2),
                     "cs_prob": round(math.exp(-mu_h), 3)})
    if not rows:
        return None
    return pd.DataFrame(rows)
