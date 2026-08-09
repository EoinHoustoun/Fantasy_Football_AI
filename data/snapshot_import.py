"""Install a refreshed snapshot, or refuse it and say why.

The four hand-refreshed inputs (Hub predictions, Scout's per-gameweek and season
tables, Scout's player stats) are the models the whole board is blended from,
and every bug they have caused was SILENT:

  - Rate My Team wrote "GK" where the code expected "G". All 55 keepers dropped
    out of a join keyed on position, and the overall match rate still read 89%
    because the outfield players carried it.
  - A column of zeros became `pd.NA`, promoted a numeric Series to object, and
    took the draft page down two screens later.

So this module's job is not really copying a file. It is refusing one. A
snapshot that installs cleanly and quietly breaks a join is the failure mode
worth engineering against; a loud refusal costs a minute.

Deliberately NOT a downloader. These are paid subscriptions, and CLAUDE.md is
explicit that snapshots are manual: a human exports the file, this installs it.
There is no polling and no scheduling here on purpose.
"""
import logging
import shutil
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from config import CACHE_DIR, NEXT_SEASON

logger = logging.getLogger(__name__)

CACHE = Path(CACHE_DIR)
# NOT under data/cache/archive · that path is deliberately un-ignored and
# committed, so a backup of paid Scout data dropped there would publish it to a
# public repo.
BACKUPS = CACHE / "_snapshot_backups"

_S = NEXT_SEASON.replace("-", "_")

Spec = namedtuple("Spec", "key filename label required numeric min_rows")

SPECS = {
    "ffh": Spec(
        "ffh", "ffh_predictions_%s.csv" % _S, "Fantasy Football Hub predictions",
        required=["name", "team", "pos", "price", "gw1_pts", "gw1_min",
                  "gw2_pts", "gw2_min", "gw3_pts", "gw3_min"],
        numeric=["price", "gw1_pts", "gw1_min", "gw2_pts", "gw3_pts"],
        min_rows=200),
    "scout_rmt_gw": Spec(
        "scout_rmt_gw", "scout_rmt_gw1_6_%s.csv" % _S, "Scout Rate My Team, per gameweek",
        required=["name", "team", "pos", "gw1", "gw2", "gw3", "total", "price"],
        numeric=["gw1", "gw2", "gw3", "total", "price"],
        min_rows=300),
    "scout_rmt_season": Spec(
        "scout_rmt_season", "scout_rmt_season_%s.csv" % _S, "Scout Rate My Team, season",
        required=["name", "team", "pos", "season_total", "price"],
        numeric=["season_total", "price"],
        min_rows=300),
    "scout_stats": Spec(
        "scout_stats", "scout_projections_%s.csv" % _S, "Scout player stats",
        required=["name", "team", "pos", "price", "mins", "pts"],
        numeric=["price", "mins", "pts"],
        min_rows=200),
}

# How many shared surnames are normal. The real files run 2.5-3% · different
# players called Silva. Only a wholesale doubling is a problem.
_MAX_DUPLICATE_SHARE = 0.10


def identify(df: pd.DataFrame) -> Optional[str]:
    """Which snapshot this file is, from its columns. None if unrecognised.

    Never guesses · installing the wrong file over another is worse than asking.
    """
    cols = {str(c).strip().lower() for c in df.columns}
    # Most specific first · the season table's columns are a subset of nothing
    # else, but the per-gameweek table shares `name/team/pos/price` with all.
    if {"gw1_pts", "gw1_min"} <= cols:
        return "ffh"
    if "season_total" in cols:
        return "scout_rmt_season"
    if {"gw1", "gw6", "total"} <= cols:
        return "scout_rmt_gw"
    if {"mins", "pts", "cs"} <= cols:
        return "scout_stats"
    return None


def current(key: str) -> Optional[pd.DataFrame]:
    """The snapshot in place right now, or None on a first import."""
    p = CACHE / SPECS[key].filename
    if not p.exists():
        return None
    try:
        return pd.read_csv(p)
    except Exception:                       # noqa: BLE001
        return None


def validate(df: pd.DataFrame, key: str,
             reference: Optional[pd.DataFrame] = "auto") -> Tuple[bool, List[str]]:
    """(ok, problems). Every check corresponds to a bug that has happened.

    `reference` is the snapshot currently installed, used to spot a CHANGE in
    shape rather than to police an absolute vocabulary. Pass None to skip that
    comparison; the default reads whatever is on disk.
    """
    spec = SPECS[key]
    if isinstance(reference, str) and reference == "auto":
        reference = current(key)
    problems = []
    cols = {str(c).strip().lower(): c for c in df.columns}

    for col in spec.required:
        if col not in cols:
            problems.append("missing required column %r" % col)
    if problems:
        return False, problems           # nothing else is meaningful without them

    if len(df) < spec.min_rows:
        problems.append(
            "only %d rows, expected at least %d · a truncated export, or a "
            "filter left on" % (len(df), spec.min_rows))

    for col in spec.numeric:
        if col not in cols:
            continue
        # Strip a trailing unit before testing. Scout writes price as "15.5m",
        # and the parsers downstream already handle that · an earlier version of
        # this check called the column non-numeric and refused the real file.
        raw = df[cols[col]].astype(str).str.replace(
            r"[^0-9.\-]", "", regex=True).replace("", None)
        if pd.to_numeric(raw, errors="coerce").notna().sum() == 0:
            problems.append("column %r is entirely empty or non-numeric" % col)

    # Position spellings are compared against the file that currently works,
    # never against a hardcoded list. The four snapshots use three different
    # vocabularies ("Goalkeeper", "GK", and "G"), none of them guessable, and an
    # earlier version of this check refused the real Hub export. What matters is
    # a spelling the existing joins have never seen.
    if "pos" in cols and reference is not None and "pos" in {
            str(c).strip().lower() for c in reference.columns}:
        ref_col = [c for c in reference.columns if str(c).strip().lower() == "pos"][0]
        known = {str(p).strip().upper() for p in reference[ref_col].dropna().unique()}
        seen = {str(p).strip().upper() for p in df[cols["pos"]].dropna().unique()}
        new = seen - known
        if new:
            problems.append(
                "pos column now contains %s, which the current snapshot never "
                "had (%s) · the join keys on position, so a changed spelling "
                "silently drops every player with it. This is the GK/G bug."
                % (sorted(new)[:6], sorted(known)[:6]))

    if "name" in cols:
        dupes = int(df[cols["name"]].duplicated().sum())
        if dupes > len(df) * _MAX_DUPLICATE_SHARE:
            problems.append(
                "%d duplicate player names (%.0f%%) · the export looks doubled"
                % (dupes, 100.0 * dupes / max(len(df), 1)))

    return (not problems), problems


def install(df: pd.DataFrame, key: str) -> Path:
    """Validate, back up whatever is there, then write. Raises on a bad file."""
    ok, problems = validate(df, key)
    if not ok:
        raise ValueError("%s did not validate:\n  - %s"
                         % (SPECS[key].label, "\n  - ".join(problems)))
    target = CACHE / SPECS[key].filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
        shutil.copy2(target, BACKUPS / ("%s.%s.csv" % (target.stem, stamp)))
    df.to_csv(target, index=False)
    logger.info("installed %s · %d rows -> %s", SPECS[key].label, len(df), target)
    return target


def read_any(path) -> pd.DataFrame:
    """Read a CSV, TSV or Excel export without caring which it is."""
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p)
    head = p.read_text(errors="ignore")[:4000]
    sep = "\t" if head.count("\t") > head.count(",") else ","
    return pd.read_csv(p, sep=sep)
