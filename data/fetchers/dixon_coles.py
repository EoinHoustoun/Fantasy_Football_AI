"""
Dixon-Coles team strength ratings for FF.

Fetches historical Premier League results from football-data.co.uk,
fits a Dixon-Coles MLE model with exponential time decay, and returns
per-team attack/defence parameters keyed by FPL team name.

Cache: data/cache/dixon_coles.json  (24h TTL)
"""
from __future__ import annotations

import json
import logging
import time
from io import StringIO
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
import requests
from scipy.optimize import minimize
from scipy.stats import poisson

from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

# ── Data sources ──────────────────────────────────────────────────────────────
_SEASONS = {
    "2023-24": "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
    "2024-25": "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
    "2025-26": "https://www.football-data.co.uk/mmz4281/2526/E0.csv",
}
_LIVE_SEASONS = {"2024-25", "2025-26"}

# football-data.co.uk short name → FPL full name
_FD_TO_FPL: Dict[str, str] = {
    "Man City":       "Manchester City",
    "Man United":     "Manchester United",
    "Newcastle":      "Newcastle United",
    "Wolves":         "Wolverhampton Wanderers",
    "Nott'm Forest":  "Nottingham Forest",
    "Brighton":       "Brighton & Hove Albion",
    "Tottenham":      "Tottenham Hotspur",
    "West Ham":       "West Ham United",
    "Leicester":      "Leicester City",
    "Ipswich":        "Ipswich Town",
    "Luton":          "Luton Town",
}

_CACHE_FILE = CACHE_DIR / "dixon_coles.json"
_TTL = 24 * 3600


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_valid() -> bool:
    if not _CACHE_FILE.exists():
        return False
    return (time.time() - _CACHE_FILE.stat().st_mtime) < _TTL


def _load_cache() -> Optional[dict]:
    try:
        with open(_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(data: dict) -> None:
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"DC cache write failed: {e}")


# ── Data loading ──────────────────────────────────────────────────────────────

def _fetch_csv(url: str) -> Optional[pd.DataFrame]:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text), encoding="utf-8-sig")
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _load_match_data() -> pd.DataFrame:
    """Download (or use on-disk cache) match results from football-data.co.uk."""
    frames = []
    for season, url in _SEASONS.items():
        cache_path = CACHE_DIR / f"fd_{season.replace('-', '')}.csv"
        use_cached = cache_path.exists() and season not in _LIVE_SEASONS

        if use_cached:
            try:
                df = pd.read_csv(cache_path, encoding="utf-8-sig")
                frames.append(df)
                continue
            except Exception:
                pass

        df = _fetch_csv(url)
        if df is not None and not df.empty:
            df.to_csv(cache_path, index=False)
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Keep only played matches with required columns
    required = {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "Date"}
    missing = required - set(combined.columns)
    if missing:
        logger.warning(f"Match data missing columns: {missing}")
        return pd.DataFrame()

    combined = combined.dropna(subset=["FTHG", "FTAG", "Date"])
    combined["Date"] = pd.to_datetime(combined["Date"], dayfirst=True, errors="coerce")
    combined = combined.dropna(subset=["Date"])
    combined["FTHG"] = pd.to_numeric(combined["FTHG"], errors="coerce").fillna(0).astype(int)
    combined["FTAG"] = pd.to_numeric(combined["FTAG"], errors="coerce").fillna(0).astype(int)

    # Attach xG if present (Understat-enriched versions)
    if "xg_h" not in combined.columns:
        combined["xg_h"] = combined["FTHG"].astype(float)
    if "xg_a" not in combined.columns:
        combined["xg_a"] = combined["FTAG"].astype(float)

    return combined.sort_values("Date").reset_index(drop=True)


# ── Dixon-Coles MLE ───────────────────────────────────────────────────────────

