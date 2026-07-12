"""
FPL Points Prediction Model · XGBoost with Optuna hyperparameter tuning.

Training data: vaastav GW-by-GW history (this season).
Features (all computed using ONLY past data · no lookahead):
    roll_pts_4      Mean points over last 4 GWs
    roll_xgi_4      Sum xGI over last 4 GWs
    roll_xgc_4      Sum xGC over last 4 GWs
    roll_mins_4     Mean minutes over last 4 GWs
    roll_starts_4   Start rate over last 4 GWs (0-1)
    roll_xp_4       Mean lagged xP over last 4 GWs
    cum_ppg         Season PPG up to that point
    price_m         Price that GW (£m)
    was_home        1 = home, 0 = away
    is_gkp/def/mid/fwd  Position one-hot

Tuning: Optuna minimises RMSE on TimeSeriesSplit CV (3 folds, 50 trials).
        Tuned params cached to disk · only re-tunes if cache >24h old.

RMSE evaluated on temporal holdout (last 30% of GWs) · out-of-sample.
"""

import logging
import time
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Any

import xgboost as xgb
import optuna
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

from config import CACHE_DIR

logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ── Constants ──────────────────────────────────────────────────────────────────
ROLL_WINDOW      = 4
TRAIN_SPLIT      = 0.70
MIN_GWS_PLAYED   = 3
TOTAL_MANAGERS   = 11_000_000
OPTUNA_TRIALS    = 50
TUNE_CACHE_TTL   = 24 * 3600          # retune after 24h
TUNE_CACHE_PATH  = CACHE_DIR / "xgb_tuned_params.joblib"

# FPL squad constraints
SQUAD_LIMITS   = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
SQUAD_TOTAL    = 15
MAX_PER_TEAM   = 3

FEATURES = [
    "roll_pts_4",       # EWM avg points · recency-weighted
    "roll_xgi_4",       # EWM sum xGI · recency-weighted
    "roll_xgc_4",       # EWM sum xGC · recency-weighted
    "roll_mins_4",      # EWM avg minutes · recency-weighted
    "roll_starts_4",    # EWM start rate · recency-weighted
    "roll_xp_4",        # EWM avg expected points
    "roll_bps_4",       # EWM avg BPS · captures defensive + bonus contributions
    "roll_cs_4",        # EWM clean sheets (DEF=6pts, MID=1pt · separated from xGI)
    "roll_goals_4",     # EWM goals (DEF goals=6pts · separated since xGI treats all equal)
    "roll_cbit_4",      # EWM CBIT (clearances+blocks+interceptions+tackles) · actual DEFCON signal
    "cum_ppg",
    "price_m",
    "was_home",
    "is_gkp", "is_def", "is_mid", "is_fwd",
]


# ── Feature engineering ────────────────────────────────────────────────────────

