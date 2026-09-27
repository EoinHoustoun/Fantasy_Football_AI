"""One door to the app's decisions, shared by the Streamlit pages and the MCP server.

Every function returns plain JSON-able dicts/lists, so the same answer reaches
the Home page, the My Team planner and Claude. If two surfaces disagree, one of
them is not calling this module.

No Streamlit imports.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from analytics import brain
from analytics.chip_state import LABEL as CHIP_LABEL, chip_state

logger = logging.getLogger(__name__)

_MEMO: Dict[str, Any] = {}
_TTL = 600


def _memo(key: str, fn, ttl: int = _TTL):
    hit = _MEMO.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _MEMO[key] = (time.time(), val)
    return val


def default_team_id() -> Optional[int]:
    from config import FPL_TEAM_ID
    return int(FPL_TEAM_ID) if FPL_TEAM_ID else None


# ── Inputs ────────────────────────────────────────────────────────────────────

def inputs() -> Dict[str, Any]:
    from data.fetchers.fpl_api import (fetch_bootstrap, fetch_fixtures,
                                       get_fixtures_df, get_players_df)

    def _load():
        bs = fetch_bootstrap()
        return {"bootstrap": bs, "players": get_players_df(bs),
                "fixtures": get_fixtures_df(fetch_fixtures(), bs)}
    return _memo("inputs", _load, ttl=300)


def projections(allow_compute: bool = True) -> Optional[pd.DataFrame]:
    """The availability-adjusted brain, long form (one row per player per GW).

    Memoised for two minutes: pages call this on every rerun, and injury news
    (the only live input once the base is cached) does not move faster.
    """
    hit = _MEMO.get("projections")
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    i = inputs()
    base = brain.load(i["bootstrap"], i["players"], i["fixtures"],
                      allow_compute=allow_compute)
    if base is None:
        return None
    out = brain.with_availability(base, i["players"])
    _MEMO["projections"] = (time.time(), out)
    return out


def gameweek_info() -> Dict[str, Any]:
    bs = inputs()["bootstrap"]
    nxt = next((e for e in bs["events"] if e.get("is_next")), None)
    fin = [e["id"] for e in bs["events"] if e.get("finished")]
    return {"next_gw": nxt["id"] if nxt else None,
            "deadline": nxt["deadline_time"] if nxt else None,
            "last_finished_gw": max(fin) if fin else 0}


# ── The manager's team ────────────────────────────────────────────────────────

def free_transfers(history: Dict, next_gw: int) -> int:
    """Banked FTs going into `next_gw`, replayed from the public history.

    1 FT after GW1, +1 a week to a cap of 5, spent FTs subtracted, hits do not
    borrow. A Wildcard or Free Hit week keeps the FTs you had and accrues none.
    The public API has no banked-FT field, so this is a replay, not a read.
    """
    chips = {c["event"]: c["name"] for c in history.get("chips", [])}
    ft = 0
    for row in sorted(history.get("current", []), key=lambda r: r["event"]):
        gw = int(row["event"])
        if gw >= next_gw:
            break
        if gw == 1:
            ft = 1
            continue
        if chips.get(gw) in ("wildcard", "freehit"):
            continue
        ft = min(5, max(0, ft - int(row.get("event_transfers", 0))) + 1)
    return max(ft, 1)


def team(team_id: Optional[int] = None) -> Dict[str, Any]:
    """Squad, bank, FTs, chips, selling prices, identity. Cached 10 min."""
    team_id = int(team_id or default_team_id())

    def _load():
        from data.fetchers.fpl_api import (fetch_entry_history, fetch_team_info,
                                           fetch_team_picks)
        from analytics.transfer_plan import purchase_prices, selling_price
        i = inputs()
        gwi = gameweek_info()
        nxt = int(gwi["next_gw"] or 1)
        hist = fetch_entry_history(team_id)
        info = fetch_team_info(team_id)
        picks = fetch_team_picks(team_id, nxt)
        players = i["players"].set_index("fpl_id")
        ids = [int(p["element"]) for p in picks.get("picks", [])]
        # GW1 prices for the squad players never transferred in.
        gw1 = {}
        for pid in ids:
            try:
                from data.fetchers.fpl_history import _get, FPL_BASE
                h = _get("%s/element-summary/%d/" % (FPL_BASE, pid)).get("history", [])
                if h:
                    gw1[pid] = h[0]["value"] / 10.0
            except Exception:  # noqa: BLE001
                pass
        paid = purchase_prices(team_id, ids, gw1)
        squad = []
        for p in picks.get("picks", []):
            pid = int(p["element"])
            r = players.loc[pid]
            now = float(r["price"])
            buy = paid.get(pid) or now
            squad.append({"fpl_id": pid, "code": int(r["code"]), "name": r["web_name"],
                          "team": r["team_short"], "position": r["position"],
                          "price": now, "purchase_price": buy,
                          "sell_price": selling_price(buy, now),
                          "status": r.get("status"), "news": r.get("news") or "",
                          "chance": r.get("chance_of_playing_next_round"),
                          "slot": int(p.get("position", 0)),
                          "is_captain": bool(p.get("is_captain")),
                          "on_bench": int(p.get("position", 0)) > 11})
        cur = sorted(hist.get("current", []), key=lambda r: r["event"])
        last = cur[-1] if cur else {}
        return {
            "team_id": team_id,
            "team_name": info.get("name"),
            "manager": "%s %s" % (info.get("player_first_name", ""), info.get("player_last_name", "")),
            "overall_points": info.get("summary_overall_points"),
            "overall_rank": info.get("summary_overall_rank"),
            "next_gw": nxt,
            "bank": (last.get("bank") or 0) / 10.0,
            "team_value": (last.get("value") or 0) / 10.0,
            "free_transfers": free_transfers(hist, nxt),
            "chips": chip_state(hist.get("chips", []), nxt),
            "squad": squad,
            "gw_points": [{"gw": r["event"], "points": r["points"], "rank": r["overall_rank"],
                           "bench": r["points_on_bench"], "hits": r["event_transfers_cost"]}
                          for r in cur],
        }
    return _memo("team:%d" % team_id, _load)


# ── Decisions ─────────────────────────────────────────────────────────────────

def fixtures_for(team_id: int, gws: List[int]) -> List[str]:
    fx = inputs()["fixtures"]
    bs = inputs()["bootstrap"]
    short = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    out = []
    for g in gws:
        rows = fx[fx["gameweek"] == g]
        labs = []
        for _, r in rows.iterrows():
            if int(r["home_team_id"]) == int(team_id):
                labs.append("%s(H)" % short.get(int(r["away_team_id"]), "?"))
            elif int(r["away_team_id"]) == int(team_id):
                labs.append("%s(A)" % short.get(int(r["home_team_id"]), "?"))
        out.append("+".join(labs) if labs else "BLANK")
    return out


def _rows(df: pd.DataFrame, gws: List[int], long: pd.DataFrame) -> List[Dict]:
    per = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw",
                                                 values="xp", aggfunc="sum")
    out = []
    for _, r in df.iterrows():
        c = int(r["code"])
        out.append({
            "name": r["web_name"], "team": r.get("team_short"), "position": r.get("position"),
            "price": round(float(r.get("price", 0) or 0), 1),
            "xp_next": round(float(r.get("xp_next", 0)), 2),
            "xp_window": round(float(r.get("xp_total", 0)), 2),
            "xp_by_gw": {int(g): round(float(per.at[c, g]), 2) if (c in per.index and g in per.columns) else 0.0
                         for g in gws},
            "xmins": round(float(r.get("xmins", 0) or 0), 0),
            "status": r.get("status"), "news": r.get("news") or "",
            "ownership": r.get("ownership"),
            "fixtures": fixtures_for(int(r["team_id"]), gws) if not pd.isna(r.get("team_id")) else [],
            "code": c,
        })
    return out


def top_players(position: Optional[str] = None, max_price: Optional[float] = None,
                horizon: int = 6, top_n: int = 20, sort: str = "xp_window") -> Dict:
    long = projections()
    gws = sorted(long["gw"].unique())[:int(horizon)]
    s = brain.summary(long, gws)
    if position:
        s = s[s["position"] == position.upper()]
    if max_price:
        s = s[s["price"] <= float(max_price)]
    key = {"xp_window": "xp_total", "xp_next": "xp_next", "value": "xp_per_m"}.get(sort, "xp_total")
    s = s.sort_values(key, ascending=False).head(int(top_n))
    return {"gws": [int(g) for g in gws], "players": _rows(s, gws, long)}


def find_players(names: List[str]) -> List[int]:
    """Names (any case, accents optional, 'Palmer (CHE)' to disambiguate) -> codes."""
    from analytics.squad_rules import fold_accents
    p = inputs()["players"]
    folded = p.assign(_n=p["web_name"].map(lambda s: fold_accents(str(s)).lower()),
                      _f=p["name"].map(lambda s: fold_accents(str(s)).lower()))
    codes = []
    for raw in names:
        if isinstance(raw, (int,)) or (isinstance(raw, str) and raw.isdigit() and len(raw) > 4):
            codes.append(int(raw))          # already a player code
            continue
        q = fold_accents(str(raw)).lower().strip()
        club = None
        if "(" in q and q.endswith(")"):
            q, club = q[:q.index("(")].strip(), q[q.index("(") + 1:-1].strip().upper()
        m = folded[(folded["_n"] == q)]
        if m.empty:
            m = folded[folded["_f"].str.contains(q, regex=False) | folded["_n"].str.contains(q, regex=False)]
        if club:
            m = m[m["team_short"] == club]
        if not m.empty:
            codes.append(int(m.sort_values("ownership", ascending=False).iloc[0]["code"]))
    return codes


def player_detail(names: List[str], horizon: int = 6) -> Dict:
    long = projections()
    gws = sorted(long["gw"].unique())[:int(horizon)]
    codes = find_players(names)
    s = brain.summary(long[long["code"].isin(codes)], gws)
    rows = _rows(s, gws, long)
    comp = long[long["code"].isin(codes) & (long["gw"] == gws[0])].set_index("code")
    for r in rows:
        if r["code"] in comp.index:
            c = comp.loc[r["code"]]
            r["next_gw_components"] = {k: round(float(c[k]), 3) for k in
                                       ("p_play", "p60", "exp_minutes", "e_goals", "e_assists",
                                        "e_bonus", "p_clean_sheet", "p_defcon", "avail")
                                       if k in c.index}
    p = inputs()["players"].set_index("code")
    for r in rows:
        if r["code"] in p.index:
            q = p.loc[r["code"]]
            r["season"] = {k: (None if pd.isna(q.get(k)) else q.get(k)) for k in
                           ("total_points", "minutes", "goals_scored", "assists", "form",
                            "points_per_game", "fpl_xg", "fpl_xa", "fpl_xgi_per90",
                            "penalties_order") if k in q.index}
    return {"gws": [int(g) for g in gws], "players": rows}


def captaincy(team_id: Optional[int] = None, gw: Optional[int] = None, top_n: int = 5) -> Dict:
    long = projections()
    gw = int(gw or long["gw"].min())
    t = team(team_id)
    codes = [p["code"] for p in t["squad"]]
    wk = long[(long["gw"] == gw) & long["code"].isin(codes)].sort_values("xp", ascending=False)
    opts = [{"name": r["web_name"], "team": r["team_short"], "xp": round(float(r["xp"]), 2),
             "p60": round(float(r["p60"]), 2), "e_goals": round(float(r["e_goals"]), 2),
             "e_assists": round(float(r["e_assists"]), 2), "status": r.get("status"),
             "fixture": fixtures_for(int(r["team_id"]), [gw])[0]}
            for _, r in wk.head(int(top_n)).iterrows()]
    gap = (opts[0]["xp"] - opts[1]["xp"]) if len(opts) > 1 else None
    return {"gw": gw, "options": opts, "margin_over_second": None if gap is None else round(gap, 2)}


def optimise(team_id: Optional[int] = None, horizon: int = 6,
             free_transfers: Optional[int] = None, settings: Optional[Dict] = None,
             lock: Optional[List[str]] = None, ban: Optional[List[str]] = None,
             alternatives: int = 2) -> Dict:
    from analytics import transfer_plan as tp
    long = projections()
    t = team(team_id)
    owned = [p["code"] for p in t["squad"]]
    sell = {p["code"]: p["sell_price"] for p in t["squad"]}
    gws = sorted(long["gw"].unique())[:int(horizon)]
    summ = brain.summary(long, gws)
    ft = t["free_transfers"] if free_transfers is None else int(free_transfers)
    res = tp.plan(summ, long[long["gw"].isin(gws)], owned, t["bank"], ft, sell,
                  settings=settings, locks=find_players(lock or []),
                  bans=find_players(ban or []), alternatives=alternatives)

    def _brief(p):
        if not p or not p.get("weeks"):
            return p
        return {"xp_total": p["xp_total"], "objective": p["objective"], "ft_end": p["ft_end"],
                "weeks": [{k: w[k] for k in ("gw", "in_names", "out_names", "captain_name",
                                             "xp", "hits", "ft_before", "bank_after")}
                          for w in p["weeks"]]}
    return {"team": t["team_name"], "free_transfers_used_as": ft, "bank": t["bank"],
            "gws": [int(g) for g in gws], "gain_vs_hold": res.get("gain_vs_hold"),
            "best": _brief(res["best"]), "hold": _brief(res["hold"]),
            "alternatives": [_brief(a) for a in res["alternatives"]],
            "settings": res["best"].get("settings"), "_raw": res}


def save_plan_to_app(week_moves: List[Dict], team_id: Optional[int] = None) -> Dict:
    """Write moves into the My Team planner as working drafts.

    week_moves: [{"gw": 6, "out": ["Rogers"], "in": ["Mbeumo"], "captain": "Haaland",
                  "chip": None}]. Drafts, not saved plans: the user still presses Save.
    """
    from analytics import team_plan
    team_id = int(team_id or default_team_id())
    done = []
    for wk in week_moves:
        outs, ins = find_players(wk.get("out", [])), find_players(wk.get("in", []))
        if len(outs) != len(ins):
            return {"ok": False, "error": "GW%s: %d out vs %d in" % (wk.get("gw"), len(outs), len(ins))}
        cap = find_players([wk["captain"]])[0] if wk.get("captain") else None
        chip = {"bboost": "BB", "3xc": "TC", "wildcard": "WC", "freehit": "FH"}.get(
            (wk.get("chip") or "").lower(), wk.get("chip"))
        entry = {"swaps": dict(zip(outs, ins)), "captain": cap, "chip": chip}
        team_plan.save_draft(team_id, int(wk["gw"]), entry)
        done.append({"gw": int(wk["gw"]), "swaps": len(outs), "captain": wk.get("captain")})
    return {"ok": True, "saved_drafts": done,
            "open": "http://localhost:8510/my_team"}


def team_xp(codes: List[int], per_gw: pd.DataFrame, pos: Dict[int, str],
            bench_weight: float = 0.1) -> float:
    """Squad points over the window: best legal XI each week, captain doubled,
    bench at `bench_weight`. Greedy is exact here: fill the formation minimums
    (1 GKP, 3 DEF, 2 MID, 1 FWD) with the best, then the best 4 remaining outfielders.
    """
    total = 0.0
    for g in per_gw.columns:
        xs = {c: float(per_gw.at[c, g]) if c in per_gw.index else 0.0 for c in codes}
        by = {k: sorted([c for c in codes if pos.get(c) == k], key=lambda c: -xs[c])
              for k in ("GKP", "DEF", "MID", "FWD")}
        xi = by["GKP"][:1] + by["DEF"][:3] + by["MID"][:2] + by["FWD"][:1]
        rest = sorted([c for k in ("DEF", "MID", "FWD") for c in by[k] if c not in xi],
                      key=lambda c: -xs[c])[:4]
        xi += rest
        bench = [c for c in codes if c not in xi]
        pts = sum(xs[c] for c in xi) + (max(xs[c] for c in xi) if xi else 0.0)
        total += pts + bench_weight * sum(xs[c] for c in bench)
    return total


def best_moves(team_id: Optional[int] = None, horizon: int = 6, top_n: int = 5,
               friction: float = 2.0, per_out: int = 8) -> Dict:
    """Best single transfers over the window, scored on the TEAM · fast, no solver.

    Each candidate is priced by how much the squad's best-XI-plus-captain points
    over the window change, so a bench keeper upgrade is worth what a bench
    keeper is worth. `optimise` is the full multi-week answer; this is the quick
    read Home shows.
    """
    long = projections(allow_compute=False)
    if long is None:
        return {"ready": False, "moves": []}
    t = team(team_id)
    gws = sorted(long["gw"].unique())[:int(horizon)]
    s = brain.summary(long, gws).set_index("code")
    per = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw", values="xp",
                                                 aggfunc="sum").fillna(0.0)
    pos = s["position"].to_dict()
    owned = {p["code"]: p for p in t["squad"]}
    base = team_xp(list(owned), per, pos)
    club_n: Dict[str, int] = {}
    for p in t["squad"]:
        club_n[p["team"]] = club_n.get(p["team"], 0) + 1
    pool = s[~s.index.isin(owned.keys())]
    moves = []
    for code, p in owned.items():
        budget = t["bank"] + p["sell_price"]
        cand = pool[(pool["position"] == p["position"]) & (pool["price"] <= budget + 1e-9)]
        cand = cand[[club_n.get(c, 0) - (1 if c == p["team"] else 0) < 3
                     for c in cand["team_short"]]]
        best = None
        for c_code, c in cand.nlargest(int(per_out), "xp_total").iterrows():
            codes = [x for x in owned if x != code] + [int(c_code)]
            gain = team_xp(codes, per, pos) - base
            if best is None or gain > best[0]:
                best = (gain, int(c_code), c)
        if best is None:
            continue
        gain, c_code, c = best
        moves.append({"out": p["name"], "out_code": code, "in": c["web_name"],
                      "in_code": c_code, "in_team": c["team_short"],
                      "in_team_code": c.get("team_code"), "position": p["position"],
                      "gain": round(gain, 2), "net_gain": round(gain - friction, 2),
                      "cost_change": round(float(c["price"]) - p["sell_price"], 1)})
    moves.sort(key=lambda m: -m["gain"])
    return {"ready": True, "gws": [int(g) for g in gws], "team_xp": round(base, 2),
            "moves": moves[:int(top_n)], "free_transfers": t["free_transfers"],
            "bank": t["bank"], "friction": friction}


def chip_squad(chip: str, gw: Optional[int] = None, weeks: int = 1,
               team_id: Optional[int] = None, per_pos: int = 40) -> Dict:
    """Best fifteen for a Free Hit (one gameweek) or a Wildcard (a window), on the engine.

    The budget is what the manager can actually spend: bank plus the SELLING
    value of the current fifteen. The answer is judged against the current
    squad's best XI and captain over the same weeks, so the chip's value is
    stated, not implied. A Free Hit squad reverts afterwards, which is why it is
    solved for its single week only.
    """
    from analytics.squad_milp import optimize_squad
    long = projections()
    t = team(team_id)
    gws_all = sorted(int(g) for g in long["gw"].unique())
    gw = int(gw or gws_all[0])
    n = 1 if chip.lower() in ("fh", "freehit", "free hit") else max(1, int(weeks))
    gws = [g for g in gws_all if gw <= g < gw + n]
    if not gws:
        return {"ok": False, "error": "GW%d is outside the projection horizon" % gw}
    per = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw", values="xp",
                                                 aggfunc="sum").fillna(0.0)
    s = brain.summary(long, gws).set_index("code")
    s = s.join(per.rename(columns=lambda g: "gw_%d" % g), how="left").fillna(
        {"gw_%d" % g: 0.0 for g in gws})
    keep = set()
    for _, grp in s.groupby("position"):
        keep |= set(grp.nlargest(per_pos, "xp_total").index)
    pool = s.loc[sorted(keep)].reset_index()
    budget = round(t["bank"] + sum(p["sell_price"] for p in t["squad"]), 1)
    cols = ["gw_%d" % g for g in gws]
    if len(cols) == 1:
        res = optimize_squad(pool, budget=budget, pts_col=cols[0], time_limit=60)
    else:
        res = optimize_squad(pool, budget=budget, gw_pts_cols=cols, time_limit=90)
    if res is None:
        return {"ok": False, "error": "no legal squad inside £%.1fm" % budget}
    sq = res["squad"]
    mine = [p["code"] for p in t["squad"]]
    pos = s["position"].to_dict()
    current = team_xp(mine, per, pos, bench_weight=0.0)
    new_total = res.get("window_points", res["xi_points"])
    players = [{"name": r["web_name"], "team": r["team_short"], "position": r["position"],
                "price": float(r["price"]), "xp": round(float(sum(r[c] for c in cols)), 2),
                "in_xi": bool(r["in_xi"]), "captain": bool(r["is_captain"]),
                "code": int(r["code"]), "team_code": r.get("team_code"),
                "owned": int(r["code"]) in mine}
               for _, r in sq.iterrows()]
    return {"ok": True, "chip": "Free Hit" if n == 1 else "Wildcard", "gws": gws,
            "budget": budget, "cost": res["squad_cost"], "points": round(float(new_total), 2),
            "current_points": round(float(current), 2),
            "gain": round(float(new_total - current), 2),
            "proven_optimal": bool(res.get("proven_optimal")), "squad": players,
            "keeps": sum(1 for p in players if p["owned"])}


def season_rows():
    """This season's per-match rows (minutes, xG, DEFCON actions...). Cached 30 min."""
    def _load():
        from analytics.component_model import active_season
        from data.processors.archive import _normalize_vaastav_season
        return _normalize_vaastav_season(active_season())
    return _memo("season_rows", _load, ttl=1800)


