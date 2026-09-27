# Brain validation (2026-09-27)

Walk-forward, 15 folds: seasons 2023-24, 2024-25 and 2025-26, anchors GW6/12/18/24/30.
Train on everything before the anchor, project the next 6 gameweeks on the real
fixtures, and score against what happened. The population is regulars (60+ minutes in
2 of the previous 4 gameweeks). Script: `scripts/benchmark_brain_horizon.py`; raw
results are in `brain_horizon_2026-09-27.json`.

The comparison is against a 4-gameweek form mean. That is the honest stand-in for FPL's
live `ep_next`, which is 30-day form.

| Window | Spearman brain | Spearman form | Brain wins | Top-20 actual pts, brain vs form | Brain wins |
|---|---|---|---|---|---|
| Next GW | 0.357 | 0.206 | 14/15 | 4.4 vs 4.0 | 11/15 |
| Next 3 | 0.415 | 0.259 | 15/15 | 13.5 vs 11.6 | 13/15 |
| Next 6 | 0.442 | 0.293 | 15/15 | 25.8 vs 21.8 | 15/15 |

Rejected: a blend with the archive's FPL `xp` column. It is recorded after team news,
so it leaks the result. Among regulars it correlates 0.61 with the same gameweek's
points but only 0.30 with the next gameweek's. The `fpl_xp` and `blend` columns in the
JSON are therefore an upper bound, not a baseline.