def _build_rolling_features(gw_df: pd.DataFrame) -> pd.DataFrame:
    df = gw_df.sort_values(["name", "GW"]).copy()

    # Exponentially-weighted moving average · recent GWs count more.
    # halflife=2 means a game 2 GWs ago carries ~50% the weight of the latest game.
    # shift(1) ensures no lookahead (we only use past data to predict current GW).
    def _ewm(series: pd.Series) -> pd.Series:
        return series.shift(1).ewm(halflife=2, min_periods=2, adjust=True).mean()

    # Simple rolling sum (still useful for accumulating stats like xGI, CS, goals)
    def _roll_sum(series: pd.Series, window: int) -> pd.Series:
        return series.shift(1).rolling(window, min_periods=1).sum()

    g = df.groupby("name")
    df["roll_pts_4"]    = g["total_points"].transform(_ewm)
    df["roll_xgi_4"]    = g["expected_goal_involvements"].transform(lambda x: _roll_sum(x, ROLL_WINDOW))
    df["roll_xgc_4"]    = g["expected_goals_conceded"].transform(lambda x: _roll_sum(x, ROLL_WINDOW))
    df["roll_mins_4"]   = g["minutes"].transform(_ewm)
    df["roll_starts_4"] = g["starts"].transform(_ewm)
    df["roll_xp_4"]     = g["xP"].transform(_ewm) \
                          if "xP" in df.columns else pd.Series(0.0, index=df.index)

    # DEFCON & position-specific features (EWM for recency, sum for accumulation)
    df["roll_bps_4"]   = g["bps"].transform(_ewm) \
                         if "bps" in df.columns else pd.Series(0.0, index=df.index)
    df["roll_cs_4"]    = g["clean_sheets"].transform(lambda x: _roll_sum(x, ROLL_WINDOW)) \
                         if "clean_sheets" in df.columns else pd.Series(0.0, index=df.index)
    df["roll_goals_4"] = g["goals_scored"].transform(lambda x: _roll_sum(x, ROLL_WINDOW)) \
                         if "goals_scored" in df.columns else pd.Series(0.0, index=df.index)

    # Real CBIT: clearances+blocks+interceptions+tackles (2025-26 data has this)
    if "clearances_blocks_interceptions" in df.columns:
        df["cbit"] = df["clearances_blocks_interceptions"].fillna(0) + \
                     df.get("tackles", pd.Series(0, index=df.index)).fillna(0)
    else:
        df["cbit"] = pd.Series(0.0, index=df.index)
    df["roll_cbit_4"] = g["cbit"].transform(_ewm)

    df["cum_pts"]  = g["total_points"].transform(lambda x: x.shift(1).expanding().sum())
    df["gw_count"] = g.cumcount()
    df["cum_ppg"]  = df["cum_pts"] / df["gw_count"].clip(lower=1)

    df["price_m"]   = df["value"] / 10.0
    df["own_pct"]   = df["selected"] / TOTAL_MANAGERS * 100.0
    df["was_home"]  = df["was_home"].astype(float)

    pos = df["position"].str.upper()
    df["is_gkp"] = (pos == "GKP").astype(float)
    df["is_def"] = (pos == "DEF").astype(float)
    df["is_mid"] = (pos == "MID").astype(float)
    df["is_fwd"] = (pos == "FWD").astype(float)

    df = df[df["gw_count"] >= MIN_GWS_PLAYED]
    return df


def build_training_data(gw_df: pd.DataFrame) -> pd.DataFrame:
    df = _build_rolling_features(gw_df)
    df = df.dropna(subset=FEATURES + ["total_points"])
    logger.info(f"Training data: {len(df)} rows, {df['name'].nunique()} players, "
                f"GW{df['GW'].min()}-{df['GW'].max()}")
    return df


# ── Hyperparameter tuning ──────────────────────────────────────────────────────

def _is_tune_cache_fresh() -> bool:
    if not TUNE_CACHE_PATH.exists():
        return False
    return (time.time() - TUNE_CACHE_PATH.stat().st_mtime) < TUNE_CACHE_TTL


def tune_hyperparameters(X: np.ndarray, y: np.ndarray, n_trials: int = OPTUNA_TRIALS) -> dict:
    """
    Use Optuna to minimise CV RMSE on a TimeSeriesSplit.
    Returns best hyperparameter dict.
    """
    if _is_tune_cache_fresh():
        params = joblib.load(TUNE_CACHE_PATH)
        logger.info(f"Loaded tuned params from cache: {params}")
        return params

    logger.info(f"Tuning XGBoost hyperparameters ({n_trials} Optuna trials)...")

    tscv = TimeSeriesSplit(n_splits=3)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators":      trial.suggest_int("n_estimators", 100, 800),
            "max_depth":         trial.suggest_int("max_depth", 3, 8),
            "learning_rate":     trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample":         trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight":  trial.suggest_int("min_child_weight", 1, 10),
            "reg_alpha":         trial.suggest_float("reg_alpha", 1e-4, 1.0, log=True),
            "reg_lambda":        trial.suggest_float("reg_lambda", 0.5, 3.0),
            "gamma":             trial.suggest_float("gamma", 0.0, 0.5),
        }
        fold_rmses = []
        for train_idx, val_idx in tscv.split(X):
            m = xgb.XGBRegressor(
                **params, random_state=42, n_jobs=-1,
                verbosity=0, eval_metric="rmse",
            )
            m.fit(X[train_idx], y[train_idx])
            pred = np.clip(m.predict(X[val_idx]), 0, None)
            fold_rmses.append(float(np.sqrt(mean_squared_error(y[val_idx], pred))))
        return float(np.mean(fold_rmses))

    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    joblib.dump(best, TUNE_CACHE_PATH)
    logger.info(f"Best params (CV RMSE={study.best_value:.3f}): {best}")
    return best


