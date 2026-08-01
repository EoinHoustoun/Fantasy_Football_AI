"""Fantasy Football Hub predicted points · a match-level second opinion.

Our own projection is a season carryover model: it spreads a season total over 38
gameweeks and shapes it by fixture difficulty. That is a fixture SHAPE, not a
match forecast, and it has no idea whether a player is expected to start.

Fantasy Football Hub's predictions tool models each fixture individually and,
critically, publishes an **expected minutes** figure per gameweek. That is the
single signal our stack has never had: "will he actually be on the pitch". This
module loads a manual snapshot of that tool and joins it to the board.

The snapshot is a LOCAL file the user refreshes when they choose, exactly like
the Fantasy Football Scout one. It is never polled or scraped on a schedule ·
bulk harvesting a paid site breaks its terms. `data/cache/` is gitignored, so it
stays on the machine and never reaches the public repo.

Every surface degrades quietly when the snapshot is absent: `load_snapshot`
returns None and callers show a caption rather than failing.

Snapshot columns (as exported from the tool):
    name, team, pos, price, own, pps, pred,
    gw{1..4}_pts, gw{1..4}_opp, gw{1..4}_min
where `pred` is the total over the snapshot's gameweek window, `pps` is points
per start, and `gw*_min` is expected minutes for that fixture.
"""
import logging
import re
from typing import Dict, List, Optional

import pandas as pd

from config import CACHE_DIR, NEXT_SEASON

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = CACHE_DIR / ("ffh_predictions_%s.csv" % NEXT_SEASON.replace("-", "_"))

# The window the snapshot covers. The tool defaults to the next four gameweeks;
# `window_gws` re-derives it from the file so a wider export still works.
DEFAULT_WINDOW = 4

# FFH writes FPL's full club names verbatim, so the join is direct. Kept as a map
# so a future divergence is a one-line fix rather than a debugging session.
TEAM_ALIASES: Dict[str, str] = {}

POS_ALIASES = {"Goalkeeper": "GKP", "Defender": "DEF",
               "Midfielder": "MID", "Forward": "FWD"}

_FIXTURE_RE = re.compile(r"^([A-Z]{3})\((H|A)\)$")


def window_gws(df: pd.DataFrame) -> List[int]:
    """Which gameweeks this snapshot actually carries, in order."""
    gws = []
    for col in df.columns:
        m = re.match(r"^gw(\d+)_pts$", str(col))
        if m:
            gws.append(int(m.group(1)))
    return sorted(gws)


