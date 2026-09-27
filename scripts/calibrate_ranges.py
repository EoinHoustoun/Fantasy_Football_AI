"""Fit and check the uncertainty ranges (analytics/ranges.py) walk-forward.

For every cached brain fold (data/cache/bench_brain/, see
scripts/benchmark_brain_horizon.py) and every candidate RATE_SIGMA:

  - coverage   share of regular players whose actual points land inside the
               simulated 10-90% band (target 0.80), for 1- and 6-week windows
  - below/above  where the misses fall (a band too high or too low)
  - pair_brier  for random pairs of regulars, the Brier score of "A outscores B
               over six weeks" against what happened, and a reliability table

Regulars = 60+ minutes in at least two of the four gameweeks before the fold,
the same set the horizon benchmark scores.

    python scripts/calibrate_ranges.py
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics import ranges as RG  # noqa: E402
from data.processors.archive import load_gw_archive  # noqa: E402

logging.basicConfig(level=logging.WARNING)
SIGMAS = ((0.45, 0.08), (0.5, 0.1), (0.55, 0.08))
WINDOWS = (1, 6)
N = 800


def main():
    archive = load_gw_archive()
    folds = sorted((ROOT / "data" / "cache" / "bench_brain").glob("*.pkl"))
    res = {s: {w: [] for w in WINDOWS} for s in SIGMAS}
    pairs = {s: [] for s in SIGMAS}
    rng = np.random.default_rng(0)
    for f in folds:
        season, t = f.stem.split("_gw")
        t = int(t)
        long = pd.read_pickle(f)
        srows = archive[archive["season"] == season]
        pos = srows.groupby("code")["position"].first()
        long = long.join(pos.rename("position"), on="code")
        last4 = srows[(srows["gw"] < t) & (srows["gw"] >= t - 4)]
        regs = set(last4[last4["minutes"] >= 60].groupby("code")["gw"].nunique().loc[lambda s: s >= 2].index)
        truth = srows[(srows["gw"] >= t) & (srows["gw"] < t + 6)].groupby(["code", "gw"])["total_points"].sum()
        L = long[long["code"].isin(regs) & long["position"].notna()]
        for w in WINDOWS:
            gws = list(range(t, t + w))
            act = truth[truth.index.get_level_values("gw").isin(gws)].groupby("code").sum()
            rows = L[L["gw"].isin(gws)]
            for s in SIGMAS:
                sims = RG.simulate(rows, n=N, sigma=s[0], hazard=s[1], seed=t)
                for c, x in sims.items():
                    if c not in act.index:
                        continue
                    lo, hi = np.percentile(x, 10), np.percentile(x, 90)
                    a = float(act[c])
                    res[s][w].append((a < lo, a > hi))
                if w == 6:
                    codes = [c for c in sims if c in act.index]
                    for _ in range(400):
                        i, j = rng.choice(len(codes), 2, replace=False)
                        ci, cj = codes[i], codes[j]
                        p = RG.p_beats(sims[ci], sims[cj])
                        o = 1.0 if act[ci] > act[cj] else (0.5 if act[ci] == act[cj] else 0.0)
                        pairs[s].append((p, o))
        print("fold", f.stem, flush=True)
    out = {}
    for s in SIGMAS:
        row = {}
        for w in WINDOWS:
            m = np.array(res[s][w], float)
            row["w%d" % w] = {"coverage": round(1 - m.sum(axis=1).mean(), 3),
                              "below": round(m[:, 0].mean(), 3), "above": round(m[:, 1].mean(), 3),
                              "n": int(len(m))}
        pp = np.array(pairs[s])
        bins = np.clip((pp[:, 0] * 10).astype(int), 0, 9)
        rel = {("%.1f-%.1f" % (b / 10, (b + 1) / 10)): [round(float(pp[bins == b, 0].mean()), 3),
                                                       round(float(pp[bins == b, 1].mean()), 3),
                                                       int((bins == b).sum())]
               for b in range(10) if (bins == b).sum() >= 30}
        row["pair_brier"] = round(float(((pp[:, 0] - pp[:, 1]) ** 2).mean()), 4)
        row["pair_brier_coinflip"] = round(float(((0.5 - pp[:, 1]) ** 2).mean()), 4)
        row["reliability"] = rel
        out[str(s)] = row
        print(s, json.dumps(row))
    dest = ROOT / "docs" / "research" / "ranges_calibration.json"
    dest.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