def move_dossier(out_code: int, in_code: int, team_id: Optional[int] = None,
                 horizon: int = 8, friction: float = 2.0) -> Dict:
    """Everything needed to decide one transfer: timing, robustness, both
    players' background checks, the team-level gain and a verdict.

    Memoised against the projection frame in use, so a page rerun (or a card
    grid of six moves) does not re-audit what has not changed.
    """
    key = "dossier:%s:%s:%s:%s:%s:%s" % (team_id, out_code, in_code, horizon, friction,
                                         id(projections(allow_compute=False)))
    return _memo(key, lambda: _move_dossier(out_code, in_code, team_id, horizon, friction), ttl=600)


def _move_dossier(out_code: int, in_code: int, team_id: Optional[int] = None,
                  horizon: int = 8, friction: float = 2.0) -> Dict:
    from analytics import transfer_audit as TA
    long = projections()
    t = team(team_id)
    gws = sorted(int(g) for g in long["gw"].unique())[:int(horizon)]
    per = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw", values="xp",
                                                 aggfunc="sum").fillna(0.0)
    xp_of = lambda c: {int(g): float(per.at[c, g]) if c in per.index else 0.0 for g in gws}
    out_xp, in_xp = xp_of(int(out_code)), xp_of(int(in_code))
    # Timing and robustness are priced on the TEAM (best XI + captain each
    # week), not on the two players: selling a bench keeper for a starter is
    # worth what it changes on the pitch, not the gap between their totals.
    owned0 = [p["code"] for p in t["squad"]]
    pos0 = dict(zip(long["code"], long["position"]))
    if int(out_code) in owned0:
        sw = [c for c in owned0 if c != int(out_code)] + [int(in_code)]
        team_before = {g: team_xp(owned0, per[[g]], pos0) for g in gws}
        team_after = {g: team_xp(sw, per[[g]], pos0) for g in gws}
    else:
        team_before, team_after = out_xp, in_xp
    tm = TA.timing(team_before, team_after, friction)
    hz = TA.horizon_gains(team_before, team_after)
    rows = season_rows()
    players = inputs()["players"]
    fx = inputs()["fixtures"]
    po, pi = TA.profile(int(out_code), rows, players), TA.profile(int(in_code), rows, players)
    tid = dict(zip(players["code"], players["team_id"]))
    after = list(range(gws[-1] + 1, gws[-1] + 7))
    ease_o = TA.fixture_ease(int(tid.get(out_code, 0)), fx, after)
    ease_i = TA.fixture_ease(int(tid.get(in_code, 0)), fx, after)
    # Team-level gain over six weeks (best XI + captain), the number Home shows.
    six = [g for g in gws[:6]]
    owned = [p["code"] for p in t["squad"]]
    pos = dict(zip(long["code"], long["position"]))
    team_gain = None
    if int(out_code) in owned:
        swapped = [c for c in owned if c != int(out_code)] + [int(in_code)]
        team_gain = round(team_xp(swapped, per[six], pos) - team_xp(owned, per[six], pos), 2)
    verdict = TA.audit(po, pi, tm, hz, ease_o, ease_i, team_gain, friction)
    # Who the move really changes on the pitch. Selling a benchwarmer means the
    # new man displaces a STARTER, and that is the comparison that matters.
    if int(out_code) in owned:
        def _xi(codes, g):
            xs = {c: float(per.at[c, g]) if c in per.index else 0.0 for c in codes}
            by = {k: sorted([c for c in codes if pos.get(c) == k], key=lambda c: -xs[c])
                  for k in ("GKP", "DEF", "MID", "FWD")}
            xi = by["GKP"][:1] + by["DEF"][:3] + by["MID"][:2] + by["FWD"][:1]
            xi += sorted([c for k in ("DEF", "MID", "FWD") for c in by[k] if c not in xi],
                         key=lambda c: -xs[c])[:4]
            return set(xi)
        benched = sum(1 for g in six if int(out_code) not in _xi(owned, g))
        if benched >= len(six) / 2:
            sw = [c for c in owned if c != int(out_code)] + [int(in_code)]
            dropped = {}
            for g in six:
                for c in _xi(owned, g) - _xi(sw, g):
                    dropped[c] = dropped.get(c, 0) + 1
            name = dict(zip(players["code"], players["web_name"]))
            if dropped:
                who = max(dropped, key=dropped.get)
                verdict["flags"].insert(0, {"side": "move", "level": "info", "text":
                    "%s is on your bench in %d of %d weeks, so this is really %s replacing %s in "
                    "your XI. Judge it on that." % (po["name"], benched, len(six), pi["name"],
                                                    name.get(who, "a starter"))})
            else:
                verdict["flags"].insert(0, {"side": "move", "level": "warn", "text":
                    "%s sits on your bench in %d of %d weeks and %s would too: this buys bench "
                    "cover, not points." % (po["name"], benched, len(six), pi["name"])})
    return {"gws": gws, "out": po, "in": pi, "out_xp": out_xp, "in_xp": in_xp,
            "out_fixtures": fixtures_for(int(tid.get(out_code, 0)), gws),
            "in_fixtures": fixtures_for(int(tid.get(in_code, 0)), gws),
            "timing": tm, "horizons": hz, "team_gain_6": team_gain,
            "ease_after": {"gws": [after[0], after[-1]], "out": ease_o, "in": ease_i},
            **verdict}


