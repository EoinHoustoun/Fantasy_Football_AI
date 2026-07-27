"""Season Opener · the early chip route, priced as one decision.

The Chip Planner ranks Bench Boost, Triple Captain and Free Hit independently on
a fixed squad. That is the wrong shape for the decision actually on the table.
An early Bench Boost needs fifteen playing assets, which costs XI strength EVERY
week you carry that squad, and an early Wildcard is what repairs it. Playing BB
in GW1 and wildcarding in GW3 is one plan; the two chips cannot be scored apart.

Two clocks disagree about when to wildcard, and this module surfaces both rather
than picking a side:

  - the DILUTION clock · how long you can carry a Boost-ready fifteen before the
    XI cost outruns the chip. Short, and it argues for a GW3 wildcard.
  - the FIXTURE clock · when your clubs' fixtures actually turn. Longer, and it
    argues for GW6-7.

`compare_routes` scores whole routes end to end so the two can be read off the
same number instead of argued about.
"""
import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import CHIP_ROUTES, CHIP_TIMING, OPENING_FIXTURES, SEASON_OPENER

logger = logging.getLogger(__name__)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _long_fixtures(fixtures: pd.DataFrame) -> pd.DataFrame:
    """One row per team per fixture · the shape every read below wants."""
    rows: List[Dict] = []
    for _, r in fixtures.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        gw = int(r["gameweek"])
        rows.append({"team_id": int(r["home_team_id"]), "gw": gw,
                     "fdr": float(r["home_fdr"]), "home": True,
                     "opp_id": int(r["away_team_id"])})
        rows.append({"team_id": int(r["away_team_id"]), "gw": gw,
                     "fdr": float(r["away_fdr"]), "home": False,
                     "opp_id": int(r["home_team_id"])})
    return pd.DataFrame(rows)


def _ease(fdr: float, slope: float, floor: float) -> float:
    """Fixture-ease multiplier · >1 easier than average, <1 harder."""
    return max(floor, 1.0 + (3.0 - float(fdr)) * slope)


def opening_ease(fixtures: pd.DataFrame, gw_lo: int = 1, gw_hi: int = 6,
                 cfg: Optional[Dict] = None) -> pd.DataFrame:
    """Per club: mean FDR, mean ease multiplier and home count over a GW window.

    Generalises what `ui.value_board._opening_factors` did for a single hardcoded
    window, so the draft weight and the route comparator read one implementation.
    """
    cfg = cfg or OPENING_FIXTURES
    lf = _long_fixtures(fixtures)
    sub = lf[(lf["gw"] >= gw_lo) & (lf["gw"] <= gw_hi)]
    if sub.empty:
        return pd.DataFrame(columns=["team_id", "fdr", "ease", "home", "n"])
    sub = sub.assign(ease=sub["fdr"].map(
        lambda f: _ease(f, cfg["fdr_slope"], cfg["factor_floor"])))
    out = (sub.groupby("team_id")
           .agg(fdr=("fdr", "mean"), ease=("ease", "mean"),
                home=("home", "sum"), n=("gw", "count"))
           .reset_index())
    out["fdr"] = out["fdr"].round(3)
    out["ease"] = out["ease"].round(3)
    return out.sort_values("fdr").reset_index(drop=True)


def opening_factors(fixtures: pd.DataFrame, cfg: Optional[Dict] = None) -> Dict[int, float]:
    """team_id -> mean opening ease · the draft objective's opening weight."""
    cfg = cfg or OPENING_FIXTURES
    df = opening_ease(fixtures, 1, int(cfg["gw_hi"]), cfg)
    return dict(zip(df["team_id"].astype(int), df["ease"].astype(float)))


