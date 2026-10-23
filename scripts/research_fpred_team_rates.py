"""Research only · F Pred's Dixon-Coles goal rates vs the engine's conceded model.

The engine prices clean sheets and goals conceded from one XGBoost Poisson
regression on team form (`ComponentPointsModel`, stage B3): EWM of GOALS
scored and conceded, halflife 6, no allowance for who they came against.
F Pred's Dixon-Coles model fits attack and defence ratings jointly on Understat
xG with time decay, so it is opponent-adjusted and luck-light by construction.

Question: does F Pred's rate, alone or blended, predict a side's goals
conceded and clean sheet better than the engine's, out of sample?

Mechanics mirror the live brain at team level:
  * anchor at gameweek t of a test season; train on every side before t
  * engine features FROZEN at t for gameweeks t..t+3 (a team's ratings from
    its first match at or after t, opponent's likewise), as the brain freezes
    features at the planning point
  * Dixon-Coles fitted only on matches dated before t's first kickoff
  * anchors start at GW5 so every promoted side has history in both models
    (F Pred's seeding prior reads TODAY's relegation market, which would leak)

Variants: engine, dc (Poisson CS), dc_matrix (DC's own low-score correction),
geometric blends of the two rates at w = 0.25, 0.5, 0.75 (w = DC weight).

Scores: Poisson negative log-likelihood of goals conceded, clean-sheet log loss
and Brier, by horizon (1 = next gameweek ... 4) and by season.

Run (one heavy job at a time on the 8 GB Air):
    python scripts/research_fpred_team_rates.py --timing
    python scripts/research_fpred_team_rates.py
Writes data/cache/research_fpred_team_rates.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.special import gammaln

ROOT = Path(__file__).resolve().parent.parent
FPRED = ROOT.parent / "F_PRED"
sys.path.insert(0, str(ROOT))

from analytics import component_model as cm  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger("analytics").setLevel(logging.ERROR)

OUT = ROOT / "data" / "cache" / "research_fpred_team_rates.json"
TF = ["team_att", "team_def", "opp_att", "opp_def", "was_home_f",
      "team_matches", "league_gf"]
TEST_SEASONS = ["2023-24", "2024-25", "2025-26", "2026-27"]
FIRST_ANCHOR = 5
HORIZON = 4
BLENDS = (0.25, 0.5, 0.75)

# FPL club names -> football-data names (the rest match exactly)
NAME_MAP = {"Man Utd": "Man United", "Spurs": "Tottenham", "Nott'm Forest": "Nott'm Forest",
            "Sheffield Utd": "Sheffield United", "Coventry City": "Coventry",
            "Hull City": "Hull", "Ipswich Town": "Ipswich"}


def fpl_sides() -> pd.DataFrame:
    """Engine team-form rows for every fixture side, with names and kickoff."""
    hist = cm.build_history(cm.active_season())
    sides = cm._attach_opponent_ratings(cm.build_team_form(hist))
    sides["was_home_f"] = sides["was_home"].astype(float)
    ko = (hist.groupby(["season", "fixture"])["kickoff_time"].max()
          .rename("kickoff").reset_index())
    sides = sides.merge(ko, on=["season", "fixture"], how="left")
    sides["kickoff"] = pd.to_datetime(sides["kickoff"], utc=True, errors="coerce")
    other = sides[["season", "fixture", "was_home", "team_key"]].rename(
        columns={"team_key": "opp_key", "was_home": "_wh"})
    other["_wh"] = ~other["_wh"].astype(bool)
    sides = sides.merge(other, left_on=["season", "fixture", "was_home"],
                        right_on=["season", "fixture", "_wh"], how="left").drop(columns="_wh")
    sides["team_fd"] = sides["team_key"].map(lambda n: NAME_MAP.get(n, n))
    sides["opp_fd"] = sides["opp_key"].map(lambda n: NAME_MAP.get(n, n))
    return sides.dropna(subset=["conceded", "kickoff"])


DC_HELPER = ROOT / "scripts" / "_fpred_dc_rates.py"
FPRED_PY = FPRED / ".venv" / "bin" / "python"


def fpred_rates(jobs: pd.DataFrame) -> pd.DataFrame:
    """Dixon-Coles rates from F Pred, run in F Pred's own interpreter.

    F Pred has a top-level `data.py` and FF has a `data/` package, so the two
    cannot share a process. `jobs` holds (fold, cutoff, home, away); the helper
    refits once per fold on matches dated before the cutoff."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "jobs.parquet", Path(d) / "rates.parquet"
        jobs.to_parquet(src)
        subprocess.run([str(FPRED_PY), str(DC_HELPER), str(src), str(dst)],
                       cwd=str(FPRED), check=True)
        return pd.read_parquet(dst)


