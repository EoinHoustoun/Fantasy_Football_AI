"""First-half chip timing · Bench Boost, Triple Captain, Free Hit over GW1-19.

2026/27 hands out two of every chip and the first set must be used by GW19, so
this only scans the first half. It works off a fixed squad (a chosen draft) and
the released fixture list · no live gameweek data needed, which is the point in
preseason.

Per-GW player points = (season projection / 38) scaled by that week's fixture
ease. A blank gameweek scores 0, a double gameweek stacks both fixtures. That
makes the three chip signals fall out:

  - Bench Boost · the GW your four bench players score most (easy fixtures / a
    double). GW1 is always shown too · it needs no transfer or wildcard prep.
  - Triple Captain · the GW your best XI player has the softest fixture.
  - Free Hit · the GW your squad is weakest (bad fixtures or blanks) · the week a
    one-off pivot gains the most.

All approximate and fixture-driven · flagged as such · because doubles and blanks
are rarely confirmed this early.
"""
from typing import Dict, List, Optional

import pandas as pd

from config import CHIP_TIMING


def _factor(fdr: float, cfg: Dict) -> float:
    """Fixture-ease multiplier · >1 for easy (FDR<3), <1 for hard."""
    return max(cfg["factor_floor"], 1.0 + (3.0 - float(fdr)) * cfg["fdr_slope"])


def _fixtures_by_team_gw(fixtures: pd.DataFrame) -> Dict:
    """(team_id, gw) -> list of that team's FDRs that GW (0, 1 or 2 entries)."""
    out: Dict = {}
    for _, r in fixtures.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        gw = int(r["gameweek"])
        out.setdefault((int(r["home_team_id"]), gw), []).append(float(r["home_fdr"]))
        out.setdefault((int(r["away_team_id"]), gw), []).append(float(r["away_fdr"]))
    return out


def _player_gw_points(proj: float, team_id: int, gw: int, fmap: Dict, cfg: Dict) -> float:
    base = proj / 38.0
    return sum(base * _factor(f, cfg) for f in fmap.get((team_id, gw), []))


def chip_windows(squad: pd.DataFrame, fixtures: pd.DataFrame,
                 gw_lo: int = 1, gw_hi: Optional[int] = None,
                 cfg: Optional[Dict] = None, proj=None) -> Dict[str, List[Dict]]:
    """Rank GW1-19 for each first-half chip.

    `squad` needs columns: web_name, team_id, pts (season projection), in_xi.
    Returns {bench_boost, triple_captain, free_hit} · each a list of per-GW dicts
    sorted best-first for that chip.

    **Pass `proj`.** A `GwProjection` gives the same per-fixture numbers every
    other surface uses, so this page and the Draft page cannot disagree about the
    same squad. Without it the fallback spreads a season projection over 38 and
    scales it by fixture difficulty, which is a fixture SHAPE rather than a
    forecast: blind to a player on 15 minutes after a tournament, and wrong for
    anyone whose scoring is lumpy. The fallback stays only because other callers
    have no projector to hand.
    """
    cfg = cfg or CHIP_TIMING
    gw_hi = gw_hi or cfg["first_batch_gw_hi"]
    fmap = _fixtures_by_team_gw(fixtures)

    bb: List[Dict] = []
    tc: List[Dict] = []
    fh: List[Dict] = []
    for gw in range(gw_lo, gw_hi + 1):
        bench_pts = 0.0
        squad_pts = 0.0
        best_cap = ("", 0.0)
        blanks = 0
        for _, p in squad.iterrows():
            fdrs = fmap.get((int(p["team_id"]), gw), [])
            if not fdrs:
                blanks += 1
            if proj is not None and "code" in squad.columns:
                pts = float(proj.points(int(p["code"]), gw))
            else:
                pts = _player_gw_points(float(p["pts"]), int(p["team_id"]), gw, fmap, cfg)
            squad_pts += pts
            if bool(p.get("in_xi", True)):
                if pts > best_cap[1]:
                    best_cap = (str(p["web_name"]), pts)
            else:
                bench_pts += pts
        # Which model produced this week · the Chip Planner levels on it, and
        # the page labels it, because a real forecast and a fixture shape are
        # not the same kind of number.
        src = "shape"
        if proj is not None and hasattr(proj, "source") and "code" in squad.columns:
            srcs = [proj.source(int(c), gw) for c in squad["code"]]
            src = "match" if srcs and all(x == "match" for x in srcs) else (
                "mixed" if any(x == "match" for x in srcs) else "shape")
        bb.append({"gw": gw, "bench_pts": round(bench_pts, 1), "source": src})
        tc.append({"gw": gw, "captain": best_cap[0],
                   "extra_pts": round(best_cap[1], 1), "source": src})
        fh.append({"gw": gw, "squad_pts": round(squad_pts, 1),
                   "blanks": blanks, "source": src})

    return {
        "bench_boost": sorted(bb, key=lambda x: -x["bench_pts"]),
        "triple_captain": sorted(tc, key=lambda x: -x["extra_pts"]),
        "free_hit": sorted(fh, key=lambda x: (x["squad_pts"], -x["blanks"])),
    }


def level_by_source(rows: List[Dict], key: str = "squad_pts",
                    anchor: str = "match") -> List[Dict]:
    """Put weeks from different models on one scale before they compete.

    Measured on the real board: GW1-6 come entirely from the Hub's per-fixture
    forecasts and total 56-59 points for a squad, while GW7-19 come from the
    fixture-shape fallback and total 68-75. A 23% step at exactly the source
    boundary, and it is an artefact of two models, not a fact about football.

    Left alone it decides every chip. Anything wanting a low week lands in
    GW1-6, anything wanting a high week lands in GW7-19, whatever the fixtures
    say. Same trap as ranking players on a raw gap between models when one runs
    hot · the offset gets read as signal.

    So each region is shifted onto the anchor region's mean. Differences WITHIN
    a region are untouched, because that is the real fixture signal; only the
    step between them goes. The match region anchors because it is a genuine
    forecast and the shape is the approximation.
    """
    if not rows:
        return rows
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(str(r.get("source", anchor)), []).append(r)
    if len(groups) < 2 or anchor not in groups:
        return rows

    def _mean(rs):
        vals = [float(r.get(key) or 0.0) for r in rs]
        return sum(vals) / len(vals) if vals else 0.0

    base = _mean(groups[anchor])
    out = []
    for src, rs in groups.items():
        m = _mean(rs)
        # A region averaging zero carries no level to correct, and dividing by
        # it would produce NaN across the whole page.
        shift = (base - m) if (src != anchor and m) else 0.0
        for r in rs:
            q = dict(r)
            q[key] = round(float(r.get(key) or 0.0) + shift, 1)
            out.append(q)
    return sorted(out, key=lambda r: r["gw"])