def squad_exit_map(team_id: Optional[int] = None, horizon: int = 8, margin: float = 1.0) -> Dict:
    """Each owned player's xP per week, flagged where an affordable replacement
    in his position beats him by `margin` or more · his exit weeks.

    Affordable = selling price plus bank. The replacement can differ week to week;
    the point is to show WHEN a player stops earning his slot, not whom to buy.
    """
    long = projections()
    t = team(team_id)
    gws = sorted(int(g) for g in long["gw"].unique())[:int(horizon)]
    per = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw", values="xp",
                                                 aggfunc="sum").fillna(0.0)
    s = brain.summary(long, gws).set_index("code")
    owned = [p["code"] for p in t["squad"]]
    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    rows = []
    for p in sorted(t["squad"], key=lambda p: (order.get(p["position"], 9), p["slot"])):
        c = p["code"]
        budget = t["bank"] + p["sell_price"]
        pool = s[(s["position"] == p["position"]) & (s["price"] <= budget + 1e-9)
                 & (~s.index.isin(owned))]
        best = per.reindex(pool.index).max() if not pool.empty else pd.Series(0.0, index=gws)
        own = {g: float(per.at[c, g]) if c in per.index else 0.0 for g in gws}
        beaten = {g: bool(float(best.get(g, 0.0)) - own[g] >= margin) for g in gws}
        first_exit = next((g for g in gws if beaten[g] and beaten.get(g + 1, beaten[g])), None)
        rows.append({"code": c, "name": p["name"], "position": p["position"], "xp": own,
                     "beaten": beaten, "exit_gw": first_exit,
                     "weeks_beaten": sum(beaten.values())})
    return {"gws": gws, "rows": rows, "margin": margin}


