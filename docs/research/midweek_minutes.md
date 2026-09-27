# Midweek minutes and weekend rotation (2026-09-27)

**Question.** Does the engine overrate players who played cup or European minutes in the six days
before a Premier League match (the "rotation after midweek" belief)?

**Data.** Non-PL appearances (Champions League, Europa, Conference, EFL Cup) from
FPL-Core-Insights (github.com/olbauday/FPL-Core-Insights; no licence, so it is cached locally only and
never committed). Scored against the engine's out-of-sample predictions in the cached 2025-26
walk-forward folds (GW6/12/18/24/30, six weeks each). Only regulars (predicted p60 >= 0.6).
Script: `scripts/test_midweek_effect.py`.

| Midweek minutes | n | predicted P(60+) | actual | gap | predicted xP | actual pts |
|---|---|---|---|---|---|---|
| none | 4815 | 0.822 | 0.693 | -0.129 | 3.21 | 2.76 |
| 1-45 | 172 | 0.803 | 0.785 | -0.018 | 3.52 | 3.76 |
| 46+ | 452 | 0.830 | 0.759 | -0.071 | 3.56 | 3.38 |

46+ minus none, P(60+) gap: **+0.058** (bootstrap 95% CI +0.017 to +0.100), same sign in four of
five folds.

**Reading.** The opposite of the rotation belief: players coming off a full midweek game started and
lasted MORE reliably than the engine expected. Midweek minutes mark a first-choice player at a
stronger club, and that outweighs fatigue. A rotation penalty would make the engine worse.

**Decision.** No change to the engine. A positive adjustment is not shipped either: one season,
confounded with club strength. The fetcher (`data/fetchers/core_insights.py`) stays so this can be
re-tested when 2026-27 has enough weeks. The player sheet shows recent cup and European minutes as
context only.
