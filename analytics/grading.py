"""
Turning a projected score into red, amber or green.

A flat cut ("green above 4.2") looks decisive and is quietly wrong, because a
gameweek score does not mean the same thing in every position. Measured across
GW1-8 for players expected to start:

    GKP  mean 3.95  sd 0.65      MID  mean 3.88  sd 1.20
    DEF  mean 3.63  sd 1.09      FWD  mean 3.87  sd 1.82

The MEANS are close enough that a flat cut looks defensible. The SPREADS are
not: a forward varies three times as much as a keeper, so 4.5 is an ordinary
week for a forward and an excellent one for a keeper. Cutting on percentiles
within a position says "good for a keeper" rather than "good in the abstract",
which is the only comparison that helps when you are filling one squad slot.

The cuts are derived from the board on screen, not hardcoded, so they move as
prices and projections do. They are surfaced in the UI rather than applied
silently · a colour nobody can explain is worse than no colour.
"""

import logging
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Below AMBER_AT you are in the bottom 40% for the position, above GREEN_AT the
# top 30%. Chosen so "green" means roughly a top-third week rather than merely
# above average, which is a bar almost half the league clears.
AMBER_AT = 0.40
GREEN_AT = 0.70

# Fallbacks if a position has too few players on the board to fit cuts from.
MIN_SAMPLE = 20
DEFAULT_CUTS = (3.5, 4.3)

BAND_TOKENS = {"red": "red", "amber": "gold", "green": "mint"}


def points_cuts(samples: Dict[str, Iterable[float]]) -> Dict[str, Tuple[float, float]]:
    """Per-position (amber_at, green_at) cut points from real values.

    `samples` is {position: iterable of per-gameweek projected points}. A
    position with too little data falls back rather than fitting cuts to five
    numbers and pretending they mean something.
    """
    cuts = {}
    for pos, vals in (samples or {}).items():
        v = pd.to_numeric(pd.Series(list(vals)), errors="coerce").dropna()
        v = v[v > 0]
        if len(v) < MIN_SAMPLE:
            cuts[pos] = DEFAULT_CUTS
            continue
        cuts[pos] = (round(float(v.quantile(AMBER_AT)), 2),
                     round(float(v.quantile(GREEN_AT)), 2))
    return cuts


def band_of(value: Optional[float], pos: str,
            cuts: Optional[Dict[str, Tuple[float, float]]] = None) -> str:
    """'red' | 'amber' | 'green' for one projected score."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "red"
    lo, hi = (cuts or {}).get(pos, DEFAULT_CUTS)
    v = float(value)
    if v >= hi:
        return "green"
    if v >= lo:
        return "amber"
    return "red"


def band_label(pos: str, cuts: Optional[Dict[str, Tuple[float, float]]] = None) -> str:
    """The legend. State the cuts so the colour is explainable, not decreed."""
    lo, hi = (cuts or {}).get(pos, DEFAULT_CUTS)
    return ("green %.1f+ · amber %.1f-%.1f · red under %.1f "
            "(top 30%% / middle / bottom 40%% for a %s)" % (hi, lo, hi, lo, pos))


def sample_from_projection(board: pd.DataFrame, proj, gws: List[int],
                           min_mins_share: float = 0.5) -> Dict[str, List[float]]:
    """Collect per-gameweek projections by position, starters only.

    Bench fodder projected at 0.4 a week would drag every cut down and make an
    ordinary score look green.
    """
    out: Dict[str, List[float]] = {}
    if board is None or board.empty or proj is None:
        return out
    share = pd.to_numeric(board.get("mins_share"), errors="coerce").fillna(0.0)
    for (_, row), s in zip(board.iterrows(), share):
        if s < min_mins_share:
            continue
        pos = str(row.get("position", ""))
        code = int(row.get("code", 0) or 0)
        for g in gws:
            try:
                v = float(proj.points(code, g))
            except Exception:
                continue
            if v > 0:
                out.setdefault(pos, []).append(v)
    return out


# ── Bench Boost ──────────────────────────────────────────────────────────────

def bench_boost_grade(points: Optional[float]) -> Dict:
    """Is this bench worth the chip?

    A bench is four players, so the target is roughly all four starting and
    returning a normal score. Grading it against a fixed target rather than
    against other benches is deliberate: the chip is played once, and what
    matters is whether THIS week clears the bar, not whether it beats a bench
    you are not going to field.
    """
    from config import BENCH_BOOST as B
    if points is None:
        return {"call": "unknown", "token": "muted2", "line": "No bench forecast."}
    p = float(points)
    if p >= B["strong"]:
        return {"call": "strong", "token": "mint",
                "line": "A strong week to spend it · %.1f from the bench, "
                        "well past the %.0f you want." % (p, B["target"])}
    if p >= B["target"]:
        return {"call": "on target", "token": "mint",
                "line": "On target · %.1f from the bench against the %.0f "
                        "you want." % (p, B["target"])}
    if p >= B["acceptable"]:
        return {"call": "acceptable", "token": "gold",
                "line": "Acceptable · %.1f from the bench, just under the %.0f "
                        "target." % (p, B["target"])}
    if p >= B["weak"]:
        return {"call": "thin", "token": "orange",
                "line": "Thin · %.1f from the bench against a %.0f target. "
                        "Worth waiting for a better week." % (p, B["target"])}
    return {"call": "wasted", "token": "red",
            "line": "Close to wasted · %.1f from the bench. The chip is worth "
                    "more almost any other week." % p}
