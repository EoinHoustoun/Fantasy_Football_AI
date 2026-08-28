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
    if raw.get("schema") != SCHEMA and (plans or drafts):
        _store(team_id, plans, drafts)                     # write back as v2 once
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
                    drafts: Dict[int, Entry], up_to_gw: int) -> List[int]:
    """The fifteen after every week up to and including `up_to_gw`.

    Draft beats plan for the same week. A Free Hit week applies only when it
    IS the viewed week; afterwards the squad reverts, which is the rule.
    """
    squad = [int(c) for c in start_codes]
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            break
        e = _entry_for(plans, drafts, gw)
        if not e:
            continue
        if e.get("chip") == "FH" and gw != int(up_to_gw):
            continue
        for out, inn in (e.get("swaps") or {}).items():
            if int(out) in squad:
                squad[squad.index(int(out))] = int(inn)
    return squad
