"""Walk-forward benchmark · component model vs the incumbent, on the full archive.

Protocol, and why each piece is there:

* **Expanding walk-forward, never a random split.** For every fold the training
  set is everything that finished strictly before the first gameweek being
  scored. Nothing in a fold's training data happened after its test window.
* **Blocks of gameweeks, retrained each block.** A manager retrains as the
  season goes; testing one gameweek at a time would be the same thing at higher
  cost. Default blocks are GW 10-16, 17-23, 24-30, 31-38.
* **Every test season from the second one onward**, so the headline is an
  average over folds and the worst season is visible rather than hidden.
* **Four arms.** The incumbent exactly as it runs today (current season only,
  its own feature list), the incumbent given the full archive to train on (so
  architecture and data volume can be told apart), the component model, and two
  baselines that cost nothing.
* **Two populations.** All rows, and only the players a manager would actually
  consider (rolling minutes >= 60). The second is the one that matters; a model
  can look strong on the first purely by predicting that reserves score zero.
* **A decision metric, not just an error metric.** Mean actual points of the
  top-ranked XI each gameweek, against the best possible XI, is closer to what
  the app is for than RMSE is.

Usage:
    python3 scripts/benchmark_points_models.py                  # everything
    python3 scripts/benchmark_points_models.py --seasons 2024-25 2025-26
    python3 scripts/benchmark_points_models.py --quick          # 2 folds/season
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics.component_model import (ComponentPointsModel, PLAYER_FEATURES,  # noqa: E402
                                       prepare)
from config import CACHE_DIR  # noqa: E402

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("benchmark")
logging.getLogger("analytics").setLevel(logging.ERROR)

ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "cache" / "archive" / "gw_archive.parquet"
OUT_JSON = Path(CACHE_DIR) / "benchmark_points_models.json"

# Fold boundaries. A fold scores [lo, hi] and trains on everything before lo.
BLOCKS: List[Tuple[int, int]] = [(10, 16), (17, 23), (24, 30), (31, 38)]
QUICK_BLOCKS: List[Tuple[int, int]] = [(17, 23), (31, 38)]

# The population a manager actually chooses between.
STARTER_MINUTES = 60.0

# Size of the notional XI used by the decision metric.
XI = 11


# ── the incumbent, reproduced ──────────────────────────────────────────────────

def incumbent_frame(gw_df: pd.DataFrame) -> pd.DataFrame:
    """`points_model`'s feature frame, built on the archive schema.

    The archive names columns differently from vaastav, so this maps them and
    then calls the real feature builder · the arm has to be the incumbent, not a
    reimplementation of it.

    Built one season at a time on purpose. The incumbent's rolling windows are
    within-season by construction (it only ever sees one season), and its `GW`
    column restarts at 1, so pooling seasons first would interleave them in the
    sort and produce features it would never actually compute.
    """
    from analytics.points_model import build_training_data

    out = []
    for season, block in gw_df.groupby("season"):
        df = block.rename(columns={
            "gw": "GW", "xgi": "expected_goal_involvements",
            "xgc": "expected_goals_conceded", "xp": "xP",
            "cbi": "clearances_blocks_interceptions",
        }).copy()
        for c in ("expected_goal_involvements", "expected_goals_conceded", "xP",
                  "clearances_blocks_interceptions", "tackles", "bps",
                  "clean_sheets", "goals_scored", "starts", "selected", "value"):
            if c not in df.columns:
                df[c] = 0.0
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        # `name` is the incumbent's grouping key. The archive's player_name is
        # not guaranteed unique, so the stable player code stands in for it.
        df["name"] = df["code"].astype(str)
        built = build_training_data(df)
        built["season_key"] = season
        out.append(built)
    return pd.concat(out, ignore_index=True)


TUNE_INCUMBENT = False


def fit_incumbent(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Train `points_model`'s XGBoost on `train`, score `test`.

    Uses the incumbent's untuned defaults by default. The live app runs 50
    Optuna trials on top of those, so `--tune-incumbent` re-runs the same folds
    with the real search · slow, and only worth doing to check that the
    comparison is not an artifact of leaving the tuner out.
    """
    import xgboost as xgb
    from analytics.points_model import FEATURES, tune_hyperparameters

    params = {"n_estimators": 400, "max_depth": 5, "learning_rate": 0.05,
              "subsample": 0.8, "colsample_bytree": 0.7, "min_child_weight": 5,
              "reg_alpha": 0.1, "reg_lambda": 1.0, "gamma": 0.1}
    if TUNE_INCUMBENT and len(train) > 500:
        # The tuner caches its result to disk for 24 hours, so without clearing
        # it every fold after the first would silently reuse the first fold's
        # parameters and the search would be measured once, not per fold.
        from analytics.points_model import TUNE_CACHE_PATH
        if TUNE_CACHE_PATH.exists():
            TUNE_CACHE_PATH.unlink()
        params = tune_hyperparameters(train[FEATURES].values,
                                      train["total_points"].values)
    m = xgb.XGBRegressor(**params, random_state=42, n_jobs=-1, verbosity=0,
                         eval_metric="rmse")
    m.fit(train[FEATURES].values, train["total_points"].values)
    return np.clip(m.predict(test[FEATURES].values), 0, None)


