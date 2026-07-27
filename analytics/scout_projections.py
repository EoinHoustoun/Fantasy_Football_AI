"""Second-opinion projections · Fantasy Football Scout season-long model.

Our 26/27 projection is a carryover model fitted on last season plus three hand
layers (overrides, live-bootstrap correction, confidence). It has no external
check. This module joins a manually-refreshed snapshot of Fantasy Football
Scout's independent season projection (the Rate My Team engine) so the two can
be compared player by player.

The snapshot is a LOCAL file the user refreshes when they choose. It is never
polled or scraped on a schedule · bulk harvesting a paid site breaks its terms.
`data/cache/` is gitignored, so the snapshot stays on the machine.

Every surface degrades quietly when the snapshot is absent: `load_snapshot`
returns None and callers show a caption rather than failing.
"""
import logging
import unicodedata
from typing import Dict, List, Optional

import pandas as pd

from config import CACHE_DIR, NEXT_SEASON

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = CACHE_DIR / ("scout_projections_%s.csv" % NEXT_SEASON.replace("-", "_"))

# Scout's club codes against FPL's. Only Brighton differs; kept as a map so a
# future divergence is a one-line fix rather than a debugging session.
TEAM_ALIASES = {"BRI": "BHA"}

# Characters NFKD will not decompose (they are distinct letters, not accents).
# Odegaard is the live example: NFKD leaves 'O with stroke' intact, so the join
# silently missed him until this map existed.
CHAR_ALIASES = {
    "ø": "o", "Ø": "o",     # o-slash
    "đ": "d", "Đ": "d",     # d-stroke
    "ł": "l", "Ł": "l",     # l-stroke
    "ß": "ss",                    # sharp s
    "æ": "ae", "Æ": "ae",
}

POS_FROM_ELEMENT_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
# The board carries FPL's position labels; Scout writes GK where FPL writes GKP.
POS_ALIASES = {"GKP": "GK"}


def normalise_name(name: str) -> str:
    """Fold a player name to a join key · accents, punctuation and case removed."""
    s = str(name)
    for src, dst in CHAR_ALIASES.items():
        s = s.replace(src, dst)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    for ch in (".", "-", "'", "’"):
        s = s.replace(ch, " " if ch == "-" else "")
    return " ".join(s.lower().split())


def load_snapshot(path=None) -> Optional[pd.DataFrame]:
    """Read the Scout snapshot. Returns None when no snapshot has been saved."""
    path = path or SNAPSHOT_PATH
    if not path.exists():
        logger.info("no Scout snapshot at %s", path)
        return None
    df = pd.read_csv(path)
    missing = {"name", "team", "pos", "price", "mins", "pts"} - set(df.columns)
    if missing:
        logger.warning("Scout snapshot missing columns: %s", sorted(missing))
        return None
    df = df.rename(columns={"name": "scout_name", "team": "scout_team",
                            "price": "scout_price", "mins": "scout_mins",
                            "pts": "scout_pts", "value": "scout_value"})
    df["team_short"] = df["scout_team"].replace(TEAM_ALIASES)
    df["pos"] = df["pos"].replace(POS_ALIASES)
    df["join_key"] = df["scout_name"].map(normalise_name)
    return df


