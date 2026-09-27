"""Is the brain's DEFCON probability wrong for players new to the Premier League,
and does blending their own season-so-far hit rate fix it? Walk-forward.

Only 2025-26 records defensive actions, so the test uses its five cached brain
folds (GW6/12/18/24/30). For each fold at gameweek t:

  predicted  p_defcon (given 60+) from the brain, features frozen before t
  observed   hit rate in the next six gameweeks, 60+ appearances only
  in-season  hit rate in 60+ appearances BEFORE t (the candidate signal)

Groups: newcomers (no Premier League rows before 2025-26) vs established.
Candidate: p' = (k * p + hits) / (k + starts60), a beta-style shrink of the
season-so-far rate toward the brain, for several k. Scored by Brier on each
future 60+ appearance, per fold, per group.

    python scripts/test_defcon_newcomers.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from data.processors.archive import load_gw_archive  # noqa: E402

THR = {"DEF": 10, "MID": 12, "FWD": 12}
KS = (2, 4, 6, 10, 20)


def main():
    a = load_gw_archive()
    season = "2025-26"
    s = a[a["season"] == season].copy()
    prior = set(a[a["season"] < season]["code"].unique())
    s = s[s["position"].isin(THR)]
    s["hit"] = (s["defensive_contribution"].fillna(0) >= s["position"].map(THR)).astype(float)
    s60 = s[s["minutes"] >= 60]
    out = {}
    rows_all = []
    for t in (6, 12, 18, 24, 30):
        long = pd.read_pickle(ROOT / ("data/cache/bench_brain/%s_gw%d.pkl" % (season, t)))
        before = s60[s60["gw"] < t].groupby("code")["hit"].agg(["sum", "count"])
        fut = s60[(s60["gw"] >= t) & (s60["gw"] < t + 6)][["code", "gw", "hit", "position"]]
        p = long.groupby(["code", "gw"])["p_defcon"].mean()
        fut = fut.join(p.rename("p"), on=["code", "gw"]).dropna(subset=["p"])
        fut = fut.join(before, on="code").fillna({"sum": 0, "count": 0})
        fut["new"] = ~fut["code"].isin(prior)
        fut["fold"] = t
        rows_all.append(fut)
    d = pd.concat(rows_all)
    res = {}
    for grp, x in (("newcomers", d[d["new"]]), ("established", d[~d["new"]]), ("all", d)):
        r = {"n": int(len(x)), "players": int(x["code"].nunique()),
             "mean_p": round(float(x["p"].mean()), 3), "mean_hit": round(float(x["hit"].mean()), 3),
             "brier_brain": round(float(((x["p"] - x["hit"]) ** 2).mean()), 4)}
        for k in KS:
            pk = (k * x["p"] + x["sum"]) / (k + x["count"])
            r["brier_k%d" % k] = round(float(((pk - x["hit"]) ** 2).mean()), 4)
        # worst fold for the best k
        per_fold = {}
        for f, y in x.groupby("fold"):
            pk = (6 * y["p"] + y["sum"]) / (6 + y["count"])
            per_fold[int(f)] = [round(float(((y["p"] - y["hit"]) ** 2).mean()), 4),
                                round(float(((pk - y["hit"]) ** 2).mean()), 4), int(len(y))]
        r["per_fold_brain_vs_k6"] = per_fold
        # calibration by predicted bucket
        b = pd.cut(x["p"], [0, .1, .2, .3, .45, .6, 1.0])
        r["calibration"] = {str(k): [round(float(v["p"].mean()), 3), round(float(v["hit"].mean()), 3), int(len(v))]
                            for k, v in x.groupby(b) if len(v) >= 30}
        res[grp] = r
    print(json.dumps(res, indent=1))
    (ROOT / "docs/research/defcon_newcomers.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