# ── metrics ────────────────────────────────────────────────────────────────────

def _metrics(y: np.ndarray, p: np.ndarray) -> Dict[str, float]:
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0, None)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    if len(y) < 10:
        return {}
    denom = ((y - y.mean()) ** 2).sum()
    sp = pd.Series(p).corr(pd.Series(y), method="spearman")
    return {
        "rmse": float(np.sqrt(((p - y) ** 2).mean())),
        "mae": float(np.abs(p - y).mean()),
        "r2": float(1 - ((p - y) ** 2).sum() / denom) if denom > 0 else float("nan"),
        "spearman": float(sp) if pd.notna(sp) else float("nan"),
        "n": int(len(y)),
    }


def _xi_capture(df: pd.DataFrame, pred_col: str) -> Dict[str, float]:
    """Mean actual points of the top-XI by prediction, per gameweek.

    Reported next to the best possible XI so the number reads as a share of what
    was there to be had. This is the metric closest to the app's job.
    """
    got, best, cap1 = [], [], []
    for _, block in df.groupby("gw"):
        if len(block) < XI:
            continue
        top = block.nlargest(XI, pred_col)["total_points"].sum()
        ceiling = block.nlargest(XI, "total_points")["total_points"].sum()
        got.append(top)
        best.append(ceiling)
        cap1.append(block.nlargest(1, pred_col)["total_points"].iloc[0])
    if not got:
        return {}
    return {"xi_points": float(np.mean(got)),
            "xi_ceiling": float(np.mean(best)),
            "xi_capture": float(np.sum(got) / np.sum(best)),
            "top1_points": float(np.mean(cap1)),
            "gws": len(got)}


# ── the run ────────────────────────────────────────────────────────────────────

