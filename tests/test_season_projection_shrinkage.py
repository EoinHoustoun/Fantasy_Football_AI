"""Early-season points-per-game must not be extrapolated raw over 37 games.

After GW1 a defender on 10 pts had "projects ~372 pts for the rest of the
season" on the Transfers page. Each player's ppg is shrunk toward the average
for their position with a prior worth PPG_PRIOR_GAMES matches, so one haul
moves the projection a little and a season of hauls moves it all the way.
"""
import pandas as pd

from analytics import transfer_engine as te


def _df(minutes_max):
    n = 10   # one hauler among nine ordinary defenders, plus a midfielder
    return pd.DataFrame({
        "position":           ["DEF"] * n + ["MID"],
        "points_per_game":    [10.0] + [2.0] * (n - 1) + [5.0],
        "minutes":            [minutes_max] * (n + 1),
        "remaining_fixtures": [37] * (n + 1),
        "season_avg_fdr":     [3.0] * (n + 1),
    })


def test_one_gameweek_is_shrunk_hard_toward_position_mean():
    out = te.estimate_season_points(_df(minutes_max=90))
    proj = out["projected_season_pts"].iloc[0]
    assert proj < 200, proj                      # not 10 * 37 = 370
    assert proj > 2.0 * 37                        # still above the plain 2-ppg peers


def test_deep_into_season_the_players_own_rate_dominates():
    out = te.estimate_season_points(_df(minutes_max=90 * 30))
    proj = out["projected_season_pts"].iloc[0]
    assert proj > 0.85 * 10 * 37


def test_shrinkage_never_rewrites_the_column_callers_read():
    out = te.estimate_season_points(_df(minutes_max=90))
    assert "projected_season_pts" in out.columns
    assert out["points_per_game"].iloc[0] == 10.0   # input untouched