def ownership_history(min_own: float = 1.0, top_traded: int = 60) -> pd.DataFrame:
    """Real per-gameweek ownership and price for the players that matter.

    The live gameweek feed has no history for `selected` or `value`: it stamps
    today's figure on every past week, so an ownership chart built on it is
    flat. FPL's per-player history does carry them. Fetched for everyone owned
    by `min_own`% or more plus the `top_traded` most bought and sold, in parallel,
    and cached on disk until the next gameweek finishes.
    Columns: code, web_name, name, team_short, position, GW, selected, value,
    transfers_in, transfers_out.
    """
    import json
    from concurrent.futures import ThreadPoolExecutor
    from data.fetchers.fpl_history import FPL_BASE, _get
    i = inputs()
    fin = gameweek_info()["last_finished_gw"]
    path = brain.CACHE_DIR / ("ownership_history_gw%d.json" % fin)
    p = i["players"]
    pick = set(p.loc[p["ownership"].fillna(0) >= min_own, "fpl_id"])
    net = (p["transfers_in_event"].fillna(0) - p["transfers_out_event"].fillna(0))
    pick |= set(p.loc[net.abs().nlargest(top_traded).index, "fpl_id"])
    cached = {}
    if path.exists():
        try:
            cached = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            cached = {}
    todo = [int(x) for x in pick if str(int(x)) not in cached]
    if todo:
        def _one(pid):
            d = _get("%s/element-summary/%d/" % (FPL_BASE, pid)) or {}
            return pid, [{"GW": h["round"], "selected": h.get("selected"), "value": h.get("value"),
                          "transfers_in": h.get("transfers_in"), "transfers_out": h.get("transfers_out")}
                         for h in d.get("history", [])]
        with ThreadPoolExecutor(max_workers=8) as ex:
            for pid, rows in ex.map(_one, todo):
                cached[str(pid)] = rows
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cached))
    meta = p.set_index("fpl_id")
    out = []
    for pid, rows in cached.items():
        pid = int(pid)
        if pid not in meta.index or pid not in pick:
            continue
        m = meta.loc[pid]
        for r in rows:
            out.append({"code": int(m["code"]), "web_name": m["web_name"], "name": m["name"],
                        "team": m["team"], "team_short": m["team_short"], "position": m["position"],
                        **r})
    df = pd.DataFrame(out)
    if df.empty:
        return df
    # A double gameweek gives two rows per round; ownership is per round.
    return (df.sort_values("GW").groupby(["code", "GW"], as_index=False)
              .agg({k: "last" for k in df.columns if k not in ("code", "GW")}))