def run(seasons: Optional[List[str]] = None, quick: bool = False,
        min_career: int = 3) -> Dict:
    if not ARCHIVE.exists():
        raise SystemExit("archive missing · run scripts/build_archive.py first")

    gw = pd.read_parquet(ARCHIVE)
    all_seasons = sorted(gw["season"].unique())
    test_seasons = seasons or all_seasons[1:]
    blocks = QUICK_BLOCKS if quick else BLOCKS

    logger.warning("preparing features on %d rows across %d seasons…",
                   len(gw), len(all_seasons))
    t0 = time.time()
    comp = prepare(gw)
    inc = incumbent_frame(gw)
    logger.warning("features ready in %.0fs", time.time() - t0)

    # The incumbent's frame is keyed (name=code, GW) within a season; align it
    # to the component frame so both arms score the identical rows.
    inc_key = inc.assign(code=inc["name"].astype(int),
                         gw=inc["GW"].astype(int),
                         season=inc["season_key"].astype(str))
    inc_key = inc_key.drop_duplicates(subset=["season", "gw", "code", "fixture"])

    rows: List[Dict] = []
    for season in test_seasons:
        for lo, hi in blocks:
            t_fold = time.time()
            comp_tr = comp[(comp["season"] < season)
                           | ((comp["season"] == season) & (comp["gw"] < lo))]
            comp_te = comp[(comp["season"] == season)
                           & (comp["gw"] >= lo) & (comp["gw"] <= hi)]
            comp_tr = comp_tr[comp_tr["career_games"] >= min_career]
            comp_te = comp_te[comp_te["career_games"] >= min_career]
            if len(comp_te) < 200 or len(comp_tr) < 2000:
                continue

            # Arm 1+2 · the incumbent, on this season only and on everything.
            inc_te = inc_key[(inc_key["season"] == season)
                             & (inc_key["gw"] >= lo) & (inc_key["gw"] <= hi)]
            inc_tr_season = inc_key[(inc_key["season"] == season)
                                    & (inc_key["gw"] < lo)]
            inc_tr_all = inc_key[(inc_key["season"] < season)
                                 | ((inc_key["season"] == season)
                                    & (inc_key["gw"] < lo))]

            scored = comp_te[["season", "gw", "code", "fixture", "position",
                              "total_points", "ewm_minutes"]].copy()

            if len(inc_tr_season) >= 500 and len(inc_te) >= 100:
                p = fit_incumbent(inc_tr_season, inc_te)
                scored = scored.merge(
                    inc_te[["season", "gw", "code", "fixture"]].assign(pred_incumbent=p),
                    on=["season", "gw", "code", "fixture"], how="left")
            else:
                scored["pred_incumbent"] = np.nan

            if len(inc_tr_all) >= 500 and len(inc_te) >= 100:
                p = fit_incumbent(inc_tr_all, inc_te)
                scored = scored.merge(
                    inc_te[["season", "gw", "code", "fixture"]].assign(pred_incumbent_all=p),
                    on=["season", "gw", "code", "fixture"], how="left")
            else:
                scored["pred_incumbent_all"] = np.nan

            # Arm 3 · the component model.
            model = ComponentPointsModel().fit(comp_tr)
            scored["pred_component"] = model.predict(comp_te)["xp"].values

            # Arms 4+5 · the free baselines.
            scored["pred_career_ppg"] = comp_te["career_ppg"].values
            scored["pred_ewm_points"] = comp_te["ewm_points"].values

            rows.append({"season": season, "lo": lo, "hi": hi,
                         "frame": scored, "secs": time.time() - t_fold,
                         "n_train": len(comp_tr)})
            logger.warning("%s GW%d-%d · %d test rows, %d train, %.0fs",
                           season, lo, hi, len(comp_te), len(comp_tr),
                           time.time() - t_fold)

    return _summarise(rows)


ARMS = [("pred_component", "component model"),
        ("pred_incumbent", "incumbent (this season only)"),
        ("pred_incumbent_all", "incumbent (full archive)"),
        ("pred_ewm_points", "baseline: EWM points"),
        ("pred_career_ppg", "baseline: career PPG")]


def _summarise(folds: List[Dict]) -> Dict:
    if not folds:
        raise SystemExit("no folds ran · check the season list")
    everything = pd.concat([f["frame"] for f in folds], ignore_index=True)

    # Score every arm on the SAME rows. The incumbent needs three played
    # gameweeks in the current season before it will predict at all, so without
    # this it would be measured on an easier, more established population than
    # the model it is being compared with.
    arm_cols = [c for c, _ in ARMS if c in everything.columns]
    before = len(everything)
    everything = everything.dropna(subset=arm_cols)
    dropped = before - len(everything)

    out: Dict = {"folds": len(folds), "rows": int(len(everything)),
                 "rows_dropped_for_common_support": int(dropped),
                 "overall": {}, "starters": {}, "per_season": {}, "decision": {}}

    starters = everything[everything["ewm_minutes"] >= STARTER_MINUTES]
    for col, label in ARMS:
        if everything[col].notna().sum() < 100:
            continue
        out["overall"][label] = _metrics(everything["total_points"], everything[col])
        out["starters"][label] = _metrics(starters["total_points"], starters[col])

    # Per season, on the population that matters, so the WORST season is visible.
    for season, block in starters.groupby("season"):
        out["per_season"][season] = {
            label: _metrics(block["total_points"], block[col])
            for col, label in ARMS if block[col].notna().sum() >= 100}

    # Decision metric over the whole pool, per season then averaged.
    for col, label in ARMS:
        if everything[col].notna().sum() < 100:
            continue
        per = []
        for season, block in everything.groupby("season"):
            d = _xi_capture(block.dropna(subset=[col]), col)
            if d:
                d["season"] = season
                per.append(d)
        if per:
            out["decision"][label] = {
                "xi_capture_mean": float(np.mean([d["xi_capture"] for d in per])),
                "xi_capture_worst": float(np.min([d["xi_capture"] for d in per])),
                "xi_points_mean": float(np.mean([d["xi_points"] for d in per])),
                "xi_ceiling_mean": float(np.mean([d["xi_ceiling"] for d in per])),
                "per_season": {d["season"]: round(d["xi_capture"], 4) for d in per},
            }
    return out


