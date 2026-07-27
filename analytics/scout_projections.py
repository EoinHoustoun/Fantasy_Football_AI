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


def backfill_projections(scout_frame: pd.DataFrame, snapshot: pd.DataFrame,
                         scale: float = 1.0) -> pd.DataFrame:
    """Give no-history players a projection so the draft can actually pick them.

    Promoted-club players and new signings have no 2025-26 Premier League record,
    so our carryover model produces nothing for them and they were dropped from
    the optimiser pool entirely. That is not a small gap: it removed EVERY
    Coventry, Hull and Ipswich player, and their £4.0m defenders are exactly the
    enablers a squad is built around.

    Scout projects them because its model is forward-looking rather than
    carryover. We rescale onto our own scale (see `model_scale`) so the numbers
    are comparable with the rest of the board, mark them Low confidence, and tag
    `projection_source` so the UI can be honest about where the figure came from.
    """
    if scout_frame is None or scout_frame.empty or snapshot is None or snapshot.empty:
        return pd.DataFrame()

    s = scout_frame.copy()
    s["join_key"] = s["web_name"].map(normalise_name)
    s["pos"] = s["position"].replace(POS_ALIASES)

    snap = snapshot[["join_key", "team_short", "pos", "scout_pts", "scout_mins",
                     "g", "a", "cs", "dc", "bonus"]]
    m = s.merge(snap, on=["join_key", "team_short", "pos"], how="inner")
    if m.empty:
        return m

    k = float(scale) if scale and scale > 0 else 1.0
    m["projected_points"] = (m["scout_pts"] * k).round(1)
    m["projected_minutes"] = m["scout_mins"].round(0)
    # A rescaled external projection is a wide guess, not a forecast. The band is
    # deliberately generous · these are the least-known players on the board.
    m["proj_lo"] = (m["projected_points"] * 0.65).round(1)
    m["proj_hi"] = (m["projected_points"] * 1.35).round(1)
    m["confidence"] = "Low"
    m["confidence_note"] = "External projection · no Premier League record yet"
    m["projection_source"] = "scout"
    m["value_score"] = (m["projected_points"] / m["actual_price"].clip(lower=0.1)).round(2)
    m["mins_share"] = (m["projected_minutes"] / 3420.0).clip(0, 1).round(2)
    m["last_season_points"] = 0.0
    m["last_season_minutes"] = 0.0
    m["pricing_surprise"] = 0.0
    m["override_note"] = ""
    m["starts_ratio"] = float("nan")
    return m.drop(columns=["join_key", "pos"])


def override_no_evidence(board: pd.DataFrame, snapshot: pd.DataFrame,
                         scale: float = 1.0, max_minutes: int = 500,
                         min_scout_minutes: int = 1500) -> pd.DataFrame:
    """Use Scout's projection where ours is built on no evidence at all.

    A player can hold a 2025-26 row and still be invisible to our model: Luka
    Vuskovic was registered to Spurs, played ZERO Premier League minutes, and
    came out at 8 projected points. That is not a low forecast, it is an empty
    one, and it is worse than having no row at all because the backfill for
    no-history players skips him.

    So where our sample is essentially empty (`max_minutes`) and Scout expects a
    real season (`min_scout_minutes`), take the rescaled Scout figure and say so.
    Everyone else keeps our projection · this is a narrow repair, not a merge.
    """
    if board is None or board.empty or snapshot is None or snapshot.empty:
        return board

    b = board.copy()
    if "last_season_minutes" not in b.columns:
        return b

    # A hand override is knowledge no model has · it beats the Scout fallback.
    try:
        from analytics.projection_overrides import load_overrides
        _manual = set(load_overrides().keys())
    except Exception:
        _manual = set()

    # A hand override is knowledge the Scout model does not have · it wins.
    try:
        from analytics.projection_overrides import load_overrides
        _manual = set(load_overrides().keys())
    except Exception:
        _manual = set()

    b["join_key"] = b["web_name"].map(normalise_name)
    b["_pos"] = b["position"].replace(POS_ALIASES) if "position" in b.columns else ""
    snap = snapshot[["join_key", "team_short", "pos", "scout_pts", "scout_mins"]] \
        .rename(columns={"pos": "_pos"})
    b = b.merge(snap, on=["join_key", "team_short", "_pos"], how="left")

    k = float(scale) if scale and scale > 0 else 1.0
    empty = (b["last_season_minutes"].fillna(0) <= max_minutes) \
        & (b["scout_mins"].fillna(0) >= min_scout_minutes) \
        & (~b["code"].isin(_manual))

    if empty.any():
        b.loc[empty, "projected_points"] = (b.loc[empty, "scout_pts"] * k).round(1)
        b.loc[empty, "projected_minutes"] = b.loc[empty, "scout_mins"].round(0)
        b.loc[empty, "proj_lo"] = (b.loc[empty, "projected_points"] * 0.65).round(1)
        b.loc[empty, "proj_hi"] = (b.loc[empty, "projected_points"] * 1.35).round(1)
        b.loc[empty, "confidence"] = "Low"
        b.loc[empty, "confidence_note"] = "No Premier League minutes · external projection"
        b.loc[empty, "projection_source"] = "scout"
        if "actual_price" in b.columns:
            b.loc[empty, "value_score"] = (
                b.loc[empty, "projected_points"]
                / b.loc[empty, "actual_price"].clip(lower=0.1)).round(2)
        if "mins_share" in b.columns:
            b.loc[empty, "mins_share"] = (
                b.loc[empty, "projected_minutes"] / 3420.0).clip(0, 1).round(2)
        logger.info("overrode %d empty-sample projections from Scout", int(empty.sum()))

    return b.drop(columns=["join_key", "_pos", "scout_pts", "scout_mins"])


def coverage(result: Dict[str, pd.DataFrame]) -> Dict:
    """Join health · for the UI caption. Never let a silent 50% match look fine."""
    n_m, n_u = len(result["matched"]), len(result["unmatched"])
    total = n_m + n_u
    return {"matched": n_m, "unmatched": n_u, "total": total,
            "pct": round(100.0 * n_m / total, 1) if total else 0.0,
            "unmatched_names": result["unmatched"]["scout_name"].tolist()[:20]}
