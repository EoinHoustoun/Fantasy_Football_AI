"""Plan persistence for the My Team forward-week planner.

FT banking, the effective squad and hit pricing now live in
`analytics/team_plan.py` (keyed by player `code`, the Draft's engine). This
module keeps the disk format the plan/draft JSON was built on:
  1. Plan persistence · saved transfers per future GW live in
     data/cache/squad_plans.json (survives restarts; volatile cache, not git).
  2. `FT_CAP` / `HIT_COST` · the constants `team_plan.py` builds its ledger on.

Pure logic + JSON I/O · no Streamlit imports, fully unit-testable.
Python 3.8: typing.Dict/Optional only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

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


def normalize_entry(entry) -> Dict[str, Any]:
    """A plan/draft entry is {"transfers": [...], "captain": id|None,
    "chip": "BB"|"TC"|"WC"|"FH"|None}. Legacy entries were bare transfer
    lists · normalise on read so old saves keep working."""
    if isinstance(entry, list):
        return {"transfers": entry, "captain": None, "chip": None}
    if isinstance(entry, dict):
        return {"transfers": entry.get("transfers", []) or [],
                "captain": entry.get("captain"),
                "chip": entry.get("chip")}
    return {"transfers": [], "captain": None, "chip": None}


def _is_empty(entry: Dict[str, Any]) -> bool:
    return not (entry.get("transfers") or entry.get("captain") or entry.get("chip"))


def _load_ns(ns: str, team_id: int) -> Dict[int, Dict[str, Any]]:
    section = _read().get(ns, {}).get(str(int(team_id)), {})
    return {int(gw): normalize_entry(e) for gw, e in section.items()}


def _save_ns(ns: str, team_id: int, gw: int,
             entry: Optional[Dict[str, Any]]) -> None:
    raw = _read()
    team = raw[ns].get(str(int(team_id)), {})
    entry = normalize_entry(entry) if entry is not None else None
    if entry is not None and (ns == "drafts" or not _is_empty(entry)):
        team[str(int(gw))] = entry
    else:
        team.pop(str(int(gw)), None)
    raw[ns][str(int(team_id))] = team
    _write(raw)


def load_plans(team_id: int) -> Dict[int, Dict[str, Any]]:
    """Saved {gw: entry} for this team (entries normalised). Missing → empty."""
    return {g: e for g, e in _load_ns("plans", team_id).items() if not _is_empty(e)}


def save_plan(team_id: int, gw: int, entry) -> None:
    """Persist one GW's plan entry (empty entry deletes the GW's plan).
    Accepts a bare transfer list or a full entry dict."""
    _save_ns("plans", team_id, gw, normalize_entry(entry))


def load_drafts(team_id: int) -> Dict[int, Dict[str, Any]]:
    """Working (unsaved) entries per GW. A gw key may hold an empty entry,
    which means 'draft says nothing this week' and overrides a saved plan."""
    return _load_ns("drafts", team_id)


def save_draft(team_id: int, gw: int, entry) -> None:
    """Persist the working entry for one GW (call on every mutation)."""
    _save_ns("drafts", team_id, gw, normalize_entry(entry if entry is not None else []))


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


