"""Shared expected-points engine · one xP number, every page, every gameweek.

Projects per-player points for each gameweek in a planning horizon, replacing
scattered uses of FPL's single-week `ep_next`. The model is deliberately
transparent (the Playbook's findings drive it):

  xp(player, gw) = base_rate × minutes_factor × Σ_fixtures ease(fdr) × home_adj

  · base_rate       0.55×form + 0.45×points_per_game (both per-match signals;
                    form self-heals to ppg off-season via build_player_universe)
  · minutes_factor  sqrt(avg_minutes/90) floored at 0.45 for regulars, 0 for
                    unavailable players, scaled by chance_of_playing when set.
                    Minutes are the master variable (ρ≈0.98 season-level).
  · ease(fdr)       1 + (3 − fdr)×0.15, clipped 0.5–1.5 · identical to the
                    points_model treatment so the two stay comparable.
  · home_adj        1.05 home / 0.95 away.
  · DGW sums both fixtures; BGW → 0.

Finally the whole surface is calibrated so the first-GW mean matches FPL's
own `ep_next` mean (familiar units, honest relative ordering).

Python 3.8: typing only. No Streamlit imports · cache at the call site.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _minutes_factor(row: pd.Series) -> float:
    status = str(row.get("status", "a"))
    if status in ("i", "s", "u"):
        return 0.0
    avg_min = row.get("avg_minutes")
    try:
        avg_min = float(avg_min)
        if pd.isna(avg_min):
            raise ValueError
    except (TypeError, ValueError):
        mins = float(row.get("minutes", 0) or 0)
        avg_min = min(90.0, mins / 38.0 * 1.4)   # rough per-appearance estimate
    mf = (max(0.0, min(avg_min, 90.0)) / 90.0) ** 0.5
    if avg_min >= 45:
        mf = max(mf, 0.45)
    cop = row.get("chance_of_playing_next_round")
    try:
        cop = float(cop)
        if not pd.isna(cop):
            mf *= max(0.0, min(cop, 100.0)) / 100.0
    except (TypeError, ValueError):
        pass
    return mf


def _team_fixture_map(fixtures_df: pd.DataFrame, first_gw: int, horizon: int
                      ) -> Dict[Tuple[int, int], List[Tuple[float, bool]]]:
    """{(team_id, gw): [(fdr, is_home), ...]} over the horizon."""
    window = fixtures_df[
        (fixtures_df["gameweek"] >= first_gw)
        & (fixtures_df["gameweek"] < first_gw + horizon)
    ]
    out: Dict[Tuple[int, int], List[Tuple[float, bool]]] = {}
    for _, f in window.iterrows():
        gw = int(f["gameweek"])
        out.setdefault((int(f["home_team_id"]), gw), []).append(
            (float(f.get("home_fdr", 3) or 3), True))
        out.setdefault((int(f["away_team_id"]), gw), []).append(
            (float(f.get("away_fdr", 3) or 3), False))
    return out


def project_horizon(players_df: pd.DataFrame,
                    fixtures_df: pd.DataFrame,
                    first_gw: int,
                    horizon: int = 5,
                    calibrate: bool = True) -> pd.DataFrame:
    """Per-player xP for each GW in [first_gw, first_gw+horizon).

    Returns a DataFrame indexed by fpl_id with one column per gameweek
    (int column names) plus 'xp_total'. Every page needing multi-week
    expected points should read from here, not from ep_next.
    """
    fix_map = _team_fixture_map(fixtures_df, first_gw, horizon)
    gws = list(range(int(first_gw), int(first_gw) + int(horizon)))

    form = pd.to_numeric(players_df.get("form"), errors="coerce").fillna(0.0)
    ppg = pd.to_numeric(players_df.get("points_per_game"), errors="coerce").fillna(0.0)
    base = 0.55 * form + 0.45 * ppg

    rows = []
    for i, (_, p) in enumerate(players_df.iterrows()):
        mf = _minutes_factor(p)
        rate = float(base.iloc[i]) * mf
        tid = p.get("team_id")
        tid = int(tid) if pd.notna(tid) else -1
        rec = {"fpl_id": int(p["fpl_id"])}
        total = 0.0
        for gw in gws:
            xp = 0.0
            for fdr, home in fix_map.get((tid, gw), []):
                ease = min(1.5, max(0.5, 1.0 + (3.0 - fdr) * 0.15))
                xp += rate * ease * (1.05 if home else 0.95)
            rec[gw] = round(xp, 2)
            total += xp
        rec["xp_total"] = round(total, 2)
        rows.append(rec)

    out = pd.DataFrame(rows).set_index("fpl_id")

    if calibrate and "ep_next" in players_df.columns:
        ep = pd.to_numeric(players_df["ep_next"], errors="coerce").fillna(0.0)
        first_col = out[gws[0]]
        played = first_col > 0
        if played.any() and float(first_col[played].mean()) > 0 and float(ep.mean()) > 0:
            scale = float(ep[ep > 0].mean()) / float(first_col[played].mean())
            scale = min(2.0, max(0.5, scale))
            for gw in gws:
                out[gw] = (out[gw] * scale).round(2)
            out["xp_total"] = out[gws].sum(axis=1).round(2)

    return out


def xp_for_gw(horizon_df: pd.DataFrame, gw: int) -> Dict[int, float]:
    """{fpl_id: xp} for one gameweek · convenience for pitch/panel overrides."""
    if gw not in horizon_df.columns:
        return {}
    return {int(i): float(v) for i, v in horizon_df[gw].items()}
