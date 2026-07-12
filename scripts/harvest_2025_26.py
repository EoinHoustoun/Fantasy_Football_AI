"""
One-shot harvest of the complete 2025-26 season from the FPL API.

URGENT: the API serves last season's data only until the 2026-27 game
launches (~early July 2026). Run this once; output is immutable.

Usage:
    python scripts/harvest_2025_26.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from data.fetchers.fpl_history import harvest_season

SEASON = "2025-26"


def main() -> int:
    df = harvest_season(SEASON)
    if df is None or df.empty:
        print("HARVEST FAILED · no data returned")
        return 1

    n_players = df["code"].nunique()
    n_gws = int(df["gw"].max())
    print("\n── Harvest summary ──────────────────────────")
    print(f"Season:        {SEASON}")
    print(f"Rows:          {len(df)}")
    print(f"Players:       {n_players}")
    print(f"Max GW:        {n_gws}")
    print(f"Total points:  {int(df['total_points'].sum())}")

    top = (df.groupby("web_name")["total_points"].sum()
             .sort_values(ascending=False).head(10))
    print("\nTop 10 scorers (sanity check vs FPL site):")
    for name, pts in top.items():
        print(f"  {name:<20} {int(pts)}")

    if n_gws < 38:
        print(f"\nWARNING: only {n_gws} GWs present · API may already be partially wiped!")
        return 1
    print("\nOK · full 38-GW season archived.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
