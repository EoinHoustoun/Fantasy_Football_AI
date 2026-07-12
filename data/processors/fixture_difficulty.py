"""
Fixture difficulty processor.

Calculates average FDR over upcoming gameweeks for each team,
and attaches a fixture ticker (list of upcoming fixtures with difficulty)
to each player.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple

from config import FIXTURE_LOOKAHEAD


def get_team_fixture_ratings(
    fixtures_df: pd.DataFrame,
    current_gw: int,
    lookahead: int = FIXTURE_LOOKAHEAD,
) -> pd.DataFrame:
    """
    For each team, return a DataFrame with upcoming fixture difficulty.

    Returns a DataFrame indexed by team_id with columns:
        - avg_fdr_next_N: average FDR over next N gameweeks
        - fixtures: list of dicts [{gw, opponent, fdr, home}, ...]
    """
    upcoming = fixtures_df[
        (fixtures_df["gameweek"] >= current_gw) &
        (fixtures_df["gameweek"] < current_gw + lookahead)
    ].copy()

    records = {}

    # For each fixture, add entries for both home and away team
    for _, row in upcoming.iterrows():
        for side in ("home", "away"):
            team_id   = row["home_team_id"] if side == "home" else row["away_team_id"]
            opp       = row["away_team"]    if side == "home" else row["home_team"]
            fdr       = row["home_fdr"]     if side == "home" else row["away_fdr"]
            is_home   = (side == "home")

            if team_id not in records:
                records[team_id] = {"fixtures": []}

            records[team_id]["fixtures"].append({
                "gw":       row["gameweek"],
                "opponent": opp,
                "fdr":      fdr,
                "home":     is_home,
            })

    # Build summary rows
    rows = []
    for team_id, data in records.items():
        fdrs = [f["fdr"] for f in data["fixtures"]]
        rows.append({
            "team_id":       team_id,
            f"avg_fdr_next_{lookahead}": round(np.mean(fdrs), 2) if fdrs else 3.0,
            "upcoming_fixtures": data["fixtures"],
        })

    return pd.DataFrame(rows)


def attach_fixture_difficulty(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    current_gw: int,
    lookahead: int = FIXTURE_LOOKAHEAD,
) -> pd.DataFrame:
    """
    Merge fixture difficulty data onto the players DataFrame.

    Adds columns:
        - avg_fdr_next_N
        - upcoming_fixtures
    """
    team_fdrs = get_team_fixture_ratings(fixtures_df, current_gw, lookahead)
    merged = players_df.merge(team_fdrs, on="team_id", how="left")
    fdr_col = f"avg_fdr_next_{lookahead}"
    if fdr_col in merged.columns:
        merged[fdr_col] = merged[fdr_col].fillna(3.0)
    else:
        merged[fdr_col] = 3.0
    return merged


def attach_season_difficulty(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    current_gw: int,
) -> pd.DataFrame:
    """
    Attach season-long fixture metrics to each player.

    Adds columns:
        - season_avg_fdr   : average FDR across all remaining fixtures
        - remaining_fixtures: count of remaining fixtures this season
    """
    remaining = fixtures_df[fixtures_df["gameweek"] >= current_gw].copy()

    team_fdrs = {}  # team_id -> list of FDR values

    for _, row in remaining.iterrows():
        for side in ("home", "away"):
            team_id = row["home_team_id"] if side == "home" else row["away_team_id"]
            fdr     = row["home_fdr"]     if side == "home" else row["away_fdr"]
            if team_id not in team_fdrs:
                team_fdrs[team_id] = []
            team_fdrs[team_id].append(fdr)

    rows = []
    for team_id, fdrs in team_fdrs.items():
        rows.append({
            "team_id":            team_id,
            "season_avg_fdr":     round(np.mean(fdrs), 2) if fdrs else 3.0,
            "remaining_fixtures": len(fdrs),
        })

    season_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["team_id", "season_avg_fdr", "remaining_fixtures"]
    )

    merged = players_df.merge(season_df, on="team_id", how="left")
    merged["season_avg_fdr"]     = merged["season_avg_fdr"].fillna(3.0)
    merged["remaining_fixtures"] = merged["remaining_fixtures"].fillna(8).astype(int)
    return merged


def attach_composite_fixture_difficulty(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    current_gw: int,
    team_stats: pd.DataFrame,
    lookahead: int = FIXTURE_LOOKAHEAD,
    dc_ratings: Optional[Dict] = None,
) -> pd.DataFrame:
    """
    Compute composite fixture difficulty.

    When Dixon-Coles ratings are available (dc_ratings):
        Attackers: 50% DC defence strength + 50% Understat xGC
        Defenders: 50% DC attack strength  + 50% Understat xGA

    Without DC ratings (fallback):
        Attackers: 35% FPL FDR + 65% Understat xGC
        Defenders: 35% FPL FDR + 65% Understat xGA

    DC parameters are in log-space:
        defenses[opp] high → leaky defence → easy for attackers → low FDR
        attacks[opp]  high → dangerous attack → hard for defenders → high FDR

    Adds:
        composite_att_fdr_next_N : composite FDR for attackers (MID/FWD)
        composite_def_fdr_next_N : composite FDR for defenders (DEF/GKP)
    """
    xgc_map = dict(zip(team_stats["team"], team_stats["xgc_per_game"]))
    xga_map = dict(zip(team_stats["team"], team_stats["xga_per_game"]))

    all_xgc = [v for v in xgc_map.values() if v > 0]
    all_xga = [v for v in xga_map.values() if v > 0]
    xgc_min = min(all_xgc) if all_xgc else 0.5
    xgc_max = max(all_xgc) if all_xgc else 2.5
    xga_min = min(all_xga) if all_xga else 0.5
    xga_max = max(all_xga) if all_xga else 2.5

    def xgc_to_fdr(xgc: float) -> float:
        if xgc_max == xgc_min:
            return 3.0
        norm = (xgc - xgc_min) / (xgc_max - xgc_min)
        return round(1.0 + 4.0 * (1.0 - norm), 2)

    def xga_to_fdr(xga: float) -> float:
        if xga_max == xga_min:
            return 3.0
        norm = (xga - xga_min) / (xga_max - xga_min)
        return round(1.0 + 4.0 * norm, 2)

    # ── DC helpers ─────────────────────────────────────────────────────────────
    _use_dc = dc_ratings is not None and dc_ratings.get("attacks")
    if _use_dc:
        dc_att = dc_ratings["attacks"]   # type: ignore[index]
        dc_def = dc_ratings["defenses"]  # type: ignore[index]
        _att_vals = list(dc_def.values())   # opponent's defence leakiness
        _def_vals = list(dc_att.values())   # opponent's attack danger
        _att_min, _att_max = min(_att_vals), max(_att_vals)
        _def_min, _def_max = min(_def_vals), max(_def_vals)

        def dc_att_fdr(opp: str) -> float:
            """DC-derived FDR for attackers: high opp defence = hard."""
            v = dc_def.get(opp)
            if v is None:
                return 3.0
            if _att_max == _att_min:
                return 3.0
            # high defenses[opp] = leaky = easy for attacker = low FDR
            norm = (v - _att_min) / (_att_max - _att_min)
            return round(1.0 + 4.0 * (1.0 - norm), 2)

        def dc_def_fdr(opp: str) -> float:
            """DC-derived FDR for defenders: high opp attack = hard."""
            v = dc_att.get(opp)
            if v is None:
                return 3.0
            if _def_max == _def_min:
                return 3.0
            norm = (v - _def_min) / (_def_max - _def_min)
            return round(1.0 + 4.0 * norm, 2)

    upcoming = fixtures_df[
        (fixtures_df["gameweek"] >= current_gw) &
        (fixtures_df["gameweek"] < current_gw + lookahead)
    ].copy()

    xgc_fallback = float(np.mean(all_xgc)) if all_xgc else 1.5
    xga_fallback = float(np.mean(all_xga)) if all_xga else 1.2

    records: Dict[int, Dict[str, List[float]]] = {}
    for _, row in upcoming.iterrows():
        for side in ("home", "away"):
            team_id  = int(row["home_team_id"] if side == "home" else row["away_team_id"])
            opp_name = str(row["away_team"]    if side == "home" else row["home_team"])
            raw_fdr  = float(row["home_fdr"]   if side == "home" else row["away_fdr"])

            opp_xgc = float(xgc_map.get(opp_name, xgc_fallback))
            opp_xga = float(xga_map.get(opp_name, xga_fallback))

            if _use_dc:
                comp_att = round(0.50 * dc_att_fdr(opp_name) + 0.50 * xgc_to_fdr(opp_xgc), 2)
                comp_def = round(0.50 * dc_def_fdr(opp_name) + 0.50 * xga_to_fdr(opp_xga), 2)
            else:
                comp_att = round(0.35 * raw_fdr + 0.65 * xgc_to_fdr(opp_xgc), 2)
                comp_def = round(0.35 * raw_fdr + 0.65 * xga_to_fdr(opp_xga), 2)

            if team_id not in records:
                records[team_id] = {"att": [], "def": []}
            records[team_id]["att"].append(comp_att)
            records[team_id]["def"].append(comp_def)

    att_col = f"composite_att_fdr_next_{lookahead}"
    def_col = f"composite_def_fdr_next_{lookahead}"

    rows = [
        {
            "team_id": tid,
            att_col: round(float(np.mean(data["att"])), 2),
            def_col: round(float(np.mean(data["def"])), 2),
        }
        for tid, data in records.items()
    ]
    comp_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["team_id", att_col, def_col]
    )

    merged = players_df.merge(comp_df, on="team_id", how="left")
    merged[att_col] = merged[att_col].fillna(3.0)
    merged[def_col] = merged[def_col].fillna(3.0)
    return merged


def attach_dgw_bgw(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    current_gw: int,
    lookahead: int = FIXTURE_LOOKAHEAD,
) -> pd.DataFrame:
    """
    Detect Double Gameweeks (2+ fixtures) and Blank Gameweeks (0 fixtures)
    for each player within the lookahead window.

    Adds:
        has_dgw       : bool · has at least one DGW in lookahead window
        has_bgw       : bool · has at least one BGW in lookahead window
        dgw_gameweeks : list of GW numbers where team plays twice
        bgw_gameweeks : list of GW numbers where team has no fixture
    """
    from collections import defaultdict

    upcoming = fixtures_df[
        (fixtures_df["gameweek"] >= current_gw) &
        (fixtures_df["gameweek"] < current_gw + lookahead)
    ]

    team_gw_count: Dict[Tuple[int, int], int] = defaultdict(int)
    for _, row in upcoming.iterrows():
        team_gw_count[(int(row["home_team_id"]), int(row["gameweek"]))] += 1
        team_gw_count[(int(row["away_team_id"]), int(row["gameweek"]))] += 1

    all_team_ids = set(
        int(t) for t in players_df["team_id"].dropna().unique()
    )
    gw_range = range(current_gw, current_gw + lookahead)

    team_dgw: Dict[int, List[int]] = {tid: [] for tid in all_team_ids}
    team_bgw: Dict[int, List[int]] = {tid: [] for tid in all_team_ids}

    for tid in all_team_ids:
        for gw in gw_range:
            count = team_gw_count.get((tid, gw), 0)
            if count >= 2:
                team_dgw[tid].append(gw)
            elif count == 0:
                team_bgw[tid].append(gw)

    df = players_df.copy()
    df["dgw_gameweeks"] = df["team_id"].map(
        lambda t: team_dgw.get(int(t), []) if pd.notna(t) else []
    )
    df["bgw_gameweeks"] = df["team_id"].map(
        lambda t: team_bgw.get(int(t), []) if pd.notna(t) else []
    )
    df["has_dgw"] = df["dgw_gameweeks"].apply(lambda x: len(x) > 0)
    df["has_bgw"] = df["bgw_gameweeks"].apply(lambda x: len(x) > 0)
    return df
