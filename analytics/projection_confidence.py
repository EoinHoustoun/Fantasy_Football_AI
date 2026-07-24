"""Projection confidence · how much to trust each projected-points number.

The projection validates at Spearman ~0.4 with a ~38-point average error, so a
single number is a point on a wide distribution, not a promise. Confidence is
driven by two honest signals:

  - sample size · last season's minutes. A rate from 3000 minutes is far more
    reliable than one from 600 (a small sample inflates and swings).
  - assumption · any player carrying a manual override is a judgement call about
    fitness or role, so it is capped at Low no matter the old sample.

Each player gets a tier (High / Medium / Low) and an honest range around the
point estimate, wider for lower confidence.
"""
from typing import Dict, Optional

import pandas as pd

from config import PROJECTION_CONFIDENCE


def _tier(minutes: float, has_override: bool, cfg: Dict) -> str:
    if has_override:
        return "Low"
    if minutes >= cfg["high_minutes"]:
        return "High"
    if minutes >= cfg["medium_minutes"]:
        return "Medium"
    return "Low"


_DOWNGRADE = {"High": "Medium", "Medium": "Low", "Low": "Low"}


def add_confidence(df: pd.DataFrame, cfg: Optional[Dict] = None) -> pd.DataFrame:
    """Add `confidence` (High/Medium/Low), `confidence_note`, `proj_lo`, `proj_hi`
    to a projection frame. Needs `projected_points`, `last_season_minutes`, and
    (optional) `override_note`, `role` (CB/FB), `changed_club` (bool).

    One tier is knocked off for a harder-to-forecast profile: a fullback (returns
    swing on attack, unlike a CB's DEFCON floor) or a player at a new club (system
    fit unproven). Reasons are combined in `confidence_note`.
    """
    cfg = cfg or PROJECTION_CONFIDENCE
    df = df.copy()
    notes = df["override_note"] if "override_note" in df.columns else pd.Series("", index=df.index)
    mins = df.get("last_season_minutes", pd.Series(0.0, index=df.index)).fillna(0.0)

    df["confidence"] = [
        _tier(float(m), bool(str(n or "")), cfg)
        for m, n in zip(mins, notes)
    ]

    is_fb = (df["role"].astype(str) == "FB") if "role" in df.columns \
        else pd.Series(False, index=df.index)
    moved = df["changed_club"].fillna(False) if "changed_club" in df.columns \
        else pd.Series(False, index=df.index)
    reason = []
    for fb, mv in zip(is_fb, moved):
        bits = []
        if fb:
            bits.append("fullback, harder to call than a CB")
        if mv:
            bits.append("new club, unproven fit")
        reason.append(" · ".join(bits))
    df["confidence_note"] = reason
    downgrade_mask = is_fb | moved
    df.loc[downgrade_mask, "confidence"] = df.loc[downgrade_mask, "confidence"].map(_DOWNGRADE)

    spread = df["confidence"].map(cfg["spread"]).astype(float)
    pts = df["projected_points"].astype(float)
    df["proj_lo"] = (pts * (1.0 - spread)).round(0)
    df["proj_hi"] = (pts * (1.0 + spread)).round(0)
    return df
