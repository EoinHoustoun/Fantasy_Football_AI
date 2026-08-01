"""
Template risk · what it costs you when a player you skipped hauls.

FPL rank is relative. A player owned by 75% of the game is not a source of
points so much as a source of RANK: own him and you move with the field, skip
him and every week is a bet. The asymmetry is the whole point and it is not
symmetric in the way people assume.

  Skipping a 75%-owned player who hauls 12 costs you about 0.75 x 12 = 9 points
  of rank. Skipping one who blanks GAINS you about 0.75 x 2 = 1.5.

So a template skip is a bet that pays small and often, and loses big and
rarely. That is fine · it is how you win a mini-league · but it should be a
decision rather than an accident, which means it has to be visible.

`effective_ownership` is deliberately simple: FPL's raw ownership plus the
captaincy weight, because a captained template player doubles the damage. We do
not have live captaincy shares off-season, so the captain uplift is applied to
the single highest-owned attacker as a stated assumption rather than a guess
dressed as data.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Above this ownership a player is "template" · skipping him is a live bet.
TEMPLATE_OWNERSHIP = 15.0

# A haul and a blank, in points, for sizing the swing. Deliberately round
# numbers: this is a decision aid, not a projection.
HAUL_POINTS = 12.0
BLANK_POINTS = 2.0


def effective_ownership(board: pd.DataFrame,
                        captain_code: Optional[int] = None) -> pd.Series:
    """Ownership weighted for captaincy, as a percentage.

    A captained player is on the field twice for everyone who owns him, so his
    effective ownership exceeds 100% in a heavily captained week.
    """
    own = pd.to_numeric(board.get("ownership"), errors="coerce").fillna(0.0)
    eo = own.copy()
    if captain_code is not None and "code" in board.columns:
        is_cap = board["code"].astype(int) == int(captain_code)
        # Assume roughly half of that player's owners captain him. Stated, not
        # measured · there is no live captaincy feed off-season.
        eo = eo + own.where(is_cap, 0.0) * 0.5
    return eo.round(1)


def skipped_template(board: pd.DataFrame, squad_codes: List[int],
                     threshold: float = TEMPLATE_OWNERSHIP) -> pd.DataFrame:
    """Template players this squad does NOT own, worst risk first."""
    if board is None or board.empty or "ownership" not in board.columns:
        return pd.DataFrame()
    own = pd.to_numeric(board["ownership"], errors="coerce").fillna(0.0)
    out = board[(own >= threshold)
                & (~board["code"].astype(int).isin({int(c) for c in squad_codes}))].copy()
    if out.empty:
        return out
    out["ownership"] = pd.to_numeric(out["ownership"], errors="coerce").fillna(0.0)
    return out.sort_values("ownership", ascending=False)


def punt_meter(board: pd.DataFrame, squad_codes: List[int],
               threshold: float = TEMPLATE_OWNERSHIP) -> Dict:
    """How exposed this squad is to the players it left out.

    `downside` is the rank-points hit if EVERY skipped template player hauls in
    the same week · the worst realistic case, not an expected value. `upside` is
    what you gain if they all blank. The gap between them is the bet.
    """
    missing = skipped_template(board, squad_codes, threshold)
    if missing.empty:
        return {"n": 0, "downside": 0.0, "upside": 0.0, "worst": [],
                "level": "template", "eo_skipped": 0.0}

    own = missing["ownership"] / 100.0
    downside = float((own * HAUL_POINTS).sum())
    upside = float((own * BLANK_POINTS).sum())

    eo_skipped = float(missing["ownership"].sum())
    # Levels are about how the squad READS, not about which is correct.
    if downside >= 18:
        level = "maverick"
    elif downside >= 8:
        level = "differential"
    else:
        level = "template"

    worst = [{"name": str(r.get("web_name", "?")),
              "team": str(r.get("team_short", "") or ""),
              "own": float(r.get("ownership") or 0),
              "cost": round(float(r.get("ownership") or 0) / 100.0 * HAUL_POINTS, 1)}
             for _, r in missing.head(5).iterrows()]

    return {"n": int(len(missing)), "downside": round(downside, 1),
            "upside": round(upside, 1), "worst": worst, "level": level,
            "eo_skipped": round(eo_skipped, 1)}


def verdict_line(meter: Dict) -> str:
    """One sentence a human can act on."""
    if not meter or not meter.get("n"):
        return "You own every template player. No rank risk, and no edge either."
    lvl = meter["level"]
    if lvl == "maverick":
        shape = ("This is a maverick squad. It wins big or it bleeds rank "
                 "quietly for weeks.")
    elif lvl == "differential":
        shape = "A real differential position, but not a reckless one."
    else:
        shape = "Close to template. Safe rank, limited upside."
    return (f"{shape} Skipping {meter['n']} template "
            f"{'player' if meter['n'] == 1 else 'players'} costs about "
            f"{meter['downside']:.0f} rank points if they all haul, and gains "
            f"about {meter['upside']:.0f} if they all blank.")
