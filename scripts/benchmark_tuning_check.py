"""Does Optuna close the gap? · fairness check on the incumbent arm.

`benchmark_points_models.py` runs the incumbent with `points_model`'s untuned
defaults, while the live app runs 50 Optuna trials on top of them. If the tuner
were worth a lot, the benchmark would be unfair to the incumbent and its verdict
would be an artifact of how the arms were configured.

This scores the same folds twice, tuned and untuned, on the small arm only
(current season, ~25k rows) · tuning the full-archive arm would take hours and
the question is whether the search matters at all, not by how much on every arm.

    python3 scripts/benchmark_tuning_check.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.benchmark_points_models as bench  # noqa: E402
from analytics.component_model import prepare  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("tuning-check")

SEASON = "2025-26"
BLOCKS = [(17, 23), (31, 38)]


def main() -> None:
    gw = pd.read_parquet(bench.ARCHIVE)
    comp = prepare(gw)
    inc = bench.incumbent_frame(gw)
    inc = inc.assign(code=inc["name"].astype(int), gw=inc["GW"].astype(int),
                     season=inc["season_key"].astype(str))
    inc = inc.drop_duplicates(subset=["season", "gw", "code", "fixture"])

    rows = []
    for lo, hi in BLOCKS:
        te = inc[(inc["season"] == SEASON) & (inc["gw"] >= lo) & (inc["gw"] <= hi)]
        tr = inc[(inc["season"] == SEASON) & (inc["gw"] < lo)]
        if len(tr) < 500 or len(te) < 100:
            continue

        preds = {}
        for label, tune in (("untuned", False), ("Optuna 50 trials", True)):
            bench.TUNE_INCUMBENT = tune
            t0 = time.time()
            preds[label] = bench.fit_incumbent(tr, te)
            logger.warning("%s GW%d-%d · %s in %.0fs", SEASON, lo, hi, label,
                           time.time() - t0)

        keys = te[["season", "gw", "code", "fixture"]].copy()
        for label, p in preds.items():
            keys[label] = p
        merged = comp[["season", "gw", "code", "fixture", "total_points",
                       "ewm_minutes"]].merge(keys, on=["season", "gw", "code",
                                                       "fixture"], how="inner")
        rows.append(merged)

    if not rows:
        raise SystemExit("no folds ran")
    all_rows = pd.concat(rows, ignore_index=True)
    starters = all_rows[all_rows["ewm_minutes"] >= 60]

    print("\nIncumbent, tuned vs untuned · %s, %d folds, %d rows (%d starters)"
          % (SEASON, len(rows), len(all_rows), len(starters)))
    for label in ("untuned", "Optuna 50 trials"):
        for name, block in (("all rows", all_rows), ("starters", starters)):
            y = block["total_points"].values
            p = np.clip(block[label].values, 0, None)
            rmse = float(np.sqrt(((p - y) ** 2).mean()))
            sp = float(pd.Series(p).corr(pd.Series(y), method="spearman"))
            print("  %-18s %-9s RMSE %.3f   Spearman %.3f   n=%d"
                  % (label, name, rmse, sp, len(block)))


if __name__ == "__main__":
    main()
