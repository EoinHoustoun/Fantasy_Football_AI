"""Simulated projection ranges (analytics/ranges.py) on synthetic rows."""

import numpy as np
import pandas as pd

from analytics import ranges as RG


def _rows(code, pos, xp, p_play=0.95, p60=0.9, eg=0.3, ea=0.2, pcs=0.35, pdc=0.3,
          gws=(1, 2, 3, 4, 5, 6)):
    return pd.DataFrame([{"code": code, "gw": g, "position": pos, "xp": xp, "p_play": p_play,
                          "p60": p60, "e_goals": eg, "e_assists": ea, "e_saves": 0.0,
                          "e_bonus": 0.4, "p_clean_sheet": pcs, "p_defcon": pdc,
                          "fixtures": 1} for g in gws])


def test_single_week_mean_matches_engine():
    r = _rows(1, "MID", 5.0, gws=(1,))
    s = RG.simulate(r, n=6000, sigma=0.0, hazard=0.0)[1]
    assert abs(s.mean() - 5.0) < 0.05


def test_band_widens_with_rate_uncertainty():
    r = _rows(1, "MID", 5.0)
    tight = RG.band(RG.simulate(r, n=4000, sigma=0.0, hazard=0.0)[1])
    wide = RG.band(RG.simulate(r, n=4000, sigma=0.55, hazard=0.0)[1])
    assert (wide["hi"] - wide["lo"]) > (tight["hi"] - tight["lo"])


def test_hazard_pulls_down_only_later_weeks():
    r = _rows(1, "DEF", 4.0)
    no = RG.simulate(r, n=6000, sigma=0.0, hazard=0.0)[1].mean()
    yes = RG.simulate(r, n=6000, sigma=0.0, hazard=0.2)[1].mean()
    assert yes < no
    one = _rows(1, "DEF", 4.0, gws=(1,))
    assert abs(RG.simulate(one, n=6000, sigma=0.0, hazard=0.5)[1].mean() - 4.0) < 0.1


def test_p_beats_orders_and_splits_ties():
    rows = pd.concat([_rows(1, "MID", 6.0), _rows(2, "MID", 3.0)])
    sims = RG.simulate(rows, n=4000)
    assert RG.p_beats(sims[1], sims[2]) > 0.6
    same = np.ones(100)
    assert RG.p_beats(same, same) == 0.5


def test_nonplayer_is_zero():
    r = _rows(1, "FWD", 0.0, p_play=0.0, p60=0.0)
    s = RG.simulate(r, n=500)[1]
    assert float(np.abs(s).max()) == 0.0
