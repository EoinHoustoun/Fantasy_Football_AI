"""Walk-forward test of the brain over 1, 3 and 6 gameweek horizons.

Question: does the brain rank players for the NEXT FEW WEEKS better than the
numbers the app's pages were using (FPL's published xP, 30-day form, season PPG)?

For each (season, anchor gameweek t):
  - train on every row before t (all earlier seasons + this season's GW < t)
  - project GW t .. t+5 with the real fixtures (outcomes blanked)
  - score against what actually happened

Population: "regulars", players with 60+ minutes in at least 2 of the 4
gameweeks before t. That is who a manager actually chooses between.

Metrics per window:
  - spearman   rank agreement of predicted vs actual window points
  - top20_pts  mean actual window points of the 20 players each method ranks highest
               (the decision metric: pick by this number, score this much)
  - slope      OLS slope of actual on predicted (1.0 = calibrated scale)
  - bias       mean(actual - predicted)

Run:  python scripts/benchmark_brain_horizon.py [--seasons 2023-24,2024-25,2025-26]
                                                [--anchors 6,12,18,24,30]
Writes docs/research/brain_horizon_<date>.json
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
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics import brain  # noqa: E402
from data.processors.archive import load_gw_archive  # noqa: E402

logging.basicConfig(level=logging.WARNING)
WINDOWS = (1, 3, 6)
OUTCOME_COLS = ["minutes", "total_points", "goals_scored", "assists", "clean_sheets",
                "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
                "saves", "yellow_cards", "red_cards", "bonus", "bps", "starts", "xp",
                "xg", "xa", "xgi", "xgc", "cbi", "tackles", "recoveries", "cbit",
                "defensive_contribution", "selected", "transfers_in", "transfers_out"]


def baselines(season_rows: pd.DataFrame, t: int) -> pd.DataFrame:
    before = season_rows[season_rows["gw"] < t]
    last4 = before[before["gw"] >= t - 4]
    per_gw = last4.groupby(["code", "gw"])["total_points"].sum().reset_index()
    form = per_gw.groupby("code")["total_points"].mean().rename("form")
    played = before[before["minutes"] > 0]
    ppg = played.groupby("code")["total_points"].mean().rename("ppg")
    # FPL's published xP for gameweek t as the archive holds it. WARNING: it is
    # captured after team news / kickoff (0.61 with same-GW points, 0.30 with the
    # next GW's), so `fpl_xp` and `blend` below are an upper bound, not a
    # baseline. The honest pre-deadline baseline is `form`.
    at_t = season_rows[season_rows["gw"] == t].groupby("code")["xp"].first().rename("fpl_xp")
    m60 = last4[last4["minutes"] >= 60].groupby("code")["gw"].nunique().rename("n60")
    return pd.concat([form, ppg, at_t, m60], axis=1)


def score(df: pd.DataFrame, pred_col: str) -> dict:
    d = df[["actual", pred_col]].dropna()
    if len(d) < 30:
        return {}
    rho = spearmanr(d[pred_col], d["actual"]).correlation
    top = d.nlargest(20, pred_col)["actual"].mean()
    x, y = d[pred_col].values, d["actual"].values
    slope = float(np.polyfit(x, y, 1)[0]) if np.std(x) > 0 else float("nan")
    return {"spearman": round(float(rho), 4), "top20_pts": round(float(top), 3),
            "slope": round(slope, 3), "bias": round(float((y - x).mean()), 3), "n": int(len(d))}


def run_fold(archive: pd.DataFrame, season: str, t: int) -> dict:
    hist = archive[(archive["season"] < season) |
                   ((archive["season"] == season) & (archive["gw"] < t))]
    srows = archive[archive["season"] == season]
    fut = srows[(srows["gw"] >= t) & (srows["gw"] < t + max(WINDOWS))].copy()
    truth = fut.groupby(["code", "gw"])["total_points"].sum().reset_index()
    up = fut.copy()
    for c in OUTCOME_COLS:
        if c in up.columns:
            up[c] = np.nan
    cache = ROOT / "data" / "cache" / "bench_brain" / ("%s_gw%d.pkl" % (season, t))
    if cache.exists():
        long = pd.read_pickle(cache)
    else:
        long = brain.project(hist, up)
        cache.parent.mkdir(parents=True, exist_ok=True)
        long.to_pickle(cache)

    base = baselines(srows, t)
    regulars = set(base.index[base["n60"].fillna(0) >= 2])
    out = {}
    for w in WINDOWS:
        gws = list(range(t, t + w))
        act = truth[truth["gw"].isin(gws)].groupby("code")["total_points"].sum().rename("actual")
        pr = long[long["gw"].isin(gws)].groupby("code")["xp"].sum().rename("brain")
        # Fixture count per player in the window, so the flat baselines are
        # per-match rates times matches played, which is how a page used them.
        nfx = long[long["gw"].isin(gws)].groupby("code")["fixtures"].sum().rename("nfx")
        df = pd.concat([act, pr, nfx], axis=1).join(base, how="left")
        df = df[df.index.isin(regulars)]
        for b in ("form", "ppg", "fpl_xp"):
            df[b + "_w"] = df[b] * df["nfx"].fillna(w)
        # Fair fight: live, the brain is scaled by FPL's chance-of-playing. The
        # archive has no chance column, but FPL's published xP is 0 exactly when
        # FPL rates a player out, so use that as the availability mask for the
        # first week and fade it like brain.availability_factor does.
        av_week = {}
        if df["fpl_xp"].notna().any():
            out_now = (df["fpl_xp"].fillna(0) <= 0).astype(float)
            per_gw = long[long["gw"].isin(gws)].pivot_table(
                index="code", columns="gw", values="xp", aggfunc="sum").reindex(df.index).fillna(0)
            fade = {0: 0.0, 1: 0.5, 2: 0.85}
            adj = sum(per_gw[g] * (1 - out_now * (1 - fade.get(g - t, 1.0)))
                      for g in per_gw.columns)
            df["brain_av"] = adj
            # Blend: brain's multi-week shape, FPL's read of next week.
            df["blend"] = df["brain_av"] * 0.5 + df["fpl_xp_w"].fillna(0) * 0.5 * (
                df["brain_av"].sum() / max(df["fpl_xp_w"].fillna(0).sum(), 1e-9))
        cols = [("brain", "brain"), ("brain_av", "brain_av"), ("blend", "blend"),
                ("form", "form_w"), ("ppg", "ppg_w"), ("fpl_xp", "fpl_xp_w")]
        out["w%d" % w] = {name: score(df, col) for name, col in cols if col in df.columns}
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
            print("%s GW%-2d %4ds  w3 rho/top20  " % (s, t, r["secs"]) + "  ".join(
                "%s %.3f/%.1f" % (m, w3[m].get("spearman", np.nan), w3[m].get("top20_pts", np.nan))
                for m in ("brain", "brain_av", "blend", "form", "fpl_xp") if w3.get(m)), flush=True)

    summary = {}
    for w in WINDOWS:
        k = "w%d" % w
        summary[k] = {}
        for m in ("brain", "brain_av", "blend", "form", "ppg", "fpl_xp"):
            vals = [r[k][m] for r in results if r[k].get(m)]
            if vals:
                summary[k][m] = {q: round(float(np.nanmean([v[q] for v in vals])), 4)
                                 for q in ("spearman", "top20_pts", "slope", "bias")}
            if m != "brain" and m in summary[k]:
                wins = sum(1 for r in results if r[k].get("brain") and r[k].get(m)
                           and r[k]["brain"]["spearman"] > r[k][m]["spearman"])
                summary[k][m]["brain_beats_in"] = "%d/%d" % (wins, len(results))
    print(json.dumps(summary, indent=1))
    out = ROOT / "docs" / "research" / ("brain_horizon_%s.json" % date.today().isoformat())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "folds": results}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
