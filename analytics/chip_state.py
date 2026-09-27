"""Which chips a manager still holds, per half of the season.

From 2025-26 FPL gives two of every chip: the first set must be played by GW19,
the second from GW20. The Chip Planner used to plan all four first-half chips
for a squad that had already spent three of them, so it recommended a Bench
Boost in GW16 to someone who played it in GW1.
"""
from typing import Dict, List

CHIPS = ("wildcard", "freehit", "bboost", "3xc")
LABEL = {"wildcard": "Wildcard", "freehit": "Free Hit",
         "bboost": "Bench Boost", "3xc": "Triple Captain"}
FIRST_HALF_LAST_GW = 19


def half_of(gw: int, last_first_half: int = FIRST_HALF_LAST_GW) -> int:
    return 1 if int(gw) <= last_first_half else 2


def chip_state(played: List[Dict], planning_gw: int,
               last_first_half: int = FIRST_HALF_LAST_GW) -> Dict:
    """Summarise chips for the half that `planning_gw` falls in.

    `played` is the FPL history `chips` list. Returns
    {half, gw_lo, gw_hi, used: {chip: gw}, remaining: [chip, ...]}.
    """
    half = half_of(planning_gw, last_first_half)
    gw_lo = int(planning_gw)
    gw_hi = last_first_half if half == 1 else 38
    used: Dict[str, int] = {}
    for c in played or []:
        name, ev = c.get("name"), c.get("event")
        if name in CHIPS and ev is not None and half_of(ev, last_first_half) == half:
            used[name] = int(ev)
    remaining = [c for c in CHIPS if c not in used]
    return {"half": half, "gw_lo": gw_lo, "gw_hi": gw_hi,
            "used": used, "remaining": remaining}
