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


def plan_window(wildcard_gw) -> Optional[tuple]:
    """The gameweeks an opening squad is actually built for.

    You own the fifteen until you wildcard, so that is the window worth
    optimising. Scoring it over a whole season rewards players who pay off in
    weeks you will have already torn the squad up before reaching.

    Returns None when there is no wildcard to build up to, which means "score
    the season" · and also when the wildcard is GW1, because a squad you replace
    before a ball is kicked has no window at all.
    """
    if wildcard_gw in (None, ""):
        return None
    try:
        wc = int(wildcard_gw)
    except (TypeError, ValueError):
        return None
    return (1, wc - 1) if wc > 1 else None


def spec_key(spec: Dict) -> str:
    """A stable cache key for a draft spec.

    Solving the opening fifteen is a MILP, and it was running on every app
    rerun. Clicking a player's shirt is an app rerun, so opening the card
    re-solved the squad it had just solved: measured at 41 seconds on the real
    page, because that solve competes with the background ceiling MILPs.

    Two things this must get right or the cache never hits. Streamlit rebuilds
    the spec from widgets on every run, so **insertion order is not stable** and
    keying on it would miss every time. And list-valued dials (locks, vetoes,
    cover) come back in widget-click order, which carries no meaning, so they
    sort before hashing.
    """
    import hashlib
    import json

    def _norm(v):
        if isinstance(v, dict):
            return {str(k): _norm(v[k]) for k in sorted(v, key=str)}
        if isinstance(v, (list, tuple, set)):
            return sorted((_norm(x) for x in v), key=repr)
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, (int, float)):
            return round(float(v), 6)
        return str(v)

    blob = json.dumps(_norm(dict(spec)), sort_keys=True, default=str)
    return hashlib.blake2b(blob.encode(), digest_size=12).hexdigest()


def squad_diff(before: Iterable[int], after: Iterable[int],
               price_by_code: Dict) -> Dict:
    """What the optimiser changed, joined on code and never on name.

    Both lists come back most expensive first, so the move that spent the money
    is the one the eye meets. A code the board no longer carries still appears
    in `out` and is named in `unpriced` · omitting it would make a player
    disappear from the squad with nothing said, which is exactly the silent
    failure this diff exists to surface.
    """
    b = [int(c) for c in before]
    a = [int(c) for c in after]

    def _price(code):
        try:
            return float(price_by_code[code])
        except (KeyError, TypeError, ValueError):
            return None

    def _by_price(codes):
        return sorted(codes, key=lambda c: (-(_price(c) or 0.0), c))

    def _spend(codes):
        return round(sum(p for p in (_price(c) for c in codes)
                         if p is not None), 1)

    return {
        "out": _by_price(set(b) - set(a)),
        "in": _by_price(set(a) - set(b)),
        "spend_before": _spend(b),
        "spend_after": _spend(a),
        "unpriced": sorted(c for c in set(b) | set(a) if _price(c) is None),
    }


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


def fold_accents(s: str) -> str:
    """Lower-case and strip diacritics, so "sesko" finds "Šeško".

    Nobody types Š, and half the Premier League has an accent in their name ·
    Šeško, Dúbravka, João Pedro, Højlund, Ødegaard. A search box that only
    matches the exact glyph is a search box that hides those players.

    NFD splits a letter from its accent, then the combining marks (category Mn)
    are dropped. It also handles the ones that do not decompose, like ø and đ,
    through an explicit map.
    """
    import unicodedata
    if not s:
        return ""
    out = unicodedata.normalize("NFD", str(s).lower())
    out = "".join(c for c in out if unicodedata.category(c) != "Mn")
    for a, b in (("ø", "o"), ("đ", "d"), ("ł", "l"), ("æ", "ae"),
                 ("œ", "oe"), ("ß", "ss"), ("ð", "d"), ("þ", "th"),
                 # Turkish dotless i · Kadıoğlu. It is its own letter, not an
                 # accented one, so NFD leaves it exactly where it was.
                 ("ı", "i")):
        out = out.replace(a, b)
    return out


