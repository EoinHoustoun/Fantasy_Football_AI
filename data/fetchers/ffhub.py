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

# The snapshot writes "BOU(H)". Whitespace is tolerated so a formatting change
# upstream degrades to a parsed fixture rather than a silently blank run.
_FIXTURE_RE = re.compile(r"^([A-Za-z]{3})\s*\(\s*(H|A)\s*\)$", re.IGNORECASE)


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
    return {"opp": m.group(1).upper(), "home": m.group(2).upper() == "H"}


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

    _ren = {"pred": "ffh_pred", "pps": "ffh_pts_per_start",
            "own": "ffh_ownership", "price": "ffh_price"}
    merged = b.merge(
        s[["_key", "_club"] + keep].rename(columns=_ren),
        on=["_key", "_club"], how="left")

    # Second pass on the surname · FPL writes a clashing name as an initial plus
    # a surname ("M.Fernandes"), the Hub usually drops the initial, so the exact
    # key misses and the player loses this model entirely while the page still
    # calls his number a blend. Only unambiguous surname+club pairs are taken:
    # a wrong join silently attributes another player's forecast, which is worse
    # than a missing one.
    from analytics.scout_projections import surname_key
    miss = merged["ffh_pred"].isna()
    if miss.any():
        bs = b.loc[miss, ["code", "web_name", "_club"]].copy()
        bs["_sur"] = bs["web_name"].map(surname_key)
        bs = bs[bs.groupby(["_sur", "_club"])["code"].transform("size") == 1]

        ss = s.copy()
        ss["_sur"] = ss["name"].map(surname_key)
        ss = ss[ss.groupby(["_sur", "_club"])["name"].transform("size") == 1]

        pair = bs.merge(ss[["_sur", "_club"] + keep].rename(columns=_ren),
                        on=["_sur", "_club"], how="inner")
        if not pair.empty:
            cols = [_ren.get(c, c) for c in keep]
            idx = merged.set_index("code").index
            for c in cols:
                if c in pair.columns:
                    fill = pair.set_index("code")[c]
                    merged[c] = merged[c].fillna(
                        pd.Series(idx.map(fill), index=merged.index))
            logger.info("FFH surname rescue matched %d: %s", len(pair),
                        ", ".join(sorted(pair["web_name"].astype(str))[:8]))

    hit = merged["ffh_pred"].notna()
    matched = merged[hit].drop(columns=["_key", "_club"])
    unmatched = s[~s["_key"].isin(set(b.loc[b["_key"].isin(s["_key"]), "_key"]))]
    rate = float(hit.mean()) if len(merged) else 0.0
    logger.info("FFH match rate %.1f%% (%d of %d board rows)",
                rate * 100, int(hit.sum()), len(merged))
    return {"matched": matched, "unmatched": unmatched, "rate": rate,
            "all": merged.drop(columns=["_key", "_club"])}


# The Hub's window total, turned into a season, runs high for a player it has no
# Premier League record for · it is extrapolating an opening month onto 38 weeks
# for exactly the players whose role is least settled. Measured against Scout on
# the 2026-08-05 snapshot: 0.970x on players with a record, 1.109x on those
# without, so the no-record figure needs about a 0.875 haircut to sit on the same
# scale as everything else. Recomputed from the live board when it can be, since
# the gap moves with each refresh · this is the fallback when the sample is thin.
NO_RECORD_DEFLATOR = 0.875
MIN_DEFLATOR_SAMPLE = 8


def no_record_deflator(board) -> float:
    """How much hotter the Hub runs on players it has no PL record for.

    Derived from the board rather than pinned to a literal, because the bias
    moves every time the snapshot is refreshed · it was ~0.70 in early August
    and ~0.875 a snapshot later. A stale constant here silently mis-prices every
    new signing on the board.
    """
    try:
        need = {"src_scout", "src_ffh", "consensus_echoed_scout"}
        if not need.issubset(board.columns):
            return NO_RECORD_DEFLATOR
        d = board.dropna(subset=["src_scout", "src_ffh"]).copy()
        d = d[(d["src_scout"] > 20) & (d["src_ffh"] > 20)]
        ratio = d["src_ffh"] / d["src_scout"]
        norec = d["consensus_echoed_scout"].fillna(False).astype(bool)
        if int(norec.sum()) < MIN_DEFLATOR_SAMPLE or int((~norec).sum()) < MIN_DEFLATOR_SAMPLE:
            return NO_RECORD_DEFLATOR
        with_r, no_r = ratio[~norec].median(), ratio[norec].median()
        if not (with_r > 0 and no_r > 0):
            return NO_RECORD_DEFLATOR
        return float(min(1.0, max(0.5, with_r / no_r)))
    except Exception:
        return NO_RECORD_DEFLATOR


