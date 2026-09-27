# Projection ranges · walk-forward calibration (27 Sep 2026)

`analytics/ranges.py` simulates each player's points from the brain's components
(minutes, goals, assists, saves, clean sheet, DEFCON, bonus), keeps the engine's
mean, and adds two things a per-match draw cannot produce:

- a per-player **rate multiplier** shared across the window (lognormal, sigma
  `RATE_SIGMA`): the engine can be wrong about a player's level;
- an **absence hazard** (`HAZARD` per week from week two, spells of 1-4 weeks):
  injuries and dropped places nobody knew about at the deadline.

Scored on the 15 cached walk-forward folds (2023-24 to 2025-26, GW6/12/18/24/30),
regular starters only, `scripts/calibrate_ranges.py`:

| sigma, hazard | 1-wk coverage | 6-wk coverage | 6-wk below / above | pair Brier (coin 0.242) |
|---|---|---|---|---|
| 0, 0 (match noise only) | 0.80 | 0.58 | 0.27 / 0.15 | 0.217 |
| 0.25, 0.04 | 0.82 | 0.68 | 0.18 / 0.14 | 0.210 |
| 0.35, 0.08 | 0.83 | 0.74 | 0.13 / 0.13 | 0.212 |
| **0.55, 0.08 (chosen)** | 0.85 | **0.80** | **0.10 / 0.10** | **0.209** |

Target: the 10-90% band holds 80% of outcomes with misses split evenly.
Match noise alone is badly overconfident over six weeks and misses LOW twice as
often as high; that asymmetry is unforeseen absence, which the hazard fixes.

"A outscores B over six weeks" is reliable: predicted 0.93 -> 0.89 happened,
predicted 0.07 -> 0.08 happened. So a displayed "62% Groß outscores Le Fée" can be
read at face value.

A sigma of 0.55 is a statement about the engine, not the game: its six-week
level for a player is wrong by about half either way often enough that the band
must say so. Spearman 0.44 over six weeks is consistent with that.
