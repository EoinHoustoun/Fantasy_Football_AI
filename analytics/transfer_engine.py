"""
Transfer suggestion engine.

Scores every player as a potential transfer target using a weighted composite
of form, fixture ease, xG potential, value, ownership trend, and minutes security.

All weights are tunable in config.py — adjust them after each GW
to reflect what's been predictive.

This module is UI-free and has no Streamlit imports — fully testable in isolation.
"""

import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any

from config import (
    TRANSFER_WEIGHTS, FIXTURE_LOOKAHEAD,
    FPL_GOAL_PTS, FPL_CS_PTS, FPL_ASSIST_PTS, FPL_BONUS_MAX,
    HAUL_THRESHOLD, TWENTY_PLUS_THRESHOLD, TRANSFER_CLOSE_MARGIN,
)


def score_players(
    players_df: pd.DataFrame,
    weights: Optional[dict] = None,
    lookahead: int = FIXTURE_LOOKAHEAD,
) -> pd.DataFrame:
    """
    Compute a transfer_score for every player.

    Each component is normalised to [0, 1] before weighting so that
    players on different scales are comparable.

    Returns the input DataFrame with added columns:
        - score_form, score_fixture, score_xg, score_value,
          score_ownership_trend, score_minutes, transfer_score
    """
    w = weights or TRANSFER_WEIGHTS
    df = players_df.copy()

    fdr_col = f"avg_fdr_next_{lookahead}"
    if fdr_col not in df.columns:
        fdr_col = "avg_fdr_next_6"  # fallback

    # ── Component scores (each normalised 0-1) ────────────────────────────────

    # Form: higher is better
    df["score_form"] = _normalise(df["form"])

    # Fixture ease: use position-aware composite FDR if available, else raw FDR
    att_col = f"composite_att_fdr_next_{lookahead}"
    def_col = f"composite_def_fdr_next_{lookahead}"

    if att_col in df.columns and def_col in df.columns:
        is_def = df["position"].isin(["DEF", "GKP"])
        effective_fdr = df[att_col].where(~is_def, df[def_col])
    elif fdr_col in df.columns:
        effective_fdr = df[fdr_col]
    else:
        effective_fdr = pd.Series(3.0, index=df.index)

    fixture_ease = _normalise(6.0 - effective_fdr)

    # Boost DGW players, penalise BGW players
    if "has_dgw" in df.columns:
        fixture_ease = fixture_ease * df["has_dgw"].map({True: 1.15, False: 1.0}).fillna(1.0)
    if "has_bgw" in df.columns:
        fixture_ease = fixture_ease * df["has_bgw"].map({True: 0.75, False: 1.0}).fillna(1.0)

    df["score_fixture"] = fixture_ease.clip(0, 1)

    # xG potential: rolling xGI (last 4 GWs) is most predictive.
    # Fall back chain: rolling_xgi → npxg (Understat season) → fpl_xgi_per90 → ict_index
    if "rolling_xgi" in df.columns and df["rolling_xgi"].notna().any():
        df["score_xg"] = _normalise(df["rolling_xgi"].fillna(0))
    elif "npxg" in df.columns and df["npxg"].notna().any():
        df["score_xg"] = _normalise(df["npxg"].fillna(0))
    elif "fpl_xgi_per90" in df.columns and df["fpl_xgi_per90"].notna().any():
        df["score_xg"] = _normalise(df["fpl_xgi_per90"].fillna(0))
    else:
        df["score_xg"] = _normalise(df["ict_index"])

    # Value: points per million
    df["score_value"] = _normalise(df["points_per_million"].fillna(0))

    # Ownership trend: high transfer_balance = rising ownership.
    # Cap at 0 (we don't penalise being sold as a buy target score)
    if "transfer_balance" in df.columns:
        df["score_ownership_trend"] = _normalise(df["transfer_balance"].clip(lower=0))
    else:
        df["score_ownership_trend"] = 0.5

    # ── Minutes multiplier (replaces minutes_security additive component) ────
    # Use avg_minutes from DEFCON stats when available, else estimate from totals.
    # Continuous curve: 90 mins=1.0, 75 mins=0.91, 60 mins=0.82, 45 mins=0.71.
    if "avg_minutes" in df.columns and df["avg_minutes"].notna().any():
        avg_mins = df["avg_minutes"].fillna(45.0).clip(0, 90)
    else:
        gws_played = _estimate_gws_played(df)
        avg_mins = (df["minutes"] / max(gws_played, 1)).clip(0, 90)

    df["mins_multiplier"] = ((avg_mins / 90.0) ** 0.5).clip(lower=0.45, upper=1.0)

    # ── Set piece bonus (flat addition before multiplier) ─────────────────────
    # Penalty taker #1 is the biggest bonus — direct route to 6+ pts.
    _nan = pd.Series(np.nan, index=df.index)
    pen_order  = pd.to_numeric(df["penalties_order"]  if "penalties_order"  in df.columns else _nan, errors="coerce")
    corn_order = pd.to_numeric(df["corners_order"]    if "corners_order"    in df.columns else _nan, errors="coerce")
    fk_order   = pd.to_numeric(df["freekicks_order"]  if "freekicks_order"  in df.columns else _nan, errors="coerce")

    df["score_setpiece"] = (
        pen_order.eq(1).fillna(False).astype(float)  * 0.08 +
        pen_order.eq(2).fillna(False).astype(float)  * 0.03 +
        corn_order.le(2).fillna(False).astype(float) * 0.02 +
        fk_order.le(2).fillna(False).astype(float)   * 0.02
    )

    # ── Composite score ───────────────────────────────────────────────────────
    # Minutes is now a multiplier on the whole score, not an additive component.
    # This means a player who only plays 60 mins gets an ~18% score haircut —
    # far more impactful than the old 0.05-weighted additive term.
    base_score = (
        df["score_form"]            * w.get("form", 0.25) +
        df["score_fixture"]         * w.get("fixture_ease", 0.25) +
        df["score_xg"]              * w.get("xg_potential", 0.20) +
        df["score_value"]           * w.get("value", 0.15) +
        df["score_ownership_trend"] * w.get("ownership_trend", 0.10) +
        df["score_setpiece"]
    )

    df["transfer_score"] = (base_score * df["mins_multiplier"]).round(4)
    df["score_minutes"]  = df["mins_multiplier"]  # keep for display

    return df