def fixture_ticker(horizon: int = 6) -> Dict:
    """Each club's expected goals and clean-sheet chance per gameweek, from the engine."""
    long = projections()
    gws = sorted(int(g) for g in long["gw"].unique())[:int(horizon)]
    t = (long[long["gw"].isin(gws)].groupby(["team_short", "team_id", "gw"])
         .agg(xg=("e_goals", "sum"), cs=("p_clean_sheet", "max")).reset_index())
    out = []
    for (short, tid), g in t.groupby(["team_short", "team_id"]):
        fx = fixtures_for(int(tid), gws)
        out.append({"team": short,
                    "weeks": [{"gw": int(r["gw"]), "fixture": fx[gws.index(int(r["gw"]))],
                               "xg": round(float(r["xg"]), 2), "cs": round(float(r["cs"]), 2)}
                              for _, r in g.sort_values("gw").iterrows()],
                    "xg_total": round(float(g["xg"].sum()), 2),
                    "cs_total": round(float(g["cs"].sum()), 2)})
    return {"gws": gws, "teams": sorted(out, key=lambda x: -x["xg_total"])}


def league_rivals(league_id: int, team_id: Optional[int] = None, top_n: int = 20,
                  horizon: int = 6) -> Dict:
    """Your mini-league on the engine: every rival's squad projected like yours.

    For the top `top_n` managers (plus you): the fifteen they hold now (latest
    public picks), their best-XI-plus-captain xP for the next gameweek and the
    window, and the league's ownership of every player. That gives the two lists
    that decide rank in a mini-league: THREATS (owned by many rivals, not by
    you, weighted by xP) and SWORDS (yours, owned by few of them).
    Picks are cached with the rest of the memo (10 minutes).
    """
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from data.fetchers.fpl_api import HEADERS
    team_id = int(team_id or default_team_id())
    long = projections()
    gws = sorted(int(g) for g in long["gw"].unique())[:int(horizon)]
    per = long[long["gw"].isin(gws)].pivot_table(index="code", columns="gw", values="xp",
                                                 aggfunc="sum").fillna(0.0)
    pos = dict(zip(long["code"], long["position"]))
    i = inputs()
    code_of = dict(zip(i["players"]["fpl_id"].astype(int), i["players"]["code"].astype(int)))
    fin = gameweek_info()["last_finished_gw"]

    def _get(url):
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()

    def _load():
        st_ = _get("https://fantasy.premierleague.com/api/leagues-classic/%d/standings/" % int(league_id))
        rows = st_.get("standings", {}).get("results", [])[: int(top_n)]
        if all(int(r["entry"]) != team_id for r in rows):
            rows.append({"entry": team_id, "entry_name": team(team_id)["team_name"],
                         "player_name": "You", "rank": None, "total": team(team_id)["overall_points"]})

        def _picks(r):
            try:
                d = _get("https://fantasy.premierleague.com/api/entry/%d/event/%d/picks/" % (int(r["entry"]), fin))
                return r, [code_of.get(int(p["element"])) for p in d.get("picks", [])]
            except Exception:  # noqa: BLE001
                return r, []
        with ThreadPoolExecutor(max_workers=8) as ex:
            return st_.get("league", {}).get("name"), list(ex.map(_picks, rows))

    name, managers = _memo("league:%d:%d:%d" % (int(league_id), team_id, fin), _load)
    out, own = [], {}
    for r, codes in managers:
        codes = [c for c in codes if c]
        if len(codes) < 11:
            continue
        nxt = team_xp(codes, per[[gws[0]]], pos, bench_weight=0.0)
        win = team_xp(codes, per, pos, bench_weight=0.0)
        me = int(r["entry"]) == team_id
        out.append({"entry": int(r["entry"]), "team": r.get("entry_name"), "manager": r.get("player_name"),
                    "rank": r.get("rank"), "total": r.get("total"), "xp_next": round(nxt, 2),
                    "xp_window": round(win, 2), "you": me, "codes": codes})
        if not me:
            for c in set(codes):
                own[c] = own.get(c, 0) + 1
    n_riv = max(1, sum(1 for m in out if not m["you"]))
    mine = next((set(m["codes"]) for m in out if m["you"]), set())
    s = brain.summary(long, gws).set_index("code")

    def _row(c, share):
        return {"code": int(c), "name": s.at[c, "web_name"] if c in s.index else str(c),
                "team": s.at[c, "team_short"] if c in s.index else "", "league_own": round(100 * share, 0),
                "xp_window": round(float(s.at[c, "xp_total"]), 2) if c in s.index else 0.0}
    threats = sorted([_row(c, k / n_riv) for c, k in own.items() if c not in mine and k / n_riv >= 0.2],
                     key=lambda x: -(x["league_own"] * x["xp_window"]))[:10]
    swords = sorted([_row(c, own.get(c, 0) / n_riv) for c in mine if own.get(c, 0) / n_riv <= 0.3],
                    key=lambda x: -x["xp_window"])[:8]
    for m in out:
        m.pop("codes", None)
    return {"league": name, "gws": gws, "managers": sorted(out, key=lambda m: -m["xp_window"]),
            "threats": threats, "swords": swords, "n_rivals": n_riv}
