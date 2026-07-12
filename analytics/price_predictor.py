"""
2026-27 start-price predictor.

FPL re-prices every player each summer, roughly on performance + popularity.
We learn that mapping from 9 historical season-pairs (2016-17→…→2025-26)
joined on the stable `code`, then apply it to the 2025-26 season summary.

Launch prices are multiples of £0.5m, so this is really ordinal bucket
prediction: we regress, then round to the nearest 0.5 and clip to
position-specific floors. Ridge baseline vs XGBoost · the backtest
(train ≤2023-24 pairs, test on 2024-25→2025-26) decides which ships.

Limitation (stated in the UI): players new to FPL next season · promoted
clubs, overseas signings · have no history and are not predicted.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import ARCHIVE_SEASONS

logger = logging.getLogger(__name__)

PRICE_FLOORS = {"GKP": 4.0, "DEF": 4.0, "MID": 4.5, "FWD": 4.5}
PRICE_CEILING = 15.0

FEATURES = [
    "end_price", "start_price", "price_change", "total_points", "ppg",
    "pp90", "minutes", "games_played", "goals_per90", "assists_per90",
    "bonus", "ownership_pctile", "team_changed",
    "is_gkp", "is_def", "is_mid", "is_fwd",
]


def _prep(summary: pd.DataFrame) -> pd.DataFrame:
    df = summary.copy()
    # ownership as within-season percentile (raw counts aren't comparable
    # across seasons with different player bases)
    df["ownership_pctile"] = (
        df.groupby("season")["selected_end"].rank(pct=True).fillna(0.5))
    for pos in ("GKP", "DEF", "MID", "FWD"):
        df[f"is_{pos.lower()}"] = (df["position"] == pos).astype(int)
    return df


def build_training_pairs(summary: pd.DataFrame) -> pd.DataFrame:
    """Join season N stats → season N+1 GW1 price on `code`."""
    df = _prep(summary)
    pairs = []
    for s_n, s_next in zip(ARCHIVE_SEASONS[:-1], ARCHIVE_SEASONS[1:]):
        left = df[df["season"] == s_n]
        right = df[(df["season"] == s_next) & (~df["joined_late"])][
            ["code", "start_price", "team_name"]
        ].rename(columns={"start_price": "next_start_price",
                          "team_name": "next_team"})
        merged = left.merge(right, on="code", how="inner")
        merged["team_changed"] = (merged["team_name"] != merged["next_team"]).astype(int)
        merged["pair"] = f"{s_n}→{s_next}"
        pairs.append(merged)
    out = pd.concat(pairs, ignore_index=True)
    logger.info(f"Training pairs: {len(out)} rows across {len(pairs)} season-pairs")
    return out


def _round_to_bucket(prices: np.ndarray, positions: pd.Series) -> np.ndarray:
    rounded = np.round(prices * 2) / 2
    floors = positions.map(PRICE_FLOORS).values
    return np.clip(rounded, floors, PRICE_CEILING)


def _fit_ridge(X, y):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer
    model = make_pipeline(SimpleImputer(strategy="median"),
                          StandardScaler(), Ridge(alpha=1.0))
    model.fit(X, y)
    return model


def _fit_xgb(X, y):
    from xgboost import XGBRegressor
    model = XGBRegressor(n_estimators=400, max_depth=4, learning_rate=0.05,
                         subsample=0.9, colsample_bytree=0.8,
                         random_state=42, verbosity=0)
    model.fit(X, y)
    return model


def train_price_model(summary: pd.DataFrame) -> Dict:
    """
    Backtest Ridge vs XGBoost on the most recent pair, retrain the winner
    on ALL pairs, and return {model, backtest, feature_importance}.
    """
    pairs = build_training_pairs(summary)
    test_pair = f"{ARCHIVE_SEASONS[-2]}→{ARCHIVE_SEASONS[-1]}"
    train = pairs[pairs["pair"] != test_pair]
    test = pairs[pairs["pair"] == test_pair]

    X_tr, y_tr = train[FEATURES], train["next_start_price"]
    X_te, y_te = test[FEATURES], test["next_start_price"]

    report = {}
    fitted = {}
    for name, fit in (("ridge", _fit_ridge), ("xgb", _fit_xgb)):
        model = fit(X_tr, y_tr)
        pred = _round_to_bucket(model.predict(X_te), test["position"])
        mae = float(np.abs(pred - y_te).mean())
        exact = float((pred == y_te).mean())
        within1 = float((np.abs(pred - y_te) <= 0.5).mean())
        report[name] = {"mae": round(mae, 3), "exact_bucket": round(exact, 3),
                        "within_half_m": round(within1, 3), "n_test": len(test)}
        fitted[name] = model
        logger.info(f"Price model [{name}]: MAE £{mae:.2f}m, "
                    f"exact {exact:.0%}, ±0.5 {within1:.0%}")

    winner = min(report, key=lambda k: report[k]["mae"])
    final_model = (_fit_ridge if winner == "ridge" else _fit_xgb)(
        pairs[FEATURES], pairs["next_start_price"])

    return {"model": final_model, "winner": winner, "backtest": report,
            "test_pair": test_pair}


def predict_next_season_prices(summary: pd.DataFrame,
                               trained: Optional[Dict] = None) -> pd.DataFrame:
    """
    Predict 2026-27 GW1 prices for every player in the last complete season.
    Returns: code, web_name, position, team_name, price_2025_26_end,
             predicted_start_price, total_points (last season).
    """
    if trained is None:
        trained = train_price_model(summary)

    last = _prep(summary[summary["season"] == ARCHIVE_SEASONS[-1]].copy())
    last["team_changed"] = 0   # unknowable pre-launch; assume stays

    raw = trained["model"].predict(last[FEATURES])
    last["predicted_start_price"] = _round_to_bucket(raw, last["position"])
    last["predicted_raw"] = np.round(raw, 2)

    out = last[["code", "web_name", "player_name", "position", "team_name",
                "end_price", "predicted_start_price", "predicted_raw",
                "total_points", "minutes", "ppg"]].rename(
        columns={"end_price": "price_2025_26_end"})
    return out.sort_values("predicted_start_price", ascending=False)
