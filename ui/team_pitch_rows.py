"""Row builders for My Team's forward-week pitch and candidate table.

Functions of their arguments, so the shapes the pitch and `ff_table` expect are
unit-tested without a Streamlit runtime. Not Streamlit-free: `live_projection`
is imported for `fixtures_for`, which pulls Streamlit in transitively. Nothing
here reads `session_state` or writes to the page, which is the property the
tests rely on.

Mirrors the Draft's `planner()` dicts and `_pool_rows`, so the two pages cannot
drift apart on what a shirt or a candidate row carries.

Every numeric read goes through `_num` / `_ident` rather than
`float(x or 0)`: a squad code the board has no row for arrives as NaN, and
`float('nan') or 0` is NaN, not 0 (NaN is truthy). That is the whole class of
"the pitch renders but the numbers are nan" bug this module exists to stop.
"""
from typing import Callable, Dict, List, Optional

import pandas as pd

from ui import live_projection as LP

# FPL allows at most three players from one club. Hard-coded rather than shared
# because the rule is a competition constant, not a tuning dial · the MILP's
# `max_from_club` is a different thing (a per-club override you choose).
MAX_FROM_CLUB = 3


def _num(value, default: float = 0.0) -> float:
    """A float, with NaN and None both meaning "not known"."""
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _ident(value, default: int = 1) -> int:
    """An int id, NaN-safe (see the module docstring)."""
    return int(_num(value, default) or default)


def _text(value, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return str(value)


def pitch_rows(sq: pd.DataFrame, gw: int, proj, fix: Dict, xi: set,
               captain: Optional[int], axed: List[int], sub_from: Optional[int],
               swap_targets: set) -> List[Dict]:
    """One dict per shirt for `components.pitch_view.render_squad_pitch`.

    `fpl_id` carries the stable `code`, not the season-local FPL id, because
    that is the value `pitch_click` reports back as `id` and every caller here
    speaks codes. Exactly what the Draft does.
    """
    players = []
    for _, r in sq.iterrows():
        code = int(r["code"])
        players.append({
            "web_name": _text(r.get("web_name"), "Unknown"),
            "position": _text(r.get("position"), "MID"),
            "team_code": _ident(r.get("team_code"), 1),
            "team_short": r.get("team_short"),
            "on_bench": code not in xi,
            "is_captain": code == captain,
            "price": _num(r.get("actual_price")),
            "fixtures": LP.fixtures_for(_ident(r.get("team_id"), 0), gw, 3, fix=fix),
            "fpl_id": code,
            "stat": round(_num(proj.points(code, gw)), 1), "stat_dp": 1,
            "exp_mins": proj.expected_minutes(code, gw),
            "penalties_order": r.get("pens_order"),
            "is_axed": code in axed, "allow_axe": True, "allow_bench": True,
            "is_sub_source": sub_from == code,
            "swap_ok": code in swap_targets,
        })
    return players


def candidate_rows(pool: pd.DataFrame, gw: int, proj, fix: Dict,
                   out_row: Optional[pd.Series], pts_col: str,
                   dc_hit_fn: Callable, glyph_fn: Callable) -> List[Dict]:
    """One dict per replacement candidate for `components.ff_table.render`."""
    rows = []
    out_price = _num(out_row.get("actual_price")) if out_row is not None else 0.0
    for _, a in pool.iterrows():
        code = int(a["code"])
        price = _num(a.get("actual_price"))
        season = _num(a.get(pts_col))
        spread = a.get("model_spread")
        rows.append({
            "code": code, "web_name": _text(a.get("web_name"), "Unknown"),
            "team_short": _text(a.get("team_short")),
            "position": _text(a.get("position"), "MID"),
            "actual_price": price,
            "d_price": round(price - out_price, 1) if out_row is not None else 0.0,
            "run": LP.fixtures_for(_ident(a.get("team_id"), 0), gw, 3, fix=fix),
            "gw_pts": proj.points(code, gw),
            "mins": proj.expected_minutes(code, gw),
            "season": season,
            "per_m": season / price if price else 0.0,
            "confidence": a.get("consensus_confidence", a.get("confidence", "")),
            # How far the three models are apart, where the decision is made.
            "spread": round(_num(spread) * 100, 0) if pd.notna(spread) else None,
            # DEFCON pays at a THRESHOLD, so the hit rate is what converts.
            "dc_hit": dc_hit_fn(code, _text(a.get("position"), "MID")),
            "setp": glyph_fn(a),
        })
    return rows


def eligible_pool(board: pd.DataFrame, codes_now: List[int], axed: List[int],
                  position: str, budget: float) -> pd.DataFrame:
    """Replacements you could actually sign · position, budget and the club cap.

    The 3-per-club rule is counted against the squad you will have AFTER the
    marked players are sold, not the one on the pitch, so selling a Man City
    player to buy another Man City player is allowed while a fourth from an
    untouched club is not. Filtering here rather than validating after the click
    is what lets the table show only legal moves, which is how the interface
    teaches the rule instead of enforcing it after the fact.
    """
    owned = {int(c) for c in codes_now}
    outs = {int(c) for c in axed}
    club_of = dict(zip(board["code"].astype(int), board["team_id"]))
    clubs = {}
    for c in owned - outs:
        tid = club_of.get(int(c))
        if tid is None or not pd.notna(tid):
            continue
        clubs[int(tid)] = clubs.get(int(tid), 0) + 1
    price = pd.to_numeric(board["actual_price"], errors="coerce")
    pool = board[(board["position"] == position)
                 & (~board["code"].astype(int).isin(owned))
                 & (price <= float(budget))].copy()
    if pool.empty:
        return pool
    taken = pool["team_id"].map(
        lambda t: clubs.get(int(t), 0) if pd.notna(t) else 0)
    return pool[taken < MAX_FROM_CLUB]
