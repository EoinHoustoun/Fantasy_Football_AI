#!/usr/bin/env python3
"""Install a refreshed snapshot from an exported file.

    python3 scripts/import_snapshot.py ~/Downloads/hub-export.csv
    python3 scripts/import_snapshot.py ~/Downloads/*.csv
    python3 scripts/import_snapshot.py --status

It works out which of the four snapshots each file is, refuses anything that
would silently break a join, backs up what is already there, and reports the
match rate against the live board so you know immediately whether the import is
any good.

Deliberately NOT a downloader. The Hub and Scout are paid subscriptions and
snapshots are manual by design · export the file yourself, then point this at
it. There is no polling and no scheduling here.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data import snapshot_import as SI     # noqa: E402


GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _age(path: Path) -> str:
    if not path.exists():
        return RED + "missing" + OFF
    hours = (time.time() - path.stat().st_mtime) / 3600.0
    txt = ("%.0f h ago" % hours) if hours < 48 else ("%.1f days ago" % (hours / 24))
    col = GREEN if hours < 48 else YELLOW if hours < 24 * 5 else RED
    return col + txt + OFF


def status() -> int:
    print("\n  Snapshot freshness\n  " + "-" * 52)
    for spec in SI.SPECS.values():
        p = SI.CACHE / spec.filename
        rows = ""
        if p.exists():
            try:
                import pandas as pd
                rows = DIM + ("%d rows" % len(pd.read_csv(p))) + OFF
            except Exception:               # noqa: BLE001
                rows = RED + "unreadable" + OFF
        print("  %-34s %-22s %s" % (spec.label, _age(p), rows))
    print()
    return 0


def _match_rate(df, key: str) -> str:
    """How much of this file actually joins onto the live board.

    The check that matters. An import can be perfectly well-formed and still
    join at 89% because one position spelling changed, which is precisely how
    every goalkeeper went missing last time.
    """
    try:
        from analytics import freshness
        from ui.value_board import build_board
        board, _s, _b, _v = build_board(freshness.inputs_stamp())
        if board is None or "web_name" not in board.columns:
            return ""
        import re

        def norm(s):
            return re.sub(r"[^a-z]", "", str(s).lower())

        theirs = {norm(n) for n in df[df.columns[0]].dropna()}
        ours = {norm(n) for n in board["web_name"].dropna()}
        hit = len(ours & theirs)
        pct = 100.0 * hit / max(len(ours), 1)
        col = GREEN if pct >= 85 else YELLOW if pct >= 70 else RED
        return "  join rate %s%.0f%%%s of %d board players" % (col, pct, OFF, len(ours))
    except Exception as exc:                # noqa: BLE001
        return DIM + "  (could not check the join rate: %s)" % exc + OFF


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="exported CSV / TSV / XLSX")
    ap.add_argument("--status", action="store_true", help="show snapshot ages and exit")
    ap.add_argument("--dry-run", action="store_true", help="validate without installing")
    args = ap.parse_args()

    if args.status or not args.files:
        return status()

    failed = 0
    for f in args.files:
        if not f.exists():
            print("  %sno such file%s  %s" % (RED, OFF, f))
            failed += 1
            continue
        try:
            df = SI.read_any(f)
        except Exception as exc:            # noqa: BLE001
            print("  %scould not read%s %s · %s" % (RED, OFF, f.name, exc))
            failed += 1
            continue

        key = SI.identify(df)
        if key is None:
            print("  %sunrecognised%s %s" % (YELLOW, OFF, f.name))
            print(DIM + "    columns: %s" % list(df.columns)[:10] + OFF)
            print(DIM + "    expected one of: %s"
                  % ", ".join(s.label for s in SI.SPECS.values()) + OFF)
            failed += 1
            continue

        spec = SI.SPECS[key]
        ok, problems = SI.validate(df, key)
        if not ok:
            print("  %sREFUSED%s  %s -> %s" % (RED, OFF, f.name, spec.label))
            for p in problems:
                print("    - %s" % p)
            failed += 1
            continue

        if args.dry_run:
            print("  %swould install%s %s -> %s (%d rows)"
                  % (GREEN, OFF, f.name, spec.label, len(df)))
        else:
            SI.install(df, key)
            print("  %sinstalled%s  %s -> %s (%d rows)"
                  % (GREEN, OFF, f.name, spec.label, len(df)))
        print(_match_rate(df, key))

    if not args.dry_run and failed == 0:
        print(DIM + "\n  The board rebuilds on the next page load · the content "
                    "stamp has moved." + OFF)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
