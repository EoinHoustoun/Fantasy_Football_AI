"""
2026-27 season points projector.

Projects next-season total points for every 2025-26 player:

  projected_points = pp90_next × projected_minutes / 90

Both components are fitted on the 9 historical season-pairs, not hand-set:
  - minutes:  per-position linear regression minutes_{N+1} ~ minutes_N
              (captures both shrinkage slope and the churn intercept)
  - pp90:     per-position regression pp90_{N+1} ~ pp90_N (+ xgi_per90 where
              the season has xG data) on players with ≥900 minutes both
              seasons · empirical-Bayes-style shrinkage falls out of the slope

Validated by predicting 2025-26 totals from 2024-25 only (Spearman ~0.6-0.7
expected · minutes churn is the dominant noise and we say so in the UI).
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import ARCHIVE_SEASONS

logger = logging.getLogger(__name__)

MIN_MINUTES_FIT = 900     # both seasons, for pp90 fitting


def _pairs(summary: pd.DataFrame, through: Optional[str] = None) -> pd.DataFrame:
    """Stack season-pairs (N stats + N+1 outcomes), optionally truncated."""
    seasons = ARCHIVE_SEASONS
    if through is not None:
        seasons = seasons[: seasons.index(through) + 1]
    rows = []
    for s_n, s_next in zip(seasons[:-1], seasons[1:]):
        left = summary[summary["season"] == s_n]
        right = summary[summary["season"] == s_next][
            ["code", "minutes", "pp90", "total_points"]
        ].rename(columns={"minutes": "minutes_next", "pp90": "pp90_next",
                          "total_points": "points_next"})
        rows.append(left.merge(right, on="code", how="inner"))
    return pd.concat(rows, ignore_index=True)


def _fit_linear(x: pd.Series, y: pd.Series) -> Dict:
    """Least-squares slope/intercept with graceful degenerate fallback."""
    x, y = x.astype(float), y.astype(float)
    if len(x) < 10 or x.std() < 1e-9:
        return {"slope": 1.0, "intercept": 0.0}
    slope, intercept = np.polyfit(x, y, 1)
    return {"slope": float(slope), "intercept": float(intercept)}


def fit_projection_params(summary: pd.DataFrame,
                          through: Optional[str] = None) -> Dict:
    """Fit per-position minutes + pp90 carryover models on season-pairs."""
    pairs = _pairs(summary, through)
    params = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        grp = pairs[pairs["position"] == pos]
        minutes_fit = _fit_linear(grp["minutes"], grp["minutes_next"])

        nailed = grp[(grp["minutes"] >= MIN_MINUTES_FIT) &
                     (grp["minutes_next"] >= MIN_MINUTES_FIT)]
        pp90_fit = _fit_linear(nailed["pp90"], nailed["pp90_next"])

        # xGI adjustment (only pairs where season N has xG data)
        xgi_fit = None
        with_xg = nailed[nailed["xgi"].notna() & (nailed["minutes"] > 0)]
        if len(with_xg) >= 30 and pos != "GKP":
            xgi90 = with_xg["xgi"] / with_xg["minutes"] * 90
            resid = (with_xg["pp90_next"]
                     - (pp90_fit["slope"] * with_xg["pp90"] + pp90_fit["intercept"]))
            xgi_fit = _fit_linear(xgi90, resid)

        params[pos] = {"minutes": minutes_fit, "pp90": pp90_fit, "xgi": xgi_fit}
        logger.info(f"Projection [{pos}]: minutes slope {minutes_fit['slope']:.2f}, "
                    f"pp90 slope {pp90_fit['slope']:.2f}"
                    + (f", xGI slope {xgi_fit['slope']:.2f}" if xgi_fit else ""))
    return params


def project_season(summary: pd.DataFrame, season: str,
                   params: Optional[Dict] = None) -> pd.DataFrame:
    """Project next-season points for every player of `season`."""
    if params is None:
        params = fit_projection_params(summary)

    df = summary[summary["season"] == season].copy()
    out_rows = []
    for _, r in df.iterrows():
        p = params[r["position"]]
        proj_min = max(0.0, p["minutes"]["slope"] * r["minutes"]
                       + p["minutes"]["intercept"])
        proj_min = min(proj_min, 38 * 90.0)

        pp90 = r["pp90"] if r["minutes"] >= 360 else 0.0
        proj_pp90 = p["pp90"]["slope"] * pp90 + p["pp90"]["intercept"]
        if p["xgi"] is not None and pd.notna(r["xgi"]) and r["minutes"] > 0:
            xgi90 = r["xgi"] / r["minutes"] * 90
            proj_pp90 += p["xgi"]["slope"] * xgi90 + p["xgi"]["intercept"]
        proj_pp90 = max(proj_pp90, 0.0)

        out_rows.append({
            "code": r["code"], "web_name": r["web_name"],
            "player_name": r["player_name"], "position": r["position"],
            "team_name": r["team_name"],
            "projected_minutes": round(proj_min, 0),
            "projected_pp90": round(proj_pp90, 2),
            "projected_points": round(proj_pp90 * proj_min / 90.0, 1),
            "last_season_points": r["total_points"],
            "last_season_minutes": r["minutes"],
        })
    return (pd.DataFrame(out_rows)
            .sort_values("projected_points", ascending=False)
            .reset_index(drop=True))


def validate_projection(summary: pd.DataFrame) -> Dict:
    """
    Honest multi-holdout: for each of the last three season transitions,
    fit on strictly earlier pairs, project, compare with actuals.

    Context for reading the numbers: 2024-25→2025-26 spans the DEFCON
    scoring change (whole player pool re-ranked) · expect ~0.39 there
    vs ~0.48-0.50 on stable transitions. Season-to-season FPL points are
    irreducibly noisy; the projector's value is calibrated scale for the
    draft optimizer, not crystal-ball rankings.
    """
    results = {}
    for fit_through, frm, to in (("2022-23", "2022-23", "2023-24"),
                                 ("2023-24", "2023-24", "2024-25"),
                                 ("2024-25", "2024-25", "2025-26")):
        params = fit_projection_params(summary, through=fit_through)
        proj = project_season(summary, frm, params)
        actual = summary[summary["season"] == to][["code", "total_points"]]
        merged = proj.merge(
            actual.rename(columns={"total_points": "actual_points"}),
            on="code", how="inner")
        sample = merged[merged["last_season_minutes"] >= 450]
        spearman = float(sample["projected_points"].corr(
            sample["actual_points"], method="spearman"))
        mae = float((sample["projected_points"] - sample["actual_points"]).abs().mean())
        results[f"{frm}→{to}"] = {"spearman": round(spearman, 3),
                                  "mae_points": round(mae, 1), "n": len(sample)}
        logger.info(f"Projection validation {frm}→{to}: "
                    f"Spearman {spearman:.3f}, MAE {mae:.1f} (n={len(sample)})")
    return results
