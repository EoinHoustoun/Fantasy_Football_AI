"""Manual projection overrides · ground truth a last-season model can't derive.

The season projection is `pp90 x minutes / 90` fitted on the archive. It is
blind to three things no historical model can know:

  - fitness · a player injured last season projects almost nothing (few minutes),
    even if he is now a nailed starter (Isak, Havertz, Palmer)
  - role · a starter who moved to a backup job will not repeat his minutes (a
    keeper who signed as a No.2)
  - regression · a career-high season that will not repeat (a haircut)

These are encoded by hand in assets/player_overrides_{season}.json, keyed by the
stable FPL player code, and applied here. `minutes` recomputes points from the
per-90 rate; `pts_mult` haircuts the points; `benched`/`nailed` are shortcuts.
Transparent and user-editable · not a refit, so it can't overfit the season.
"""
from typing import Dict

import json
from pathlib import Path

import pandas as pd

from config import ROOT_DIR, NEXT_SEASON, PROJECTION_OVERRIDE

_FULL_SEASON_MIN = 3420.0   # 38 x 90


def overrides_path(season: str = NEXT_SEASON) -> Path:
    return ROOT_DIR / "assets" / f"player_overrides_{season.replace('-', '_')}.json"


def load_overrides(season: str = NEXT_SEASON) -> Dict[int, dict]:
    """code -> adjustment dict. Missing file returns {} (no overrides)."""
    path = overrides_path(season)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {int(k): v for k, v in raw.items()
            if not str(k).startswith("_") and isinstance(v, dict)}


def apply_overrides(uni: pd.DataFrame, season: str = NEXT_SEASON) -> pd.DataFrame:
    """Apply manual overrides to a projection universe in place of a refit.

    Adjusts `projected_minutes`, `projected_points`, and the nailed-ness signals
    (`mins_share`, `starts_ratio`) for each overridden player, and records a
    human `override_note`. Rows without an override are untouched.
    """
    ov = load_overrides(season)
    uni = uni.copy()
    if "override_note" not in uni.columns:
        uni["override_note"] = ""
    if "early_nailedness" not in uni.columns:
        uni["early_nailedness"] = float("nan")
    if not ov:
        return uni

    nailed_min = PROJECTION_OVERRIDE["nailed_minutes"]
    bench_min = PROJECTION_OVERRIDE["bench_minutes"]

    for code, adj in ov.items():
        rows = uni.index[uni["code"] == code]
        if len(rows) == 0:
            continue
        i = rows[0]
        pp90 = float(uni.at[i, "projected_pp90"] or 0)

        # Minutes-type override recomputes points from the per-90 rate.
        new_min = None
        if adj.get("benched"):
            new_min = bench_min
        elif adj.get("nailed"):
            new_min = nailed_min
        elif "minutes" in adj:
            new_min = int(adj["minutes"])

        # `pp90` sets the per-90 rate outright. Needed when a player has NO
        # Premier League history to fit a rate from · Vuskovic played zero
        # minutes here, so his rate is 0 and a minutes override alone would
        # still project nothing. The rate then comes from another league.
        if "pp90" in adj:
            pp90 = float(adj["pp90"])
            uni.at[i, "projected_pp90"] = pp90

        if new_min is not None:
            uni.at[i, "projected_minutes"] = new_min
            uni.at[i, "projected_points"] = round(pp90 * new_min / 90.0, 1)
            share = round(min(max(new_min / _FULL_SEASON_MIN, 0.0), 1.0), 2)
            uni.at[i, "mins_share"] = share
            uni.at[i, "starts_ratio"] = share   # assert nailed-ness from the call
        # `early_nailedness` is a SEPARATE call from season minutes, and the two
        # genuinely differ for the most interesting players. Mosquera starts
        # while Saliba is injured and loses the place when he returns: nailed in
        # the opening window, rotation risk over a season. A season-minutes
        # override cannot say that, and using one to gate EARLY minutes marks
        # him down in exactly the weeks he is certain to play.
        #
        # So: `minutes` drives the season projection, `early_nailedness` drives
        # the opening-window gate, and only the latter outranks the match model.
        if "early_nailedness" in adj and "early_nailedness" in uni.columns:
            uni.at[i, "early_nailedness"] = float(adj["early_nailedness"])

        # `points` sets the season projection outright · the bluntest override,
        # for when you simply know better than every model on the board.
        if "points" in adj:
            uni.at[i, "projected_points"] = round(float(adj["points"]), 1)

        # Regression haircut on the final points (independent of minutes).
        if "pts_mult" in adj:
            uni.at[i, "projected_points"] = round(
                float(uni.at[i, "projected_points"]) * float(adj["pts_mult"]), 1)

        uni.at[i, "override_note"] = str(adj.get("note", "manual override"))

    return uni