def fixture_swing(fixtures: pd.DataFrame,
                  early: Optional[Tuple[int, int]] = None,
                  late: Optional[Tuple[int, int]] = None,
                  cfg: Optional[Dict] = None) -> pd.DataFrame:
    """Which clubs' fixtures turn, and when · the wildcard-timing read.

    `swing` is late FDR minus early FDR, so POSITIVE means the run gets HARDER
    after the early window. Those are the clubs to load up on first and move off
    at the wildcard; negative-swing clubs are what you wildcard into.
    """
    o = cfg or SEASON_OPENER
    early = early or tuple(o["swing_early"])
    late = late or tuple(o["swing_late"])
    e = opening_ease(fixtures, early[0], early[1]).rename(
        columns={"fdr": "early_fdr", "ease": "early_ease"})
    l = opening_ease(fixtures, late[0], late[1]).rename(
        columns={"fdr": "late_fdr", "ease": "late_ease"})
    out = e[["team_id", "early_fdr", "early_ease"]].merge(
        l[["team_id", "late_fdr", "late_ease"]], on="team_id", how="outer")
    out["swing"] = (out["late_fdr"] - out["early_fdr"]).round(3)
    return out.sort_values("swing", ascending=False).reset_index(drop=True)


# ── Bench Boost dilution ──────────────────────────────────────────────────────

def squad_frame(squad: Optional[Dict]) -> Optional[pd.DataFrame]:
    """The fifteen out of an `optimize_squad` result, or None if it failed.

    `optimize_squad` returns {"squad": df, ...} with an `in_xi` boolean column ·
    it does not hand back separate XI and bench frames.
    """
    if not squad:
        return None
    df = squad.get("squad")
    if df is None or df.empty:
        return None
    return df


def _split_pts(squad: Optional[Dict], pts_col: str = "pts") -> Tuple[float, float]:
    """(XI points, bench points) for a solved squad."""
    df = squad_frame(squad)
    if df is None or pts_col not in df.columns:
        return 0.0, 0.0
    xi = df[df["in_xi"]]
    bench = df[~df["in_xi"]]
    return float(xi[pts_col].sum()), float(bench[pts_col].sum())


def bb_dilution(board: pd.DataFrame, solve_fn, cfg: Optional[Dict] = None) -> Optional[Dict]:
    """What an all-playing fifteen costs, and how long you can afford to carry it.

    Two squads, one constraint apart: a normal squad whose bench is fodder, and a
    Bench Boost squad where all fifteen genuinely start. The difference in XI
    strength is a cost paid EVERY gameweek; the difference in bench strength is a
    gain banked ONCE, in the week the chip is played. Break-even is the ratio.

    Returns the bracket, not a single number. A freely-chosen bench and a
    price-capped bench give different answers and both are honest, so the caller
    shows a range rather than a false decimal.

    `solve_fn(board, all_must_play, bench_price_cap) -> squad dict or None` is
    injected so this stays testable without Streamlit's cached draft solver.
    """
    o = cfg or SEASON_OPENER
    gws = float(o["season_gws"])

    boost = solve_fn(board, all_must_play=True, bench_price_cap=None)
    if squad_frame(boost) is None:
        logger.warning("bb_dilution: Boost squad infeasible")
        return None

    b_xi, b_bench = _split_pts(boost)

    arms: List[Dict] = []
    for label, cap in (("free bench", None),
                       ("cheap bench", float(o["bench_price_cap"]))):
        norm = solve_fn(board, all_must_play=False, bench_price_cap=cap)
        if squad_frame(norm) is None:
            logger.warning("bb_dilution: normal squad infeasible for %s", label)
            continue
        n_xi, n_bench = _split_pts(norm)
        dilution = (n_xi - b_xi) / gws
        gain = (b_bench - n_bench) / gws
        if dilution <= 0:
            # The all-play squad is not actually weaker · nothing to trade off.
            arms.append({"arm": label, "dilution_per_gw": round(dilution, 2),
                         "bb_gain": round(gain, 1), "break_even_gws": None})
            continue
        arms.append({"arm": label,
                     "dilution_per_gw": round(dilution, 2),
                     "bb_gain": round(gain, 1),
                     "break_even_gws": round(gain / dilution, 1)})

    if not arms:
        return None
    be = [a["break_even_gws"] for a in arms if a["break_even_gws"] is not None]
    return {"arms": arms,
            "boost_xi": round(b_xi), "boost_bench": round(b_bench),
            "break_even_lo": min(be) if be else None,
            "break_even_hi": max(be) if be else None}


# ── Route comparator ──────────────────────────────────────────────────────────