def transfer_ledger(swaps: Dict, upto_gw: int, ft_cap: int = 5,
                    first_paid_gw: int = 2,
                    start_codes: Optional[Iterable[int]] = None,
                    wildcard_gw: Optional[int] = None,
                    no_accrual_gws: Optional[Iterable[int]] = None) -> Dict:
    """Free transfers, hits and what each week's moves cost.

    One free transfer a gameweek from GW2, banked up to `ft_cap`, spent oldest
    first. Anything past the free allowance costs 4 points. GW1 is the draft
    itself, so it is free by definition and never appears in the ledger.

    Saving transfers early is worth more than it looks: a bank of five in GW6 is
    the flexibility to react once there is real information, which is a large
    part of why an early Bench Boost and Wildcard are attractive.

    `wildcard_gw` is the week you play a Wildcard. That week has **unlimited**
    transfers and costs nothing however many you make, and it grants no free
    transfer of its own · you played the chip instead. Your bank is untouched
    and carries straight through, so three saved going into a GW4 Wildcard is
    still three in GW5.

    `swaps` is {gw: {out_code: in_code}}.

    Moves are counted NET against the squad at the start of the week. Selling
    Virgil for Gabriel and then buying Virgil back is two entries in the chain
    and zero transfers made: anyone who starts the week in the squad and ends it
    there was never transferred, whatever route he took. That is also how a user
    undoes a change of mind, so charging for it would be charging for nothing.
    Pass `start_codes` (the drafted fifteen) to enable it.

    `no_accrual_gws` names further weeks that behave the same way as the
    Wildcard week: no free transfer accrues, nothing is spent and nothing is
    charged. A Free Hit week is exactly that, and My Team passes its Free Hit
    weeks here. Left as None the ledger is unchanged, which is what the Draft
    relies on.
    """
    weeks, avail, total_hits = [], 0, 0
    squad = [int(c) for c in (start_codes or [])]
    wc = int(wildcard_gw) if wildcard_gw else None
    frozen = {int(g) for g in (no_accrual_gws or ())}

    for g in range(int(first_paid_gw), int(upto_gw) + 1):
        wild = wc is not None and g == wc
        # No accrual in the Wildcard week · the chip is what you played that
        # week. The bank itself is untouched and rolls on unchanged. A Free Hit
        # week is the same deal, and arrives through `no_accrual_gws`.
        chip_week = wild or g in frozen
        if not chip_week:
            avail = min(ft_cap, avail + 1)
        moves = (swaps or {}).get(g, {}) or {}

        if squad:
            began = set(squad)
            for out, inn in moves.items():
                if int(out) in squad:
                    squad[squad.index(int(out))] = int(inn)
            ended = set(squad)
            gone, came = began - ended, ended - began
            used = len(gone)
            moves = {"out": sorted(gone), "in": sorted(came)}
        else:
            used = len(moves)

        free_used = used if chip_week else min(used, avail)
        hits = 0 if chip_week else used - free_used
        total_hits += hits
        weeks.append({
            "gw": g, "moves": moves, "used": used,
            "free_used": free_used, "hits": hits, "cost": hits * HIT_COST,
            "available_before": avail, "wildcard": wild,
        })
        if not chip_week:
            avail = max(0, avail - used)
    return {"weeks": weeks, "available_now": avail, "hits": total_hits,
            "points_cost": total_hits * HIT_COST, "cap": ft_cap,
            "wildcard_gw": wc}


def banned_price_names(board, bans, name_col: str = "uniq_name",
                       exempt=()) -> list:
    """Player names ruled out by a position/price-band ban.

    Eoin's rule for 2026-27: no £4.5m defender. The band is the worst of both
    worlds · it costs half a million more than the £4.0m floor without buying a
    materially better chance of a clean sheet, so if the fifteen needs a cheap
    defender it should take the cheapest one.

    Expressed as a ban on a PRICE BAND rather than on a list of players, because
    prices move and a name list would silently go stale. Returned as names so it
    can join the existing veto list, which is what both the solver and the UI
    already understand.

    `bans` is an iterable of (position, price) pairs.

    `exempt` names survive the ban. Eoin's 2026-08-11 refinement: he does not
    want a £4.5m defender if it can be avoided, but if the fifteen genuinely
    needs one it has to be Kad&#305;o&#287;lu. A blanket ban cannot express "avoid
    unless necessary, and then only him", and the alternative · banning the band
    and hand-adding one player back · would be a name list going stale, which is
    the thing this function exists to avoid.
    """
    if board is None or not len(board) or not bans:
        return []
    col = name_col if name_col in board.columns else "web_name"
    price_col = "actual_price" if "actual_price" in board.columns else "price"
    if price_col not in board.columns or "position" not in board.columns:
        return []

    keep = {str(n) for n in (exempt or ())}
    out = []
    for pos, price in bans:
        hit = board[(board["position"].astype(str) == str(pos))
                    & (board[price_col].round(1) == round(float(price), 1))]
        out.extend(str(n) for n in hit[col].tolist() if str(n) not in keep)
    return sorted(set(out))


def below_floor_names(board, floors, name_col: str = "uniq_name") -> list:
    """Player names under a per-position price floor.

    Eoin's rule for 2026-27: no striker under £6.0m. A sub-£6m forward is a
    bench body dressed as a pick · it plays in a Bench Boost week and does
    nothing the rest of the time, and the fifteen is better off spending the
    money in midfield where the cheap end still starts.

    A floor rather than a name list, for the same reason as
    `banned_price_names`: prices move.

    `floors` is a mapping of position -> minimum price.
    """
    if board is None or not len(board) or not floors:
        return []
    col = name_col if name_col in board.columns else "web_name"
    price_col = "actual_price" if "actual_price" in board.columns else "price"
    if price_col not in board.columns or "position" not in board.columns:
        return []

    import pandas as pd
    out = []
    for pos, floor in dict(floors).items():
        price = pd.to_numeric(board[price_col], errors="coerce")
        hit = board[(board["position"].astype(str) == str(pos))
                    & (price < float(floor))]
        out.extend(str(n) for n in hit[col].tolist())
    return sorted(set(out))
