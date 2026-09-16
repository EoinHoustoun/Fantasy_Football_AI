"""Solve the opening draft headlessly, the same way the Draft page does.

Exists so a squad can be produced and inspected without a browser, and so the
numbers in a written answer come from the app's own solver rather than from a
second implementation that could quietly disagree with it.

It reproduces `views/18_draft_2026_27.py::_solve_opening_uncached`:
board → minutes gate and availability haircut → rescore on the wildcard window
→ weekly-lineup MILP with the Bench Boost week priced in.

    python3 scripts/solve_opening_draft.py                 # config defaults
    python3 scripts/solve_opening_draft.py --wildcard 4 --bench-boost 1
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("draft")


def club_fixtures() -> Dict:
    """(team_id, gw) -> [(opponent short, is_home, fdr), ...] · page parity."""
    from components.fixture_ticker import load_scout_ticker
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df

    bs = fetch_bootstrap()
    short = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    fx = get_fixtures_df(fetch_fixtures(), bs)
    scout_fdr = load_scout_ticker() or {}
    out: Dict = {}
    for _, r in fx.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        gw = int(r["gameweek"])
        h, a = int(r["home_team_id"]), int(r["away_team_id"])
        hs, as_ = short.get(h, "?"), short.get(a, "?")
        out.setdefault((h, gw), []).append(
            (as_, True, float(scout_fdr.get((hs, gw), r["home_fdr"]))))
        out.setdefault((a, gw), []).append(
            (hs, False, float(scout_fdr.get((as_, gw), r["away_fdr"]))))
    return out


def tuned_board(board: pd.DataFrame, pts_col: str, gate: float) -> pd.DataFrame:
    """Minutes gate + hand-entered availability haircut · page parity."""
    from config import OPENING_FIXTURES

    d = board.copy()
    if pts_col != "projected_points":
        d["projected_points"] = d[pts_col]

    if gate > 0 and "ffh_nailedness" in d.columns:
        share = pd.to_numeric(d.get("mins_share"), errors="coerce").clip(0, 1)
        nail = pd.to_numeric(d["ffh_nailedness"], errors="coerce")
        if "early_nailedness" in d.columns:
            hand = pd.to_numeric(d["early_nailedness"], errors="coerce")
            nail = hand.combine_first(nail)
        nail = nail.fillna(share).fillna(0.75)
        factor = (1.0 - gate) + gate * nail.clip(0.0, 1.0)
        for c in ("projected_points", "proj_lo"):
            if c in d.columns:
                d[c] = (d[c] * factor).round(1)

    try:
        from analytics.projection_overrides import load_overrides
        window = max(1, int(OPENING_FIXTURES.get("gw_hi", 6)))
        miss = {int(c): [int(g) for g in adj.get("miss_gws", [])]
                for c, adj in load_overrides().items() if adj.get("miss_gws")}
        if miss:
            hair = d["code"].astype(int).map(
                lambda c: 1.0 - min(1.0, len([g for g in miss.get(c, [])
                                              if g <= window]) / window))
            for c in ("projected_points", "proj_lo"):
                if c in d.columns:
                    d[c] = (d[c] * hair.fillna(1.0)).round(1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("availability haircut skipped: %s", exc)
    return d


def window_board(base: pd.DataFrame, proj, pts_col: str, lo: int, hi: int
                 ) -> pd.DataFrame:
    """Rescore every player on the window the squad is actually owned for."""
    d = base.copy()
    codes = [int(c) for c in d["code"]]
    run = proj.matrix(codes, list(range(int(lo), int(hi) + 1))).sum(axis=1)
    run = d["code"].astype(int).map(run).fillna(0.0).round(2)
    season = pd.to_numeric(d[pts_col], errors="coerce").replace(0, float("nan"))
    ratio = (run / season).astype(float).clip(0, 5).fillna(0.0)
    if "proj_lo" in d.columns:
        d["proj_lo"] = (pd.to_numeric(d["proj_lo"], errors="coerce") * ratio).round(2)
    d["projected_points"] = run
    d[pts_col] = run
    return d


def solve(spec: Dict) -> Optional[Dict]:
    """The opening fifteen for a draft spec · mirrors the page's solver."""
    from analytics import gw_projection, opening_plan as OPLAN, squad_rules as SR
    from analytics import freshness as _freshness
    from ui.value_board import build_board, solve_draft

    board, _scout, _bt, _val = build_board(_freshness.inputs_stamp())
    if board is None:
        raise SystemExit("archive not built · run scripts/build_archive.py")

    pts_col = ("consensus_points" if "consensus_points" in board.columns
               else "projected_points")

    bans = (SR.banned_price_names(board, spec.get("ban_price_bands") or (),
                                  exempt=spec.get("price_band_exempt") or ())
            + SR.below_floor_names(board, spec.get("min_price_by_position") or {}))
    if bans:
        spec = dict(spec)
        spec["vetoes"] = list(spec.get("vetoes", [])) + bans
        logger.warning("price-band ban rules out %d players: %s",
                       len(bans), ", ".join(bans[:6]) + ("…" if len(bans) > 6 else ""))
    fix = club_fixtures()
    proj = gw_projection.build(board, fix)

    b = tuned_board(board, pts_col, float(spec.get("minutes_gate", 0.5)))
    win = SR.plan_window(spec.get("wildcard_gw"))
    if win:
        b = window_board(b, proj, pts_col, win[0], win[1])

    strategy = spec.get("strategy") or "⚖️ Optimal value"
    cap = None if not spec.get("cap_attackers") else 1
    cover = tuple(tuple(c) for c in (spec.get("cover") or ()))

    # "No more than N from this club" · club SHORT codes resolved here so the
    # config stays season-proof (team ids are reassigned every summer).
    _ids = _club_ids()
    mfc = tuple((_ids[c], int(n)) for c, n in (spec.get("max_from_club") or ())
                if isinstance(c, str) and c in _ids) + \
          tuple((int(c), int(n)) for c, n in (spec.get("max_from_club") or ())
                if not isinstance(c, str))

    uncapped = tuple(int(t) for t in (spec.get("attack_cap_exempt") or ()))

    def _weekly(frame, gw_cols, boost_col):
        return solve_draft(frame, strategy, float(spec.get("budget", 100.0)),
                           float(spec.get("risk", 0.3)),
                           tuple(spec.get("vetoes", [])),
                           float(spec.get("opening", 0.35)),
                           force_names=tuple(spec.get("locks", [])),
                           max_attackers_per_club=cap, min_club_cover=cover,
                           max_from_club=mfc,
                           attack_cap_exempt=uncapped,
                           max_price_band=tuple(
                               tuple(b) for b in (spec.get("max_price_band") or ())),
                           max_defenders_per_club=spec.get("max_defenders_per_club", 1),
                           captain_must_take_pens=bool(spec.get("captain_must_take_pens")),
                           gw_pts_cols=gw_cols, boost_col=boost_col)

    bb = spec.get("bench_boost_gw")
    gws = list(range(win[0], win[1] + 1)) if win else []
    if not gws:
        raise SystemExit("no window · set a wildcard gameweek")

    out = OPLAN.solve_window(b, proj, gws, int(bb) if bb else None, _weekly)
    if out:
        out["_proj"], out["_gws"], out["_bb"] = proj, gws, bb
        out["_board"] = board
    return out


