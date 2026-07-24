"""Acceptance harness for the 2026-27 rollover. Fetches the live bootstrap,
then asserts the app will treat the new season correctly. Exit 0 = all pass."""
from typing import List, Tuple

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from data.fetchers.fpl_api import (
    fetch_bootstrap, get_season_phase, get_current_gameweek,
)


def _checks(bs: dict) -> List[Tuple[str, bool, str]]:
    teams = bs.get("teams", [])
    players = bs.get("elements", [])
    phase = get_season_phase(bs)
    shorts = sorted(t["short_name"] for t in teams)
    uncoloured = [s for s in shorts if s not in config.TEAM_COLORS]
    priced = [p for p in players if p.get("now_cost", 0) > 0]
    return [
        ("20 teams", len(teams) == 20, f"{len(teams)} teams"),
        ("players loaded", len(players) >= 400, f"{len(players)} players"),
        ("preseason phase", phase.get("phase") == "preseason", phase.get("phase")),
        ("gw1 is current target", get_current_gameweek(bs) == 1,
         f"gw={get_current_gameweek(bs)}"),
        ("all clubs coloured", not uncoloured, f"uncoloured={uncoloured}"),
        ("prices set", len(priced) >= 400, f"{len(priced)} priced"),
    ]


def verify_rollover() -> int:
    bs = fetch_bootstrap()
    rows = _checks(bs)
    print("2026-27 ROLLOVER VERIFICATION")
    ok = True
    for name, passed, detail in rows:
        mark = "PASS" if passed else "FAIL"
        ok = ok and passed
        print(f"  [{mark}] {name}: {detail}")
    print("RESULT:", "ALL PASS" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(verify_rollover())
