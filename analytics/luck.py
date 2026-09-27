"""How much of each projection is last month's finishing luck.

The brain learns from recent goals, assists and bonus as well as xG and xA, so a
player who has scored well above his chances carries part of that streak into
his forecast. Luck does not persist (G+A minus xGI predicts later luck at
r = -0.01, 22 Sep persistence test), so that part is noise the manager should
not pay for.

Method, measured on the live projections every time rather than assumed:

1. For each position, regress the engine's projected goal involvements per 90
   and projected bonus per 90 on this season's xGI per 90 and luck per 90
   (G+A per 90 minus xGI per 90), over players with enough minutes.
2. The luck coefficient is how much past luck the engine carries forward
   (27 Sep 2026: 0.18 for midfielders' G+A, 0.20 for bonus).
3. Per player and gameweek, the carried luck in points is
   (c_gi * luck90 * points per involvement + c_bonus * luck90) * xMins / 90.
   `xp_clean = xp - luck_pts`.

A cold player gets points back, a hot one loses them. Players under
`MIN_MINUTES` this season carry no adjustment: their luck is not measurable.

No Streamlit imports.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

MIN_MINUTES = 270
GOAL_PTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_PTS = 3


def season_luck(season_rows: pd.DataFrame) -> pd.DataFrame:
    """code -> minutes, xgi90, ga90, luck90 for this season's rows."""
    if season_rows is None or season_rows.empty:
        return pd.DataFrame(columns=["minutes", "xgi90", "ga90", "luck90"])
    r = season_rows
    g = r.groupby("code").agg(minutes=("minutes", "sum"), G=("goals_scored", "sum"),
                              A=("assists", "sum"), xg=("xg", "sum"), xa=("xa", "sum"))
    m = g["minutes"].where(g["minutes"] > 0)
    g["xgi90"] = (g["xg"].fillna(0) + g["xa"].fillna(0)) / m * 90
    g["ga90"] = (g["G"].fillna(0) + g["A"].fillna(0)) / m * 90
    g["luck90"] = g["ga90"] - g["xgi90"]
    return g[["minutes", "xgi90", "ga90", "luck90"]].fillna(0.0)


def carry_coefficients(long: pd.DataFrame, luck: pd.DataFrame,
                       gws) -> Dict[str, Tuple[float, float]]:
    """Per position: (share of luck carried into G+A, share carried into bonus)."""
    L = long[long["gw"].isin(list(gws))]
    eng = L.groupby("code").agg(eg=("e_goals", "sum"), ea=("e_assists", "sum"),
                                eb=("e_bonus", "sum"), mins=("exp_minutes", "sum"),
                                pos=("position", "first"))
    d = eng.join(luck, how="inner")
    d = d[(d["minutes"] >= MIN_MINUTES) & (d["mins"] > 0)]
    out = {}
    for pos, x in d.groupby("pos"):
        if len(x) < 12:
            continue
        X = np.c_[np.ones(len(x)), x["xgi90"], x["luck90"]]
        gi = (x["eg"] + x["ea"]) / x["mins"] * 90
        b = x["eb"] / x["mins"] * 90
        cg = float(np.linalg.lstsq(X, gi, rcond=None)[0][2])
        cb = float(np.linalg.lstsq(X, b, rcond=None)[0][2])
        # Only ever REMOVE carried luck. A negative fit is the model already
        # regressing, not something to add back on top.
        out[str(pos)] = (max(0.0, cg), max(0.0, cb))
    return out


def adjust(long: pd.DataFrame, season_rows: pd.DataFrame, gws) -> pd.DataFrame:
    """Rows of `long` in `gws` with `luck_pts` and `xp_clean` added."""
    luck = season_luck(season_rows)
    coef = carry_coefficients(long, luck, gws)
    L = long[long["gw"].isin(list(gws))].copy()
    L = L.join(luck[["minutes", "luck90"]].rename(columns={"minutes": "_season_min"}), on="code")
    L["luck90"] = L["luck90"].where(L["_season_min"].fillna(0) >= MIN_MINUTES, 0.0).fillna(0.0)
    pos = L["position"].astype(str)
    cg = pos.map(lambda p: coef.get(p, (0.0, 0.0))[0])
    cb = pos.map(lambda p: coef.get(p, (0.0, 0.0))[1])
    gi = (L["e_goals"] + L["e_assists"]).replace(0, np.nan)
    ppi = ((L["e_goals"] * pos.map(GOAL_PTS).fillna(4) + L["e_assists"] * ASSIST_PTS) / gi)
    ppi = ppi.fillna(pos.map(GOAL_PTS).fillna(4) * 0.5 + ASSIST_PTS * 0.5)
    L["luck_pts"] = ((cg * L["luck90"] * ppi + cb * L["luck90"]) * L["exp_minutes"].fillna(0) / 90.0)
    L["xp_clean"] = L["xp"] - L["luck_pts"]
    return L.drop(columns=["_season_min"])


def window(adjusted: pd.DataFrame) -> pd.DataFrame:
    """code -> xp, luck_pts, xp_clean, luck90 summed over the adjusted window."""
    return adjusted.groupby("code").agg(xp=("xp", "sum"), luck_pts=("luck_pts", "sum"),
                                        xp_clean=("xp_clean", "sum"), luck90=("luck90", "first"))