def _club_ids() -> Dict:
    from data.fetchers.fpl_api import fetch_bootstrap
    return {t["short_name"]: int(t["id"]) for t in fetch_bootstrap()["teams"]}


def _resolve_cover(cover) -> tuple:
    """Club SHORT codes in config resolved to live team ids, as the page does."""
    ids = _club_ids()
    out = []
    for club, side, n in cover or ():
        tid = ids.get(club)
        if tid is None:
            logger.warning("cover club %s not in this season · skipped", club)
            continue
        out.append((tid, side, int(n)))
    return tuple(out)


def _resolve_clubs(shorts) -> tuple:
    ids = _club_ids()
    return tuple(ids[c] for c in (shorts or ()) if c in ids)


def report(res: Dict) -> str:
    from analytics import opening_plan as OPLAN

    proj, gws, bb = res["_proj"], res["_gws"], res["_bb"]
    squad = res["squad"].copy()
    board = res["_board"]

    name_col = "uniq_name" if "uniq_name" in squad.columns else "web_name"
    per_week = OPLAN._per_week(squad, proj, gws, int(bb) if bb else None)

    lines: List[str] = []
    total = OPLAN.plan_total(squad, proj, gws, int(bb) if bb else None)
    lines.append("Opening fifteen · GW%d-%d, Bench Boost GW%s"
                 % (gws[0], gws[-1], bb))
    lines.append("cost £%.1fm of £%.1fm   ·   projected %.1f pts over the window"
                 % (squad["price"].sum(), 100.0, total))
    lines.append("")

    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    squad["_o"] = squad["position"].map(order).fillna(9)
    gw_cols = []
    for g in gws:
        col = "GW%d" % g
        squad[col] = squad["code"].astype(int).map(
            lambda c, g=g: round(proj.points(int(c), g), 2))
        gw_cols.append(col)
    squad["window"] = squad[gw_cols].sum(axis=1).round(2)

    show = [name_col, "position", "team_short", "price"] + gw_cols + ["window"]
    show = [c for c in show if c in squad.columns]
    lines.append(squad.sort_values(["_o", "window"], ascending=[True, False])[show]
                 .to_string(index=False))
    lines.append("")

    # `_per_week` reports the captain's POINTS, not his name · look the man up
    # so the week reads as a decision rather than a number.
    from analytics.gw_projection import best_xi
    name_of = dict(zip(squad["code"].astype(int), squad[name_col]))
    for w in per_week:
        g = int(w["gw"])
        xi = best_xi(squad, proj, g)
        cap = max(xi, key=lambda c: proj.points(c, g)) if xi else None
        benched = [name_of.get(int(c), "?") for c in squad["code"].astype(int)
                   if int(c) not in xi]
        lines.append("GW%-3s XI %5.1f   bench %5.1f   captain %-12s total %5.1f%s"
                     % (g, w.get("xi", 0.0), w.get("bench", 0.0),
                        name_of.get(int(cap), "?") if cap is not None else "-",
                        w.get("total", 0.0),
                        "   [BENCH BOOST · all 15 score]" if g == bb else ""))
        lines.append("        benched: %s" % ", ".join(benched))
    lines.append("")

    src = {}
    for c in squad["code"].astype(int):
        for g in gws:
            src[proj.source(int(c), g)] = src.get(proj.source(int(c), g), 0) + 1
    lines.append("projection sources across the fifteen: %s" % src)
    if "consensus_confidence" in board.columns:
        conf = (board[board["code"].isin(squad["code"])]["consensus_confidence"]
                .value_counts().to_dict())
        lines.append("consensus confidence: %s" % conf)
    return "\n".join(lines)


