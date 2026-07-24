"""Seed assets/defender_roles_2026_27.json from last season's curated roles,
keeping only players still in the 2026-27 player pool and marking every carried
label provisional. User-editable afterwards; the Playbook hot-reloads it."""
from typing import Dict

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetchers.fpl_api import fetch_bootstrap

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "defender_roles_2025_26.json"
DST = ROOT / "assets" / "defender_roles_2026_27.json"


def seed() -> int:
    old: Dict = json.loads(SRC.read_text())
    bs = fetch_bootstrap()
    current_codes = {str(p["code"]) for p in bs.get("elements", [])}

    out: Dict = {
        "_readme": ("Provisional CB/FB roles for 2026-27, carried from 2025-26 "
                    "for players still in the pool. 'provisional': true means "
                    "unverified for the new season · edit freely, the Playbook "
                    "reloads this file. Keyed by FPL player code."),
    }
    carried = 0
    for code, entry in old.items():
        if code == "_readme" or not isinstance(entry, dict):
            continue
        if code in current_codes:
            new_entry = dict(entry)
            new_entry["provisional"] = True
            out[code] = new_entry
            carried += 1

    DST.write_text(json.dumps(out, indent=2))
    print(f"Seeded {carried} provisional roles -> {DST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(seed())