def frozen_features(season_sides: pd.DataFrame, t: int) -> pd.DataFrame:
    """Each side in GWs t..t+3 carries its team's (and opponent's) ratings as
    they stood before that team's first match at or after t."""
    win = season_sides[(season_sides["gw"] >= t) & (season_sides["gw"] < t + HORIZON)].copy()
    first = (season_sides[season_sides["gw"] >= t].sort_values(["gw", "kickoff"])
             .groupby("team_key").first())
    for c in ("team_att", "team_def", "team_matches", "league_gf"):
        win[c] = win["team_key"].map(first[c])
    win["opp_att"] = win["opp_key"].map(first["team_att"])
    win["opp_def"] = win["opp_key"].map(first["team_def"])
    win["k"] = win["gw"] - t + 1
    return win


def poisson_nll(lam, y):
    lam = np.clip(lam, 1e-6, None)
    return lam - y * np.log(lam) + gammaln(y + 1)


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def run(timing: bool = False) -> dict:
    from analytics import team_rates as TR
    t0 = time.time()
    sides = fpl_sides()
    port_sides = TR.fixture_sides(cm.build_history(cm.active_season()))
    port_sides = port_sides[port_sides["conceded"].notna()]
    print("loaded in %.0fs" % (time.time() - t0))
    order = sorted(sides["season"].unique())
    folds = [(s, t) for s in TEST_SEASONS
             for t in range(FIRST_ANCHOR, int(sides.loc[sides["season"] == s, "gw"].max()) + 1)]
    if timing:
        folds = folds[:2]
    rows, jobs = [], []
    for i, (season, t) in enumerate(folds):
        ss = sides[sides["season"] == season]
        test = frozen_features(ss, t).dropna(subset=TF)
        if test.empty:
            continue
        train = sides[(sides["season"].map(order.index) < order.index(season))
                      | ((sides["season"] == season) & (sides["gw"] < t))].dropna(subset=TF)
        m = xgb.XGBRegressor(objective="count:poisson", **cm._TREE)
        m.fit(train[TF], train["conceded"].astype(float))
        test["lam_engine"] = np.clip(m.predict(test[TF]), 0.05, 6.0)
        test["fold"] = i
        cutoff = ss.loc[ss["gw"] == t, "kickoff"].min().tz_convert(None).normalize()
        rates = TR.fit(port_sides[port_sides["kickoff"] < cutoff.tz_localize("UTC")])
        lp = [rates.conceded(a, b, bool(h)) for a, b, h in
              zip(test["team_key"], test["opp_key"], test["was_home"])]
        test["lam_port"] = [np.nan if v is None else v for v in lp]
        test["home"] = np.where(test["was_home"], test["team_fd"], test["opp_fd"])
        test["away"] = np.where(test["was_home"], test["opp_fd"], test["team_fd"])
        jobs.append(test[["fold", "home", "away"]].assign(cutoff=cutoff))
        rows.append(test)
    print("engine folds done in %.0fs" % (time.time() - t0), flush=True)
    jobs = pd.concat(jobs).drop_duplicates(["fold", "home", "away"])
    rates = fpred_rates(jobs)
    res = pd.concat(rows, ignore_index=True).merge(rates, on=["fold", "home", "away"], how="left")
    res["lam_dc"] = np.where(res["was_home"], res["lam_a"], res["lam_h"])
    res["cs_dc_matrix"] = np.where(res["was_home"], res["cs_h"], res["cs_a"])
    missing = res["lam_dc"].isna().mean()
    print("DC coverage %.1f%%" % (100 * (1 - missing)))
    res = res.dropna(subset=["lam_dc"])
    keep = ["season", "gw", "k", "fold", "team_key", "opp_key", "was_home",
            "conceded", "lam_engine", "lam_dc", "cs_dc_matrix", "lam_port"]
    print("port coverage %.1f%%" % (100 * res["lam_port"].notna().mean()))
    res["lam_port"] = res["lam_port"].fillna(res["lam_engine"])
    res[keep].to_parquet(OUT.with_suffix(".parquet"))
    return score(res)