# ── Model training & evaluation ────────────────────────────────────────────────

def train_and_evaluate(
    training_df: pd.DataFrame,
    tune: bool = True,
) -> Tuple[xgb.XGBRegressor, Dict[str, Any]]:
    """
    Train XGBoost on GW data with temporal train/test split.
    Optionally runs Optuna hyperparameter tuning first.

    Returns: (fitted model, metrics dict)
    """
    all_gws     = sorted(training_df["GW"].unique())
    n_train_gws = max(1, int(len(all_gws) * TRAIN_SPLIT))
    train_gws   = all_gws[:n_train_gws]
    test_gws    = all_gws[n_train_gws:]

    train = training_df[training_df["GW"].isin(train_gws)]
    test  = training_df[training_df["GW"].isin(test_gws)]

    X_train = train[FEATURES].values
    y_train = train["total_points"].values
    X_test  = test[FEATURES].values
    y_test  = test["total_points"].values

    # Tune or use defaults
    if tune and len(X_train) > 500:
        best_params = tune_hyperparameters(X_train, y_train)
    else:
        best_params = {
            "n_estimators": 400, "max_depth": 5, "learning_rate": 0.05,
            "subsample": 0.8, "colsample_bytree": 0.7, "min_child_weight": 5,
            "reg_alpha": 0.1, "reg_lambda": 1.0, "gamma": 0.1,
        }

    model = xgb.XGBRegressor(
        **best_params,
        random_state=42, n_jobs=-1, verbosity=0, eval_metric="rmse",
    )
    model.fit(X_train, y_train)

    y_pred = np.clip(model.predict(X_test), 0, None)
    rmse   = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae    = float(mean_absolute_error(y_test, y_pred))
    r2     = float(r2_score(y_test, y_pred))

    # Per-position RMSE
    test_copy = test.copy()
    test_copy["predicted"] = y_pred
    test_copy["error"]     = y_pred - y_test
    pos_rmse = {}
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        sub = test_copy[test_copy["position"].str.upper() == pos]
        if not sub.empty:
            pos_rmse[pos] = float(np.sqrt(mean_squared_error(sub["total_points"], sub["predicted"])))

    # Per-player error (for misses display)
    player_errors = (
        test_copy.groupby("name")
        .agg(actual_avg=("total_points", "mean"),
             pred_avg=("predicted",    "mean"),
             gw_count=("GW",           "count"))
        .reset_index()
    )
    player_errors["mean_error"] = player_errors["pred_avg"] - player_errors["actual_avg"]
    player_errors["abs_error"]  = player_errors["mean_error"].abs()
    player_errors = player_errors[player_errors["gw_count"] >= 3]

    # Feature importances
    importances = dict(zip(FEATURES, model.feature_importances_.tolist()))

    metrics = {
        "rmse":          rmse,
        "mae":           mae,
        "r2":            r2,
        "train_gws":     (int(min(train_gws)), int(max(train_gws))),
        "test_gws":      (int(min(test_gws)),  int(max(test_gws))) if test_gws else (0, 0),
        "n_train":       len(train),
        "n_test":        len(test),
        "pos_rmse":      pos_rmse,
        "player_errors": player_errors,
        "test_df":       test_copy[["name", "position", "GW", "total_points", "predicted", "error"]],
        "importances":   importances,
        "best_params":   best_params,
    }

    logger.info(f"XGBoost RMSE={rmse:.3f} MAE={mae:.3f} R²={r2:.3f}")
    return model, metrics


# ── Forward prediction ─────────────────────────────────────────────────────────

