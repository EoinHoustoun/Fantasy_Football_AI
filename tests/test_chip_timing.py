"""First-half chip timing over GW1-19."""
import pandas as pd

from analytics.chip_timing import chip_windows


def _squad() -> pd.DataFrame:
    # Two teams: 1 (bench players live here), 2 (a star in the XI).
    return pd.DataFrame([
        {"web_name": "Star", "team_id": 2, "pts": 200, "in_xi": True},
        {"web_name": "XIfillerA", "team_id": 3, "pts": 100, "in_xi": True},
        {"web_name": "BenchA", "team_id": 1, "pts": 90, "in_xi": False},
        {"web_name": "BenchB", "team_id": 1, "pts": 80, "in_xi": False},
    ])


def _fixtures() -> pd.DataFrame:
    rows = []
    # GW1: everyone average (FDR 3)
    # GW2: team 1 (bench) get a very easy fixture (FDR 1) -> best Bench Boost week
    # GW3: team 2 (Star) gets an easy fixture (FDR 1) -> best Triple Captain week
    # GW4: team 2 & 3 blank (no fixture), team 1 hard -> weakest -> Free Hit week
    def fx(gw, home, away, hf, af):
        rows.append({"gameweek": gw, "home_team_id": home, "away_team_id": away,
                     "home_fdr": hf, "away_fdr": af})
    for t in (1, 2, 3):
        fx(1, t, 9, 3, 3)
    fx(2, 1, 9, 1, 5); fx(2, 2, 9, 3, 3); fx(2, 3, 9, 3, 3)
    fx(3, 2, 9, 1, 5); fx(3, 1, 9, 3, 3); fx(3, 3, 9, 3, 3)
    fx(4, 1, 9, 5, 1)   # only team 1 plays GW4; teams 2 & 3 blank
    return pd.DataFrame(rows)


def test_bench_boost_picks_the_bench_easy_week():
    w = chip_windows(_squad(), _fixtures(), gw_lo=1, gw_hi=4)
    assert w["bench_boost"][0]["gw"] == 2


def test_triple_captain_picks_the_star_easy_week():
    w = chip_windows(_squad(), _fixtures(), gw_lo=1, gw_hi=4)
    assert w["triple_captain"][0]["gw"] == 3
    assert w["triple_captain"][0]["captain"] == "Star"


def test_free_hit_picks_the_weakest_week():
    w = chip_windows(_squad(), _fixtures(), gw_lo=1, gw_hi=4)
    # GW4: two of four players blank -> lowest squad points
    assert w["free_hit"][0]["gw"] == 4
    assert w["free_hit"][0]["blanks"] == 2


def test_only_scans_the_requested_window():
    w = chip_windows(_squad(), _fixtures(), gw_lo=1, gw_hi=4)
    assert all(1 <= r["gw"] <= 4 for r in w["bench_boost"])
