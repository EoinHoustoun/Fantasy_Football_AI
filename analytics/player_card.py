"""The numbers behind the player card, kept out of the view that draws them.

Two jobs the card needs and nothing else in the app supplies:

**Match shape.** Clean-sheet probability and expected goals for a specific
fixture. Fantasy Football Scout publish a ticker with these, but it is paid data
behind a members' login, and we already fit a Dixon-Coles model on
football-data.co.uk results (`data/fetchers/dixon_coles.py`). So the numbers are
derived here rather than scraped, which also means they update with our own fit
instead of someone else's refresh schedule.

**Percentile ranks.** A DEFCON rate of 6.7 per 90 means nothing on its own. The
card shows where that sits among players who actually play, which is the
question a human is really asking.
"""
import logging
import math
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Below this many minutes a per-90 rate is noise, and including those players
# flatters everyone else's percentile.
MIN_MINUTES_FOR_RANK = 450


def match_shape(ratings: Optional[Dict], team: str, opponent: str,
                is_home: bool) -> Optional[Dict]:
    """Expected goals both ways, and the clean-sheet chance, for one fixture.

    Dixon-Coles fits attack and defence strengths on the log scale, so the
    expected goals for a side are exp(attack + opponent_defence [+ home]). The
    clean-sheet chance is then the Poisson probability that the opponent scores
    zero.

    `rho`, the low-score correction, deliberately is NOT applied. It adjusts the
    JOINT probability of specific scorelines (0-0, 1-0, 0-1, 1-1) and cancels out
    of the marginal used here. Applying it to a marginal would be wrong, and
    quietly so.

    Returns None when either club is missing from the fit · a promoted side with
    no history in the results file is the ordinary case, and a guess dressed as
    a probability is worse than a blank.
    """
    if not ratings:
        return None
    atk, dfn = ratings.get("attacks") or {}, ratings.get("defenses") or {}
    if team not in atk or team not in dfn or opponent not in atk or opponent not in dfn:
        return None

    home_adv = float(ratings.get("home_adv") or 0.0)
    for_log = atk[team] + dfn[opponent] + (home_adv if is_home else 0.0)
    against_log = atk[opponent] + dfn[team] + (0.0 if is_home else home_adv)

    gf = float(math.exp(for_log))
    ga = float(math.exp(against_log))
    # Unrounded on purpose · the view formats. Rounding here made the displayed
    # goals-against disagree with the clean-sheet chance derived from it, which
    # is the kind of small inconsistency that makes a user distrust the page.
    return {
        "exp_goals_for": gf,
        "exp_goals_against": ga,
        "p_clean_sheet": math.exp(-ga),
        "p_score_2_plus": 1.0 - math.exp(-gf) * (1.0 + gf),
    }


# Names the token matcher below cannot resolve on its own. "Spurs" shares no
# word with "Tottenham Hotspur", and "Wolves" shares none with "Wolverhampton
# Wanderers", so those two are stated rather than guessed.
_TEAM_ALIASES = {
    "spurs": "tottenham",
    "wolves": "wolverhampton",
    "nott'm forest": "nottingham forest",
    "notts forest": "nottingham forest",
}

# Abbreviations FPL uses that are not prefixes of the long form. Kept as
# SYNONYMS rather than by deleting the word: an earlier version treated "utd"
# and "city" as noise and dropped them, which made "Man Utd" and "Man City"
# identical and resolved both to nothing.
_TOKEN_SYNONYMS = {"utd": "united", "fc": "", "afc": "", "and": ""}


def _team_tokens(name: str) -> set:
    s = str(name).lower().strip()
    s = _TEAM_ALIASES.get(s, s)
    for ch in ".&'":
        s = s.replace(ch, " ")
    out = set()
    for p in s.split():
        p = _TOKEN_SYNONYMS.get(p, p)
        if p:
            out.add(p)
    return out


def resolve_team(board_name: str, candidates) -> Optional[str]:
    """Map a board club name onto the name Dixon-Coles was fitted with.

    The fit comes from football-data.co.uk ("Manchester United", "Brighton &
    Hove Albion"); the board uses FPL's shorter names ("Man Utd", "Brighton").
    Joining those by raw string silently returns nothing, and joining them
    loosely is worse: four clubs end in "United", so a careless token match
    points Newcastle at Sheffield.

    So: exact match first, then a match on the distinctive words only, and a
    unique winner is required. Ambiguity returns None, because a promoted club
    with no history in the fit is the ordinary case and a wrong club's attack
    strength is worse than a blank.
    """
    if not board_name or not candidates:
        return None
    cands = list(candidates)
    for c in cands:
        if str(c).lower() == str(board_name).lower():
            return c

    want = _team_tokens(board_name)
    if not want:
        return None

    def _covers(cand) -> bool:
        """Every distinctive word in the board name must be present in the
        candidate, as a whole word or as a prefix of one · FPL abbreviates
        ("Man Utd" for "Manchester United"). Three characters minimum, so a
        stray initial cannot match half the league."""
        have = _team_tokens(cand)
        return all(any(h == w or (len(w) >= 3 and h.startswith(w)) for h in have)
                   for w in want)

    hits = [c for c in cands if _covers(c)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        logger.debug("ambiguous club name %r -> %s", board_name, hits)
    return None


def percentile(population: pd.Series, value) -> Optional[int]:
    """Where `value` sits in `population`, 1-100. None when either is missing.

    Rounded to a whole number on purpose · the underlying projections validate
    at Spearman ~0.4, and a decimal place here would imply a resolution the
    inputs do not have.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    pop = pd.to_numeric(population, errors="coerce").dropna()
    if pop.empty:
        return None
    return int(round(100.0 * float((pop <= v).mean())))


def rank_population(df: pd.DataFrame, col: str,
                    position: Optional[str] = None,
                    min_minutes: int = MIN_MINUTES_FOR_RANK) -> pd.Series:
    """The comparison group for a percentile.

    Filtered to players with real minutes, because a per-90 rate off 90 minutes
    is noise and including those players flatters everyone above them. Filtered
    by position when given: a defender's DEFCON rate belongs against other
    defenders, whose threshold is 10 rather than a midfielder's 12.
    """
    if col not in df.columns:
        return pd.Series([], dtype=float)
    d = df
    if position and "position" in d.columns:
        d = d[d["position"] == position]
    if min_minutes and "minutes" in d.columns:
        d = d[pd.to_numeric(d["minutes"], errors="coerce").fillna(0) >= min_minutes]
    return pd.to_numeric(d[col], errors="coerce").dropna()
