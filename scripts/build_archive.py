"""
Build the 10-season historical archive (2016-17 → 2025-26).

Downloads vaastav per-season CSVs (cached forever once fetched · completed
seasons never change), merges in the 2025-26 FPL-API harvest, and writes:

  data/cache/archive/gw_archive.parquet
  data/cache/archive/season_summary.parquet

Usage:
    python scripts/build_archive.py [--force]
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from data.processors.archive import build_gw_archive, build_season_summary


def main() -> int:
    force = "--force" in sys.argv

    archive = build_gw_archive(force=force)
    if archive is None:
        print("ARCHIVE BUILD FAILED")
        return 1

    print("\n── GW archive ───────────────────────────────")
    per_season = archive.groupby("season").agg(
        rows=("code", "size"), players=("code", "nunique"), max_gw=("gw", "max"))
    print(per_season.to_string())

    summary = build_season_summary(archive, force=force)
    if summary is None:
        print("SEASON SUMMARY BUILD FAILED")
        return 1

    print("\n── Season summary ───────────────────────────")
    print(f"Player-seasons: {len(summary)}")
    multi = summary.groupby("code")["season"].nunique()
    print(f"Players appearing in 2+ seasons: {(multi >= 2).sum()} "
          f"(cross-season join is working)" if (multi >= 2).sum() > 500
          else f"WARNING: only {(multi >= 2).sum()} multi-season players · check code join!")

    print("\nTop 10 by points-per-million (min 1500 mins), all seasons:")
    eligible = summary[summary["minutes"] >= 1500]
    top = eligible.nlargest(10, "pts_per_million")
    for _, r in top.iterrows():
        print(f"  {r['season']}  {r['web_name']:<18} £{r['start_price']:.1f} → "
              f"{int(r['total_points'])} pts  ({r['pts_per_million']:.1f} pts/£m)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