def backfill_from_hub(no_history: pd.DataFrame, snapshot: pd.DataFrame,
                      scale: float = 1.0, deflator: float = NO_RECORD_DEFLATOR):
    """Put a no-history player on the board when only the Hub has heard of him.

    `scout_projections.backfill_projections` already rescues no-history players
    from the SCOUT snapshot, which covers promoted clubs well. It does not cover
    a mid-window signing from another league: Scout's table simply has no row, so
    the player was dropped from the board, the optimiser and every table on the
    page. He did not read as a bad pick · he did not exist.

    That is not a fringe case. On the 2026-08-05 snapshots 35 live FPL players
    were missing from the board and the Hub had a forecast for 32 of them,
    including a £5.5m Brentford midfielder the Hub expects to play 80 minutes a
    week. Cheap, nailed and invisible is the worst combination there is for a
    squad being built around enablers.

    The season number is deliberately the least trusted figure we publish: a
    window extrapolation, rescaled onto our scale, then deflated for the Hub's
    no-record bias. The number that actually matters for these players is the
    PER-GAMEWEEK one, which `gw_projection` reads straight from this same
    snapshot as a real per-fixture forecast the moment the player is on the
    board at all.
    """
    if no_history is None or getattr(no_history, "empty", True):
        return pd.DataFrame()
    if snapshot is None or snapshot.empty:
        return pd.DataFrame()

    from analytics.scout_projections import normalise_name

    s = snapshot.copy()
    s["_key"] = s["name"].map(normalise_name)
    s["_club"] = s["team"].astype(str).str.strip()

    b = no_history.copy()
    b["_key"] = b["web_name"].map(normalise_name)
    b["_club"] = b["team_name"].astype(str).str.strip()

    gws = window_gws(s)
    take = ["_key", "_club", "pred", "pps", "exp_mins_mean", "nailedness"]
    take += ["gw%d_pts" % g for g in gws]
    m = b.merge(s[[c for c in take if c in s.columns]], on=["_key", "_club"], how="inner")
    if m.empty:
        return pd.DataFrame()

    # Join on name AND club, never name alone · there are two Sangarés in this
    # very dataset, one at Brentford and one at Nott'm Forest, and name-only
    # would hand one of them the other's forecast.
    k = float(scale) if scale and scale > 0 else 1.0
    d = float(deflator) if deflator and deflator > 0 else 1.0
    per_gw = pd.to_numeric(m.get("pps"), errors="coerce")
    if per_gw is None or per_gw.isna().all():
        n = max(len(gws), 1)
        per_gw = pd.to_numeric(m["pred"], errors="coerce") / n

    m["projected_points"] = (per_gw * 38.0 * k * d).round(1)
    mins = pd.to_numeric(m.get("exp_mins_mean"), errors="coerce").fillna(0.0)
    m["projected_minutes"] = (mins * 38.0).round(0)
    # Wider than the Scout backfill's band on purpose. This is one model, on a
    # player it is extrapolating, with no second opinion anywhere to check it.
    m["proj_lo"] = (m["projected_points"] * 0.55).round(1)
    m["proj_hi"] = (m["projected_points"] * 1.45).round(1)
    m["confidence"] = "Low"
    m["confidence_note"] = ("Match model only · no Premier League record and no "
                            "Scout projection to cross-check")
    m["projection_source"] = "ffh"
    m["value_score"] = (m["projected_points"]
                        / m["actual_price"].clip(lower=0.1)).round(2)
    m["mins_share"] = (m["projected_minutes"] / 3420.0).clip(0, 1).round(2)
    m["last_season_points"] = 0.0
    m["last_season_minutes"] = 0.0
    m["pricing_surprise"] = 0.0
    m["override_note"] = ""
    m["starts_ratio"] = float("nan")
    drop = [c for c in ("_key", "_club", "pred", "pps") if c in m.columns]
    logger.info("Hub backfill added %d players Scout could not see: %s", len(m),
                ", ".join(sorted(m["web_name"].astype(str))[:8]))
    return m.drop(columns=drop)
