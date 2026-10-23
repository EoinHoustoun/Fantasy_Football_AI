"""Does a midweek game change minutes in a way the brain misses?

Uses the brain's own walk-forward folds (`data/cache/bench_brain/`, 3 seasons x
5 anchors x 6 weeks, built by scripts/benchmark_brain_horizon.py), so every
prediction was made only from matches before the anchor. For each regular
(60+ minutes in at least 2 of the 4 weeks before the anchor), single-fixture
weeks only, compare predicted with actual minutes and P(60+) by the club's
congestion: a European or cup match in the 4 days before the league match
(`mw_before`), in the 4 days after (`mw_after`), both, or neither.

If the brain already reads rotation from recent minutes, the residuals by flag
are near zero and there is nothing to add. If not, a per-flag multiplier on
expected minutes and P(60+) is fitted on two seasons and scored on the third
(leave one season out), and judged on minutes MAE, P(60+) Brier score and the
points ranking (Spearman) among regulars, worst season first.

Run:  python scripts/research_congestion_minutes.py
Writes docs/research/congestion_minutes_<date>.json
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics.congestion import archive_context  # noqa: E402
from data.fetchers.espn_fixtures import team_code  # noqa: E402
from data.processors.archive import load_gw_archive  # noqa: E402

SEASONS = ["2023-24", "2024-25", "2025-26"]
ANCHORS = [6, 12, 18, 24, 30]
FLAGS = ["none", "before", "after", "both"]


def flag(b, a):
    return "both" if (b and a) else "before" if b else "after" if a else "none"


def build():
    arc = load_gw_archive()
    out = []
    for s in SEASONS:
        rows = arc[arc["season"] == s]
        ctx = archive_context(arc, s)
        ctx["flag"] = [flag(b, a) for b, a in zip(ctx["mw_before"], ctx["mw_after"])]
        cmap = ctx.set_index(["team", "fixture"])["flag"]
        rmap = ctx.set_index(["team", "fixture"])["rest_days"]
        per = rows.groupby(["code", "gw"]).agg(minutes=("minutes", "sum"), points=("total_points", "sum"),
                                               n=("fixture", "nunique"), fixture=("fixture", "first"),
                                               team=("team_name", "first")).reset_index()
        per["team"] = per["team"].map(team_code)
        per["flag"] = [cmap.get((t, f), "none") for t, f in zip(per["team"], per["fixture"])]
        per["rest"] = [rmap.get((t, f), np.nan) for t, f in zip(per["team"], per["fixture"])]
        for t in ANCHORS:
            # Our own walk-forward cache, written by scripts/benchmark_brain_horizon.py.
            pr = pd.read_pickle(ROOT / "data" / "cache" / "bench_brain" / ("%s_gw%d.pkl" % (s, t)))
            before = per[(per["gw"] < t) & (per["gw"] >= t - 4)]
            reg = set(before[before["minutes"] >= 60].groupby("code")["gw"].nunique().loc[lambda x: x >= 2].index)
            d = pr.merge(per, on=["code", "gw"], how="inner")
            d = d[d["code"].isin(reg) & (d["n"] == 1) & (d["fixtures"] == 1)]
            d = d.assign(season=s, anchor=t, ahead=d["gw"] - t)
            out.append(d)
    return pd.concat(out, ignore_index=True)


def metrics(d, mins_col, p60_col, xp_col):
    rho = np.nanmean([spearmanr(g[xp_col], g["points"]).correlation for _, g in d.groupby(["anchor", "gw"]) if len(g) > 20])
    return {"mins_mae": round(float((d[mins_col] - d["minutes"]).abs().mean()), 3),
            "p60_brier": round(float(((d[p60_col] - (d["minutes"] >= 60)) ** 2).mean()), 4),
            "xp_spearman": round(float(rho), 4)}


def main():
    d = build()
    d["p60_hit"] = (d["minutes"] >= 60).astype(float)
    summary = {"rows": int(len(d)), "by_flag": {}, "by_flag_next_week": {}}
    for name, sub in (("by_flag", d), ("by_flag_next_week", d[d["ahead"] == 0])):
        for f in FLAGS:
            x = sub[sub["flag"] == f]
            if len(x):
                summary[name][f] = {"n": int(len(x)), "pred_mins": round(float(x["exp_minutes"].mean()), 1),
                                    "actual_mins": round(float(x["minutes"].mean()), 1),
                                    "mins_ratio": round(float(x["minutes"].sum() / x["exp_minutes"].sum()), 3),
                                    "pred_p60": round(float(x["p60"].mean()), 3),
                                    "actual_p60": round(float(x["p60_hit"].mean()), 3)}
    # rest days buckets (all flags)
    d["rest_b"] = pd.cut(d["rest"], [0, 3.5, 5.5, 8.5, 60], labels=["<=3", "4-5", "6-8", "9+"])
    summary["by_rest"] = {str(k): {"n": int(len(g)), "mins_ratio": round(float(g["minutes"].sum() / g["exp_minutes"].sum()), 3),
                                   "p60_gap": round(float(g["p60_hit"].mean() - g["p60"].mean()), 3)}
                          for k, g in d.groupby("rest_b")}
    # leave one season out
    loso = {}
    for test in SEASONS:
        tr, te = d[d["season"] != test], d[d["season"] == test].copy()
        mult = {f: float(tr.loc[tr["flag"] == f, "minutes"].sum() / tr.loc[tr["flag"] == f, "exp_minutes"].sum())
                for f in FLAGS if (tr["flag"] == f).any()}
        base = float(tr["minutes"].sum() / tr["exp_minutes"].sum())
        rel = {f: m / base for f, m in mult.items()}            # relative to the season-wide bias
        pg = {f: float(tr.loc[tr["flag"] == f, "p60_hit"].mean() - tr.loc[tr["flag"] == f, "p60"].mean()
                       - (tr["p60_hit"].mean() - tr["p60"].mean())) for f in rel}
        k = te["flag"].map(rel).fillna(1.0)
        te["mins_adj"] = te["exp_minutes"] * k
        te["p60_adj"] = (te["p60"] + te["flag"].map(pg).fillna(0.0)).clip(0, 1)
        te["xp_adj"] = te["xp"] * k
        loso[test] = {"rel_multiplier": {f: round(v, 3) for f, v in rel.items()},
                      "incumbent": metrics(te, "exp_minutes", "p60", "xp"),
                      "adjusted": metrics(te, "mins_adj", "p60_adj", "xp_adj")}
    summary["leave_one_season_out"] = loso
    print(json.dumps(summary, indent=1))
    path = ROOT / "docs" / "research" / ("congestion_minutes_%s.json" % date.today().isoformat())
    path.write_text(json.dumps(summary, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
