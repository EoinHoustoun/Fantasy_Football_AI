"""Future-gameweek squad planner · the engine behind the My Team pitch planner.

Owns three things:
  1. Plan persistence · saved transfers per future GW live in
     data/cache/squad_plans.json (survives restarts; volatile cache, not git).
  2. FPL free-transfer banking · 1 FT per week, +1 banked per week you save no
     transfer, capped at 5. Extra transfers beyond your FTs cost -4 points each.
  3. Effective squad · applies every saved transfer from the first planning GW
     up to the viewed GW, so scrubbing forward shows the squad as it will be.

Pure logic + JSON I/O · no Streamlit imports, fully unit-testable.
Python 3.8: typing.List/Dict/Optional only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from config import CACHE_DIR

PLANS_PATH = Path(CACHE_DIR) / "squad_plans.json"

FT_CAP = 5          # FPL 2024-25+ rule: bank at most 5 free transfers
HIT_COST = 4        # points per transfer beyond your free ones


# ── Persistence ────────────────────────────────────────────────────────────────
# File schema: {"plans": {team: {gw: [transfer, ...]}},
#               "drafts": {team: {gw: [transfer, ...]}}}
# Drafts are the working (unsaved) moves · they must survive the full page
# reload that pitch ✕/kit links cause, so they live on disk, not in session.

def _read() -> Dict[str, Any]:
    try:
        with open(PLANS_PATH) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {"plans": {}, "drafts": {}}
    if "plans" not in raw:
        raw = {"plans": raw, "drafts": {}}
    raw.setdefault("drafts", {})
    return raw


def _write(raw: Dict[str, Any]) -> None:
    PLANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLANS_PATH, "w") as f:
        json.dump(raw, f, indent=1)


def _load_ns(ns: str, team_id: int) -> Dict[int, List[Dict[str, Any]]]:
    section = _read().get(ns, {}).get(str(int(team_id)), {})
    return {int(gw): transfers for gw, transfers in section.items()}


def _save_ns(ns: str, team_id: int, gw: int,
             transfers: Optional[List[Dict[str, Any]]]) -> None:
    raw = _read()
    team = raw[ns].get(str(int(team_id)), {})
    if transfers:
        team[str(int(gw))] = transfers
    else:
        team.pop(str(int(gw)), None)
    raw[ns][str(int(team_id))] = team
    _write(raw)


def load_plans(team_id: int) -> Dict[int, List[Dict[str, Any]]]:
    """Saved {gw: [transfer, ...]} for this team. Missing file → empty."""
    return {g: t for g, t in _load_ns("plans", team_id).items() if t}


def save_plan(team_id: int, gw: int, transfers: List[Dict[str, Any]]) -> None:
    """Persist one GW's transfer list (empty list deletes the GW's plan)."""
    _save_ns("plans", team_id, gw, transfers)


def load_drafts(team_id: int) -> Dict[int, List[Dict[str, Any]]]:
    """Working (unsaved) moves per GW. A gw key may hold an empty list, which
    means 'draft says no transfers' and overrides a saved plan on display."""
    return _load_ns("drafts", team_id)


def save_draft(team_id: int, gw: int, transfers: List[Dict[str, Any]]) -> None:
    """Persist the working moves for one GW (call on every mutation)."""
    _save_ns("drafts", team_id, gw, transfers if transfers is not None else [])


def clear_draft(team_id: int, gw: int) -> None:
    """Drop the working draft · the saved plan (if any) shows again."""
    raw = _read()
    team = raw["drafts"].get(str(int(team_id)), {})
    team.pop(str(int(gw)), None)
    raw["drafts"][str(int(team_id))] = team
    _write(raw)


def clear_all_plans(team_id: int) -> None:
    """Wipe every saved plan AND draft for this team."""
    raw = _read()
    raw["plans"].pop(str(int(team_id)), None)
    raw["drafts"].pop(str(int(team_id)), None)
    _write(raw)


# ── Free-transfer banking ──────────────────────────────────────────────────────

def free_transfers_for(plans: Dict[int, List[Dict[str, Any]]],
                       gw: int, first_gw: int, base_fts: int = 1) -> int:
    """Free transfers available AT `gw`, given saved plans for earlier weeks.

    Start the first planning week with `base_fts`. Each following week:
    carry over what you didn't use (never below 0), gain 1, cap at FT_CAP.
    Skip a week without saving a transfer → the FT banks. Skip six → still 5.
    """
    fts = base_fts
    for g in range(int(first_gw), int(gw)):
        used = len(plans.get(g, []))
        fts = min(FT_CAP, max(0, fts - used) + 1)
    return fts


def hit_cost(n_transfers: int, fts: int) -> int:
    """Points cost of making `n_transfers` with `fts` free ones available."""
    return max(0, int(n_transfers) - int(fts)) * HIT_COST


# ── Effective squad ────────────────────────────────────────────────────────────

def effective_squad(base_squad: pd.DataFrame,
                    players_df: pd.DataFrame,
                    plans: Dict[int, List[Dict[str, Any]]],
                    up_to_gw: int,
                    first_gw: int,
                    extra_pending: Optional[List[Dict[str, Any]]] = None,
                    ) -> pd.DataFrame:
    """The squad as it stands at `up_to_gw` after every saved transfer from
    `first_gw`..`up_to_gw` (inclusive), plus any unsaved `extra_pending` swaps.

    Incoming players are looked up in `players_df` and inherit the outgoing
    player's bench slot / squad_position so the formation stays intact.
    """
    squad = base_squad.copy()
    all_transfers: List[Dict[str, Any]] = []
    for g in range(int(first_gw), int(up_to_gw) + 1):
        all_transfers.extend(plans.get(g, []))
    all_transfers.extend(extra_pending or [])

    if not all_transfers:
        return squad

    lookup = players_df.set_index("fpl_id")
    for t in all_transfers:
        out_id, in_id = int(t["out_id"]), int(t["in_id"])
        mask = squad["fpl_id"].astype(int) == out_id
        if not mask.any() or in_id not in lookup.index:
            continue
        old = squad[mask].iloc[0]
        new = lookup.loc[in_id]
        row = {c: old.get(c) for c in squad.columns}
        for c in squad.columns:
            if c in new.index:
                row[c] = new[c]
        # Slot/identity fields keep the outgoing player's place in the XI.
        row["fpl_id"] = in_id
        row["on_bench"] = bool(old.get("on_bench", False))
        row["squad_position"] = old.get("squad_position")
        row["is_captain"] = bool(old.get("is_captain", False))
        row["is_vice_captain"] = bool(old.get("is_vice_captain", False))
        squad = squad[~mask]
        squad = pd.concat([squad, pd.DataFrame([row])], ignore_index=True)

    if "squad_position" in squad.columns:
        squad = squad.sort_values("squad_position").reset_index(drop=True)
    return squad


def bank_after(base_bank: float,
               plans: Dict[int, List[Dict[str, Any]]],
               up_to_gw: int, first_gw: int,
               extra_pending: Optional[List[Dict[str, Any]]] = None) -> float:
    """Bank balance after every saved (+ pending) transfer up to `up_to_gw`."""
    bank = float(base_bank)
    for g in range(int(first_gw), int(up_to_gw) + 1):
        for t in plans.get(g, []):
            bank += float(t.get("price_out", 0)) - float(t.get("price_in", 0))
    for t in (extra_pending or []):
        bank += float(t.get("price_out", 0)) - float(t.get("price_in", 0))
    return round(bank, 2)


def total_hits(plans: Dict[int, List[Dict[str, Any]]],
               first_gw: int, last_gw: int, base_fts: int = 1) -> int:
    """Total points spent on hits across the whole saved plan."""
    cost = 0
    for g in range(int(first_gw), int(last_gw) + 1):
        used = len(plans.get(g, []))
        if used:
            cost += hit_cost(used, free_transfers_for(plans, g, first_gw, base_fts))
    return cost
