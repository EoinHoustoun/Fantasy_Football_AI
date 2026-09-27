"""Uncertainty ranges for engine projections, by simulating the components.

The brain gives a mean per player and gameweek, plus the pieces behind it
(probability of playing and of 60 minutes, expected goals, assists, saves,
bonus, clean-sheet and DEFCON probabilities). A mean hides the thing a manager
actually weighs: a 4.5 from a nailed defender and a 4.5 from a rotation-risk
forward are different bets. This module draws whole matches from those pieces:

- minutes: plays ~ Bernoulli(p_play), 60+ ~ Bernoulli(p60 / p_play) given plays
- goals, assists, saves ~ Poisson at the rate GIVEN he plays (mean / p_play)
- goals conceded ~ Poisson(-ln p_clean_sheet): the clean sheet is k == 0, and
  keepers and defenders lose a point per two conceded (60+ only)
- DEFCON ~ Bernoulli(p_defcon) given 60+, worth 2
- bonus follows returns (goals, assists, clean sheets) and is scaled so its
  mean matches the engine's e_bonus

Each row's draws are then scaled so their mean equals the engine's xp (which
already carries injury news, cards and the rest), so the RANGE comes from here
and the CENTRE stays the engine's.

Unforeseen absences: from the second week on, each player has a weekly
`HAZARD` of starting a one-to-four-week spell out (injury, dropped, rested).
Without it the six-week bands missed low twice as often as high.

On top, each player gets one rate multiplier shared across the whole window,
lognormal with width `RATE_SIGMA`: the engine can be wrong about a player's
level, not just unlucky in a match, and that error does not average out over
six weeks. The width is fitted by `scripts/calibrate_ranges.py` on the 15
walk-forward folds so that the 10-90% band holds 80% of real outcomes.

No Streamlit imports.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

GOAL_PTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_PTS = 3
# Fitted by scripts/calibrate_ranges.py (see docs/research/ranges_calibration.md).
RATE_SIGMA = 0.55
# Weekly chance a player starts an unforeseen absence (injury, dropped, rested)
# lasting one to four weeks. News already known is in the engine's xp.
HAZARD = 0.08
N_SIMS = 2000


def simulate(rows: pd.DataFrame, n: int = N_SIMS, sigma: float = RATE_SIGMA,
             seed: int = 7, codes_order: Optional[Sequence[int]] = None,
             hazard: float = HAZARD) -> Dict[int, np.ndarray]:
    """Per player code, an (n,) array of simulated points summed over `rows`' gameweeks.

    `rows` = engine rows (code, gw, position, xp, p_play, p60, e_goals, e_assists,
    e_saves, e_bonus, p_clean_sheet, p_defcon, fixtures). One call = one window.
    Draws for different players are independent; within a player the rate
    multiplier is shared across gameweeks.
    """
    rng = np.random.default_rng(seed)
    r = rows.reset_index(drop=True)
    R = len(r)
    if R == 0:
        return {}
    col = lambda k, d=0.0: r[k].astype(float).fillna(d).values if k in r else np.full(R, d)
    pos = r["position"].astype(str).str.upper().values
    nfx = np.clip(col("fixtures", 1.0), 1, None)
    p_play = np.clip(col("p_play"), 0.0, 1.0)
    p60c = np.clip(np.divide(col("p60"), p_play, out=np.zeros(R), where=p_play > 1e-6), 0, 1)
    safe = np.where(p_play > 1e-6, p_play, 1.0)
    lam_g = col("e_goals") / safe / nfx
    lam_a = col("e_assists") / safe / nfx
    lam_s = col("e_saves") / safe / nfx
    pcs = np.clip(col("p_clean_sheet"), 1e-4, 1.0)
    lam_c = -np.log(pcs)
    pdc = np.clip(col("p_defcon"), 0.0, 1.0)
    gpts = np.array([GOAL_PTS.get(p, 4) for p in pos], float)
    cpts = np.array([CS_PTS.get(p, 0) for p in pos], float)
    defensive = np.isin(pos, ["GKP", "DEF"]).astype(float)
    keeper = (pos == "GKP").astype(float)

    total = np.zeros((R, n))
    bonus_raw = np.zeros((R, n))
    for _ in range(int(nfx.max())):
        live = (nfx > _)[:, None]
        plays = rng.random((R, n)) < p_play[:, None]
        s60 = plays & (rng.random((R, n)) < p60c[:, None])
        g = rng.poisson(np.repeat(lam_g[:, None], n, 1)) * plays
        a = rng.poisson(np.repeat(lam_a[:, None], n, 1)) * plays
        sv = rng.poisson(np.repeat(lam_s[:, None], n, 1)) * plays
        k = rng.poisson(np.repeat(lam_c[:, None], n, 1))
        cs = s60 & (k == 0)
        dc = s60 & (rng.random((R, n)) < pdc[:, None])
        pts = (plays.astype(float) + s60 + g * gpts[:, None] + a * ASSIST_PTS
               + cs * cpts[:, None] + 2.0 * dc + np.floor(sv / 3.0) * keeper[:, None]
               - np.floor(k / 2.0) * s60 * defensive[:, None])
        total += pts * live
        bonus_raw += (np.minimum(3.0, 2.0 * g + 1.0 * a + cs * defensive[:, None])) * live
    mb = bonus_raw.mean(axis=1)
    bscale = np.divide(col("e_bonus"), mb, out=np.zeros(R), where=mb > 1e-9)
    total += bonus_raw * bscale[:, None]
    m = total.mean(axis=1)
    scale = np.divide(col("xp"), m, out=np.ones(R), where=m > 1e-9)
    total *= np.clip(scale, 0.0, 3.0)[:, None]

    codes = r["code"].astype(int).values
    out: Dict[int, np.ndarray] = {}
    for c in (codes_order if codes_order is not None else pd.unique(codes)):
        idx = np.where(codes == int(c))[0]
        if len(idx) == 0:
            continue
        blk = total[idx]
        if hazard > 0 and len(idx) > 1:
            # An absence that starts in week j of the window and lasts 1-4
            # weeks. Only from the second week: the first is covered by news.
            wk = pd.Series(r.loc[idx, "gw"].values).rank(method="dense").values - 1
            start = rng.geometric(hazard, n)          # 1 = second week
            length = rng.integers(1, 5, n)
            out_ = (wk[:, None] >= start[None, :]) & (wk[:, None] < (start + length)[None, :])
            blk = np.where(out_, 0.0, blk)
        s = blk.sum(axis=0)
        if sigma > 0:
            mult = rng.lognormal(-0.5 * sigma ** 2, sigma, n)
            s = s * mult
        out[int(c)] = s
    return out


def band(samples: np.ndarray, lo: float = 10, hi: float = 90) -> Dict[str, float]:
    """Mean, median and the lo-hi percentile band of one player's draws."""
    if samples is None or len(samples) == 0:
        return {"mean": 0.0, "p50": 0.0, "lo": 0.0, "hi": 0.0}
    return {"mean": float(samples.mean()), "p50": float(np.percentile(samples, 50)),
            "lo": float(np.percentile(samples, lo)), "hi": float(np.percentile(samples, hi))}


def p_beats(a: np.ndarray, b: np.ndarray) -> float:
    """Chance A outscores B over the window (ties split)."""
    if a is None or b is None or len(a) == 0 or len(b) == 0:
        return 0.5
    n = min(len(a), len(b))
    return float((a[:n] > b[:n]).mean() + 0.5 * (a[:n] == b[:n]).mean())


def per_gw_bands(rows: pd.DataFrame, code: int, gws: Sequence[int], n: int = 1000,
                 sigma: float = RATE_SIGMA, seed: int = 7) -> Dict[int, Dict[str, float]]:
    """10-90% band for one player in each gameweek (for chart ribbons)."""
    out = {}
    for g in gws:
        sub = rows[(rows["code"] == int(code)) & (rows["gw"] == int(g))]
        s = simulate(sub, n=n, sigma=sigma, seed=seed + int(g)).get(int(code))
        out[int(g)] = band(s) if s is not None else {"mean": 0.0, "p50": 0.0, "lo": 0.0, "hi": 0.0}
    return out