def predict_next_gw(
    model: xgb.XGBRegressor,
    players_df: pd.DataFrame,
    gw_df: pd.DataFrame,
    current_gw: int,
    fdr_map: Optional[Dict[int, float]] = None,
) -> pd.DataFrame:
    """Predict points for the next GW for all available players."""
    full = _build_rolling_features(gw_df.copy())
    latest = (
        full[full["GW"] <= current_gw]
        .sort_values("GW")
        .groupby("name")
        .last()
        .reset_index()
    )
    latest["was_home"] = 0.5   # unknown for upcoming GW

    X = latest[FEATURES].fillna(0).values
    base_pred = np.clip(model.predict(X), 0, None)
    latest["base_predicted_pts"] = base_pred

    # FDR multiplier
    name_to_team_id = dict(zip(
        players_df["name"].str.lower().str.strip(),
        players_df["team_id"]
    ))
    latest["team_id_fpl"] = latest["name"].str.lower().str.strip().map(name_to_team_id)
    latest["next_gw_fdr"] = latest["team_id_fpl"].map(fdr_map or {}).fillna(3.0)
    latest["fdr_mult"]    = (1.0 + (3.0 - latest["next_gw_fdr"]) * 0.15).clip(0.5, 1.5)
    latest["predicted_pts"] = (latest["base_predicted_pts"] * latest["fdr_mult"]).round(2)

    # Join FPL info
    fpl = players_df.copy()
    fpl["name_lower"] = fpl["name"].str.lower().str.strip()
    fpl_idx = fpl.drop_duplicates("name_lower").set_index("name_lower")

    latest["name_lower"] = latest["name"].str.lower().str.strip()
    result = latest.merge(
        fpl_idx[["web_name", "team", "team_id", "team_code", "team_short", "position", "price",
                 "ownership", "status", "form", "total_points",
                 "fpl_xgi_per90"]].reset_index(),
        on="name_lower", how="left", suffixes=("_v", ""),
    )
    result["web_name"] = result["web_name"].fillna(result["name"])
    result["status"]   = result["status"].fillna("a")

    keep = ["web_name", "team", "team_id", "team_code", "team_short", "position", "price", "ownership",
            "status", "predicted_pts", "base_predicted_pts", "next_gw_fdr",
            "form", "total_points", "fpl_xgi_per90",
            "roll_pts_4", "roll_xgi_4", "roll_mins_4"]
    keep = [c for c in keep if c in result.columns]
    result = result[keep].dropna(subset=["predicted_pts"])
    result = result[result["status"] == "a"]
    result = result.sort_values("predicted_pts", ascending=False).reset_index(drop=True)
    return result


# ── Free Hit optimizer ─────────────────────────────────────────────────────────

def optimize_free_hit_squad(
    predictions: pd.DataFrame,
    budget: float = 100.0,
    min_player_price: float = 3.9,
) -> pd.DataFrame:
    """
    Greedily pick the highest-scoring 15-man squad within FPL constraints.

    Constraints:
        2 GKP, 5 DEF, 5 MID, 3 FWD
        Max 3 players per club
        Total cost ≤ budget

    Budget reservation: before each pick we reserve `min_player_price` for
    every unfilled slot remaining, so we never paint ourselves into a corner
    where we run out of money before completing the squad.

    Returns DataFrame of selected 15 players with predicted_pts.
    """
    df = predictions[
        predictions["position"].notna() &
        predictions["price"].notna() &
        predictions["predicted_pts"].notna()
    ].copy()
    df = df[df["status"] == "a"]
    df = df.sort_values("predicted_pts", ascending=False).reset_index(drop=True)

    selected: List[pd.Series] = []
    pos_counts:  Dict[str, int] = {p: 0 for p in SQUAD_LIMITS}
    team_counts: Dict[Any, int] = {}
    total_cost = 0.0

    def _slots_remaining() -> int:
        return SQUAD_TOTAL - len(selected)

    for _, row in df.iterrows():
        if len(selected) >= SQUAD_TOTAL:
            break
        pos  = str(row.get("position", ""))
        cost = float(row.get("price", 0) or 0)
        tid  = row.get("team_id") or row.get("team", "?")

        if pos not in SQUAD_LIMITS:
            continue
        if pos_counts[pos] >= SQUAD_LIMITS[pos]:
            continue
        if team_counts.get(tid, 0) >= MAX_PER_TEAM:
            continue

        # Reserve budget for all remaining slots AFTER this pick
        reserved = (_slots_remaining() - 1) * min_player_price
        if total_cost + cost + reserved > budget:
            continue

        selected.append(row)
        pos_counts[pos] += 1
        total_cost += cost
        team_counts[tid] = team_counts.get(tid, 0) + 1

    result = pd.DataFrame(selected).reset_index(drop=True)
    result["total_cost"] = total_cost
    return result