def _player_gw_pts(season_pts: float, team_id: int, gw: int,
                   fmap: Dict, cfg: Dict, season_gws: float) -> float:
    """Per-GW points · season projection spread over 38, scaled by fixture ease.

    Same model the Chip Planner uses, so the two pages cannot drift apart. A
    blank gameweek scores nothing; a double stacks both fixtures.
    """
    base = season_pts / season_gws
    return sum(base * _ease(f, cfg["fdr_slope"], cfg["factor_floor"])
               for f in fmap.get((int(team_id), int(gw)), []))


def _fixtures_by_team_gw(fixtures: pd.DataFrame) -> Dict:
    out: Dict = {}
    lf = _long_fixtures(fixtures)
    for r in lf.itertuples():
        out.setdefault((r.team_id, r.gw), []).append(r.fdr)
    return out


def _score_squad(squad_df: pd.DataFrame, gw_lo: int, gw_hi: int, fmap: Dict,
                 cfg: Dict, season_gws: float, boost_gw: Optional[int] = None) -> float:
    """Total points a fifteen returns over a GW range.

    Only the XI scores each week, except in `boost_gw` where the bench counts too.
    """
    total = 0.0
    for gw in range(gw_lo, gw_hi + 1):
        for r in squad_df.itertuples():
            if not getattr(r, "in_xi", True) and gw != boost_gw:
                continue
            total += _player_gw_pts(float(r.pts), int(r.team_id), gw,
                                    fmap, cfg, season_gws)
    return total


def compare_routes(board: pd.DataFrame, fixtures: pd.DataFrame, solve_fn,
                   routes: Optional[List[Dict]] = None,
                   gw_hi: int = 19, cfg: Optional[Dict] = None) -> pd.DataFrame:
    """Score whole chip routes over GW1..gw_hi against a no-early-chips baseline.

    Each route is {label, bb_gw, wc_gw}. A route with an early Bench Boost starts
    on an all-play fifteen (that is what makes the chip worth playing) and carries
    its XI dilution until `wc_gw`; at the wildcard it rebuilds on the fixtures
    that follow, so the aggressive route gets full credit for the reset rather
    than being punished for the squad it started with.

    `solve_fn(board, all_must_play, bench_price_cap, opening_window) -> squad dict`
    is injected · same reason as `bb_dilution`.
    """
    o = cfg or SEASON_OPENER
    ct = CHIP_TIMING
    gws = float(o["season_gws"])
    routes = routes or CHIP_ROUTES
    fmap = _fixtures_by_team_gw(fixtures)

    # Baseline · one normal squad, no early chips, carried the whole way.
    base_squad = squad_frame(solve_fn(board, all_must_play=False, bench_price_cap=None,
                                      opening_window=(1, gw_hi)))
    if base_squad is None:
        logger.warning("compare_routes: baseline squad infeasible")
        return pd.DataFrame()
    baseline = _score_squad(base_squad, 1, gw_hi, fmap, ct, gws)

    rows: List[Dict] = []
    for route in routes:
        bb_gw, wc_gw = route.get("bb_gw"), route.get("wc_gw")

        start = squad_frame(solve_fn(board, all_must_play=bb_gw is not None,
                                     bench_price_cap=None,
                                     opening_window=(1, max(1, (wc_gw or gw_hi) - 1))))
        if start is None:
            logger.warning("compare_routes: start squad infeasible for %s", route["label"])
            continue

        # Phase one · GW1 up to the wildcard, on the squad the chip demanded.
        pre_hi = (wc_gw - 1) if wc_gw else gw_hi
        total = _score_squad(start, 1, pre_hi, fmap, ct, gws, boost_gw=bb_gw)

        # Phase two · rebuild at the wildcard on the fixtures that actually follow.
        if wc_gw and wc_gw <= gw_hi:
            after = squad_frame(solve_fn(board, all_must_play=False, bench_price_cap=None,
                                         opening_window=(wc_gw, gw_hi)))
            if after is None:
                logger.warning("compare_routes: post-WC squad infeasible for %s",
                               route["label"])
                continue
            total += _score_squad(after, wc_gw, gw_hi, fmap, ct, gws)

        rows.append({"label": route["label"], "bb_gw": bb_gw, "wc_gw": wc_gw,
                     "points": round(total, 1),
                     "vs_baseline": round(total - baseline, 1)})

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("vs_baseline", ascending=False).reset_index(drop=True)
