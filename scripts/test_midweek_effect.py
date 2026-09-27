"""Does the engine overrate players coming off midweek cup / European minutes?

Uses the cached walk-forward folds (data/cache/bench_brain/2025-26_gw*.pkl):
each holds the engine's out-of-sample p60 and xP for GW t..t+5. For the week a
projection was made for, compare predicted with actual, split by the player's
non-PL minutes in the six days before that Premier League kickoff
(data/fetchers/core_insights). Only the FIRST projected week (k=0) is honest
for this: later weeks' midweek fixtures were not known... they were (fixtures
are scheduled), so all six weeks are scored, reported by k.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from data.fetchers.core_insights import attach_midweek, midweek_minutes  # noqa: E402
from data.processors.archive import load_gw_archive  # noqa: E402

SEASON = "2025-26"
arch = load_gw_archive()
s = arch[arch["season"] == SEASON].copy()
extra = midweek_minutes(SEASON)
rows = s[["code", "gw", "kickoff_time", "minutes", "total_points", "position", "team_name"]].copy()
rows = attach_midweek(rows, extra)
act = rows.groupby(["code", "gw"]).agg(mins=("minutes", "sum"), pts=("total_points", "sum"),
                                       mw=("mw_minutes", "max"), n=("minutes", "size")).reset_index()
recs = []
for f in sorted((ROOT / "data" / "cache" / "bench_brain").glob(SEASON + "_gw*.pkl")):
    t = int(f.stem.split("_gw")[1])
    L = pd.read_pickle(f)
    m = L.merge(act, on=["code", "gw"])
    m = m[m["n"] == 1]
    m["k"] = m["gw"] - t
    recs.append(m)
d = pd.concat(recs)
# Regulars only: players the engine expects to start (the decision population).
d = d[d["p60"] >= 0.6]
d["bucket"] = pd.cut(d["mw"], [-1, 0, 45, 200], labels=["none", "1-45", "46+"])
d["hit60"] = (d["mins"] >= 60).astype(float)
g = d.groupby("bucket", observed=True).agg(n=("hit60", "size"), p60_pred=("p60", "mean"),
                                           p60_act=("hit60", "mean"), xp=("xp", "mean"),
                                           pts=("pts", "mean"), mins_pred=("exp_minutes", "mean"),
                                           mins_act=("mins", "mean"))
g["p60_gap"] = g["p60_act"] - g["p60_pred"]
g["pts_gap"] = g["pts"] - g["xp"]
print(g.round(3).to_string())
# Is the 46+ gap different from the no-midweek gap? Bootstrap the difference.
a = d[d["bucket"] == "46+"]
b = d[d["bucket"] == "none"]
rng = np.random.default_rng(0)
diffs = []
for _ in range(2000):
    ra = a.sample(len(a), replace=True, random_state=int(rng.integers(1e9)))
    rb = b.sample(len(b), replace=True, random_state=int(rng.integers(1e9)))
    diffs.append(((ra["hit60"] - ra["p60"]).mean()) - ((rb["hit60"] - rb["p60"]).mean()))
lo, hi = np.percentile(diffs, [2.5, 97.5])
print("p60 gap, 46+ minus none: %.3f  (95%% CI %.3f to %.3f)" % (np.mean(diffs), lo, hi))
# Per anchor fold, to see if it holds across the season
per = d.assign(t=d["gw"] - d["k"]).groupby(["t", "bucket"], observed=True).apply(
    lambda x: (x["hit60"] - x["p60"]).mean()).unstack()
print(per.round(3).to_string())