def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Low-score correction factor (Dixon-Coles tau)."""
    if   x == 0 and y == 0: return max(1.0 - lam * mu * rho, 1e-10)
    elif x == 0 and y == 1: return max(1.0 + lam * rho,       1e-10)
    elif x == 1 and y == 0: return max(1.0 + mu  * rho,       1e-10)
    elif x == 1 and y == 1: return max(1.0 - rho,             1e-10)
    return 1.0


def _dc_neg_log_lik(
    params: np.ndarray,
    n_teams: int,
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    hgoals: np.ndarray,
    agoals: np.ndarray,
    hxg: np.ndarray,
    axg: np.ndarray,
    weights: np.ndarray,
) -> float:
    attacks  = np.concatenate([[0.0], params[:n_teams - 1]])
    defenses = params[n_teams - 1: 2 * n_teams - 1]
    home_adv = params[2 * n_teams - 1]
    rho      = params[2 * n_teams]

    lam = np.exp(attacks[home_idx] + defenses[away_idx] + home_adv)
    mu  = np.exp(attacks[away_idx] + defenses[home_idx])

    log_lik = (
        weights * (
            np.log(np.maximum(lam, 1e-10)) * hxg - lam +
            np.log(np.maximum(mu,  1e-10)) * axg - mu
        )
    ).sum()

    # Add tau low-score correction (vectorised)
    tau_vals = np.array([
        _tau(int(h), int(a), l, m, rho)
        for h, a, l, m in zip(hgoals, agoals, lam, mu)
    ])
    log_lik += (weights * np.log(np.maximum(tau_vals, 1e-10))).sum()

    return -log_lik


def _fit_dixon_coles(df: pd.DataFrame, decay_weeks: float = 16.0) -> Optional[dict]:
    """Fit Dixon-Coles model. Returns dict of attacks/defenses keyed by FD team name."""
    if df.empty or len(df) < 50:
        logger.warning("Insufficient match data for DC fitting")
        return None

    max_date = df["Date"].max()
    df = df.copy()
    df["days_ago"] = (max_date - df["Date"]).dt.days
    df["w"] = np.exp(-df["days_ago"] / (decay_weeks * 7))

    teams  = sorted(set(df["HomeTeam"]) | set(df["AwayTeam"]))
    n      = len(teams)
    t_idx  = {t: i for i, t in enumerate(teams)}

    home_idx = df["HomeTeam"].map(t_idx).values.astype(int)
    away_idx = df["AwayTeam"].map(t_idx).values.astype(int)
    hgoals   = df["FTHG"].values.astype(int)
    agoals   = df["FTAG"].values.astype(int)
    hxg      = df["xg_h"].values.astype(float)
    axg      = df["xg_a"].values.astype(float)
    weights  = df["w"].values

    n_params = 2 * n + 1
    x0 = np.zeros(n_params)
    x0[2 * n - 1] = 0.25
    x0[2 * n]     = -0.1
    bounds = [(-3.0, 3.0)] * (2 * n - 1) + [(-1.0, 1.0), (-0.99, 0.99)]

    result = minimize(
        _dc_neg_log_lik,
        x0,
        args=(n, home_idx, away_idx, hgoals, agoals, hxg, axg, weights),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 1000, "ftol": 1e-10, "gtol": 1e-7},
    )

    if not result.success:
        logger.warning(f"DC optimiser did not fully converge: {result.message}")

    params   = result.x
    attacks  = np.concatenate([[0.0], params[:n - 1]])
    defenses = params[n - 1: 2 * n - 1]

    return {
        "attacks":  {t: float(attacks[i])  for i, t in enumerate(teams)},
        "defenses": {t: float(defenses[i]) for i, t in enumerate(teams)},
        "home_adv": float(params[2 * n - 1]),
        "rho":      float(params[2 * n]),
        "converged": bool(result.success),
        "n_matches": int(len(df)),
    }


def _remap_to_fpl(ratings: dict) -> dict:
    """Rename football-data.co.uk team keys to FPL team names."""
    def remap(d: dict) -> dict:
        return {_FD_TO_FPL.get(k, k): v for k, v in d.items()}

    return {
        "attacks":   remap(ratings["attacks"]),
        "defenses":  remap(ratings["defenses"]),
        "home_adv":  ratings["home_adv"],
        "rho":       ratings["rho"],
        "converged": ratings["converged"],
        "n_matches": ratings["n_matches"],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_dixon_coles_ratings(force: bool = False) -> Optional[Dict]:
    """
    Return DC team ratings keyed by FPL team name.

    {
        "attacks":  {"Arsenal": 0.42, "Liverpool": 0.61, ...},   # log-scale
        "defenses": {"Arsenal": -0.31, "Liverpool": -0.28, ...}, # log-scale
        "home_adv": 0.24,
        "rho":      -0.08,
        "converged": True,
        "n_matches": 874,
    }

    attacks[team]  — positive = dangerous offence
    defenses[team] — positive = leaky defence (concedes more)
    """
    if not force and _cache_valid():
        cached = _load_cache()
        if cached:
            logger.info("DC ratings loaded from cache")
            return cached

    logger.info("Fitting Dixon-Coles model from football-data.co.uk...")
    df = _load_match_data()
    if df.empty:
        logger.warning("No match data — DC ratings unavailable")
        return None

    raw = _fit_dixon_coles(df)
    if raw is None:
        return None

    ratings = _remap_to_fpl(raw)
    _save_cache(ratings)
    logger.info(
        f"DC model fitted: {ratings['n_matches']} matches, "
        f"converged={ratings['converged']}, "
        f"home_adv={ratings['home_adv']:.3f}"
    )
    return ratings
