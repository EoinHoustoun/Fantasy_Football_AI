"""
Perfect Season engine · hindsight-optimal FPL season via multi-period MILP.

Given actual per-GW points and prices (from the archive), computes:
  1. set-and-forget   · best fixed 15 bought at GW1, weekly best XI + captain
  2. perfect season   · transfers each week (FT banking up to 5, -4 hits),
                        Wildcard / Triple Captain / Bench Boost in-model
                        (2025-26 rules: one full chip set per half-season)
  3. Free Hit         · layered post-hoc per half (separable: FH reverts)

Modelling conventions (footnoted in the UI):
  - buy price = sell price = actual per-GW value (real sell rule needs
    purchase-price state; bias is a few points generous)
  - no vice-captain / autosubs · with hindsight the chosen XI and captain
    are already optimal
  - DGW points pre-aggregated per (player, GW); captain doubles the GW

Run offline via scripts/run_perfect_season.py → JSON in data/cache/.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pulp

from config import CACHE_DIR, PERFECT_SEASON

logger = logging.getLogger(__name__)

RESULT_PATH_TMPL = str(CACHE_DIR / "perfect_season_{season}.json")


# ── Pool pruning ──────────────────────────────────────────────────────────────

def prune_pool(opt: pd.DataFrame, cfg: Dict = PERFECT_SEASON) -> pd.DataFrame:
    """
    Reduce ~840 players to the ~160 the optimum could plausibly touch:
    top-N by season points per position ∪ top by pts/£m ∪ cheapest enablers.
    Returns per-player frame: code, web_name, position, season_points, min_price.
    """
    per_player = (opt.groupby("code")
                  .agg(season_points=("points", "sum"),
                       min_price=("price", "min"),
                       start_price=("price", "first"),
                       web_name=("web_name", "last"),
                       player_name=("player_name", "last"),
                       position=("position", "last"))
                  .reset_index())
    per_player["ppm"] = per_player["season_points"] / per_player["start_price"]

    keep = set()
    for pos, n in cfg["pool_top_by_points"].items():
        grp = per_player[per_player["position"] == pos]
        keep |= set(grp.nlargest(n, "season_points")["code"])
        keep |= set(grp.nlargest(cfg["pool_top_by_value"], "ppm")["code"])
        keep |= set(grp.nsmallest(cfg["pool_cheapest"], "min_price")["code"])

    pool = per_player[per_player["code"].isin(keep)].reset_index(drop=True)
    logger.info(f"Pool pruned: {len(per_player)} → {len(pool)} players "
                f"({pool.groupby('position').size().to_dict()})")
    return pool


def _matrices(opt: pd.DataFrame, pool: pd.DataFrame) -> Dict:
    """Dense (player × GW) matrices for the MILP. Index = pool order."""
    codes = pool["code"].tolist()
    T = int(opt["gw"].max())
    sub = opt[opt["code"].isin(codes)]

    pts = sub.pivot(index="code", columns="gw", values="points").reindex(codes)
    price = sub.pivot(index="code", columns="gw", values="price").reindex(codes)
    team = sub.pivot(index="code", columns="gw", values="team_id").reindex(codes)

    pts = pts.reindex(columns=range(1, T + 1))
    price = price.reindex(columns=range(1, T + 1))
    team = team.reindex(columns=range(1, T + 1))

    avail = price.notna()
    # backfill price/team so unavailable cells hold harmless values
    price = price.bfill(axis=1).ffill(axis=1)
    team = team.bfill(axis=1).ffill(axis=1)
    pts = pts.fillna(0)

    return {
        "codes": codes, "T": T,
        "pts": pts.values, "price": price.values,
        "team": team.values, "avail": avail.values,
    }


# ── Set-and-forget MILP ───────────────────────────────────────────────────────

def solve_set_and_forget(opt: pd.DataFrame, pool: pd.DataFrame,
                         cfg: Dict = PERFECT_SEASON,
                         time_limit: int = 300) -> Optional[Dict]:
    """Best fixed 15 bought at GW1 prices; weekly best XI + captain."""
    m = _matrices(opt, pool)
    P, T = len(m["codes"]), m["T"]
    # only players priced (in the game) at GW1
    gw1_ok = [p for p in range(P) if m["avail"][p][0]]
    limits, lineup_min = cfg["squad_limits"], cfg["lineup_min"]
    positions = pool["position"].tolist()

    prob = pulp.LpProblem("set_and_forget", pulp.LpMaximize)
    sq = pulp.LpVariable.dicts("sq", gw1_ok, cat="Binary")
    xi = pulp.LpVariable.dicts("xi", [(p, t) for p in gw1_ok for t in range(T)], cat="Binary")
    cp = pulp.LpVariable.dicts("cp", [(p, t) for p in gw1_ok for t in range(T)], cat="Binary")

    prob += pulp.lpSum(m["pts"][p][t] * (xi[(p, t)] + cp[(p, t)])
                       for p in gw1_ok for t in range(T))

    prob += pulp.lpSum(sq[p] for p in gw1_ok) == 15
    prob += pulp.lpSum(m["price"][p][0] * sq[p] for p in gw1_ok) <= cfg["budget"]
    for pos, n in limits.items():
        prob += pulp.lpSum(sq[p] for p in gw1_ok if positions[p] == pos) == n
    for club in set(m["team"][p][0] for p in gw1_ok):
        prob += pulp.lpSum(sq[p] for p in gw1_ok if m["team"][p][0] == club) \
                <= cfg["max_per_club"]

    for t in range(T):
        prob += pulp.lpSum(xi[(p, t)] for p in gw1_ok) == 11
        prob += pulp.lpSum(cp[(p, t)] for p in gw1_ok) == 1
        for pos, lo in lineup_min.items():
            expr = pulp.lpSum(xi[(p, t)] for p in gw1_ok if positions[p] == pos)
            prob += expr >= lo
            if pos == "GKP":
                prob += expr == 1
        for p in gw1_ok:
            prob += xi[(p, t)] <= sq[p]
            prob += cp[(p, t)] <= xi[(p, t)]

    t0 = time.time()
    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit, gapRel=0.001))
    elapsed = time.time() - t0

    squad_idx = [p for p in gw1_ok if sq[p].value() and sq[p].value() > 0.5]
    if len(squad_idx) != 15:
        logger.error("set-and-forget infeasible")
        return None

    per_gw = []
    for t in range(T):
        starters = [p for p in squad_idx if xi[(p, t)].value() > 0.5]
        cap_p = next(p for p in starters if cp[(p, t)].value() > 0.5)
        gw_pts = sum(m["pts"][p][t] for p in starters) + m["pts"][cap_p][t]
        per_gw.append({"gw": t + 1,
                       "xi": [m["codes"][p] for p in starters],
                       "captain": m["codes"][cap_p],
                       "points": float(gw_pts)})

    total = sum(g["points"] for g in per_gw)
    logger.info(f"Set-and-forget: {total:.0f} pts "
                f"({pulp.LpStatus[status]}, {elapsed:.0f}s)")
    return {
        "squad_codes": [m["codes"][p] for p in squad_idx],
        "squad_cost": round(float(sum(m["price"][p][0] for p in squad_idx)), 1),
        "per_gw": per_gw,
        "total_points": float(total),
        "solver_status": pulp.LpStatus[status],
        "solve_seconds": round(elapsed, 1),
        "_squad_idx": squad_idx,          # internal, for warm start
        "_xi": {(p, t): xi[(p, t)].value() for p in squad_idx for t in range(T)},
        "_cp": {(p, t): cp[(p, t)].value() for p in squad_idx for t in range(T)},
    }


# ── Full multi-period MILP ────────────────────────────────────────────────────

def solve_perfect_season(opt: pd.DataFrame, pool: pd.DataFrame,
                         cfg: Dict = PERFECT_SEASON,
                         warm: Optional[Dict] = None,
                         time_limit: Optional[int] = None,
                         gap: Optional[float] = None,
                         max_hits_per_gw: Optional[int] = None,
                         max_hits_total: Optional[int] = None) -> Optional[Dict]:
    """
    Hindsight-optimal season with weekly transfers, FT banking, hits,
    and WC/TC/BB chips (one per half). Returns the full per-GW ledger.

    max_hits_per_gw / max_hits_total cap PAID transfers (each = -4) for
    realistic "don't take big hits" scenarios. None = unlimited.
    """
    m = _matrices(opt, pool)
    P, T = len(m["codes"]), m["T"]
    limits, lineup_min = cfg["squad_limits"], cfg["lineup_min"]
    positions = pool["position"].tolist()
    PT = [(p, t) for p in range(P) for t in range(T)]

    prob = pulp.LpProblem("perfect_season", pulp.LpMaximize)
    sq = pulp.LpVariable.dicts("sq", PT, cat="Binary")
    xi = pulp.LpVariable.dicts("xi", PT, cat="Binary")
    cp = pulp.LpVariable.dicts("cp", PT, cat="Binary")
    buy = pulp.LpVariable.dicts("buy", [(p, t) for p in range(P) for t in range(1, T)], cat="Binary")
    sell = pulp.LpVariable.dicts("sell", [(p, t) for p in range(P) for t in range(1, T)], cat="Binary")
    tcap = pulp.LpVariable.dicts("tcap", PT, cat="Binary")
    bbp = pulp.LpVariable.dicts("bbp", PT, cat="Binary")

    wc = pulp.LpVariable.dicts("wc", range(T), cat="Binary")
    tc = pulp.LpVariable.dicts("tc", range(T), cat="Binary")
    bb = pulp.LpVariable.dicts("bb", range(T), cat="Binary")

    ft = pulp.LpVariable.dicts("ft", range(1, T), lowBound=0,
                               upBound=cfg["max_banked_ft"], cat="Integer")
    ftu = pulp.LpVariable.dicts("ftu", range(1, T), lowBound=0,
                                upBound=cfg["max_banked_ft"], cat="Integer")
    paid = pulp.LpVariable.dicts("paid", range(1, T), lowBound=0, cat="Integer")
    bank = pulp.LpVariable.dicts("bank", range(T), lowBound=0)

    # objective
    prob += (pulp.lpSum(m["pts"][p][t] * (xi[(p, t)] + cp[(p, t)] + tcap[(p, t)] + bbp[(p, t)])
                        for p, t in PT)
             - cfg["hit_cost"] * pulp.lpSum(paid[t] for t in range(1, T)))

    for t in range(T):
        prob += pulp.lpSum(sq[(p, t)] for p in range(P)) == 15
        prob += pulp.lpSum(xi[(p, t)] for p in range(P)) == 11
        prob += pulp.lpSum(cp[(p, t)] for p in range(P)) == 1
        for pos, n in limits.items():
            prob += pulp.lpSum(sq[(p, t)] for p in range(P) if positions[p] == pos) == n
        for pos, lo in lineup_min.items():
            expr = pulp.lpSum(xi[(p, t)] for p in range(P) if positions[p] == pos)
            prob += expr >= lo
            if pos == "GKP":
                prob += expr == 1
        # 3-per-club with per-GW team (handles mid-season movers)
        clubs = set(m["team"][p][t] for p in range(P))
        for club in clubs:
            prob += pulp.lpSum(sq[(p, t)] for p in range(P)
                               if m["team"][p][t] == club) <= cfg["max_per_club"]
        for p in range(P):
            prob += xi[(p, t)] <= sq[(p, t)]
            prob += cp[(p, t)] <= xi[(p, t)]
            prob += tcap[(p, t)] <= cp[(p, t)]
            prob += tcap[(p, t)] <= tc[t]
            prob += bbp[(p, t)] <= sq[(p, t)] - xi[(p, t)]
            prob += bbp[(p, t)] <= bb[t]
            if not m["avail"][p][t]:
                prob += sq[(p, t)] == 0

    # transfers + money flow (buy price = sell price = actual GW value)
    prob += bank[0] == cfg["budget"] - pulp.lpSum(
        m["price"][p][0] * sq[(p, 0)] for p in range(P))
    for t in range(1, T):
        for p in range(P):
            # exact coupling · prevents phantom sells leaking money
            prob += sq[(p, t)] == sq[(p, t - 1)] + buy[(p, t)] - sell[(p, t)]
            prob += buy[(p, t)] + sell[(p, t)] <= 1
        prob += bank[t] == bank[t - 1] \
            + pulp.lpSum(m["price"][p][t] * sell[(p, t)] for p in range(P)) \
            - pulp.lpSum(m["price"][p][t] * buy[(p, t)] for p in range(P))

        n_t = pulp.lpSum(buy[(p, t)] for p in range(P))
        prob += n_t <= ftu[t] + paid[t] + 15 * wc[t]
        prob += ftu[t] <= ft[t]
        if max_hits_per_gw is not None:
            prob += paid[t] <= max_hits_per_gw
    if max_hits_total is not None:
        prob += pulp.lpSum(paid[t] for t in range(1, T)) <= max_hits_total
    # FT banking: 1 FT arrives at GW2; +1 per week, cap at max_banked_ft
    prob += ft[1] == 1
    for t in range(1, T - 1):
        prob += ft[t + 1] <= ft[t] - ftu[t] + 1

    # chips: one WC/TC/BB per half, ≤1 chip per GW (FH layered post-hoc)
    for lo, hi in cfg["chip_halves"]:
        ts = [t for t in range(T) if lo <= t + 1 <= hi]
        prob += pulp.lpSum(wc[t] for t in ts) <= 1
        prob += pulp.lpSum(tc[t] for t in ts) <= 1
        prob += pulp.lpSum(bb[t] for t in ts) <= 1
    for t in range(T):
        prob += wc[t] + tc[t] + bb[t] <= 1
    prob += wc[0] == 0   # no wildcard at GW1 (initial squad is free)

    # warm start from set-and-forget
    if warm is not None:
        squad_idx = set(warm["_squad_idx"])
        for p, t in PT:
            sq[(p, t)].setInitialValue(1 if p in squad_idx else 0)
            xi[(p, t)].setInitialValue(int(warm["_xi"].get((p, t), 0) or 0))
            cp[(p, t)].setInitialValue(int(warm["_cp"].get((p, t), 0) or 0))
            tcap[(p, t)].setInitialValue(0)
            bbp[(p, t)].setInitialValue(0)
        for t in range(T):
            wc[t].setInitialValue(0)
            tc[t].setInitialValue(0)
            bb[t].setInitialValue(0)
        for t in range(1, T):
            for p in range(P):
                buy[(p, t)].setInitialValue(0)
                sell[(p, t)].setInitialValue(0)

    t0 = time.time()
    solver = pulp.PULP_CBC_CMD(
        msg=1,
        timeLimit=time_limit or cfg["solver_time_limit"],
        gapRel=gap if gap is not None else cfg["solver_gap"],
        warmStart=warm is not None,
    )
    status = prob.solve(solver)
    elapsed = time.time() - t0
    logger.info(f"Perfect season MILP: {pulp.LpStatus[status]} in {elapsed:.0f}s, "
                f"objective {pulp.value(prob.objective):.0f}")

    if pulp.value(prob.objective) is None:
        return None

    # ── extract ledger ──
    def _on(v):
        return v.value() is not None and v.value() > 0.5

    per_gw = []
    for t in range(T):
        squad_t = [p for p in range(P) if _on(sq[(p, t)])]
        xi_t = [p for p in squad_t if _on(xi[(p, t)])]
        cap_p = next(p for p in xi_t if _on(cp[(p, t)]))
        chips = []
        if _on(wc[t]):
            chips.append("WC")
        if _on(tc[t]):
            chips.append("TC")
        if _on(bb[t]):
            chips.append("BB")
        gw_pts = sum(m["pts"][p][t] for p in xi_t) + m["pts"][cap_p][t]
        if "TC" in chips:
            gw_pts += m["pts"][cap_p][t]
        if "BB" in chips:
            gw_pts += sum(m["pts"][p][t] for p in squad_t if p not in xi_t)
        hit_cost = cfg["hit_cost"] * int(paid[t].value() or 0) if t >= 1 else 0
        per_gw.append({
            "gw": t + 1,
            "squad": [m["codes"][p] for p in squad_t],
            "xi": [m["codes"][p] for p in xi_t],
            "captain": m["codes"][cap_p],
            "chips": chips,
            "transfers_in": [m["codes"][p] for p in range(P)
                             if t >= 1 and _on(buy[(p, t)])],
            "transfers_out": [m["codes"][p] for p in range(P)
                              if t >= 1 and _on(sell[(p, t)])],
            "hit_cost": hit_cost,
            "bank": round(float(bank[t].value() or 0), 1),
            "squad_value": round(float(sum(m["price"][p][t] for p in squad_t)), 1),
            "gw_points": float(gw_pts),
            "net_points": float(gw_pts) - hit_cost,
        })

    total = sum(g["net_points"] for g in per_gw)
    return {
        "per_gw": per_gw,
        "total_points": float(total),
        "total_hits": int(sum(g["hit_cost"] for g in per_gw) // cfg["hit_cost"]),
        "solver_status": pulp.LpStatus[status],
        "solve_seconds": round(elapsed, 1),
        "objective": float(pulp.value(prob.objective)),
    }


# ── Rolling-horizon solver ────────────────────────────────────────────────────

def solve_rolling_horizon(opt: pd.DataFrame, pool: pd.DataFrame,
                          cfg: Dict = PERFECT_SEASON,
                          max_hits_per_gw: Optional[int] = None,
                          max_hits_total: Optional[int] = None,
                          window: int = 10, commit: int = 4,
                          window_time: int = 240) -> Optional[Dict]:
    """
    Same model as solve_perfect_season but solved over sliding windows
    (solve `window` GWs, commit the first `commit`, slide). Each window is
    small enough for CBC to truly optimize, which matters under hard hit
    caps where the monolithic solve can't escape its warm start.
    State (squad, bank, banked FTs, chips used, hit budget) carries across
    windows. Empirically lands within a few % of the full solve.
    """
    m = _matrices(opt, pool)
    P, T = len(m["codes"]), m["T"]
    limits, lineup_min = cfg["squad_limits"], cfg["lineup_min"]
    positions = pool["position"].tolist()

    state = {"squad": None, "bank": 0.0, "ft": 1, "chips_used": set()}
    hits_left = max_hits_total
    ledger: List[Dict] = []
    t0 = 0
    total_start = time.time()

    while t0 < T:
        t1 = min(t0 + window, T)
        ts = list(range(t0, t1))
        PT_w = [(p, t) for p in range(P) for t in ts]

        prob = pulp.LpProblem(f"window_{t0}", pulp.LpMaximize)
        sq = pulp.LpVariable.dicts("sq", PT_w, cat="Binary")
        xi = pulp.LpVariable.dicts("xi", PT_w, cat="Binary")
        cp = pulp.LpVariable.dicts("cp", PT_w, cat="Binary")
        tcap = pulp.LpVariable.dicts("tcap", PT_w, cat="Binary")
        bbp = pulp.LpVariable.dicts("bbp", PT_w, cat="Binary")
        wc = pulp.LpVariable.dicts("wc", ts, cat="Binary")
        tc = pulp.LpVariable.dicts("tc", ts, cat="Binary")
        bb = pulp.LpVariable.dicts("bb", ts, cat="Binary")

        trans_ts = ts if t0 > 0 else ts[1:]
        buy = pulp.LpVariable.dicts("buy", [(p, t) for p in range(P) for t in trans_ts], cat="Binary")
        sell = pulp.LpVariable.dicts("sell", [(p, t) for p in range(P) for t in trans_ts], cat="Binary")
        ft = pulp.LpVariable.dicts("ft", trans_ts, lowBound=0,
                                   upBound=cfg["max_banked_ft"], cat="Integer")
        ftu = pulp.LpVariable.dicts("ftu", trans_ts, lowBound=0,
                                    upBound=cfg["max_banked_ft"], cat="Integer")
        paid = pulp.LpVariable.dicts("paid", trans_ts, lowBound=0, cat="Integer")
        bank = pulp.LpVariable.dicts("bank", ts, lowBound=0)

        # tiny FT-burn penalty so the solver doesn't waste banked transfers
        prob += (pulp.lpSum(m["pts"][p][t] * (xi[(p, t)] + cp[(p, t)] + tcap[(p, t)] + bbp[(p, t)])
                            for p, t in PT_w)
                 - cfg["hit_cost"] * pulp.lpSum(paid[t] for t in trans_ts)
                 - 0.001 * pulp.lpSum(ftu[t] for t in trans_ts))

        for t in ts:
            prob += pulp.lpSum(sq[(p, t)] for p in range(P)) == 15
            prob += pulp.lpSum(xi[(p, t)] for p in range(P)) == 11
            prob += pulp.lpSum(cp[(p, t)] for p in range(P)) == 1
            for pos, n in limits.items():
                prob += pulp.lpSum(sq[(p, t)] for p in range(P) if positions[p] == pos) == n
            for pos, lo in lineup_min.items():
                expr = pulp.lpSum(xi[(p, t)] for p in range(P) if positions[p] == pos)
                prob += expr >= lo
                if pos == "GKP":
                    prob += expr == 1
            for club in set(m["team"][p][t] for p in range(P)):
                prob += pulp.lpSum(sq[(p, t)] for p in range(P)
                                   if m["team"][p][t] == club) <= cfg["max_per_club"]
            for p in range(P):
                prob += xi[(p, t)] <= sq[(p, t)]
                prob += cp[(p, t)] <= xi[(p, t)]
                prob += tcap[(p, t)] <= cp[(p, t)]
                prob += tcap[(p, t)] <= tc[t]
                prob += bbp[(p, t)] <= sq[(p, t)] - xi[(p, t)]
                prob += bbp[(p, t)] <= bb[t]
                if not m["avail"][p][t]:
                    prob += sq[(p, t)] == 0

        # transfers + money
        if t0 == 0:
            prob += bank[0] == cfg["budget"] - pulp.lpSum(
                m["price"][p][0] * sq[(p, 0)] for p in range(P))
        for t in trans_ts:
            prev = (lambda p, t=t: sq[(p, t - 1)]) if t > t0 else \
                   (lambda p: 1 if p in state["squad"] else 0)
            for p in range(P):
                prob += sq[(p, t)] == prev(p) + buy[(p, t)] - sell[(p, t)]
                prob += buy[(p, t)] + sell[(p, t)] <= 1
            prev_bank = bank[t - 1] if t > t0 else state["bank"]
            prob += bank[t] == prev_bank \
                + pulp.lpSum(m["price"][p][t] * sell[(p, t)] for p in range(P)) \
                - pulp.lpSum(m["price"][p][t] * buy[(p, t)] for p in range(P))
            n_t = pulp.lpSum(buy[(p, t)] for p in range(P))
            prob += n_t <= ftu[t] + paid[t] + 15 * wc[t]
            prob += ftu[t] <= ft[t]
            if max_hits_per_gw is not None:
                prob += paid[t] <= max_hits_per_gw
        if hits_left is not None:
            prob += pulp.lpSum(paid[t] for t in trans_ts) <= hits_left
        if trans_ts:
            prob += ft[trans_ts[0]] == state["ft"]
            for a, b in zip(trans_ts[:-1], trans_ts[1:]):
                prob += ft[b] <= ft[a] - ftu[a] + 1

        # chips: respect halves and what's already burned
        for kind, var in (("wc", wc), ("tc", tc), ("bb", bb)):
            for half_i, (lo, hi) in enumerate(cfg["chip_halves"], start=1):
                in_half = [t for t in ts if lo <= t + 1 <= hi]
                cap_n = 0 if (kind, half_i) in state["chips_used"] else 1
                if in_half:
                    prob += pulp.lpSum(var[t] for t in in_half) <= cap_n
        for t in ts:
            prob += wc[t] + tc[t] + bb[t] <= 1
        if t0 == 0:
            prob += wc[0] == 0

        status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=window_time, gapRel=0.005))
        if pulp.value(prob.objective) is None:
            logger.error(f"Rolling window GW{t0 + 1} infeasible · aborting")
            return None

        def _on(v):
            return v.value() is not None and v.value() > 0.5

        commit_end = T if t1 == T else min(t0 + commit, T)
        for t in range(t0, commit_end):
            squad_t = [p for p in range(P) if _on(sq[(p, t)])]
            xi_t = [p for p in squad_t if _on(xi[(p, t)])]
            cap_p = next(p for p in xi_t if _on(cp[(p, t)]))
            chips = [c for c, var in (("WC", wc), ("TC", tc), ("BB", bb)) if _on(var[t])]
            gw_pts = sum(m["pts"][p][t] for p in xi_t) + m["pts"][cap_p][t]
            if "TC" in chips:
                gw_pts += m["pts"][cap_p][t]
            if "BB" in chips:
                gw_pts += sum(m["pts"][p][t] for p in squad_t if p not in xi_t)
            paid_t = int(paid[t].value() or 0) if t in trans_ts else 0
            hit_cost = cfg["hit_cost"] * paid_t
            ledger.append({
                "gw": t + 1,
                "squad": [m["codes"][p] for p in squad_t],
                "xi": [m["codes"][p] for p in xi_t],
                "captain": m["codes"][cap_p],
                "chips": chips,
                "transfers_in": [m["codes"][p] for p in range(P)
                                 if t in trans_ts and _on(buy[(p, t)])],
                "transfers_out": [m["codes"][p] for p in range(P)
                                  if t in trans_ts and _on(sell[(p, t)])],
                "hit_cost": hit_cost,
                "bank": round(float(bank[t].value() or 0), 1),
                "squad_value": round(float(sum(m["price"][p][t] for p in squad_t)), 1),
                "gw_points": float(gw_pts),
                "net_points": float(gw_pts) - hit_cost,
            })
            # roll state
            state["squad"] = set(squad_t)
            state["bank"] = float(bank[t].value() or 0)
            if t in trans_ts:
                used = int(ftu[t].value() or 0)
                state["ft"] = min(state["ft"] - used + 1, cfg["max_banked_ft"])
            else:
                state["ft"] = 1
            if hits_left is not None:
                hits_left -= paid_t
            for c in chips:
                half_i = 1 if t + 1 <= cfg["chip_halves"][0][1] else 2
                state["chips_used"].add((c.lower(), half_i))
        logger.info(f"Rolling: committed GW{t0 + 1}-{commit_end} "
                    f"({pulp.LpStatus[status]}, cum {sum(g['net_points'] for g in ledger):.0f} pts)")
        t0 = commit_end

    elapsed = time.time() - total_start
    total = sum(g["net_points"] for g in ledger)
    return {
        "per_gw": ledger,
        "total_points": float(total),
        "total_hits": int(sum(g["hit_cost"] for g in ledger) // cfg["hit_cost"]),
        "solver_status": "RollingHorizon",
        "solve_seconds": round(elapsed, 1),
        "objective": float(total),
    }


# ── Free Hit post-pass ────────────────────────────────────────────────────────

def layer_free_hit(solution: Dict, opt: pd.DataFrame,
                   cfg: Dict = PERFECT_SEASON) -> List[Dict]:
    """
    For each half, find the GW where replacing the planned squad with the
    best one-week squad (budget = that week's squad value + bank) gains the
    most. Separable because FH reverts the squad. Slight upper bound: the
    no-FH plan might have spent transfers on that same week.
    """
    from analytics.squad_milp import optimize_squad

    results = []
    chip_weeks = {g["gw"] for g in solution["per_gw"] if g["chips"]}
    for half_i, (lo, hi) in enumerate(cfg["chip_halves"], start=1):
        best = None
        for g in solution["per_gw"]:
            t = g["gw"]
            if not (lo <= t <= hi) or t in chip_weeks or t == 1:
                continue
            week = opt[opt["gw"] == t].rename(columns={"points": "pts"})
            week = week[week["price"].notna()]
            res = optimize_squad(week, budget=g["squad_value"] + g["bank"],
                                 bench_weight=0.0, time_limit=30)
            if res is None:
                continue
            gain = res["xi_points"] - g["gw_points"]
            if best is None or gain > best["gain"]:
                best = {
                    "half": half_i, "gw": t, "gain": round(gain, 1),
                    "fh_points": res["xi_points"],
                    "planned_points": g["gw_points"],
                    "fh_squad": [int(c) for c in res["squad"]["code"].tolist()]
                    if "code" in res["squad"].columns else [],
                    "fh_captain": (int(res["squad"][res["squad"]["is_captain"]]["code"].iloc[0])
                                   if "code" in res["squad"].columns
                                   and res["squad"]["is_captain"].any() else None),
                }
        if best is not None and best["gain"] > 0:
            results.append(best)
            logger.info(f"Free Hit H{half_i}: GW{best['gw']} +{best['gain']:.0f} pts")
    return results
