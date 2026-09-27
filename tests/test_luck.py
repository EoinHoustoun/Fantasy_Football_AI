"""Carried-luck adjustment (analytics/luck.py) on synthetic frames."""

import numpy as np
import pandas as pd

from analytics import luck as LK


def _frames(n=40, carry=0.2, seed=0):
    rng = np.random.default_rng(seed)
    xgi90 = rng.uniform(0.05, 0.8, n)
    luck90 = rng.normal(0, 0.3, n)
    season = pd.DataFrame({"code": np.arange(n), "minutes": 450.0,
                           "xg": xgi90 * 5 * 0.5, "xa": xgi90 * 5 * 0.5,
                           "goals_scored": (xgi90 + luck90) * 5 * 0.5,
                           "assists": (xgi90 + luck90) * 5 * 0.5})
    gi90 = 0.1 + 0.6 * xgi90 + carry * luck90
    rows = []
    for gw in (6, 7):
        for i in range(n):
            rows.append({"code": i, "gw": gw, "position": "MID", "exp_minutes": 90.0,
                         "e_goals": gi90[i] / 2, "e_assists": gi90[i] / 2,
                         "e_bonus": 0.2 + carry * luck90[i], "xp": 4.0})
    return pd.DataFrame(rows), season, luck90


def test_recovers_carry_and_signs():
    long, season, luck90 = _frames()
    coef = LK.carry_coefficients(long, LK.season_luck(season), [6, 7])
    cg, cb = coef["MID"]
    assert abs(cg - 0.2) < 0.02 and abs(cb - 0.2) < 0.02
    w = LK.window(LK.adjust(long, season, [6, 7]))
    hot, cold = int(np.argmax(luck90)), int(np.argmin(luck90))
    assert w.at[hot, "luck_pts"] > 0 and w.at[hot, "xp_clean"] < w.at[hot, "xp"]
    assert w.at[cold, "luck_pts"] < 0 and w.at[cold, "xp_clean"] > w.at[cold, "xp"]


def test_no_carry_means_no_adjustment():
    long, season, _ = _frames(carry=0.0)
    w = LK.window(LK.adjust(long, season, [6, 7]))
    assert w["luck_pts"].abs().max() < 0.05


def test_small_samples_untouched():
    long, season, _ = _frames()
    season.loc[season["code"] == 3, "minutes"] = 90.0
    w = LK.window(LK.adjust(long, season, [6, 7]))
    assert w.at[3, "luck_pts"] == 0.0
