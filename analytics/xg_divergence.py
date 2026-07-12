"""
xG underperformance / overperformance tracker.

Identifies players whose actual goal/assist output significantly diverges
from their expected goals (xG) and expected assists (xA).

Players with xG >> actual goals are "due" · statistically likely to score
soon as regression to the mean kicks in.

Players with actual goals >> xG may be overperforming and could regress.

This module is UI-free and fully testable in isolation.
"""

import pandas as pd
import numpy as np
from typing import Optional, List

from config import XG_MIN_THRESHOLD, XG_GAP_THRESHOLD


def get_xg_underperformers(
    players_df: pd.DataFrame,
    min_xg: float = XG_MIN_THRESHOLD,
    min_gap: float = XG_GAP_THRESHOLD,
    positions: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Return players who have accumulated significant xG but scored fewer goals.

    These players are underperforming their expected output and are candidates
    for a scoring burst (regression to the mean).

    Args:
        players_df: Output of build_player_universe()
        min_xg: Minimum xG to qualify (filters out players with negligible shots)
        min_gap: Minimum xG - actual goals gap to qualify
        positions: List of positions to include. Defaults to ["MID", "FWD"]

    Returns:
        DataFrame sorted by xg_gap descending (most underperforming first)
    """
    df = players_df.copy()

    if "xg" not in df.columns or df["xg"].isna().all():
        return pd.DataFrame(columns=["web_name", "team", "position", "xg_gap"])

    if positions is None:
        positions = ["MID", "FWD"]

    df = df[
        (df["position"].isin(positions)) &
        (df["xg"] >= min_xg) &
        (df["xg_gap"] >= min_gap) &
        (df["status"] == "a")
    ].copy()

    # Compute a "haul potential" score:
    # combines gap size, form (are they getting chances?), and fixture ease
    fdr_col = next((c for c in df.columns if c.startswith("avg_fdr_next_")), None)
    if fdr_col:
        df["fixture_ease"] = (6 - df[fdr_col]) / 4   # 0-1 scale
    else:
        df["fixture_ease"] = 0.5

    df["haul_potential"] = (
        df["xg_gap"] * 0.5 +
        df["form"].clip(0, 10) / 10 * 0.3 +
        df["fixture_ease"] * 0.2
    ).round(3)

    display_cols = [
        "web_name", "team", "team_code", "team_short", "position", "price", "ownership",
        "xg", "goals_scored", "xg_gap",
        "xa", "assists",
        "form", "minutes",
        "haul_potential",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    return (
        df[available_cols]
        .sort_values("haul_potential", ascending=False)
        .reset_index(drop=True)
    )


def get_xg_overperformers(
    players_df: pd.DataFrame,
    min_goals: int = 3,
    min_overperformance: float = 1.5,
    positions: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Return players who have scored significantly more goals than their xG suggests.

    These players may be due a regression · useful for identifying who to sell.

    Args:
        min_goals: Minimum actual goals scored to qualify
        min_overperformance: Minimum (actual - xG) gap to qualify
    """
    df = players_df.copy()

    if "xg" not in df.columns or df["xg"].isna().all():
        return pd.DataFrame()

    if positions is None:
        positions = ["MID", "FWD"]

    # xg_gap = xG - actual. Overperformers have negative xg_gap.
    df["overperformance_gap"] = (df["goals_scored"] - df["xg"]).round(2)

    df = df[
        (df["position"].isin(positions)) &
        (df["goals_scored"] >= min_goals) &
        (df["overperformance_gap"] >= min_overperformance)
    ].copy()

    display_cols = [
        "web_name", "team", "team_code", "team_short", "position", "price", "ownership",
        "xg", "goals_scored", "overperformance_gap", "form",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    return (
        df[available_cols]
        .sort_values("overperformance_gap", ascending=False)
        .reset_index(drop=True)
    )
