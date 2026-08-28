"""The plan file: where it lives, what it costs, and raw JSON in and out.

Nothing here understands a plan any more. Entries, the effective squad, FT
banking and hit pricing all live in `analytics/team_plan.py` (keyed by player
`code`, the Draft's engine); this module is only what that one builds on:

  1. `PLANS_PATH` · data/cache/squad_plans.json (survives restarts; a volatile
     cache file, not git).
  2. `FT_CAP` / `HIT_COST` · the constants the ledger is built on.
  3. `_read` / `_write` · raw JSON, no normalisation, so a caller can patch one
     week of a file whose other weeks it cannot safely interpret.

Pure logic + JSON I/O · no Streamlit imports, fully unit-testable.
Python 3.8: typing.Dict/Optional only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from config import CACHE_DIR

PLANS_PATH = Path(CACHE_DIR) / "squad_plans.json"

FT_CAP = 5          # FPL 2024-25+ rule: bank at most 5 free transfers
HIT_COST = 4        # points per transfer beyond your free ones


# ── Persistence ────────────────────────────────────────────────────────────────
# File schema (2, written by team_plan):
#   {"schema": 2, "plans": {team: {gw: entry}}, "drafts": {team: {gw: entry}}}
# A v1 file holds {"transfers": [...], "captain": id, "chip": c} entries keyed
# by fpl_id and migrates on load. Drafts are the working (unsaved) moves · they
# must survive a full page reload, so they live on disk, not in session.

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
