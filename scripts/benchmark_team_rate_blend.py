"""Player-level walk-forward · does the team-rate blend improve the brain?

Same folds and population as `benchmark_brain_horizon.py` (regulars: 60+
minutes in 2 of the 4 gameweeks before the anchor), but each fold is fitted
ONCE (`brain.fit_frame`) and scored at several `TEAM_RATE_BLEND` weights
(`brain.score_frame`), so the variants differ only in the conceded rate.

The blend moves clean sheets and the conceded penalty, so the scores that
matter most are for keepers and defenders; all positions are reported too.

Run:  python scripts/benchmark_team_rate_blend.py [--seasons ...] [--anchors ...]
Writes docs/research/team_rate_blend_<date>.json
"""
import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from analytics import brain  # noqa: E402
from benchmark_brain_horizon import OUTCOME_COLS, baselines, score  # noqa: E402
from data.processors.archive import load_gw_archive  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger("analytics").setLevel(logging.ERROR)
BLENDS = (0.0, 0.5, 0.75)
WINDOWS = (1, 3, 6)
GROUPS = {"all": None, "def_gk": ("DEF", "GKP"), "mid_fwd": ("MID", "FWD")}


def run_fold(archive, season, t):
    hist = archive[(archive["season"] < season) |
                   ((archive["season"] == season) & (archive["gw"] < t))]
    srows = archive[archive["season"] == season]
    fut = srows[(srows["gw"] >= t) & (srows["gw"] < t + max(WINDOWS))].copy()
    truth = fut.groupby(["code", "gw"])["total_points"].sum().reset_index()
    cs_truth = fut[fut["minutes"] >= 60].groupby(["code", "gw"])["clean_sheets"].max().reset_index()
    pos = fut.groupby("code")["position"].first().astype(str).str.upper()
    up = fut.copy()
    for c in OUTCOME_COLS:
        if c in up.columns:
            up[c] = np.nan
    model, test, rate_inputs = brain.fit_frame(hist, up)
    coverage = float(np.isfinite(rate_inputs[0]).mean())
    longs = {b: brain.score_frame(model, test, rate_inputs, b) for b in BLENDS}
    base = baselines(srows, t)
    regulars = set(base.index[base["n60"].fillna(0) >= 2])
    out = {"rate_coverage": round(coverage, 3)}
    for w in WINDOWS:
        gws = list(range(t, t + w))
        act = truth[truth["gw"].isin(gws)].groupby("code")["total_points"].sum().rename("actual")
        df = pd.DataFrame(act)
        for b, long in longs.items():
            df["b%.2f" % b] = long[long["gw"].isin(gws)].groupby("code")["xp"].sum()
        df = df[df.index.isin(regulars)]
        df["pos"] = pos.reindex(df.index)
        out["w%d" % w] = {}
        for g, keep in GROUPS.items():
            sub = df if keep is None else df[df["pos"].isin(keep)]
            out["w%d" % w][g] = {"b%.2f" % b: score(sub, "b%.2f" % b) for b in BLENDS}
    # clean-sheet calibration on players who played 60+ (next gameweek only)
    cs = cs_truth[cs_truth["gw"] == t].set_index("code")["clean_sheets"]
    out["cs_next"] = {}
    for b, long in longs.items():
        p = long[long["gw"] == t].set_index("code")["p_clean_sheet"].reindex(cs.index).dropna()
        y = (cs.reindex(p.index) > 0).astype(float)
        pc = np.clip(p.values, 1e-6, 1 - 1e-6)
        out["cs_next"]["b%.2f" % b] = {
            "logloss": round(float(-(y * np.log(pc) + (1 - y) * np.log(1 - pc)).mean()), 4),
            "pred": round(float(p.mean()), 3), "actual": round(float(y.mean()), 3), "n": int(len(p))}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2023-24,2024-25,2025-26")
    ap.add_argument("--anchors", default="6,12,18,24,30")
    a = ap.parse_args()
    archive = load_gw_archive()
    results = []
    for s in a.seasons.split(","):
        for t in [int(x) for x in a.anchors.split(",")]:
            t0 = time.time()
            r = run_fold(archive, s, t)
            r.update({"season": s, "anchor": t, "secs": round(time.time() - t0)})
            results.append(r)
            w3 = r["w3"]
            print("%s GW%-2d %4ds cov %.2f  w3 rho all %s  def_gk %s  cs_ll %s" % (
                s, t, r["secs"], r["rate_coverage"],
                "/".join("%.3f" % w3["all"][k].get("spearman", np.nan) for k in w3["all"]),
                "/".join("%.3f" % w3["def_gk"][k].get("spearman", np.nan) for k in w3["def_gk"]),
                "/".join("%.4f" % r["cs_next"][k]["logloss"] for k in r["cs_next"])), flush=True)
            out = ROOT / "docs" / "research" / ("team_rate_blend_%s.json" % date.today().isoformat())
            out.write_text(json.dumps({"folds": results}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
