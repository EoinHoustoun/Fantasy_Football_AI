"""
Promoted-club adjustments.

Promoted sides defend more, so their DEFENDERS bank more defensive-contribution
points than the carryover model expects. Measured across every season in the
archive that carries defensive-action counts (2017-18, 2018-19, 2025-26 · the
2019-20 to 2024-25 seasons have no CBIT data at all):

  Defender action rate, promoted clubs vs the rest of the league
    2017-18  +4.2%      2018-19  +4.3%      2025-26  +8.1%
    pooled, season-normalised: +5.6% (90% CI -0.6% to +12.1%)

No single season reaches significance at player level, because a promoted side
only fields five or six regular defenders. The club is the right unit anyway ·
the claim is about a system, not a person · and there the effect is clear:

  8 of 9 promoted club-seasons finished above the league median for defender
  DEFCON per 90. One-sided binomial p = 0.0195. Mean rank 7.4 of 20.

Turning that into points needs care. DEFCON pays 2 points at a THRESHOLD (10
actions for a defender, 12 for a midfielder), so a multiplicative lift applied
to an integer match count changes nothing at all · 9 x 1.056 is still under 10.
The lift belongs on the underlying RATE. Modelling per-match counts as negative
binomial (fitted overdispersion 2.0) and lifting the rate 5.6%:

  mean P(hit) 0.262 -> 0.294   (+12.5% relative)
  over 38 starts: 19.9 -> 22.4 DEFCON points  (+2.5)

Hence PROMOTED_DEF_DEFCON_BONUS = 2.5 points a season. The gain is concentrated
at the threshold: a defender already averaging 13 actions, or one down at 5,
gains almost nothing. We cannot target that per player for promoted clubs
because they have no Premier League record to fit a rate to, so the bonus is
applied flat and deliberately at the low end of the interval.

MIDFIELDERS GET NOTHING. The same test on midfielders returns -0.3% (p = 0.96).
The mechanism is a defensive line sitting deeper, which is not something a
midfielder's action count inherits.
"""

import logging
from typing import Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)

# See the module docstring for the derivation. Season points, defenders only.
PROMOTED_DEF_DEFCON_BONUS = 2.5

# Evidence strength, surfaced in the UI so the number is never mistaken for a
# hard model output.
EVIDENCE = ("3 seasons with defensive-action data. 8 of 9 promoted club-seasons "
            "above the league median (p=0.02). Defenders only.")


def promoted_clubs(live_teams: Optional[pd.DataFrame] = None,
                   last_season_teams: Optional[Set[str]] = None) -> Set[str]:
    """Clubs in the live season that were not in the last complete season.

    Derived, not hardcoded, so it survives every rollover on its own. Both
    sides use FPL's own club naming (the archive's team_name comes from the
    same teams.csv the API serves), so an exact set difference is safe.

    Returns an empty set rather than guessing if either side is unavailable ·
    a wrong promoted list would silently mis-price a whole club.
    """
    if live_teams is None or live_teams.empty or "name" not in live_teams.columns:
        return set()

    if last_season_teams is None:
        last_season_teams = _last_season_teams()
    if not last_season_teams:
        return set()

    promoted = set(live_teams["name"].dropna()) - last_season_teams
    if len(promoted) > 4:
        # A naming mismatch would make every club look promoted. Refuse rather
        # than apply a bonus to the entire league.
        logger.warning("promoted_clubs: %d clubs look promoted, refusing", len(promoted))
        return set()
    return promoted


def _last_season_teams() -> Set[str]:
    try:
        from config import LAST_COMPLETE_SEASON
        from data.processors.archive import load_gw_archive
        arch = load_gw_archive()
        if arch is None or arch.empty:
            return set()
        names = arch.loc[arch["season"] == LAST_COMPLETE_SEASON, "team_name"]
        return {n for n in names.dropna().unique() if n}
    except Exception as exc:
        logger.warning("promoted_clubs: no archive baseline (%s)", exc)
        return set()


def apply_defcon_bonus(board: pd.DataFrame, promoted: Set[str],
                       points_col: str = "projected_points",
                       bonus: float = PROMOTED_DEF_DEFCON_BONUS) -> pd.DataFrame:
    """Add the promoted-club DEFCON bonus to defenders at promoted clubs.

    Marks `promoted_defcon_bonus` on every row so the UI can show why a number
    moved, and so the adjustment is auditable rather than baked in silently.
    """
    out = board.copy()
    out["promoted_defcon_bonus"] = 0.0
    if not promoted or points_col not in out.columns:
        return out

    team_col = "team_name" if "team_name" in out.columns else None
    if team_col is None:
        return out

    mask = out[team_col].isin(promoted) & (out.get("position") == "DEF")
    if not mask.any():
        return out

    out.loc[mask, "promoted_defcon_bonus"] = bonus
    out.loc[mask, points_col] = out.loc[mask, points_col].fillna(0.0) + bonus
    logger.info("promoted DEFCON bonus: +%.1f to %d defenders at %s",
                bonus, int(mask.sum()), ", ".join(sorted(promoted)))
    return out
