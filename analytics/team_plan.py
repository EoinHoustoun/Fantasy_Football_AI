"""Plan state for the REAL team, keyed by player `code`.

The 26/27 Draft keys everything by the season-stable `code`; My Team used the
season-local `fpl_id` and its own transfer dicts. This module is the one
place the real team's saved weeks and working drafts live, in the Draft's
shape (`swaps = {out_code: in_code}`), so the projector, the ledger and the
player card can be shared without translation.

File: data/cache/squad_plans.json (owned by squad_planner for the path).
  {"schema": 2, "plans": {team: {gw: Entry}}, "drafts": {team: {gw: Entry}}}
Entry = {"swaps": {out_code: in_code}, "captain": code|None, "chip": str|None}
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from analytics import squad_planner as _sp
from analytics.squad_rules import transfer_ledger as _ledger

logger = logging.getLogger(__name__)

SCHEMA = 2
CHIPS = ("BB", "TC", "WC", "FH")
Entry = Dict[str, Any]


def empty_entry() -> Entry:
    return {"swaps": {}, "captain": None, "chip": None}


def normalize(entry: Any, code_by_fpl_id: Optional[Dict[int, int]] = None) -> Entry:
    """Accept v2, v1 ({transfers:[{out_id,in_id}]}) and legacy bare lists."""
    ids = code_by_fpl_id or {}
    if isinstance(entry, list):
        entry = {"transfers": entry, "captain": None, "chip": None}
    if not isinstance(entry, dict):
        return empty_entry()
    out = empty_entry()
    chip = entry.get("chip")
    out["chip"] = chip if chip in CHIPS else None

    if "swaps" in entry:                                   # v2
        out["swaps"] = {int(k): int(v) for k, v in (entry.get("swaps") or {}).items()}
        cap = entry.get("captain")
        out["captain"] = int(cap) if cap is not None else None
        return out

    for t in entry.get("transfers") or []:                 # v1
        o, i = ids.get(int(t.get("out_id", -1))), ids.get(int(t.get("in_id", -1)))
        if o is None or i is None:
            logger.warning("team_plan: dropping v1 transfer with unknown ids %s", t)
            continue
        out["swaps"][o] = i
    cap = entry.get("captain")
    out["captain"] = ids.get(int(cap)) if cap is not None else None
    return out


def _bucket(raw: Dict, kind: str, team_id: int,
            code_by_fpl_id: Optional[Dict[int, int]]) -> Dict[int, Entry]:
    return {int(gw): normalize(e, code_by_fpl_id)
            for gw, e in (raw.get(kind, {}).get(str(team_id), {}) or {}).items()}


def load(team_id: int,
         code_by_fpl_id: Optional[Dict[int, int]] = None) -> Tuple[Dict[int, Entry], Dict[int, Entry]]:
    raw = _sp._read()
    plans = _bucket(raw, "plans", team_id, code_by_fpl_id)
    drafts = _bucket(raw, "drafts", team_id, code_by_fpl_id)
    if raw.get("schema") != SCHEMA and (plans or drafts) and code_by_fpl_id is not None:
        _store(team_id, plans, drafts)                     # write back as v2 once (only if mapping supplied)
    return plans, drafts


def _store(team_id: int, plans: Dict[int, Entry], drafts: Dict[int, Entry]) -> None:
    raw = _sp._read()
    raw["schema"] = SCHEMA
    raw.setdefault("plans", {})[str(team_id)] = {str(g): e for g, e in plans.items()}
    raw.setdefault("drafts", {})[str(team_id)] = {str(g): e for g, e in drafts.items()}
    _sp._write(raw)


def save_plan(team_id: int, gw: int, entry: Entry) -> None:
    plans, drafts = load(team_id)
    plans[int(gw)] = normalize(entry)
    drafts.pop(int(gw), None)
    _store(team_id, plans, drafts)


def save_draft(team_id: int, gw: int, entry: Entry) -> None:
    plans, drafts = load(team_id)
    drafts[int(gw)] = normalize(entry)
    _store(team_id, plans, drafts)


def clear_draft(team_id: int, gw: int) -> None:
    plans, drafts = load(team_id)
    drafts.pop(int(gw), None)
    _store(team_id, plans, drafts)


def clear_all(team_id: int) -> None:
    _store(team_id, {}, {})


# ── Replay ────────────────────────────────────────────────────────────────────

def _entry_for(plans: Dict[int, Entry], drafts: Dict[int, Entry], gw: int) -> Optional[Entry]:
    return drafts.get(gw) or plans.get(gw)


def chip_at(plans, drafts, gw: int) -> Optional[str]:
    e = _entry_for(plans, drafts, int(gw))
    return e.get("chip") if e else None


def swaps_upto(plans, drafts, up_to_gw: int) -> Dict[int, Dict[int, int]]:
    """{gw: {out: in}} for the ledger · Free Hit weeks excluded (no transfers)."""
    out: Dict[int, Dict[int, int]] = {}
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            continue
        e = _entry_for(plans, drafts, gw)
        if e and e.get("chip") != "FH" and e.get("swaps"):
            out[gw] = dict(e["swaps"])
    return out


def wildcard_gw(plans, drafts, up_to_gw: int) -> Optional[int]:
    for gw in sorted(set(plans) | set(drafts)):
        if gw <= int(up_to_gw) and chip_at(plans, drafts, gw) == "WC":
            return gw
    return None


def effective_codes(start_codes: List[int], plans: Dict[int, Entry],
                    drafts: Dict[int, Entry], up_to_gw: int,
                    first_gw: Optional[int] = None) -> List[int]:
    """The fifteen after every week up to and including `up_to_gw`.

    Draft beats plan for the same week. A Free Hit week applies only when it
    IS the viewed week; afterwards the squad reverts, which is the rule.

    `start_codes` is the squad as it stands at `first_gw`, so any plan saved
    for an EARLIER week is already baked into it. Passing `first_gw` skips
    those weeks · without it a plan left over from a gameweek that has since
    been played moves the future squad a second time.
    """
    squad = [int(c) for c in start_codes]
    lo = None if first_gw is None else int(first_gw)
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            break
        if lo is not None and gw < lo:
            continue
        e = _entry_for(plans, drafts, gw)
        if not e:
            continue
        if e.get("chip") == "FH" and gw != int(up_to_gw):
            continue
        for out, inn in (e.get("swaps") or {}).items():
            if int(out) in squad:
                squad[squad.index(int(out))] = int(inn)
    return squad


def ledger(plans, drafts, up_to_gw: int, start_codes: List[int],
           first_gw: int, banked_now: int = 1) -> Dict:
    """The Draft's ledger applied to a season already under way.

    `squad_rules.transfer_ledger` accrues one free transfer per week from
    `first_paid_gw`. A manager holding `banked_now` free transfers going into
    `first_gw` is the same as a manager who has been accruing since
    `first_gw - (banked_now - 1)` without spending, so we start it there and
    pass no moves before `first_gw`.

    A Free Hit week accrues nothing either · you played a chip instead of a
    transfer, so the bank rolls through unchanged rather than growing by one.
    """
    swaps = {g: s for g, s in swaps_upto(plans, drafts, up_to_gw).items() if g >= int(first_gw)}
    start_paid = int(first_gw) - max(0, int(banked_now) - 1)
    fh = {gw for gw in (set(plans) | set(drafts))
          if int(first_gw) <= gw <= int(up_to_gw) and chip_at(plans, drafts, gw) == "FH"}
    return _ledger(swaps, int(up_to_gw), ft_cap=_sp.FT_CAP, first_paid_gw=start_paid,
                   start_codes=start_codes, wildcard_gw=wildcard_gw(plans, drafts, up_to_gw),
                   no_accrual_gws=fh)


def bank_after(bank_now_m: float, price_by_code: Dict[int, float], start_codes: List[int],
               plans, drafts, up_to_gw: int, first_gw: Optional[int] = None) -> float:
    """Bank after every move up to up_to_gw at CURRENT prices (sell price nuances are out of scope).

    `first_gw` skips weeks already reflected in `bank_now_m`, the same lower
    bound `effective_codes` and `ledger` apply.
    """
    squad = [int(c) for c in start_codes]
    bank = float(bank_now_m)
    lo = None if first_gw is None else int(first_gw)
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            break
        if lo is not None and gw < lo:
            continue
        e = _entry_for(plans, drafts, gw)
        if not e or e.get("chip") == "FH":
            continue
        for out, inn in (e.get("swaps") or {}).items():
            if int(out) in squad:
                bank += float(price_by_code.get(int(out), 0.0)) - float(price_by_code.get(int(inn), 0.0))
                squad[squad.index(int(out))] = int(inn)
    return round(bank, 2)
