"""Score blend variants of brain x FPL xP on the cached walk-forward folds.

Reads data/cache/bench_brain/<season>_gw<t>.pkl written by
benchmark_brain_horizon.py, so trying a new blend takes seconds, not an hour.

Variants:
  brain_av        brain scaled by FPL availability (FPL xP == 0 -> out)
  flat_w          w * brain_av + (1-w) * k * FPL xP x fixtures (flat across the window)
  shape_w         w * brain_av + (1-w) * k * FPL xP x brain's week shape
                  ("FPL's level, the brain's fixture shape")
k rescales FPL's total to the brain's so the weight means what it says.

Seasons without FPL xP in the archive (2025-26) are skipped: no FPL number to blend.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from data.processors.archive import load_gw_archive  # noqa: E402

WINDOWS = (1, 3, 6)
FADE = {0: 0.0, 1: 0.5, 2: 0.85}


def metrics(pred, act):
    d = pd.concat([pred.rename("p"), act.rename("a")], axis=1).dropna()
    if len(d) < 30:
        return None
    x, y = d["p"].values, d["a"].values
    return {"rho": spearmanr(x, y).correlation,
            "top20": d.nlargest(20, "p")["a"].mean(),
            "slope": np.polyfit(x, y, 1)[0], "bias": (y - x).mean()}


def main():
    arch = load_gw_archive()
    rows = []
    for f in sorted((ROOT / "data" / "cache" / "bench_brain").glob("*.pkl")):
        season, t = f.stem.split("_gw")
        t = int(t)
        long = pd.read_pickle(f)
        s = arch[arch["season"] == season]
        fx = s[s["gw"] == t].groupby("code")["xp"].first()
        if fx.notna().sum() == 0:
            continue
        before = s[(s["gw"] < t) & (s["gw"] >= t - 4)]
        regulars = set(before[before["minutes"] >= 60].groupby("code")["gw"].nunique()
                       .loc[lambda x: x >= 2].index)
        truth = s[(s["gw"] >= t) & (s["gw"] < t + 6)].groupby(["code", "gw"])["total_points"].sum()
        per = long.pivot_table(index="code", columns="gw", values="xp", aggfunc="sum").fillna(0)
        nfx = long.pivot_table(index="code", columns="gw", values="fixtures", aggfunc="sum").fillna(0)
        per, nfx = per.reindex(sorted(regulars)).fillna(0), nfx.reindex(sorted(regulars)).fillna(0)
        fpl = fx.reindex(per.index).fillna(0)
        out_now = (fpl <= 0).astype(float)
        gws = sorted(per.columns)
        av = pd.DataFrame({g: per[g] * (1 - out_now * (1 - FADE.get(g - t, 1.0))) for g in gws})
        k = av[t].sum() / max(fpl.sum(), 1e-9) if t in av.columns else 1.0
        g0 = per[t] if t in per.columns else per[gws[0]]
        shape = pd.DataFrame({g: (per[g] / g0.replace(0, np.nan)).clip(0, 3).fillna(nfx[g]) for g in gws})
        flat_fpl = pd.DataFrame({g: fpl * nfx[g] for g in gws})
        shape_fpl = pd.DataFrame({g: fpl * shape[g] for g in gws})
        # FPL's number is for next week only; later weeks the "out" fades like brain_av.
        for g in gws:
            fade = 1 - out_now * (1 - FADE.get(g - t, 1.0))
            back = (out_now > 0) & (fade > 0)
            flat_fpl.loc[back, g] = av.loc[back, g] / max(k, 1e-9)
            shape_fpl.loc[back, g] = av.loc[back, g] / max(k, 1e-9)
        variants = {"brain_av": av, "fpl_flat": flat_fpl * k}
        for w in (0.3, 0.5, 0.7):
            variants["flat_%.1f" % w] = w * av + (1 - w) * k * flat_fpl
            variants["shape_%.1f" % w] = w * av + (1 - w) * k * shape_fpl
        for win in WINDOWS:
            gw_set = [g for g in gws if g < t + win]
            act = truth[truth.index.get_level_values("gw").isin(gw_set)].groupby("code").sum()
            act = act.reindex(per.index)
            for name, frame in variants.items():
                m = metrics(frame[gw_set].sum(axis=1), act)
                if m:
                    rows.append({"season": season, "t": t, "w": win, "variant": name, **m})
    df = pd.DataFrame(rows)
    summ = df.groupby(["w", "variant"])[["rho", "top20", "slope", "bias"]].mean().round(3)
    print(summ.to_string())
    best = df.pivot_table(index=["season", "t", "w"], columns="variant", values="rho")
    print("\nfolds:", best.reset_index()[["season", "t"]].drop_duplicates().shape[0])
    out = ROOT / "docs" / "research" / "brain_blends.json"
    out.write_text(json.dumps(summ.reset_index().to_dict("records"), indent=1))


if __name__ == "__main__":
    main()
