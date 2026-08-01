"""
The rules of the game, kept out of the view that draws them.

Formation legality and free-transfer accounting are FPL's rules, not the draft
page's opinions, and they were living inside a Streamlit view where nothing
could test them. Both are pure functions of their inputs, so they belong here
beside the rest of the analytics.
"""

from typing import Dict, Iterable, List, Optional

POS_ORDER = ["GKP", "DEF", "MID", "FWD"]

# A legal starting eleven: exactly one keeper, and at least this many of each
# outfield line. Everything above the minimum is free choice, which is what
# makes 3-4-3 and 5-4-1 both legal.
XI_MINIMUMS = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_SIZE = 11

HIT_COST = 4


def formation_of(codes: Iterable[int], pos_by_code: Dict) -> Dict[str, int]:
    """How many of each position these players are."""
    out = {p: 0 for p in POS_ORDER}
    for c in codes:
        p = pos_by_code.get(int(c))
        if p in out:
            out[p] += 1
    return out


def is_legal_xi(codes: Iterable[int], pos_by_code: Dict) -> bool:
    codes = list(codes)
    if len(codes) != XI_SIZE:
        return False
    f = formation_of(codes, pos_by_code)
    return (f["GKP"] == XI_MINIMUMS["GKP"]
            and f["DEF"] >= XI_MINIMUMS["DEF"]
            and f["MID"] >= XI_MINIMUMS["MID"]
            and f["FWD"] >= XI_MINIMUMS["FWD"])


def legal_swaps(out_code: int, xi: Iterable[int], squad_codes: Iterable[int],
                pos_by_code: Dict) -> List[int]:
    """Who could come on for this player without breaking the formation.

    A keeper can only ever be swapped for the other keeper. Outfield swaps are
    legal whenever the resulting eleven still clears the minimums, which is why
    taking off a third defender usually only allows another defender in.

    The point of computing this rather than validating afterwards is that the
    interface can TEACH the rule · only legal targets light up.
    """
    out_code = int(out_code)
    xi = {int(c) for c in xi}
    on_bench = [int(c) for c in squad_codes if int(c) not in xi]
    return [cand for cand in on_bench
            if is_legal_xi((xi - {out_code}) | {cand}, pos_by_code)]


def transfer_ledger(swaps: Dict, upto_gw: int, ft_cap: int = 5,
                    first_paid_gw: int = 2) -> Dict:
    """Free transfers, hits and what each week's moves cost.

    One free transfer a gameweek from GW2, banked up to `ft_cap`, spent oldest
    first. Anything past the free allowance costs 4 points. GW1 is the draft
    itself, so it is free by definition and never appears in the ledger.

    Saving transfers early is worth more than it looks: a bank of five in GW6 is
    the flexibility to react once there is real information, which is a large
    part of why an early Bench Boost and Wildcard are attractive.

    `swaps` is {gw: {out_code: in_code}}.
    """
    weeks, avail, total_hits = [], 0, 0
    for g in range(int(first_paid_gw), int(upto_gw) + 1):
        avail = min(ft_cap, avail + 1)
        moves = (swaps or {}).get(g, {}) or {}
        used = len(moves)
        free_used = min(used, avail)
        hits = used - free_used
        total_hits += hits
        weeks.append({
            "gw": g, "moves": moves, "used": used,
            "free_used": free_used, "hits": hits, "cost": hits * HIT_COST,
            "available_before": avail,
        })
        avail = max(0, avail - used)
    return {"weeks": weeks, "available_now": avail, "hits": total_hits,
            "points_cost": total_hits * HIT_COST, "cap": ft_cap}