def match_to_board(scout: pd.DataFrame, board: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Join a Scout snapshot to the 26/27 value board.

    Matches on (normalised name, club, position) · all three, because a name
    alone collides (two Gomez, two Munoz, two Fernandes in this pool).

    Returns {"matched": df, "unmatched": df}. Unmatched rows are RETURNED, never
    dropped, so the UI can show what failed instead of quietly losing players.
    """
    b = board.copy()
    b["join_key"] = b["web_name"].map(normalise_name)
    b["pos"] = b["position"].replace(POS_ALIASES) if "position" in b.columns else b.get("pos")

    keep = [c for c in ("code", "web_name", "team_short", "pos", "join_key",
                        "actual_price", "projected_points", "proj_lo", "proj_hi",
                        "confidence", "confidence_note", "override_note",
                        "verdict", "team_code", "team_id") if c in b.columns]
    joined = scout.merge(b[keep], on=["join_key", "team_short", "pos"], how="left")

    matched = joined[joined["code"].notna()].copy()
    matched["code"] = matched["code"].astype(int)
    unmatched = joined[joined["code"].isna()].copy()
    logger.info("Scout join: %d matched, %d unmatched", len(matched), len(unmatched))
    return {"matched": matched, "unmatched": unmatched}


def model_scale(matched: pd.DataFrame, min_mins: int = 1500) -> float:
    """How our projection scale compares to Scout's · a single robust ratio.

    The two models are NOT on the same scale. Ours is a conservative carryover
    projection and runs about 30% below Scout's across the board. Ranking players
    by the raw gap therefore ranks them by that offset, not by disagreement:
    every expensive player looks like a huge argument when the models may in fact
    agree on his standing entirely.

    Median ratio, not a regression slope · robust to the handful of players one
    model has near zero.
    """
    d = matched[(matched["scout_mins"] >= min_mins) & (matched["scout_pts"] > 0)]
    if d.empty:
        return 1.0
    ratio = (d["projected_points"].astype(float) / d["scout_pts"].astype(float))
    med = float(ratio.median())
    return med if med > 0 else 1.0


def disagreements(matched: pd.DataFrame, min_delta: float = 20.0,
                  min_mins: int = 1500,
                  scale: Optional[float] = None) -> pd.DataFrame:
    """Genuine disagreements, scale-adjusted, biggest first.

    `delta` is the raw gap (Scout minus ours), kept for transparency. But the
    ranking uses `residual`: how far a player sits from the TYPICAL relationship
    between the two models. That is the real signal · a player whose gap is just
    the global scale offset is not a disagreement, however large the gap looks.

    A positive residual means we are more bullish than our own scale predicts;
    negative means we are more bearish. Filtered to players Scout expects to
    actually play, because a gap on a 300-minute squad player is noise.
    """
    d = matched[matched["scout_mins"] >= min_mins].copy()
    if d.empty:
        return d

    k = float(scale) if scale is not None else model_scale(matched, min_mins)
    d["delta"] = (d["scout_pts"] - d["projected_points"]).round(1)
    # What our model WOULD say about him if it only differed by scale.
    d["expected_ours"] = (d["scout_pts"] * k).round(1)
    d["residual"] = (d["projected_points"] - d["expected_ours"]).round(1)
    d["abs_residual"] = d["residual"].abs()
    d = d[d["abs_residual"] >= float(min_delta)]

    # Does Scout, rescaled, land inside the honest range we already publish? If
    # it does the models agree within our own stated uncertainty.
    if {"proj_lo", "proj_hi"}.issubset(d.columns):
        d["within_our_range"] = (
            (d["expected_ours"] >= d["proj_lo"].fillna(d["projected_points"]))
            & (d["expected_ours"] <= d["proj_hi"].fillna(d["projected_points"])))
    else:
        d["within_our_range"] = False

    cols = [c for c in ("web_name", "team_short", "pos", "actual_price",
                        "projected_points", "expected_ours", "residual",
                        "proj_lo", "proj_hi", "scout_pts", "delta",
                        "within_our_range", "confidence",
                        "override_note", "verdict", "code", "team_code")
            if c in d.columns]
    return d.sort_values("abs_residual", ascending=False)[cols].reset_index(drop=True)


def coverage(result: Dict[str, pd.DataFrame]) -> Dict:
    """Join health · for the UI caption. Never let a silent 50% match look fine."""
    n_m, n_u = len(result["matched"]), len(result["unmatched"])
    total = n_m + n_u
    return {"matched": n_m, "unmatched": n_u, "total": total,
            "pct": round(100.0 * n_m / total, 1) if total else 0.0,
            "unmatched_names": result["unmatched"]["scout_name"].tolist()[:20]}
