"""
Differentials spotter.

Identifies low-ownership players with high upside — the picks that give
you an edge over the template team.

A differential is defined as a player owned by < DIFFERENTIAL_MAX_OWNERSHIP %
of managers who scores well on a ceiling-adjusted metric.

This module is UI-free and fully testable in isolation.
"""

import pandas as pd
import numpy as np
from typing import Optional

from config import DIFFERENTIAL_MAX_OWNERSHIP, FIXTURE_LOOKAHEAD


def get_differentials(
    players_df: pd.DataFrame,
    max_ownership: float = DIFFERENTIAL_MAX_OWNERSHIP,
    position: Optional[str] = None,
    max_price: Optional[float] = None,
    top_n: int = 20,
) -> pd.DataFrame:
    """
    Return top differential picks: low ownership, high ceiling.

    Differential score formula:
        ceiling = form * fixture_ease * (xg_per90 if available else ict_index_norm)
        differential_score = ceiling / (ownership + 1)   # +1 avoids division by zero

    Args:
        players_df: Output of build_player_universe()
        max_ownership: Only include players owned by <= this % of managers
        position: Filter by position
        max_price: Filter by max price in £m
        top_n: Number of results

    Returns:
        DataFrame sorted by differential_score descending
    """
    df = players_df.copy()
    fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
    if fdr_col not in df.columns:
        fdr_col = next((c for c in df.columns if c.startswith("avg_fdr_next_")), None)

    # Only available, playing players
    df = df[df["status"] == "a"].copy()
    df = df[df["minutes"] > 0].copy()
    df = df[df["ownership"] <= max_ownership].copy()

    if position:
        df = df[df["position"] == position]
    if max_price is not None:
        df = df[df["price"] <= max_price]

    # Fixture ease (0-1, higher = easier)
    if fdr_col and fdr_col in df.columns:
        df["fixture_ease"] = ((6 - df[fdr_col]) / 4).clip(0, 1)
    else:
        df["fixture_ease"] = 0.5

    # Ceiling metric: prefer xG-based, fall back to ICT
    if "xg_per90" in df.columns and df["xg_per90"].notna().any():
        ceiling_raw = df["xg_per90"].fillna(0)
    else:
        ceiling_raw = df["ict_index"] / df["ict_index"].max().clip(lower=1)

    ceiling_raw = ceiling_raw.fillna(0)

    # Differential score
    df["ceiling"] = (
        df["form"].clip(0, 10) / 10 * 0.4 +
        df["fixture_ease"] * 0.3 +
        _normalise(ceiling_raw) * 0.3
    )
    df["differential_score"] = (df["ceiling"] / (df["ownership"] + 1)).round(4)

    display_cols = [
        "web_name", "team", "position", "price", "ownership",
        "form", "total_points", "points_per_million",
        fdr_col if fdr_col else "avg_fdr_next_6",
        "differential_score",
    ]
    if "xg_per90" in df.columns:
        display_cols.insert(-1, "xg_per90")

    available_cols = [c for c in display_cols if c in df.columns]

    return (
        df[available_cols]
        .sort_values("differential_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def _normalise(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(0.5, index=series.index)
    return (series - mn) / (mx - mn)