def main() -> None:
    from config import NEW_DRAFT_DEFAULTS

    ap = argparse.ArgumentParser()
    ap.add_argument("--wildcard", type=int, default=None)
    ap.add_argument("--bench-boost", type=int, default=None)
    ap.add_argument("--budget", type=float, default=100.0)
    ap.add_argument("--risk", type=float, default=0.3)
    ap.add_argument("--minutes-gate", type=float, default=0.5)
    ap.add_argument("--opening", type=float, default=0.35)
    ap.add_argument("--no-locks", action="store_true")
    ap.add_argument("--veto", nargs="*", default=None,
                    help="extra players to rule out, on top of the config list")
    ap.add_argument("--uncap-club", nargs="*", default=None,
                    help="club SHORT codes released from the one-attacker rule")
    ap.add_argument("--allow-price-bands", action="store_true",
                    help="ignore the banned position/price bands in config")
    ap.add_argument("--one-defender-per-club", action="store_true",
                    help="put the dropped one-defender-per-club cap back on, to "
                         "price what it costs")
    args = ap.parse_args()

    spec = dict(NEW_DRAFT_DEFAULTS)
    spec.update({"budget": args.budget, "risk": args.risk,
                 "minutes_gate": args.minutes_gate, "opening": args.opening})
    spec.setdefault("cap_attackers", False)
    if args.wildcard is not None:
        spec["wildcard_gw"] = args.wildcard
    if args.bench_boost is not None:
        spec["bench_boost_gw"] = args.bench_boost
    if args.no_locks:
        spec["locks"] = []
    if args.veto:
        spec["vetoes"] = list(spec.get("vetoes", [])) + list(args.veto)
    if args.uncap_club is not None:
        spec["attack_cap_exempt"] = tuple(args.uncap_club)
    if args.allow_price_bands:
        spec["ban_price_bands"] = ()
    if args.one_defender_per_club:
        spec["max_defenders_per_club"] = 1
    spec["cover"] = _resolve_cover(spec.get("cover"))
    spec["attack_cap_exempt"] = _resolve_clubs(spec.get("attack_cap_exempt"))

    res = solve(spec)
    if not res:
        raise SystemExit("no feasible squad for this spec")
    print("\n" + report(res) + "\n")


if __name__ == "__main__":
    main()
