"""What is a free transfer kept in hand worth? Measured on the 10-season archive.

Question: when a plan spends every free transfer this week, what does it expect
to lose because it cannot react if a starter is suddenly out?

Method:
  - A REGULAR at GW t started (60+ minutes) at least 3 of his club's last 4
    league matches. That is who sits in a manager's XI.
  - A SHOCK is a regular who then plays 0 minutes at GW t although his club
    played. It covers both late injuries and rotation, the two things a spare
    transfer insures against.
  - Without a spare transfer the shock week is covered by an autosub; with one,
    by a like-for-like regular. The loss per shock is the starter's points minus
    the autosub's, from what those players really scored.
  - Weeks out after a shock are counted too: a long absence costs one week
    (the next week brings a new free transfer), so the reserve value is a
    one-week quantity.

Reserve value = expected shocks among 11 starters per week x loss per shock.

Run:  python scripts/research_ft_reserve.py
Writes docs/research/ft_reserve_<date>.json
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.processors.archive import load_gw_archive  # noqa: E402


def main():
    a = load_gw_archive()
    a = a[a["minutes"].notna()].copy()
    per = (a.groupby(["season", "code", "gw"], as_index=False)
             .agg(minutes=("minutes", "sum"), points=("total_points", "sum"),
                  value=("value", "first"), position=("position", "first")))
    per = per.sort_values(["season", "code", "gw"])
    g = per.groupby(["season", "code"])
    per["starts_last4"] = g["minutes"].transform(
        lambda m: (m >= 60).astype(float).shift(1).rolling(4, min_periods=4).sum())
    per["pts_when_start"] = g["points"].transform(lambda p: p.shift(1).rolling(4, min_periods=1).mean())
    reg = per[per["starts_last4"] >= 3].copy()
    reg["shock"] = reg["minutes"] == 0

    # weeks out after a shock (consecutive zero-minute league weeks, capped at 6)
    out_len = []
    for (s, c), grp in per.groupby(["season", "code"]):
        mins = grp["minutes"].values
        gws = grp["gw"].values
        idx = {gw: i for i, gw in enumerate(gws)}
        for gw in reg.loc[(reg["season"] == s) & (reg["code"] == c) & reg["shock"], "gw"]:
            i, n = idx[gw], 0
            while i < len(mins) and mins[i] == 0 and n < 6:
                n += 1
                i += 1
            out_len.append(n)

    # autosub value: what the outfield player you bench in practice scores.
    # Cheap regulars (value <= 4.5m) are the typical bench; their points include 0s.
    cheap = per[(per["value"] <= 45) & (per["position"] != "GK") & (per["position"] != "GKP")]
    cheap_reg = cheap[cheap.groupby(["season", "code"])["minutes"].transform(
        lambda m: (m >= 60).astype(float).shift(1).rolling(4, min_periods=4).sum()) >= 3]
    bench_pts = float(cheap_reg["points"].mean())
    starter_pts = float(reg.loc[~reg["shock"], "points"].mean())

    by_season = reg.groupby("season")["shock"].mean()
    p = float(reg["shock"].mean())
    shocks_per_week = 11 * p
    loss = starter_pts - bench_pts
    reserve = shocks_per_week * loss
    out = {
        "regular_weeks": int(len(reg)),
        "p_shock_per_regular_week": round(p, 4),
        "p_shock_by_season": {k: round(float(v), 4) for k, v in by_season.items()},
        "p_at_least_one_of_11": round(1 - (1 - p) ** 11, 3),
        "shocks_per_week_11": round(shocks_per_week, 3),
        "weeks_out": {str(k): int(v) for k, v in pd.Series(out_len).value_counts().sort_index().items()},
        "starter_pts": round(starter_pts, 2), "autosub_pts": round(bench_pts, 2),
        "loss_per_shock": round(loss, 2),
        "reserve_value_per_week": round(reserve, 2),
        "reserve_value_worst_season": round(11 * float(by_season.max()) * loss, 2),
    }
    print(json.dumps(out, indent=1))
    path = ROOT / "docs" / "research" / ("ft_reserve_%s.json" % date.today().isoformat())
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