def select_best_xi(squad: pd.DataFrame) -> pd.DataFrame:
    """
    From a 15-man squad, pick the optimal starting XI by predicted_pts.
    Constraints: 1 GKP, at least 3 DEF, at least 2 MID, at least 1 FWD, max 11 total.
    Uses a greedy: fill min requirements then add highest remaining.
    """
    if squad.empty:
        return squad

    xi_rows: List[pd.Series] = []
    used_idx = set()

    # Min requirements: 1 GKP, 3 DEF, 2 MID, 1 FWD
    requirements = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
    for pos, req in requirements.items():
        candidates = squad[squad["position"] == pos].sort_values("predicted_pts", ascending=False)
        for i, (idx, row) in enumerate(candidates.iterrows()):
            if i >= req:
                break
            xi_rows.append(row)
            used_idx.add(idx)

    # Fill remaining spots (up to 11) with highest predicted pts
    remaining = squad[~squad.index.isin(used_idx)].sort_values("predicted_pts", ascending=False)
    for idx, row in remaining.iterrows():
        if len(xi_rows) >= 11:
            break
        xi_rows.append(row)
        used_idx.add(idx)

    return pd.DataFrame(xi_rows).reset_index(drop=True)


def compare_squads(
    optimal_squad: pd.DataFrame,
    user_squad_preds: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Compare predicted pts between optimal free hit XI and user's current XI
    position by position.

    Returns dict with overall and per-position breakdowns.
    """
    opt_xi  = select_best_xi(optimal_squad)
    user_xi = select_best_xi(user_squad_preds[user_squad_preds["predicted_pts"].notna()])

    def _pos_pts(df: pd.DataFrame) -> Dict[str, float]:
        return (
            df.groupby("position")["predicted_pts"]
            .sum()
            .round(1)
            .to_dict()
        )

    opt_pos  = _pos_pts(opt_xi)
    user_pos = _pos_pts(user_xi)

    all_pos = ["GKP", "DEF", "MID", "FWD"]
    breakdown = []
    for pos in all_pos:
        opt_v  = opt_pos.get(pos, 0.0)
        user_v = user_pos.get(pos, 0.0)
        breakdown.append({
            "position":    pos,
            "optimal_pts": opt_v,
            "your_pts":    user_v,
            "difference":  round(opt_v - user_v, 1),
        })

    return {
        "optimal_total": float(opt_xi["predicted_pts"].sum()),
        "your_total":    float(user_xi["predicted_pts"].sum()),
        "gain":          float(opt_xi["predicted_pts"].sum() - user_xi["predicted_pts"].sum()),
        "breakdown":     pd.DataFrame(breakdown),
        "optimal_xi":    opt_xi,
        "your_xi":       user_xi,
    }


# ── One-shot pipeline ──────────────────────────────────────────────────────────

def run_pipeline(
    players_df: pd.DataFrame,
    current_gw: int,
    fdr_map: Optional[Dict[int, float]] = None,
    tune: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Full pipeline: load → features → tune → train → evaluate → predict."""
    from data.fetchers.vaastav import fetch_gw_history
    gw_df = fetch_gw_history()
    if gw_df is None:
        raise RuntimeError("Vaastav GW history unavailable.")

    gw_df = gw_df[gw_df["GW"] <= current_gw].copy()
    training_df = build_training_data(gw_df)
    model, metrics = train_and_evaluate(training_df, tune=tune)
    predictions = predict_next_gw(model, players_df, gw_df, current_gw, fdr_map)
    return predictions, metrics
