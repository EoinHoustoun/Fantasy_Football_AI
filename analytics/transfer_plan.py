"""Multi-week transfer optimiser on the brain's projections (PuLP / CBC).

One MILP over the planning horizon decides, for every gameweek, which players to
sell and buy, the starting XI and the captain, under the real FPL rules: 15-man
2/5/5/3 squad, three per club, a legal XI, free transfers banked to a cap of 5,
-4 per extra transfer, and a budget that uses SELLING prices (half the profit,
rounded down) for players already owned.

Design choices, each borrowed from practice that has been tested elsewhere
(Open-FPL-Solver's settings) or from Eoin's own 22 Sep analysis:

- **Friction per transfer** (default 2 pts). A move that gains less than the
  friction is noise the model cannot see (price moves, rotation, the xP error
  bar). Without it the free solver churned 13 moves over ten weeks.
- **Decay** (default 0.9 per week). Week k is weighted decay^k: a forecast six
  weeks out is worth less than next week's, and it keeps the plan from
  sacrificing the near term for a far-off fixture swing.
- **Terminal value of banked free transfers** (default 1.5 pts each). Otherwise
  the last week of the horizon spends every FT because nothing values keeping one.
- **Bench weight** (default 0.1). Bench points only arrive via autosubs.
- **Alternatives** come from no-good cuts on the first week's moves, so the
  top-N plans differ in what you actually do THIS gameweek.

The FH chip is priced separately (`free_hit_value`) because a Free Hit squad
reverts and is a different optimisation.

No Streamlit imports.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Dict, List, Optional

import pandas as pd
import pulp

logger = logging.getLogger(__name__)

SQUAD_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}
FT_CAP = 5
HIT = 4.0

DEFAULTS = {
    "friction": 2.0,
    "decay": 0.9,
    "ft_value": 1.5,
    "bench_weight": 0.1,
    "max_transfers_per_gw": 3,
    "max_hits_per_gw": 1,
    "pool_per_position": 35,
    "time_limit": 60,
}


# ── Selling prices ────────────────────────────────────────────────────────────

def selling_price(purchase: float, now: float) -> float:
    """FPL rule: you keep half of any rise, rounded DOWN to £0.1m; falls hit in full."""
    p, n = int(round(purchase * 10)), int(round(now * 10))
    if n <= p:
        return n / 10.0
    return (p + (n - p) // 2) / 10.0


def purchase_prices(team_id: int, squad_ids: List[int],
                    first_gw_price: Dict[int, float]) -> Dict[int, float]:
    """Price paid for each currently owned player (by FPL element id).

    The latest transfer-in wins (wildcards are listed too). A player never
    transferred in was in the GW1 squad, so he cost his GW1 price.
    """
    from data.fetchers.fpl_api import fetch_transfer_history
    paid: Dict[int, float] = {}
    try:
        hist = sorted(fetch_transfer_history(int(team_id)), key=lambda t: t["time"])
        for t in hist:
            paid[int(t["element_in"])] = t["element_in_cost"] / 10.0
    except Exception:  # noqa: BLE001 · fall back to current prices
        logger.warning("transfer history unavailable; selling at current price")
    return {i: paid.get(i, first_gw_price.get(i)) for i in squad_ids}


# ── The model ─────────────────────────────────────────────────────────────────

def _pool(summary: pd.DataFrame, owned: List[int], per_pos: int,
          locks: List[int]) -> pd.DataFrame:
    """Owned + locked + the best `per_pos` per position by horizon xP and by xP/£m."""
    keep = set(owned) | set(locks)
    for pos, g in summary.groupby("position"):
        keep |= set(g.nlargest(per_pos, "xp_total")["code"])
        keep |= set(g.nlargest(max(6, per_pos // 3), "xp_per_m")["code"])
    return summary[summary["code"].isin(keep)].copy()


def solve(xp: pd.DataFrame, players: pd.DataFrame, owned: List[int], bank: float,
          free_transfers: int, sell_price: Dict[int, float],
          gws: List[int], settings: Optional[Dict] = None,
          locks: Optional[List[int]] = None, bans: Optional[List[int]] = None,
          no_goods: Optional[List[Dict]] = None, hold: bool = False) -> Dict:
    """Solve one plan.

    xp       code x gw expected points (columns = gws)
    players  one row per code: position, price, team_id, web_name
    owned    15 codes currently owned
    hold     True forbids every transfer (the baseline the plan is judged against)
    no_goods list of {"in": set, "out": set} first-week move sets to exclude
    """
    s = dict(DEFAULTS)
    s.update(settings or {})
    locks, bans = list(locks or []), list(bans or [])
    players = players.assign(code=players["code"].astype(int))
    P = [int(c) for c in players["code"]]
    pos = dict(zip(players["code"], players["position"]))
    club = dict(zip(players["code"], players["team_id"]))
    price = dict(zip(players["code"], players["price"]))
    sell = {p: float(sell_price.get(p, price[p])) for p in P}
    owned_set = set(owned)
    G = [int(g) for g in gws]
    xp = xp.copy()
    xp.index = [int(i) for i in xp.index]
    xp.columns = [int(c) for c in xp.columns]
    w = {g: s["decay"] ** k for k, g in enumerate(G)}
    X = {(p, g): float(xp.at[p, g]) if (p in xp.index and g in xp.columns) else 0.0
         for p in P for g in G}

    prob = pulp.LpProblem("transfer_plan", pulp.LpMaximize)
    B = pulp.LpBinary
    sq = pulp.LpVariable.dicts("sq", (P, G), cat=B)
    xi = pulp.LpVariable.dicts("xi", (P, G), cat=B)
    cp = pulp.LpVariable.dicts("cp", (P, G), cat=B)
    tin = pulp.LpVariable.dicts("in", (P, G), cat=B)
    tout = pulp.LpVariable.dicts("out", (P, G), cat=B)
    ft = pulp.LpVariable.dicts("ft", range(len(G) + 1), lowBound=0, upBound=FT_CAP, cat="Integer")
    paid = pulp.LpVariable.dicts("paid", G, lowBound=0, upBound=s["max_hits_per_gw"], cat="Integer")
    money = pulp.LpVariable.dicts("bank", G, lowBound=0)

    prob += ft[0] == int(min(FT_CAP, max(0, free_transfers)))
    for k, g in enumerate(G):
        prev = (lambda p: 1 if p in owned_set else 0) if k == 0 else (lambda p, _g=G[k - 1]: sq[p][_g])
        for p in P:
            prob += sq[p][g] == prev(p) + tin[p][g] - tout[p][g]
            prob += tin[p][g] + tout[p][g] <= 1
            prob += xi[p][g] <= sq[p][g]
            prob += cp[p][g] <= xi[p][g]
            if p in locks:
                prob += sq[p][g] == 1
            if p in bans:
                prob += tin[p][g] == 0
        for ps, n in SQUAD_SHAPE.items():
            prob += pulp.lpSum(sq[p][g] for p in P if pos[p] == ps) == n
            prob += pulp.lpSum(xi[p][g] for p in P if pos[p] == ps) >= XI_MIN[ps]
            prob += pulp.lpSum(xi[p][g] for p in P if pos[p] == ps) <= XI_MAX[ps]
        prob += pulp.lpSum(xi[p][g] for p in P) == 11
        prob += pulp.lpSum(cp[p][g] for p in P) == 1
        for c in set(club.values()):
            prob += pulp.lpSum(sq[p][g] for p in P if club[p] == c) <= 3

        n_in = pulp.lpSum(tin[p][g] for p in P)
        prob += n_in == pulp.lpSum(tout[p][g] for p in P)
        prob += n_in <= (0 if hold else s["max_transfers_per_gw"])
        prob += paid[g] >= n_in - ft[k]
        # Free transfers: spend some, bank one more, cap at FT_CAP.
        prob += ft[k + 1] <= ft[k] - (n_in - paid[g]) + 1
        prob += ft[k + 1] >= 1

        # Budget: sell at selling price (owned) or current price, buy at current.
        spent = pulp.lpSum(tin[p][g] * price[p] for p in P)
        got = pulp.lpSum(tout[p][g] * sell[p] for p in P)
        prev_bank = float(bank) if k == 0 else money[G[k - 1]]
        prob += money[g] == prev_bank + got - spent

    if no_goods:
        g0 = G[0]
        for ng in no_goods:
            ins, outs = ng.get("in", set()), ng.get("out", set())
            size = len(ins) + len(outs)
            if size == 0:
                # Exclude "do nothing this week": at least one move.
                prob += pulp.lpSum(tin[p][g0] for p in P) >= 1
            else:
                prob += (pulp.lpSum(tin[p][g0] for p in ins)
                         + pulp.lpSum(tout[p][g0] for p in outs)
                         - pulp.lpSum(tin[p][g0] for p in P if p not in ins)
                         - pulp.lpSum(tout[p][g0] for p in P if p not in outs)) <= size - 1

    bw = s["bench_weight"]
    prob += (pulp.lpSum(w[g] * (X[p, g] * (xi[p][g] + cp[p][g]) + bw * X[p, g] * (sq[p][g] - xi[p][g]))
                        for p in P for g in G)
             - pulp.lpSum(w[g] * (HIT * paid[g] + s["friction"] * pulp.lpSum(tin[p][g] for p in P))
                          for g in G)
             + s["ft_value"] * ft[len(G)])

    t0 = time.time()
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=int(s["time_limit"]),
                                          gapRel=0.0005))
    secs = time.time() - t0
    if pulp.LpStatus[status] not in ("Optimal",) and pulp.value(prob.objective) is None:
        return {"status": pulp.LpStatus[status], "secs": secs}

    def v(x):
        return (x.varValue or 0) > 0.5

    name = dict(zip(players["code"], players["web_name"]))
    weeks = []
    for k, g in enumerate(G):
        ins = [p for p in P if v(tin[p][g])]
        outs = [p for p in P if v(tout[p][g])]
        squad = [p for p in P if v(sq[p][g])]
        xi_ = [p for p in squad if v(xi[p][g])]
        cap = next((p for p in xi_ if v(cp[p][g])), None)
        pts = sum(X[p, g] for p in xi_) + (X[cap, g] if cap else 0.0)
        bench = sum(X[p, g] for p in squad if p not in xi_)
        weeks.append({
            "gw": g, "in": ins, "out": outs,
            "in_names": [name[p] for p in ins], "out_names": [name[p] for p in outs],
            "squad": squad, "xi": xi_, "captain": cap,
            "captain_name": name.get(cap), "xp": round(pts, 2),
            "bench_xp": round(bench, 2), "hits": int(round(paid[g].varValue or 0)),
            "ft_before": int(round(ft[k].varValue or 0)),
            "bank_after": round(money[g].varValue or 0, 1),
        })
    total = sum(wk["xp"] - HIT * wk["hits"] for wk in weeks)
    return {"status": pulp.LpStatus[status], "secs": round(secs, 1),
            "objective": round(pulp.value(prob.objective), 2),
            "xp_total": round(total, 2), "weeks": weeks,
            "ft_end": int(round(ft[len(G)].varValue or 0)), "settings": s}


def plan(summary: pd.DataFrame, long: pd.DataFrame, owned: List[int], bank: float,
         free_transfers: int, sell_price: Dict[int, float],
         horizon: Optional[int] = None, settings: Optional[Dict] = None,
         locks: Optional[List[int]] = None, bans: Optional[List[int]] = None,
         alternatives: int = 0) -> Dict:
    """Best plan, the hold baseline, and up to `alternatives` distinct first-week options.

    `summary` is `brain.summary(long)`, `long` the availability-adjusted brain.
    """
    s = dict(DEFAULTS)
    s.update(settings or {})
    gws = sorted(long["gw"].unique())
    if horizon:
        gws = gws[:int(horizon)]
    pool = _pool(summary, owned, int(s["pool_per_position"]), list(locks or []))
    xp = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw", values="xp",
                                               aggfunc="sum").reindex(pool["code"]).fillna(0.0)
    players = pool[["code", "position", "price", "team_id", "web_name"]].copy()

    missing = [c for c in owned if c not in set(players["code"])]
    if missing:
        raise ValueError("owned players missing from the projection: %s" % missing)

    kw = dict(xp=xp, players=players, owned=owned, bank=bank,
              free_transfers=free_transfers, sell_price=sell_price, gws=gws,
              settings=s, locks=locks, bans=bans)
    best = solve(**kw)
    held = solve(hold=True, **kw)
    out = {"best": best, "hold": held, "gws": gws, "alternatives": []}
    if best.get("weeks") and held.get("weeks"):
        out["gain_vs_hold"] = round(best["objective"] - held["objective"], 2)
    cuts = []
    if best.get("weeks"):
        cuts.append({"in": set(best["weeks"][0]["in"]), "out": set(best["weeks"][0]["out"])})
    for _ in range(int(alternatives)):
        alt = solve(no_goods=list(cuts), **kw)
        if not alt.get("weeks"):
            break
        out["alternatives"].append(alt)
        cuts.append({"in": set(alt["weeks"][0]["in"]), "out": set(alt["weeks"][0]["out"])})
    return out
