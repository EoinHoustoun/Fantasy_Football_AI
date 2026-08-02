"""Fantasy Football Scout · Rate My Team per-gameweek projections.

A MANUAL, gitignored snapshot of the Rate My Team players table, which gives an
expected-points figure per player PER GAMEWEEK for GW1-6. That is a different
and more useful shape than the season-long Scout file:

  scout_projections_*.csv   one season total per player
  scout_rmt_gw1_6_*.csv     six per-gameweek numbers per player   <- this file

For an opening squad that gets wildcarded at GW4, the per-gameweek numbers are
the ones that matter. They also give the per-gameweek engine a SECOND opinion:
until now `gw_projection` had exactly one match-level source (the Hub), so a
single provider's view of a fixture went through unchallenged.

Snapshots are manual and local. Nothing here fetches, polls or schedules a
re-scrape · the file is refreshed by a human who chose to refresh it.
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from config import CACHE_DIR, NEXT_SEASON

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = CACHE_DIR / ("scout_rmt_gw1_6_%s.csv" % NEXT_SEASON.replace("-", "_"))

GW_COLS = ["gw1", "gw2", "gw3", "gw4", "gw5", "gw6"]

# Rate My Team writes clubs in full; the board keys on the FPL short code.
CLUB_TO_SHORT = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU",
    "Brentford": "BRE", "Brighton": "BHA", "Burnley": "BUR",
    "Chelsea": "CHE", "Coventry": "COV", "Coventry City": "COV",
    "Crystal Palace": "CRY", "Everton": "EVE", "Fulham": "FUL",
    "Hull": "HUL", "Hull City": "HUL", "Ipswich": "IPS",
    "Ipswich Town": "IPS", "Leeds": "LEE", "Leeds United": "LEE",
    "Liverpool": "LIV", "Man City": "MCI", "Man Utd": "MUN",
    "Newcastle": "NEW", "Nott'm Forest": "NFO", "Nottingham Forest": "NFO",
    "Spurs": "TOT", "Tottenham": "TOT", "Sunderland": "SUN",
    "West Ham": "WHU", "Wolves": "WOL",
}

POS_TO_FPL = {"G": "GKP", "D": "DEF", "M": "MID", "F": "FWD"}


def load_snapshot(path=None) -> Optional[pd.DataFrame]:
    """Read the Rate My Team snapshot. None when no snapshot has been saved."""
    path = path or SNAPSHOT_PATH
    if not path.exists():
        logger.info("no Scout RMT snapshot at %s", path)
        return None
    df = pd.read_csv(path)
    missing = {"name", "team", "pos"} - set(df.columns)
    if missing:
        logger.warning("RMT snapshot missing columns: %s", sorted(missing))
        return None
    have = [c for c in GW_COLS if c in df.columns]
    if not have:
        logger.warning("RMT snapshot has no gameweek columns")
        return None

    df = df.copy()
    df["team_short"] = df["team"].astype(str).str.strip().map(CLUB_TO_SHORT)
    unknown = sorted(set(df.loc[df["team_short"].isna(), "team"].astype(str)))
    if unknown:
        logger.warning("RMT clubs not mapped to a short code: %s", unknown)
    df["pos"] = df["pos"].astype(str).str.strip().map(POS_TO_FPL)
    for c in have:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    logger.info("loaded Scout RMT snapshot · %d players, %s", len(df), have)
    return df


def match_to_board(snap: pd.DataFrame, board: pd.DataFrame) -> Dict[str, object]:
    """Join RMT rows to the board on (normalised name, club, position).

    Falls back to the surname where the exact name misses and the surname
    identifies exactly one player on each side · the same rule the season-long
    Scout join uses, and for the same reason: FPL writes a name clash with an
    initial and drops it when the clash resolves.
    """
    from analytics.scout_projections import normalise_name, surname_key

    if snap is None or snap.empty or board is None or board.empty:
        return {"matched": pd.DataFrame(), "unmatched": pd.DataFrame(), "rate": 0.0}

    s = snap.copy()
    s["_key"] = s["name"].map(normalise_name)

    b = board.copy()
    b["_key"] = b["web_name"].map(normalise_name)
    b["pos"] = b["position"]

    have = [c for c in GW_COLS if c in s.columns]
    right = s[["_key", "team_short", "pos"] + have]

    joined = b.merge(right, on=["_key", "team_short", "pos"], how="left")
    miss = joined[have[0]].isna()

    if miss.any():
        bs = joined.loc[miss, ["code", "web_name", "team_short", "pos"]].copy()
        bs["_sur"] = bs["web_name"].map(surname_key)
        bs = bs[bs.groupby(["_sur", "team_short", "pos"])["code"]
                .transform("size") == 1]
        ss = s.copy()
        ss["_sur"] = ss["name"].map(surname_key)
        ss = ss[ss.groupby(["_sur", "team_short", "pos"])["name"]
                .transform("size") == 1]
        pair = bs.merge(ss[["_sur", "team_short", "pos"] + have],
                        on=["_sur", "team_short", "pos"], how="inner")
        if not pair.empty:
            fill = pair.set_index("code")
            idx = joined["code"]
            for c in have:
                joined[c] = joined[c].fillna(
                    pd.Series(idx.map(fill[c]).values, index=joined.index))
            logger.info("RMT surname rescue matched %d: %s", len(pair),
                        ", ".join(sorted(pair["web_name"].astype(str))[:8]))

    hit = joined[have[0]].notna()
    rate = float(hit.mean()) if len(joined) else 0.0
    logger.info("Scout RMT match rate %.1f%% (%d of %d board rows)",
                rate * 100, int(hit.sum()), len(joined))
    return {"matched": joined[hit].copy(), "all": joined, "rate": rate,
            "gw_cols": have}


def per_gw_by_code(snap: pd.DataFrame, board: pd.DataFrame) -> pd.DataFrame:
    """Long frame of (code, gw, pts) · the shape `gw_projection` consumes."""
    out = match_to_board(snap, board)
    m, have = out["matched"], out.get("gw_cols", GW_COLS)
    if m is None or m.empty:
        return pd.DataFrame(columns=["code", "gw", "pts"])
    rows: List[Dict] = []
    for _, r in m.iterrows():
        for c in have:
            v = r.get(c)
            if pd.notna(v):
                rows.append({"code": int(r["code"]), "gw": int(c[2:]),
                             "pts": float(v)})
    return pd.DataFrame(rows)


SEASON_PATH = CACHE_DIR / ("scout_rmt_season_%s.csv" % NEXT_SEASON.replace("-", "_"))


def load_season(path=None) -> Optional[pd.DataFrame]:
    """Scout's GW1-38 season total per player · the freshest season read we have.

    The older `scout_projections_*.csv` carries minutes, goals and clean sheets
    as well, so it is not replaced. This supplies the POINTS, which is the one
    number the consensus blends and the one that goes stale fastest.
    """
    path = path or SEASON_PATH
    if not path.exists():
        logger.info("no Scout season snapshot at %s", path)
        return None
    df = pd.read_csv(path)
    if not {"name", "team", "pos", "season_total"} <= set(df.columns):
        logger.warning("Scout season snapshot missing columns")
        return None
    df = df.copy()
    df["team_short"] = df["team"].astype(str).str.strip().map(CLUB_TO_SHORT)
    df["pos"] = df["pos"].astype(str).str.strip().map(POS_TO_FPL)
    df["season_total"] = pd.to_numeric(df["season_total"], errors="coerce")
    logger.info("loaded Scout season snapshot · %d players", len(df))
    return df


def season_by_code(snap: pd.DataFrame, board: pd.DataFrame) -> pd.Series:
    """code -> Scout season points, joined the same guarded way as everything else."""
    from analytics.scout_projections import normalise_name, surname_key

    if snap is None or snap.empty or board is None or board.empty:
        return pd.Series(dtype=float)

    s = snap.copy()
    s["_key"] = s["name"].map(normalise_name)
    b = board.copy()
    b["_key"] = b["web_name"].map(normalise_name)
    b["pos"] = b["position"]

    j = b.merge(s[["_key", "team_short", "pos", "season_total"]],
                on=["_key", "team_short", "pos"], how="left")
    miss = j["season_total"].isna()
    if miss.any():
        bs = j.loc[miss, ["code", "web_name", "team_short", "pos"]].copy()
        bs["_sur"] = bs["web_name"].map(surname_key)
        bs = bs[bs.groupby(["_sur", "team_short", "pos"])["code"]
                .transform("size") == 1]
        ss = s.copy()
        ss["_sur"] = ss["name"].map(surname_key)
        ss = ss[ss.groupby(["_sur", "team_short", "pos"])["name"]
                .transform("size") == 1]
        pair = bs.merge(ss[["_sur", "team_short", "pos", "season_total"]],
                        on=["_sur", "team_short", "pos"], how="inner")
        if not pair.empty:
            fill = pair.set_index("code")["season_total"]
            j["season_total"] = j["season_total"].fillna(
                pd.Series(j["code"].map(fill).values, index=j.index))
            logger.info("Scout season surname rescue matched %d", len(pair))
    out = j.set_index("code")["season_total"].dropna()
    logger.info("Scout season points for %d of %d board rows", len(out), len(board))
    return out
