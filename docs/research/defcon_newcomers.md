# DEFCON for players new to the Premier League (27 Sep 2026)

Question (from Sangaré, BRE: DEFCON in 3 of 4 starts, engine 0.22-0.30 per
full game): is the brain's `p_defcon` too low for newcomers, and does blending in
the season-so-far hit rate fix it?

Test: `scripts/test_defcon_newcomers.py`. Only 2025-26 records defensive actions,
so five walk-forward brain folds (GW6/12/18/24/30), scored by Brier on every
60+ appearance in the following six gameweeks. 5,553 appearances, 408 players,
84 of them newcomers (no Premier League rows before 2025-26). Candidate:
`p' = (k * p + hits) / (k + starts60)`.

| Group | mean p | actual | Brier brain | Brier k=6 | folds won (k=6) |
|---|---|---|---|---|---|
| Newcomers | 0.164 | 0.158 | 0.1274 | 0.1217 | 3 of 5 (worst: GW12 0.1318 -> 0.1336) |
| Established | 0.171 | 0.215 | 0.1512 | 0.1492 | 4 of 5 |
| All | 0.170 | 0.205 | 0.1468 | 0.1441 | 4 of 5 (GW6 0.1413 -> 0.1416) |

Findings:
- **The brain is NOT systematically low on newcomers** (0.164 predicted vs 0.158
  actual). Sangaré is an individual miss, not a class bias.
- The blend helps a little everywhere (about 2% Brier, best k 6-10) but is one
  season, and the GW6 fold, which is where the season is now, does not improve
  overall.
- The bigger pattern is **compression**: below 0.3 the brain is too low (0.04 ->
  0.08, 0.145 -> 0.22), above 0.45 too high (0.51 -> 0.41, 0.65 -> 0.52). A
  calibration map would do more than a newcomer rule.

Decision: **not shipped.** The gain is small, rests on one season, and does not
beat the incumbent at the GW6 fold. For Sangaré the blend moves his six-week xP by
about 1.3 points; his minutes (p60 0.52) move it by about 7. Revisit with
2026-27 folds once GW12 is played, and test an isotonic map on `p_defcon` then.
