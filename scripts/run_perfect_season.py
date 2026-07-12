"""
Run the full Perfect Season optimization for 2025-26 and cache the result.

Pipeline: optimizer input → pool pruning → set-and-forget MILP (warm start)
→ multi-period transfer MILP with WC/TC/BB → Free Hit post-pass → JSON.

Also fetches benchmark scores (Eoin's team + global winner) while the
FPL API still serves 2025-26.

Usage:
    python scripts/run_perfect_season.py [--time-limit 1800] [--pool-check]
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np


def _json_default(o):
    """numpy scalars → native Python (CBC results carry int64/float64)."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

import requests

from config import CACHE_DIR, FPL_BASE, FPL_TEAM_ID, PERFECT_SEASON
from data.processors.archive import build_optimizer_input
from analytics.perfect_season import (
    layer_free_hit,
    prune_pool,
    solve_perfect_season,
    solve_rolling_horizon,
    solve_set_and_forget,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)"}


def _fetch_benchmarks() -> dict:
    """Eoin's 2025-26 total + global winner's total (best effort)."""
    out = {"my_total": None, "winner_total": None, "average_total": None}
    try:
        r = requests.get(f"{FPL_BASE}/entry/{FPL_TEAM_ID}/history/",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        current = r.json().get("current", [])
        if current:
            out["my_total"] = current[-1]["total_points"]
    except Exception as e:
        logger.warning(f"Could not fetch my team history: {e}")
    try:
        r = requests.get(f"{FPL_BASE}/leagues-classic/314/standings/",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        results = r.json()["standings"]["results"]
        if results:
            out["winner_total"] = results[0]["total"]
    except Exception as e:
        logger.warning(f"Could not fetch global standings: {e}")
    try:
        r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=HEADERS, timeout=15)
        r.raise_for_status()
        events = r.json().get("events", [])
        avg = sum(e.get("average_entry_score", 0) for e in events)
        out["average_total"] = avg if avg else None
    except Exception as e:
        logger.warning(f"Could not fetch averages: {e}")
    return out


# Hit-policy scenarios: caps on PAID transfers (each = -4 pts)
SCENARIOS = {
    "unlimited": {"max_hits_per_gw": None, "max_hits_total": None,
                  "label": "Unlimited hits"},
    "limited":   {"max_hits_per_gw": 1, "max_hits_total": 6,
                  "label": "Realistic hits (≤1 per GW, ≤6 all season)"},
    "nohits":    {"max_hits_per_gw": 0, "max_hits_total": 0,
                  "label": "Free transfers only"},
}


def main() -> int:
    season = PERFECT_SEASON["season"]
    time_limit = PERFECT_SEASON["solver_time_limit"]
    if "--time-limit" in sys.argv:
        time_limit = int(sys.argv[sys.argv.index("--time-limit") + 1])
    scenario = "unlimited"
    if "--scenario" in sys.argv:
        scenario = sys.argv[sys.argv.index("--scenario") + 1]
    if scenario not in SCENARIOS:
        print(f"Unknown scenario {scenario}; pick from {list(SCENARIOS)}")
        return 1
    sc = SCENARIOS[scenario]

    opt = build_optimizer_input(season)
    if opt is None:
        print("No optimizer input · build the archive first")
        return 1

    pool = prune_pool(opt)

    logger.info("── Stage 1: set-and-forget ──")
    saf = solve_set_and_forget(opt, pool)
    if saf is None:
        return 1

    if scenario == "unlimited":
        # monolithic solve: CBC's heuristics work well when hits are soft costs
        logger.info(f"── Stage 2: full multi-period MILP ({sc['label']}) ──")
        perfect = solve_perfect_season(opt, pool, warm=saf, time_limit=time_limit)
    else:
        # hard hit caps choke CBC's neighbourhood moves on the monolith -
        # rolling horizon solves each window to (near) optimality instead
        logger.info(f"── Stage 2: rolling-horizon MILP ({sc['label']}) ──")
        perfect = solve_rolling_horizon(opt, pool,
                                        max_hits_per_gw=sc["max_hits_per_gw"],
                                        max_hits_total=sc["max_hits_total"])
    if perfect is None:
        return 1

    if perfect["total_points"] < saf["total_points"]:
        logger.warning("Transfer solution below set-and-forget · keeping both, "
                       "increase --time-limit for a better incumbent")

    logger.info("── Stage 3: Free Hit post-pass ──")
    fh = layer_free_hit(perfect, opt)

    benchmarks = _fetch_benchmarks()

    names = (opt.groupby("code")
             .agg(web_name=("web_name", "last"),
                  player_name=("player_name", "last"),
                  position=("position", "last"),
                  team_name=("team_name", "last"))
             .reset_index())
    prices = (opt.groupby("code")["price"].first().round(1))

    result = {
        "season": season,
        "scenario": scenario,
        "scenario_label": sc["label"],
        "pool_size": len(pool),
        "set_and_forget": {k: v for k, v in saf.items() if not k.startswith("_")},
        "perfect": perfect,
        "free_hit": fh,
        "grand_total": round(perfect["total_points"] + sum(f["gain"] for f in fh), 1),
        "benchmarks": benchmarks,
        "players": {
            str(r["code"]): {
                "web_name": r["web_name"], "player_name": r["player_name"],
                "position": r["position"], "team_name": r["team_name"],
                "start_price": float(prices.get(r["code"], 0)),
            } for _, r in names.iterrows()
        },
        "notes": [
            "Buy price = sell price = actual per-GW value (real sell rule is slightly stingier).",
            "Free Hit gain layered post-hoc per half; slight upper bound.",
            "Solver gap %.1f%% / time limit %ds." % (PERFECT_SEASON["solver_gap"] * 100, time_limit),
        ],
    }

    suffix = "" if scenario == "unlimited" else f"_{scenario}"
    out_path = CACHE_DIR / f"perfect_season_{season.replace('-', '_')}{suffix}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, default=_json_default)

    print(f"\n── Perfect Season 2025-26 [{sc['label']}] ─────")
    print(f"Set-and-forget:        {saf['total_points']:.0f} pts")
    print(f"With transfers+chips:  {perfect['total_points']:.0f} pts "
          f"({perfect['total_hits']} hits, {perfect['solver_status']}, "
          f"{perfect['solve_seconds']:.0f}s)")
    for f_ in fh:
        print(f"Free Hit H{f_['half']} (GW{f_['gw']}):   +{f_['gain']:.0f} pts")
    print(f"GRAND TOTAL:           {result['grand_total']:.0f} pts")
    if benchmarks["my_total"]:
        print(f"Eoin actual:           {benchmarks['my_total']} pts")
    if benchmarks["winner_total"]:
        print(f"Global winner:         {benchmarks['winner_total']} pts")
    print(f"\nSaved → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