def load_snapshot(path=None) -> Optional[pd.DataFrame]:
    """Read the FFH snapshot. Returns None when no snapshot has been saved."""
    p = path or SNAPSHOT_PATH
    if not p.exists():
        logger.info("no FFH snapshot at %s", p)
        return None
    try:
        df = pd.read_csv(p)
    except Exception as exc:
        logger.warning("FFH snapshot unreadable: %s", exc)
        return None
    if df.empty or "name" not in df.columns:
        return None

    df = df.copy()
    df["team"] = df["team"].map(lambda t: TEAM_ALIASES.get(str(t), str(t)))
    df["pos"] = df["pos"].map(lambda p: POS_ALIASES.get(str(p), str(p)))
    for col in ("price", "own", "pps", "pred"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    gws = window_gws(df)
    for g in gws:
        df["gw%d_pts" % g] = pd.to_numeric(df.get("gw%d_pts" % g), errors="coerce")
        df["gw%d_min" % g] = pd.to_numeric(df.get("gw%d_min" % g), errors="coerce")

    # Expected minutes across the window is the nailed-on signal. A player the
    # tool expects to play 90 every week is a different asset from one it expects
    # to give 20, even when their totals happen to match.
    if gws:
        mins = df[["gw%d_min" % g for g in gws]]
        df["exp_mins_mean"] = mins.mean(axis=1).round(1)
        df["exp_mins_next"] = df["gw%d_min" % gws[0]]
        # 1.0 = a full-90 starter every week in the window.
        df["nailedness"] = (df["exp_mins_mean"] / 90.0).clip(0, 1).round(3)
        # A starter who is rotated shows up as a wide spread, not a low mean.
        df["mins_volatility"] = mins.std(axis=1).fillna(0.0).round(1)
    logger.info("loaded FFH snapshot · %d players, GW%s", len(df),
                "-".join(str(g) for g in (gws[:1] + gws[-1:])) if gws else "?")
    return df


def parse_fixture(label) -> Optional[Dict]:
    """'BOU(H)' -> {'opp': 'BOU', 'home': True}. None for blanks and junk."""
    if not isinstance(label, str):
        return None
    m = _FIXTURE_RE.match(label.strip())
    if not m:
        return None
    return {"opp": m.group(1), "home": m.group(2) == "H"}


def per_gw_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Long form · one row per (player, gameweek) with points, minutes, fixture.

    Long form is what the per-gameweek surfaces want: the pitch stat, the
    opening-run chart, the bench-boost bench total. Wide form stays for tables.
    """
    gws = window_gws(df)
    out = []
    for _, r in df.iterrows():
        for g in gws:
            fx = parse_fixture(r.get("gw%d_opp" % g))
            out.append({
                "name": r["name"], "team": r["team"], "pos": r["pos"],
                "gw": g,
                "pts": r.get("gw%d_pts" % g),
                "exp_mins": r.get("gw%d_min" % g),
                "opp": (fx or {}).get("opp"),
                "home": (fx or {}).get("home"),
            })
    return pd.DataFrame(out)


def per_gw_by_code(snap: pd.DataFrame, board: pd.DataFrame) -> pd.DataFrame:
    """Long form keyed by the stable FPL player `code` · (code, gw) -> pts, mins.

    The rest of the app joins on `code`, never on name, so the name matching is
    done once here and everything downstream is spared it.
    """
    from analytics.scout_projections import normalise_name

    if snap is None or snap.empty or board is None or board.empty:
        return pd.DataFrame(columns=["code", "gw", "pts", "exp_mins", "opp", "home"])

    key = {(normalise_name(n), str(t)): int(c)
           for n, t, c in zip(board["web_name"], board["team_name"], board["code"])}
    long = per_gw_frame(snap)
    long["code"] = [key.get((normalise_name(n), str(t)))
                    for n, t in zip(long["name"], long["team"])]
    return long.dropna(subset=["code"]).astype({"code": int})


def match_to_board(snap: pd.DataFrame, board: pd.DataFrame) -> Dict:
    """Join the snapshot onto board rows. Returns {matched, unmatched, rate}.

    Matched on normalised name + club. Club is part of the key on purpose: FPL
    web_names collide across clubs (two Silvas, two Sanchezes) and a name-only
    join quietly hands one player another's projection.
    """
    from analytics.scout_projections import normalise_name

    if snap is None or snap.empty or board is None or board.empty:
        return {"matched": pd.DataFrame(), "unmatched": pd.DataFrame(), "rate": 0.0}

    s = snap.copy()
    s["_key"] = [normalise_name(n) for n in s["name"]]
    s["_club"] = s["team"].astype(str)

    b = board.copy()
    b["_key"] = [normalise_name(n) for n in b["web_name"]]
    b["_club"] = b["team_name"].astype(str)

    keep = [c for c in ("pred", "pps", "exp_mins_mean", "exp_mins_next",
                        "nailedness", "mins_volatility", "own", "price")
            if c in s.columns]
    keep += [c for c in s.columns if re.match(r"^gw\d+_(pts|min|opp)$", str(c))]

    merged = b.merge(
        s[["_key", "_club"] + keep].rename(columns={
            "pred": "ffh_pred", "pps": "ffh_pts_per_start",
            "own": "ffh_ownership", "price": "ffh_price"}),
        on=["_key", "_club"], how="left")

    hit = merged["ffh_pred"].notna()
    matched = merged[hit].drop(columns=["_key", "_club"])
    unmatched = s[~s["_key"].isin(set(b.loc[b["_key"].isin(s["_key"]), "_key"]))]
    rate = float(hit.mean()) if len(merged) else 0.0
    logger.info("FFH match rate %.1f%% (%d of %d board rows)",
                rate * 100, int(hit.sum()), len(merged))
    return {"matched": matched, "unmatched": unmatched, "rate": rate,
            "all": merged.drop(columns=["_key", "_club"])}
