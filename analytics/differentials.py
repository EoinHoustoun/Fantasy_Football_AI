"""
Differentials spotter · smarter model.

A good differential is not just "low owned + decent score". A great differential
combines several underlying signals:

  • Haul ceiling      · xGI per 90 × fixture ease × position goal weight
  • Momentum          · recent form relative to season PPG (are they ramping?)
  • Minutes security  · avg minutes / 90 (they must actually play)
  • Rank upside       · a logistic function of ownership (sharp < 10%, flat > 20%)

  diff_score = clip( ceiling × momentum × minutes × rank_upside , 0..10 )

Each player is also assigned one or more qualitative tags (e.g. "Fixture Swing",
"Set-Piece Threat", "Underlying Burst") so the UI can explain *why* each
differential is interesting.

This module is UI-free and fully testable in isolation.
"""

from __future__ import annotations

import math
from typing import List, Optional

import numpy as np
import pandas as pd

from config import DIFFERENTIAL_MAX_OWNERSHIP, FIXTURE_LOOKAHEAD


# ── Position goal weights (FPL points per goal) ────────────────────────────────
POS_GOAL_WEIGHT = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}


def get_differentials(
    players_df: pd.DataFrame,
    max_ownership: float = DIFFERENTIAL_MAX_OWNERSHIP,
    position: Optional[str] = None,
    max_price: Optional[float] = None,
    min_minutes: int = 300,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return top differential picks with a composite score and tags.

    Args:
        players_df: Output of build_player_universe()
        max_ownership: Only include players owned by <= this % of managers
        position: Optional position filter
        max_price: Optional max price in £m
        min_minutes: Minutes floor so we don't suggest 20-min cameos
        top_n: Number of results

    Returns:
        DataFrame sorted by diff_score desc, with:
          web_name, team, position, price, ownership, form, total_points,
          points_per_million, avg_fdr_next_N, xgi_per90 (when available),
          haul_ceiling, momentum, minutes_factor, rank_upside,
          differential_score, tags (list[str])
    """
    df = players_df.copy()

    # Resolve the right FDR column
    fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
    if fdr_col not in df.columns:
        fdr_col = next((c for c in df.columns if c.startswith("avg_fdr_next_")), None)

    # ── Filters ────────────────────────────────────────────────────────────────
    df = df[df["status"] == "a"].copy()
    if "minutes" in df.columns:
        df = df[df["minutes"].fillna(0) >= min_minutes].copy()
    df = df[df["ownership"] <= max_ownership].copy()
    if position:
        df = df[df["position"] == position]
    if max_price is not None:
        df = df[df["price"] <= max_price]

    if df.empty:
        return df

    # ── Signal 1: Haul ceiling ────────────────────────────────────────────────
    # xGI per 90 if available, else FPL's expected-goal-involvements, else ICT
    xgi_src = None
    for col in ("rolling_xgi", "fpl_xgi_per90", "xgi_per90", "npxg"):
        if col in df.columns and df[col].notna().any():
            xgi_src = col
            break
    xgi_raw = df[xgi_src].fillna(0) if xgi_src else df.get("ict_index", pd.Series(0, index=df.index)).fillna(0)
    xgi_norm = _normalise(xgi_raw)

    if fdr_col and fdr_col in df.columns:
        fixture_ease = ((6.0 - df[fdr_col].astype(float)) / 4.0).clip(0, 1)
    else:
        fixture_ease = pd.Series(0.5, index=df.index)

    goal_weight = df["position"].map(POS_GOAL_WEIGHT).fillna(5) / 6.0   # 0.66..1.0
    df["haul_ceiling"] = (xgi_norm * 0.55 + fixture_ease * 0.45) * goal_weight

    # ── Signal 2: Momentum ────────────────────────────────────────────────────
    # form vs season PPG · ramping up?
    ppg = df.get("points_per_game", pd.Series(0, index=df.index)).astype(float).fillna(0).clip(lower=0.1)
    form = df.get("form", pd.Series(0, index=df.index)).astype(float).fillna(0).clip(lower=0)
    ratio = (form / ppg).clip(0.3, 2.5)
    df["momentum"] = ((ratio - 0.3) / 2.2).clip(0, 1)            # 0..1

    # ── Signal 3: Minutes security ────────────────────────────────────────────
    if "avg_minutes" in df.columns and df["avg_minutes"].notna().any():
        avg_mins = df["avg_minutes"].fillna(45)
    else:
        gws = max(1, int(df["minutes"].max() / 90)) if "minutes" in df.columns else 10
        avg_mins = (df["minutes"].fillna(0) / gws).clip(0, 90)
    df["minutes_factor"] = (avg_mins / 90.0).clip(0, 1)

    # ── Signal 4: Rank upside (logistic on ownership) ────────────────────────
    # Peaks near 1 for very low ownership, drops sharply above 10-15%
    own = df["ownership"].astype(float).fillna(0).clip(lower=0.1)
    df["rank_upside"] = 1.0 / (1.0 + np.exp((own - 10.0) / 4.0))

    # ── Composite score (scaled 0..10 for readability) ────────────────────────
    df["differential_score"] = (
        df["haul_ceiling"]
        * (0.6 + 0.4 * df["momentum"])       # momentum is a multiplier (0.6..1.0)
        * df["minutes_factor"]
        * df["rank_upside"]
        * 10.0
    ).round(2)

    # ── Qualitative tags ─────────────────────────────────────────────────────
    df["tags"] = df.apply(lambda r: _build_tags(r, fdr_col), axis=1)

    display_cols = [
        "web_name", "team", "position", "price", "ownership",
        "form", "total_points", "points_per_million",
    ]
    if fdr_col:
        display_cols.append(fdr_col)
    if "team_code" in df.columns:
        display_cols.append("team_code")
    if "team_short" in df.columns:
        display_cols.append("team_short")
    if "upcoming_fixtures" in df.columns:
        display_cols.append("upcoming_fixtures")
    if xgi_src:
        display_cols.append(xgi_src)
    display_cols += [
        "haul_ceiling", "momentum", "minutes_factor", "rank_upside",
        "differential_score", "tags",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    return (
        df[available_cols]
        .sort_values("differential_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def _build_tags(row: pd.Series, fdr_col: Optional[str]) -> List[str]:
    tags: List[str] = []

    own = float(row.get("ownership", 0) or 0)
    form = float(row.get("form", 0) or 0)
    ppg = float(row.get("points_per_game", 0) or 0)
    mins_factor = float(row.get("minutes_factor", 0) or 0)

    # Template breaker: genuinely good output at very low ownership
    if own <= 6 and ppg >= 4.5:
        tags.append("Template Breaker")

    # Hot right now: recent form well above season PPG
    if ppg > 0 and form >= max(5.0, ppg * 1.4):
        tags.append("Hot Run")

    # Starting lock: playing nearly every minute
    if mins_factor >= 0.85:
        tags.append("Nailed-On Starter")

    # Set-piece threat: on pens or direct FKs
    pen = row.get("penalties_order")
    fk = row.get("freekicks_order")
    if (pen is not None and not pd.isna(pen) and int(pen) == 1) or \
       (fk is not None and not pd.isna(fk) and int(fk) == 1):
        tags.append("Set-Piece Threat")

    # Underlying burst: high xGI rate, lowish output yet (regression candidate)
    xgi = row.get("fpl_xgi_per90") or row.get("xgi_per90") or row.get("rolling_xgi")
    goals_plus_assists = float(row.get("goals_scored", 0) or 0) + float(row.get("assists", 0) or 0)
    minutes = float(row.get("minutes", 0) or 0)
    if xgi is not None and not pd.isna(xgi) and minutes > 450:
        expected = (float(xgi) * minutes) / 90.0
        if expected - goals_plus_assists >= 1.5:
            tags.append("Underlying Burst")

    # Easy fixture run
    if fdr_col:
        fdr_val = row.get(fdr_col)
        if fdr_val is not None and not pd.isna(fdr_val) and float(fdr_val) <= 2.4:
            tags.append("Dream Fixtures")

    # Rising: owners adding this player
    bal = row.get("transfer_balance")
    if bal is not None and not pd.isna(bal) and int(bal) > 40_000:
        tags.append("Rising")

    return tags


def _normalise(series: pd.Series) -> pd.Series:
    mn, mx = float(series.min()), float(series.max())
    if mx == mn:
        return pd.Series(0.5, index=series.index)
    return (series - mn) / (mx - mn)