def score(res: pd.DataFrame) -> dict:
    y = res["conceded"].astype(float).values
    cs = (y == 0).astype(float)
    variants = {"engine": res["lam_engine"].values, "dc": res["lam_dc"].values,
                "port": res["lam_port"].values}
    variants["port_blend_0.50"] = np.exp(0.5 * np.log(res["lam_port"]) + 0.5 * np.log(res["lam_engine"]))
    for w in BLENDS:
        variants["blend_%.2f" % w] = np.exp(w * np.log(res["lam_dc"]) + (1 - w) * np.log(res["lam_engine"]))
    out = {"n_sides": int(len(res)), "n_folds": int(res["fold"].nunique()),
           "by_variant": {}, "by_season": {}, "by_horizon": {}}

    def metrics(lam, p_cs, mask):
        return {"nll": round(float(poisson_nll(lam[mask], y[mask]).mean()), 4),
                "cs_logloss": round(float(logloss(p_cs[mask], cs[mask]).mean()), 4),
                "cs_brier": round(float(((p_cs[mask] - cs[mask]) ** 2).mean()), 4),
                "cs_pred": round(float(p_cs[mask].mean()), 3),
                "cs_actual": round(float(cs[mask].mean()), 3), "n": int(mask.sum())}

    allm = np.ones(len(res), bool)
    for name, lam in variants.items():
        out["by_variant"][name] = metrics(lam, np.exp(-lam), allm)
    out["by_variant"]["dc_matrix"] = metrics(res["lam_dc"].values, res["cs_dc_matrix"].values, allm)
    for s in sorted(res["season"].unique()):
        mk = (res["season"] == s).values
        out["by_season"][s] = {n: metrics(l, np.exp(-l), mk) for n, l in variants.items()}
    for k in range(1, HORIZON + 1):
        mk = (res["k"] == k).values
        out["by_horizon"][k] = {n: metrics(l, np.exp(-l), mk) for n, l in variants.items()}
    # Is the gap real? Paired bootstrap over folds (whole anchor weeks resampled,
    # so the four horizons of one anchor stay together).
    rng = np.random.default_rng(7)
    folds = res["fold"].values
    uniq = np.unique(folds)
    idx = {f: np.where(folds == f)[0] for f in uniq}
    base_ll = logloss(np.exp(-variants["engine"]), cs)
    base_nll = poisson_nll(variants["engine"], y)
    out["bootstrap_vs_engine"] = {}
    for name in [n for n in variants if n != "engine"]:
        d_ll = logloss(np.exp(-variants[name]), cs) - base_ll
        d_nll = poisson_nll(variants[name], y) - base_nll
        sums = np.array([[d_ll[idx[f]].sum(), d_nll[idx[f]].sum(), len(idx[f])] for f in uniq])
        boots = []
        for _ in range(2000):
            pick = sums[rng.integers(0, len(uniq), len(uniq))]
            boots.append((pick[:, 0].sum() / pick[:, 2].sum(), pick[:, 1].sum() / pick[:, 2].sum()))
        b = np.array(boots)
        out["bootstrap_vs_engine"][name] = {
            "cs_logloss_delta": round(float(d_ll.mean()), 4),
            "cs_ci90": [round(float(np.percentile(b[:, 0], 5)), 4), round(float(np.percentile(b[:, 0], 95)), 4)],
            "p_better_cs": round(float((b[:, 0] < 0).mean()), 3),
            "nll_delta": round(float(d_nll.mean()), 4),
            "nll_ci90": [round(float(np.percentile(b[:, 1], 5)), 4), round(float(np.percentile(b[:, 1], 95)), 4)],
            "p_better_nll": round(float((b[:, 1] < 0).mean()), 3)}
    OUT.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--timing", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    r = run(timing=a.timing)
    print(json.dumps(r["by_variant"], indent=1))
    print("total %.0fs" % (time.time() - t0))