def report(res: Dict) -> str:
    L: List[str] = []
    L.append("Walk-forward benchmark · %d folds, %d scored rows"
             % (res["folds"], res["rows"]))
    L.append("")

    def table(title: str, block: Dict, keys=("rmse", "mae", "r2", "spearman", "n")):
        L.append(title)
        L.append("  %-32s %8s %8s %8s %9s %8s"
                 % ("", "RMSE", "MAE", "R2", "Spearman", "n"))
        for _, label in ARMS:
            m = block.get(label)
            if not m:
                continue
            L.append("  %-32s %8.3f %8.3f %+8.3f %9.3f %8d"
                     % (label, m["rmse"], m["mae"], m["r2"], m["spearman"], m["n"]))
        L.append("")

    table("ALL ROWS", res["overall"])
    table("LIKELY STARTERS (rolling minutes >= 60) · the population that matters",
          res["starters"])

    L.append("DECISION METRIC · actual points of the top-11 by prediction, per GW")
    L.append("  %-32s %10s %10s %10s %10s"
             % ("", "pts/GW", "ceiling", "capture", "worst szn"))
    for _, label in ARMS:
        d = res["decision"].get(label)
        if not d:
            continue
        L.append("  %-32s %10.1f %10.1f %9.1f%% %9.1f%%"
                 % (label, d["xi_points_mean"], d["xi_ceiling_mean"],
                    100 * d["xi_capture_mean"], 100 * d["xi_capture_worst"]))
    L.append("")

    L.append("PER SEASON · Spearman among likely starters (worst season is the constraint)")
    header = "  %-10s" % "season"
    labels = [lab for _, lab in ARMS if lab in res["starters"]]
    short = {"component model": "component", "incumbent (this season only)": "incumbent",
             "incumbent (full archive)": "incumb+all", "baseline: EWM points": "EWM pts",
             "baseline: career PPG": "career PPG"}
    for lab in labels:
        header += " %11s" % short.get(lab, lab[:11])
    L.append(header)
    for season in sorted(res["per_season"]):
        line = "  %-10s" % season
        for lab in labels:
            m = res["per_season"][season].get(lab)
            line += " %11s" % ("%.3f" % m["spearman"] if m else "-")
        L.append(line)
    L.append("")

    for lab in labels:
        vals = [res["per_season"][s][lab]["spearman"]
                for s in res["per_season"] if lab in res["per_season"][s]]
        if vals:
            L.append("  %-32s mean %.3f   worst %.3f (%s)"
                     % (lab, np.mean(vals), np.min(vals),
                        sorted(res["per_season"])[int(np.argmin(vals))]))
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="*", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--min-career", type=int, default=3)
    ap.add_argument("--tune-incumbent", action="store_true",
                    help="run the incumbent's Optuna search each fold (slow)")
    args = ap.parse_args()

    global TUNE_INCUMBENT
    TUNE_INCUMBENT = bool(args.tune_incumbent)

    res = run(args.seasons, quick=args.quick, min_career=args.min_career)
    text = report(res)
    print("\n" + text + "\n")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, default=float)
    print("full results · %s" % OUT_JSON)


if __name__ == "__main__":
    main()