def get_transfer_targets(
    players_df: pd.DataFrame,
    position: Optional[str] = None,
    max_price: Optional[float] = None,
    min_price: Optional[float] = None,
    exclude_team_ids: Optional[List[int]] = None,
    top_n: int = 20,
    weights: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Return top N transfer targets, optionally filtered by position and price.

    Args:
        players_df: Output of build_player_universe()
        position: "GKP", "DEF", "MID", or "FWD" — or None for all
        max_price: Maximum price in £m
        min_price: Minimum price in £m
        exclude_team_ids: List of team IDs to exclude (e.g. teams you already have 3 of)
        top_n: Number of results to return
        weights: Override default TRANSFER_WEIGHTS

    Returns:
        DataFrame of top_n players sorted by transfer_score descending
    """
    df = score_players(players_df, weights=weights)

    # Filter: only available players
    df = df[df["status"] == "a"].copy()

    if position:
        df = df[df["position"] == position]
    if max_price is not None:
        df = df[df["price"] <= max_price]
    if min_price is not None:
        df = df[df["price"] >= min_price]
    if exclude_team_ids:
        df = df[~df["team_id"].isin(exclude_team_ids)]

    display_cols = [
        "web_name", "team", "position", "price", "ownership",
        "form", "total_points", "points_per_million",
        f"avg_fdr_next_{FIXTURE_LOOKAHEAD}",
        "transfer_score",
        "score_form", "score_fixture", "score_xg", "score_value",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    return (
        df[available_cols]
        .sort_values("transfer_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def apply_free_hit_adjustment(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    current_gw: int,
    free_hit_gw: int,
) -> pd.DataFrame:
    """
    Recalculate season_avg_fdr and remaining_fixtures excluding the Free Hit GW.

    Your regular squad doesn't play in the Free Hit week — that GW is played
    with a completely different temporary team, so it must not count towards
    regular-squad season projections or fixture difficulty averages.
    """
    # Remaining fixtures for the regular squad: exclude the free hit week
    remaining = fixtures_df[
        (fixtures_df["gameweek"] >= current_gw) &
        (fixtures_df["gameweek"] != free_hit_gw)
    ].copy()

    team_fdrs = {}  # type: Dict[int, List[float]]
    for _, row in remaining.iterrows():
        for side in ("home", "away"):
            tid = int(row["home_team_id"] if side == "home" else row["away_team_id"])
            fdr = float(row["home_fdr"]   if side == "home" else row["away_fdr"])
            team_fdrs.setdefault(tid, []).append(fdr)

    rows = [
        {
            "team_id":            tid,
            "season_avg_fdr":     round(float(np.mean(fdrs)), 2),
            "remaining_fixtures": len(fdrs),
        }
        for tid, fdrs in team_fdrs.items()
    ]
    adj = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["team_id", "season_avg_fdr", "remaining_fixtures"]
    )

    df = players_df.drop(columns=["season_avg_fdr", "remaining_fixtures"], errors="ignore")
    df = df.merge(adj, on="team_id", how="left")
    df["season_avg_fdr"]     = df["season_avg_fdr"].fillna(3.0)
    df["remaining_fixtures"] = df["remaining_fixtures"].fillna(7).astype(int)
    return df


def get_free_hit_targets(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    free_hit_gw: int,
    top_n: int = 15,
) -> pd.DataFrame:
    """
    Return the best players to target specifically for the Free Hit GW.

    Ranked by: FDR in that GW (easiest first), then form.
    Returns only available players with a fixture in that GW.
    """
    gw_fixtures = fixtures_df[fixtures_df["gameweek"] == free_hit_gw].copy()

    # Build team_id -> fdr mapping for that GW
    fdr_map = {}
    for _, row in gw_fixtures.iterrows():
        fdr_map[int(row["home_team_id"])] = float(row["home_fdr"])
        fdr_map[int(row["away_team_id"])] = float(row["away_fdr"])

    df = players_df[players_df["status"] == "a"].copy()
    df["fh_fdr"] = df["team_id"].map(fdr_map)
    df = df.dropna(subset=["fh_fdr"])  # no fixture = blank GW

    df = df.sort_values(["fh_fdr", "form"], ascending=[True, False])

    cols = ["web_name", "team", "position", "price", "form",
            "total_points", "fh_fdr", "ownership"]
    available = [c for c in cols if c in df.columns]
    return df[available].head(top_n).reset_index(drop=True)


def estimate_season_points(players_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add `projected_season_pts` column: rough estimate of points remaining this season.

    Method: points_per_game * remaining_fixtures * fixture_ease_multiplier
    Fixture ease: FDR 1 = 1.3x, FDR 3 = 1.0x, FDR 5 = 0.7x
    """
    df = players_df.copy()
    ppg = df["points_per_game"].fillna(0)

    remaining = df["remaining_fixtures"] if "remaining_fixtures" in df.columns \
        else pd.Series(8, index=df.index)
    season_fdr = df["season_avg_fdr"] if "season_avg_fdr" in df.columns \
        else pd.Series(3.0, index=df.index)

    ease = 1.0 + (3.0 - season_fdr) * 0.15
    df["projected_season_pts"] = (ppg * remaining * ease).round(1)
    return df


def estimate_ceiling(players_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add `ceiling_pts` column: estimated maximum points a player could score in their
    best upcoming game.

    Uses xG/xA rates (or goals/assists as fallback), position scoring, CS rate,
    and upcoming fixture ease.  A 2.5x multiplier models a "good day" scenario.

    Also adds:
        haul_candidate  : ceiling_pts >= HAUL_THRESHOLD
        twenty_plus     : ceiling_pts >= TWENTY_PLUS_THRESHOLD
    """
    df = players_df.copy()

    gws_played = (df["minutes"] / 90).clip(lower=1)

    # Use FPL's Opta-based per90 xG (most reliable source for ceiling)
    if "fpl_xg_per90" in df.columns and df["fpl_xg_per90"].notna().any():
        xg_pg = df["fpl_xg_per90"].fillna(0)
        xa_pg = df["fpl_xa_per90"].fillna(0) if "fpl_xa_per90" in df.columns else xg_pg * 0.5
    elif "xg" in df.columns and df["xg"].notna().any():
        xg_pg = df["xg"].fillna(0) / gws_played
        xa_pg = df["xa"].fillna(0) / gws_played
    else:
        xg_pg = df["goals_scored"] / gws_played
        xa_pg = df["assists"] / gws_played

    goal_pts = df["position"].map(FPL_GOAL_PTS).fillna(4)
    cs_pts   = df["position"].map(FPL_CS_PTS).fillna(0)
    cs_rate  = (df["clean_sheets"] / gws_played).clip(0, 1)

    fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
    if fdr_col in df.columns:
        fixture_mult = (1.0 + (3.0 - df[fdr_col]) * 0.2).clip(0.5, 1.5)
    else:
        fixture_mult = 1.0

    df["ceiling_pts"] = (
        2.0                               # minutes (60+)
        + xg_pg * 2.5 * goal_pts          # goals in a "good game"
        + xa_pg * 2.5 * FPL_ASSIST_PTS   # assists in a "good game"
        + cs_rate * cs_pts                # clean sheet (weighted by rate)
        + FPL_BONUS_MAX                   # max bonus
    ).multiply(fixture_mult).round(1)

    df["haul_candidate"] = df["ceiling_pts"] >= HAUL_THRESHOLD
    df["twenty_plus"]    = df["ceiling_pts"] >= TWENTY_PLUS_THRESHOLD
    return df


def build_transfer_reasoning(row: pd.Series) -> str:
    """
    Generate a plain-English explanation for why a player is recommended.
    Returns a markdown string.
    """
    name  = row.get("web_name", "?")
    pos   = row.get("position", "")
    team  = row.get("team", "")
    price = row.get("price", 0)

    reasons = []

    form = float(row.get("form", 0) or 0)
    if form >= 8:
        reasons.append(f"exceptional form — {form:.1f} pts/game recently")
    elif form >= 6:
        reasons.append(f"strong form ({form:.1f} pts/game)")
    elif form >= 4.5:
        reasons.append(f"good form ({form:.1f} pts/game)")

    fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
    avg_fdr = float(row.get(fdr_col, 3.0) or 3.0)
    if avg_fdr <= 2.0:
        reasons.append(f"excellent upcoming fixtures (avg FDR {avg_fdr:.1f}/5 over next {FIXTURE_LOOKAHEAD} GWs)")
    elif avg_fdr <= 2.5:
        reasons.append(f"favourable upcoming fixtures (avg FDR {avg_fdr:.1f}/5)")

    season_fdr = float(row.get("season_avg_fdr", 3.0) or 3.0)
    if season_fdr <= 2.3:
        reasons.append(f"best fixtures to end of season (season avg FDR {season_fdr:.1f})")

    proj = row.get("projected_season_pts")
    if proj and proj > 0:
        reasons.append(f"projects ~{proj:.0f} pts for the rest of the season")

    npxg = row.get("npxg")
    xg   = row.get("xg")
    xg_val = float(npxg if npxg and not pd.isna(npxg) else (xg if xg and not pd.isna(xg) else 0))
    if xg_val >= 8:
        reasons.append(f"elite xG output this season ({xg_val:.1f} npxG)")
    elif xg_val >= 5:
        reasons.append(f"high xG output ({xg_val:.1f} npxG)")

    ceiling = float(row.get("ceiling_pts", 0) or 0)
    if ceiling >= TWENTY_PLUS_THRESHOLD:
        reasons.append(f"20+ point ceiling — genuine haul threat ({ceiling:.0f} ceiling score)")
    elif ceiling >= HAUL_THRESHOLD:
        reasons.append(f"strong haul potential ({ceiling:.0f} ceiling score)")

    balance = int(row.get("transfer_balance", 0) or 0)
    if balance > 100_000:
        reasons.append(f"managers are piling in ({balance / 1000:.0f}k net transfers this GW)")
    elif balance > 30_000:
        reasons.append(f"rising in the market ({balance / 1000:.0f}k net transfers in)")

    ppm = float(row.get("points_per_million", 0) or 0)
    if ppm >= 12:
        reasons.append(f"outstanding value at £{price:.1f}m ({ppm:.1f} pts/£m)")
    elif ppm >= 9 and price < 6.5:
        reasons.append(f"great budget pick at £{price:.1f}m ({ppm:.1f} pts/£m)")

    if not reasons:
        reasons.append("best composite score across all metrics this week")

    note = f"**{name}** ({team}, {pos}, £{price:.1f}m): " + " · ".join(reasons) + "."
    return note


def get_top_recommendation(
    players_df: pd.DataFrame,
    owned_names: Optional[List[str]] = None,
    budget: Optional[float] = None,
    position: Optional[str] = None,
    weights: Optional[dict] = None,
    free_hit_gw: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Return the #1 transfer recommendation (or top 3 if scores are close).

    Returns a dict:
        top      : pd.Series — the #1 player row (with all enriched columns)
        close    : list of dicts [{player, reasoning}, ...] for top 3 if close
        is_close : bool — True if top 3 scores are within TRANSFER_CLOSE_MARGIN
        free_hit : bool — whether this is Free Hit mode (no budget/ownership filter)
    """
    is_free_hit = free_hit_gw is not None

    df = score_players(players_df, weights=weights)
    df = estimate_season_points(df)
    df = estimate_ceiling(df)

    # Filter to available players
    df = df[df["status"] == "a"].copy()

    # In Free Hit mode skip budget and owned-player filters (you build a fresh team)
    if not is_free_hit:
        if position:
            df = df[df["position"] == position]
        if budget is not None and budget > 3.5:
            df = df[df["price"] <= budget]
        if owned_names:
            df = df[~df["web_name"].isin(owned_names)]
    else:
        if position:
            df = df[df["position"] == position]

    if df.empty:
        return {"top": None, "close": [], "is_close": False, "free_hit": is_free_hit}

    df = df.sort_values("transfer_score", ascending=False).reset_index(drop=True)
    top3 = df.head(3)

    score_spread = (
        float(top3.iloc[0]["transfer_score"]) - float(top3.iloc[-1]["transfer_score"])
        if len(top3) >= 3 else 0.0
    )
    is_close = score_spread <= TRANSFER_CLOSE_MARGIN

    close_list = [
        {
            "player":    top3.iloc[i],
            "reasoning": build_transfer_reasoning(top3.iloc[i]),
        }
        for i in range(min(3, len(top3)))
    ]

    return {
        "top":       top3.iloc[0],
        "close":     close_list,
        "is_close":  is_close,
        "free_hit":  is_free_hit,
    }


def _normalise(series: pd.Series) -> pd.Series:
    """Min-max normalise a series to [0, 1]. Returns 0.5 if all values are equal."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(0.5, index=series.index)
    return (series - mn) / (mx - mn)


def _estimate_gws_played(df: pd.DataFrame) -> int:
    """Rough estimate of how many GWs have been played based on minutes data."""
    max_minutes = df["minutes"].max()
    return max(1, int(max_minutes / 90))
