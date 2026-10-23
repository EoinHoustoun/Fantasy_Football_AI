# F Pred Dixon-Coles rates vs the engine's conceded model (23 Oct 2026)

Script: `scripts/research_fpred_team_rates.py` (+ `scripts/_fpred_dc_rates.py`,
run in F Pred's interpreter). Results: `data/cache/research_fpred_team_rates.json`.

## Question

The engine prices clean sheets and goals conceded from one XGBoost Poisson model
on goals-based team form (EWM halflife 6, no opponent adjustment). F Pred's
Dixon-Coles fits attack and defence jointly on Understat xG with a 14-week
decay. Does F Pred's rate, alone or blended, predict a side's goals conceded and
clean sheet better, out of sample?

## Method

Walk-forward at team level, mirroring the brain: anchor at every GW from 5 in
2023-24, 2024-25, 2025-26 and 2026-27 (105 anchors, 7,926 fixture sides); train
both models only on matches before the anchor; engine features frozen at the
anchor for GW t..t+3. Blends are geometric in the rate (w = F Pred weight).

## Results

| Variant | CS log loss | CS Brier | Goals NLL | Mean CS pred (actual 0.230) |
|---|---|---|---|---|
| engine | 0.5299 | 0.1747 | 1.5274 | 0.255 |
| F Pred | 0.5119 | 0.1678 | 1.5066 | 0.233 |
| blend 0.50 | 0.5153 | 0.1691 | 1.5022 | 0.242 |
| blend 0.75 | 0.5122 | 0.1680 | 1.5005 | 0.237 |

By season (CS log loss, engine vs blend 0.50 vs blend 0.75):
2023-24 0.4991 / 0.4818 / 0.4775 · 2024-25 0.5453 / 0.5266 / 0.5217 ·
2025-26 0.5446 / 0.5362 / 0.5356 · 2026-27 (120 sides) 0.5483 / 0.5463 / 0.5514.

Paired bootstrap over anchors (2,000 draws), blend 0.75 minus engine: CS log loss
-0.0178 (90% CI -0.0213 to -0.0143), goals NLL -0.0269 (-0.0335 to -0.0211).
Blend 0.50: -0.0146 (-0.0170 to -0.0122) and -0.0252 (-0.0293 to -0.0210).
The gain holds at every horizon from 1 to 4 GWs.

## Reading

- The engine over-forecasts clean sheets in every season (by 1.5 to 4 points).
  F Pred is calibrated.
- Blends from 0.5 to 0.75 all beat the engine: a region, not a spike.
  Blend 0.50 is the only variant that beats the engine in all four seasons on
  both scores, so it is the worst-season choice; 0.75 has the best mean.
- 2026-27 is 120 sides: too small to separate 0.5 from 0.75.

## Not covered

Team level only. Player xP also uses team form for attacking returns, and the
gain in player points has not been measured. Next step before any live use:
wire the blend into the brain behind a flag and rerun
`scripts/benchmark_brain_horizon.py`. Live use also needs F Pred's ratings
available to the engine each gameweek (a cross-repo dependency, or a port of the
Dixon-Coles fit into FF).

## Player level (23 Oct 2026)

Script: `scripts/benchmark_team_rate_blend.py`, results in
`docs/research/team_rate_blend_2026-10-23.json`. 15 walk-forward folds
(2023-24, 2024-25, 2025-26 at GW6/12/18/24/30), one brain fit per fold, scored
with the blend at 0, 0.5 and 0.75. Blend 0.5 minus engine:

| Window | Group | Spearman | Folds won | Worst season |
|---|---|---|---|---|
| 3 GW | DEF+GK | +0.022 | 12/15 | +0.005 |
| 3 GW | all | +0.011 | 11/15 | +0.002 |
| 6 GW | DEF+GK | +0.024 | 10/15 | +0.001 |
| 6 GW | all | +0.014 | 13/15 | +0.001 |
| 1 GW | DEF+GK | +0.011 | 9/15 | +0.001 |

Top-20 DEF+GK picks gain +0.63 pts over 3 GWs (13/15 folds). Midfielders and
forwards are unchanged, as expected (only the clean-sheet point moves).
Clean-sheet log loss improves in 2023-24 and 2024-25 and is flat in 2025-26.

Reading: 0.5 is positive in every season on every DEF+GK score, so it passes
the worst-season test; 0.75 has the better mean but goes negative in one season
at 1 and 6 GWs. The weakest season is 2025-26 (the only DEFCON season, the one
most like 2026-27): DEF+GK 3 GW Spearman +0.004, worse in 3 of 5 folds. The
gain is real but small, mostly in which defenders rank above which.
