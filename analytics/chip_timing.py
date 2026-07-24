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
                 cfg: Optional[Dict] = None) -> Dict[str, List[Dict]]:
    """Rank GW1-19 for each first-half chip.

    `squad` needs columns: web_name, team_id, pts (season projection), in_xi.
    Returns {bench_boost, triple_captain, free_hit} · each a list of per-GW dicts
    sorted best-first for that chip.
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
            pts = _player_gw_points(float(p["pts"]), int(p["team_id"]), gw, fmap, cfg)
            squad_pts += pts
            if bool(p.get("in_xi", True)):
                if pts > best_cap[1]:
                    best_cap = (str(p["web_name"]), pts)
            else:
                bench_pts += pts
        bb.append({"gw": gw, "bench_pts": round(bench_pts, 1)})
        tc.append({"gw": gw, "captain": best_cap[0], "extra_pts": round(best_cap[1], 1)})
        fh.append({"gw": gw, "squad_pts": round(squad_pts, 1), "blanks": blanks})

    return {
        "bench_boost": sorted(bb, key=lambda x: -x["bench_pts"]),
        "triple_captain": sorted(tc, key=lambda x: -x["extra_pts"]),
        "free_hit": sorted(fh, key=lambda x: (x["squad_pts"], -x["blanks"])),
    }
