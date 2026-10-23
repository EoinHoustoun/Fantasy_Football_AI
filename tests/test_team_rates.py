"""Opponent-adjusted team rates (analytics/team_rates.py)."""
import numpy as np
import pandas as pd

from analytics import team_rates as TR


def _sides(n_rounds=12):
    """A strong side (Ars), a leaky side (Lee) and two average ones, every pair
    home and away. Ars scores 2.4 and concedes 0.6; Lee the reverse."""
    att = {"Ars": 0.6, "Lee": -0.5, "Avg1": 0.0, "Avg2": 0.0}
    dfn = {"Ars": -0.6, "Lee": 0.5, "Avg1": 0.0, "Avg2": 0.0}
    rows, fx = [], 0
    t0 = pd.Timestamp("2025-08-16", tz="UTC")
    teams = list(att)
    for r in range(n_rounds):
        for i, first in enumerate(teams):
            for second in teams[i + 1:]:
                h, a = (second, first) if r % 2 else (first, second)
                lam_h = np.exp(0.1 + 0.15 + att[h] + dfn[a])
                lam_a = np.exp(0.1 + att[a] + dfn[h])
                ko = t0 + pd.Timedelta(days=7 * r)
                for team, opp, home, xg_for, xg_ag in ((h, a, True, lam_h, lam_a),
                                                       (a, h, False, lam_a, lam_h)):
                    rows.append({"season": "2025-26", "fixture": fx, "was_home": home,
                                 "team_key": team, "opp_key": opp, "kickoff": ko,
                                 "xg_for": xg_for, "goals_for": round(xg_for)})
                fx += 1
    return pd.DataFrame(rows)


def test_fit_recovers_strong_and_weak_sides():
    r = TR.fit(_sides())
    assert r.conceded("Ars", "Lee", was_home=True) < 0.5
    assert r.conceded("Lee", "Ars", was_home=False) > 2.0
    # home advantage: conceding at home is less than conceding away
    assert r.conceded("Avg1", "Avg2", True) < r.conceded("Avg1", "Avg2", False)


def test_unknown_team_has_no_rate():
    r = TR.fit(_sides())
    assert r.conceded("Hull", "Ars", True) is None


def test_thin_history_shrinks_the_blend_weight():
    s = _sides(n_rounds=2)       # each side has played 6 matches, 3 per round pair
    r = TR.fit(s)
    assert r.matches("Ars") == 6
    assert TR.blend_weight(0.5, r.matches("Ars"), r.matches("Lee")) == 0.5
    assert TR.blend_weight(0.5, 2, 6) == 0.2   # 2 of the 5 needed


def test_blend_is_geometric_and_zero_weight_is_identity():
    eng = np.array([1.0, 2.0])
    rate = np.array([4.0, 2.0])
    assert np.allclose(TR.blend(eng, rate, np.array([0.0, 0.0])), eng)
    assert np.allclose(TR.blend(eng, rate, np.array([0.5, 0.5])), [2.0, 2.0])
    # a missing rate leaves the engine alone
    assert np.allclose(TR.blend(eng, np.array([np.nan, 2.0]), np.array([0.5, 0.5])), [1.0, 2.0])


def test_old_matches_are_decayed():
    s = _sides()
    # Flip Ars to leaky in an ancient copy; it should barely move the fit.
    old = s.copy()
    old["kickoff"] = old["kickoff"] - pd.Timedelta(days=700)
    old["fixture"] += 10_000
    old.loc[old["team_key"] == "Ars", "xg_for"] = 0.2
    r = TR.fit(pd.concat([s, old]))
    assert r.conceded("Lee", "Ars", False) > 1.8
