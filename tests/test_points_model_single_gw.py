"""One played gameweek must not crash the points model.

After GW1 the temporal split leaves an empty holdout: train_and_evaluate used
to hand a zero-length array to sklearn's metrics and raise. It must train on
everything it has and report the holdout as absent instead.
"""
import math

import numpy as np
import pandas as pd

from analytics import points_model as pm


def _frame(n_gws: int, n_players: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for gw in range(1, n_gws + 1):
        for i in range(n_players):
            row = {f: float(rng.random()) for f in pm.FEATURES}
            row.update({
                "GW": gw,
                "name": f"p{i}",
                "position": ["GKP", "DEF", "MID", "FWD"][i % 4],
                "total_points": float(rng.integers(0, 12)),
            })
            rows.append(row)
    return pd.DataFrame(rows)


def test_single_gameweek_trains_without_holdout():
    model, metrics = pm.train_and_evaluate(_frame(1), tune=False)
    assert model is not None
    assert metrics["n_test"] == 0
    assert metrics["test_gws"] == (0, 0)
    assert metrics["train_gws"] == (1, 1)
    assert all(math.isnan(metrics[k]) for k in ("rmse", "mae", "r2"))
    assert metrics["pos_rmse"] == {}
    assert metrics["player_errors"].empty
    assert metrics["test_df"].empty


def test_two_gameweeks_still_holds_one_out():
    _, metrics = pm.train_and_evaluate(_frame(2), tune=False)
    assert metrics["n_test"] > 0
    assert not math.isnan(metrics["rmse"])
