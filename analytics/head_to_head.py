"""Player and draft comparison · the two "which one" questions, answered.

Two comparisons matter when building a squad, and they need different shapes.

**Player vs player** ("is Alderete or Ballard the pick?") is a small number of
players scored on the same handful of axes. The trap is comparing raw totals: a
player with more projected points may simply be more expensive, or may be
getting there on minutes rather than on rate. So everything here is expressed
three ways, and the UI shows all three:

  * per season   what he is worth in total
  * per million  what he is worth for what he costs
  * per 90       what he is worth when he is actually on the pitch

**Draft vs draft** is a squad scored over a gameweek window WITH its own chip
plan, because a Bench Boost in GW1 and one in GW2 are different squads' worth of
points, not the same squad twice. The comparison prices the chip where it is
actually played and reports what drove the gap.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SEASON_MINUTES = 3420.0   # 38 x 90


# ── Player vs player ──────────────────────────────────────────────────────────
# Each axis: (label, board column, higher-is-better, "what it tells you").
# `per` marks how the raw number should be normalised for a fair read.
AXES: List[Dict] = [
    {"key": "season", "label": "Season points", "col": None, "better": "high",
     "why": "Total return if the projection lands. Flatters expensive players."},
    {"key": "per_m", "label": "Points per £m", "col": None, "better": "high",
     "why": "Return for what he costs. The only one that respects a budget."},
    {"key": "per_90", "label": "Points per 90", "col": None, "better": "high",
     "why": "Rate when he is on the pitch, with minutes taken out of it."},
    {"key": "mins", "label": "Expected minutes", "col": "ffh_nailedness",
     "better": "high", "why": "Minutes are the master variable. No minutes, no points."},
    {"key": "defcon", "label": "DEFCON hit rate", "col": None, "better": "high",
     "why": "Share of starts clearing the threshold. This is what converts."},
    {"key": "fixtures", "label": "Opening fixtures", "col": "opening_factor",
     "better": "high", "why": "Ease of the GW1-6 run. A tie-breaker, not a reason."},
    {"key": "agreement", "label": "Model agreement", "col": None, "better": "high",
     "why": "How closely the three models land. Low means the number is a guess."},
]


def player_profile(row: pd.Series, pts_col: str = "consensus_points",
                   defcon: Optional[pd.DataFrame] = None,
                   proj=None) -> Dict:
    """One player's comparable numbers, normalised three ways.

    `defcon` is the per-90 frame from the draft page (indexed by code); `proj` is
    a `GwProjection` used for the near-term run. Both optional.
    """
    code = int(row.get("code", 0) or 0)
    price = float(row.get("actual_price") or 0) or np.nan
    season = float(row.get(pts_col) or 0)

    # Projected minutes: prefer the stated forecast, fall back to the fitted one.
    nailed = row.get("ffh_nailedness")
    if pd.notna(nailed):
        minutes = float(nailed) * SEASON_MINUTES
    else:
        minutes = float(row.get("projected_minutes") or 0)

    dc_hit = np.nan
    if defcon is not None and not defcon.empty and code in defcon.index:
        dc_hit = float(defcon.loc[code].get("dc_hit_rate", np.nan))

    spread = row.get("model_spread")
    agreement = (1.0 - float(spread)) if pd.notna(spread) else np.nan

    out = {
        "code": code,
        "name": str(row.get("web_name", "?")),
        "team": str(row.get("team_name", "") or ""),
        "team_short": str(row.get("team_short", "") or ""),
        "team_code": int(row.get("team_code", 1) or 1),
        "position": str(row.get("position", "")),
        "price": price,
        "season": round(season, 1),
        "per_m": round(season / price, 1) if price and price > 0 else np.nan,
        "per_90": round(season / (minutes / 90.0), 2) if minutes > 90 else np.nan,
        "mins": round(float(nailed) * 90, 0) if pd.notna(nailed) else np.nan,
        "defcon": round(dc_hit, 3) if pd.notna(dc_hit) else np.nan,
        "fixtures": round(float(row.get("opening_factor") or 1.0), 3),
        "agreement": round(agreement, 3) if pd.notna(agreement) else np.nan,
        "confidence": str(row.get("consensus_confidence", "") or ""),
        "ownership": float(row.get("ownership") or 0),
        "pens": row.get("pens_order"),
        "src_ours": row.get("src_ours"), "src_scout": row.get("src_scout"),
        "src_ffh": row.get("src_ffh"),
    }
    if proj is not None:
        out["next6"] = round(proj.run_total(code, 1, 6), 1)
        out["gw1"] = round(proj.points(code, 1), 1)
    return out


def compare_players(profiles: List[Dict]) -> Dict:
    """Score profiles against each other and say who wins, on what, and why.

    Each axis is scaled to 0-1 across the compared players only, which is the
    right frame: the question is never "is he good" but "is he better than the
    alternative I can actually afford".
    """
    if len(profiles) < 2:
        return {"axes": [], "winner": None, "reasons": []}

    axes_out = []
    for ax in AXES:
        vals = [p.get(ax["key"]) for p in profiles]
        clean = [v for v in vals if v is not None and not pd.isna(v)]
        if len(clean) < 2:
            continue
        lo, hi = min(clean), max(clean)
        span = (hi - lo) or 1.0
        scaled = []
        for v in vals:
            if v is None or pd.isna(v):
                scaled.append(None)
            else:
                s = (v - lo) / span
                scaled.append(s if ax["better"] == "high" else 1 - s)
        best = int(np.nanargmax([-1 if s is None else s for s in scaled]))
        axes_out.append({**ax, "values": vals, "scaled": scaled, "best": best,
                         "decisive": (hi - lo) / (abs(hi) or 1.0) > 0.15})

    # Two scores, because they answer different questions.
    #
    # `totals` is the mean of the 0-1 scaled axes · it drives the bars, where
    # what you want to see is who leads on what.
    #
    # `edges` is the mean RELATIVE difference against the field. With only two
    # players every axis scales to exactly 0 or 1, so `totals` would call a 4%
    # edge on every axis a landslide. The verdict needs magnitude, not just
    # direction, so it reads `edges` instead.
    totals, edges = [], []
    for i, _p in enumerate(profiles):
        got = [a["scaled"][i] for a in axes_out if a["scaled"][i] is not None]
        totals.append(float(np.mean(got)) if got else 0.0)

        rel = []
        for a in axes_out:
            mine = a["values"][i]
            theirs = [v for j, v in enumerate(a["values"])
                      if j != i and v is not None and not pd.isna(v)]
            if mine is None or pd.isna(mine) or not theirs:
                continue
            other = float(np.mean(theirs))
            denom = max(abs(float(mine)), abs(other)) or 1.0
            d = (float(mine) - other) / denom
            rel.append(d if a["better"] == "high" else -d)
        edges.append(float(np.mean(rel)) if rel else 0.0)

    winner = int(np.argmax(edges)) if edges else None

    reasons = []
    for a in axes_out:
        if not a["decisive"]:
            continue
        w = a["best"]
        vals = a["values"]
        reasons.append({
            "axis": a["label"], "winner": profiles[w]["name"],
            "detail": "%s %s vs %s" % (
                a["label"].lower(),
                _fmt(a["key"], vals[w]),
                ", ".join(_fmt(a["key"], v) for i, v in enumerate(vals) if i != w)),
            "why": a["why"], "for_winner": w == winner,
        })
    return {"axes": axes_out, "winner": winner, "totals": totals,
            "edges": edges, "reasons": reasons}


def _fmt(key: str, v) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    if key in ("defcon",):
        return "%.0f%%" % (float(v) * 100)
    if key in ("mins",):
        return "%.0f'" % float(v)
    if key in ("agreement", "fixtures"):
        return "%.2f" % float(v)
    if key in ("per_90",):
        return "%.2f" % float(v)
    return "%.0f" % float(v) if key == "season" else "%.1f" % float(v)


def verdict_line(cmp: Dict, profiles: List[Dict]) -> str:
    """One sentence a human can act on."""
    if cmp.get("winner") is None:
        return "Not enough overlap between these players to call it."
    w = cmp["winner"]
    win = profiles[w]
    ed = cmp["edges"]
    # Mean relative advantage over the field. 12% is a real gap; 4% is a
    # rounding difference dressed up as a decision.
    margin = ed[w] - max(v for i, v in enumerate(ed) if i != w)
    others = ", ".join(p["name"] for i, p in enumerate(profiles) if i != w)
    if margin < 0.05:
        return (f"<b>{win['name']}</b> and {others} are separated by about "
                f"{margin * 100:.0f}% across these axes, which is noise. They are "
                f"the same pick · take the one whose minutes you believe.")
    edge = "clearly ahead" if margin > 0.15 else "narrowly ahead"
    top = [r["axis"].lower() for r in cmp["reasons"] if r["for_winner"]][:2]
    on = (" on " + " and ".join(top)) if top else ""
    return f"<b>{win['name']}</b> is {edge} of {others}{on}."


# ── Draft vs draft ────────────────────────────────────────────────────────────
def score_draft(squad: pd.DataFrame, proj, gw_lo: int, gw_hi: int,
                bench_boost_gw: Optional[int] = None,
                triple_captain_gw: Optional[int] = None) -> Dict:
    """Points a squad is expected to return over a window, with its chip plan.

    The XI is re-picked every gameweek (a blank or a hard away trip benches a
    player who is otherwise a starter), the captain doubles, and in a Bench Boost
    week the bench pays too. This is what makes "Bench Boost GW1" and "Bench
    Boost GW2" genuinely different plans rather than the same squad twice.
    """
    from analytics.gw_projection import best_xi

    codes = [int(c) for c in squad["code"]]
    names = {int(r["code"]): str(r["web_name"]) for _, r in squad.iterrows()}
    weeks, total, bench_total, cap_total = [], 0.0, 0.0, 0.0

    for gw in range(gw_lo, gw_hi + 1):
        xi = best_xi(squad, proj, gw)
        xi_pts = sum(proj.points(c, gw) for c in codes if c in xi)
        bench_pts = sum(proj.points(c, gw) for c in codes if c not in xi)
        cap_code = max(xi, key=lambda c: proj.points(c, gw)) if xi else None
        cap_bonus = proj.points(cap_code, gw) if cap_code else 0.0
        if triple_captain_gw == gw:
            cap_bonus *= 2

        week = xi_pts + cap_bonus
        boosted = bench_boost_gw == gw
        if boosted:
            week += bench_pts
            bench_total += bench_pts
        total += week
        cap_total += cap_bonus
        weeks.append({
            "gw": gw, "points": round(week, 1), "xi": round(xi_pts, 1),
            "bench": round(bench_pts, 1), "captain": names.get(cap_code, "?"),
            "captain_pts": round(cap_bonus, 1), "boosted": boosted,
            "dead": [names[c] for c in codes if c not in xi and proj.points(c, gw) < 1.0]
            if boosted else [],
        })

    return {
        "total": round(total, 1),
        "weeks": weeks,
        "bench_boost_gw": bench_boost_gw,
        "bench_boost_gain": round(bench_total, 1),
        "captain_points": round(cap_total, 1),
        # The solver hands back `price`; the board calls it `actual_price`.
        "cost": round(float(pd.to_numeric(
            squad["actual_price"] if "actual_price" in squad.columns else squad["price"],
            errors="coerce").sum()), 1),
        "codes": set(codes),
        "names": names,
    }


def build_phases(spec: Dict, solve, window_map, gw_lo: int, gw_hi: int,
                 board: Optional[pd.DataFrame] = None) -> List:
    """Resolve a saved draft into the squads it fields across the window.

    Usually one squad for the whole window. A Wildcard splits it in two: the
    original fifteen until the reset, then a squad rebuilt on the fixtures that
    FOLLOW it, which is the only thing a Wildcard is actually for.

    `solve(strategy, opening_weight, opening_map)` returns the solver result;
    `window_map(lo, hi)` returns the fixture-ease tuple for a window. Both are
    passed in so this module stays free of Streamlit caching concerns.
    """
    # A draft that carries an explicit fifteen is used verbatim · re-solving it
    # would compare a squad the user never chose.
    explicit = spec.get("squad")
    if explicit and len(explicit) == 15 and board is not None:
        codes = [int(c) for c in explicit]
        sq = board[board["code"].isin(codes)].copy()
        if len(sq) == 15:
            sq = sq.set_index("code").reindex(codes).reset_index()
            sq["price"] = sq["actual_price"]
            sq["pts"] = sq.get("consensus_points", sq.get("projected_points"))
            sq["in_xi"] = True
            return [(gw_lo, sq)]

    first = solve(spec.get("strategy"), spec.get("opening", 0.35), ())
    if first is None:
        return []
    phases = [(gw_lo, first["squad"])]

    wc = spec.get("wildcard_gw")
    if wc and gw_lo < int(wc) <= gw_hi:
        hi = min(38, int(wc) + 5)
        after = solve(spec.get("strategy"), 1.0, window_map(int(wc), hi))
        if after is not None:
            phases.append((int(wc), after["squad"]))
    return phases


# ── Uncertainty · is the gap real, or is it noise? ────────────────────────────
# A projection is a middle, not a promise, so two drafts four points apart over
# eight gameweeks are not meaningfully different. Saying so requires simulating
# the spread rather than comparing two point estimates.
#
# Two sources of uncertainty, and they behave differently:
#
#   rate   how good the player actually is. One draw per player for the whole
#          window, because being wrong about Isak in GW1 means being wrong about
#          him in GW8 too. Width comes from the gap between the three models.
#   match  week to week variance. Football is lumpy: a striker's weekly score is
#          heavily overdispersed, so this is drawn fresh every gameweek.
#
# The thing that makes the answer trustworthy is that both draws are SHARED
# between drafts. If two squads have twelve players in common, those twelve
# cancel in the difference, and the comparison narrows to the picks that actually
# differ. Simulating each draft independently would drown that signal in variance
# neither draft owns.
DEFAULT_SIMS = 1500
RATE_CV_FLOOR, RATE_CV_CAP = 0.06, 0.55
MATCH_OVERDISPERSION = 2.4      # weekly variance / mean, fitted loosely on FPL scores


def _player_uncertainty(board: pd.DataFrame, codes: List[int]) -> Dict[int, float]:
    """Coefficient of variation per player, from how far the models disagree."""
    idx = board.set_index("code")
    out = {}
    for c in codes:
        cv = np.nan
        if c in idx.index:
            r = idx.loc[c]
            lo, hi = r.get("consensus_lo"), r.get("consensus_hi")
            mean = r.get("consensus_points", r.get("projected_points"))
            if pd.notna(lo) and pd.notna(hi) and pd.notna(mean) and float(mean) > 0:
                # Treat the model spread as roughly a 95% interval.
                cv = (float(hi) - float(lo)) / 4.0 / float(mean)
        if not np.isfinite(cv):
            cv = 0.25
        out[c] = float(np.clip(cv, RATE_CV_FLOOR, RATE_CV_CAP))
    return out


def simulate_drafts(entries: List[Dict], proj, board: pd.DataFrame,
                    gw_lo: int, gw_hi: int, n_sims: int = DEFAULT_SIMS,
                    seed: int = 20262027) -> Dict:
    """Monte Carlo over several drafts at once, on shared draws.

    `entries` = [{name, phases: [(gw_from, squad_df), ...], bench_boost_gw}].
    Phases let a Wildcard swap the squad partway through the window.

    Returns per-draft cumulative mean and an 80% band, plus the pairwise
    probability that one draft finishes ahead of another.
    """
    from analytics.gw_projection import best_xi

    gws = list(range(gw_lo, gw_hi + 1))
    rng = np.random.default_rng(seed)

    # Union of everyone any draft might field.
    codes = sorted({int(c) for e in entries for _g, sq in e["phases"]
                    for c in sq["code"]})
    ci = {c: i for i, c in enumerate(codes)}
    P, G, S = len(codes), len(gws), int(n_sims)
    if not P or not G:
        return {"gws": gws, "drafts": [], "n_sims": 0}

    mu = np.zeros((P, G))
    for c in codes:
        for j, g in enumerate(gws):
            mu[ci[c], j] = max(0.0, float(proj.points(c, g)))

    cv = _player_uncertainty(board, codes)
    rate = rng.normal(1.0, np.array([cv[c] for c in codes]), size=(S, P))
    rate = np.clip(rate, 0.15, 2.2)

    sd = np.sqrt(np.maximum(mu, 0.4) * MATCH_OVERDISPERSION)
    noise = rng.normal(0.0, 1.0, size=(S, P, G)) * sd[None, :, :]

    # A gameweek score cannot be negative in any way that matters here.
    realised = np.maximum(mu[None, :, :] * rate[:, :, None] + noise, 0.0)

    out = []
    for e in entries:
        # Weight per (player, gameweek): 1 if starting, 2 if captain, and the
        # bench joins in the Boost week.
        w = np.zeros((P, G))
        phases = sorted(e["phases"], key=lambda t: t[0])
        for j, g in enumerate(gws):
            sq = phases[0][1]
            for start, cand in phases:
                if g >= start:
                    sq = cand
            sq_codes = [int(c) for c in sq["code"]]
            xi = best_xi(sq, proj, g)
            cap = max(xi, key=lambda c: proj.points(c, g)) if xi else None
            boosted = e.get("bench_boost_gw") == g
            for c in sq_codes:
                if c not in ci:
                    continue
                if c in xi:
                    w[ci[c], j] = 2.0 if c == cap else 1.0
                elif boosted:
                    w[ci[c], j] = 1.0
            if cap is not None and boosted and cap in ci:
                w[ci[cap], j] = 2.0

        weekly = np.einsum("spg,pg->sg", realised, w)
        cum = np.cumsum(weekly, axis=1)
        out.append({
            "name": e["name"],
            "weekly_mean": weekly.mean(axis=0).round(2).tolist(),
            "cum_mean": cum.mean(axis=0).round(1).tolist(),
            "cum_lo": np.percentile(cum, 10, axis=0).round(1).tolist(),
            "cum_hi": np.percentile(cum, 90, axis=0).round(1).tolist(),
            "total_mean": float(cum[:, -1].mean().round(1)),
            "total_lo": float(np.percentile(cum[:, -1], 10).round(1)),
            "total_hi": float(np.percentile(cum[:, -1], 90).round(1)),
            "_totals": cum[:, -1],
        })

    # Pairwise and overall win probabilities, on the same draws.
    #
    # Ties count as half, and that is not a nicety. Shared draws mean two drafts
    # holding the same fifteen produce byte-identical totals, so a strict `>`
    # scores each of them "beats the other 0% of the time" · which reads as
    # "both lose" instead of "dead heat". Splitting ties gives 0.5, which is
    # what `significance` already interprets correctly as a coin flip.
    totals = np.vstack([d["_totals"] for d in out])
    top = totals.max(axis=0)
    leaders = (totals == top)                    # ties share the credit
    share = leaders / leaders.sum(axis=0, keepdims=True)
    for i, d in enumerate(out):
        d["p_best"] = float(share[i].mean().round(3))
        d["beats"] = {
            out[j]["name"]: float(((totals[i] > totals[j]).mean()
                                   + 0.5 * (totals[i] == totals[j]).mean()).round(3))
            for j in range(len(out)) if j != i}
        del d["_totals"]

    return {"gws": gws, "drafts": out, "n_sims": S}


def significance(a: Dict, b: Dict) -> Dict:
    """Read a pairwise probability as a decision rather than a number.

    Deliberately conservative. Anything inside 65/35 is reported as a coin flip,
    because a projection that validates at Spearman 0.4 does not earn finer
    resolution than that.
    """
    p = a["beats"].get(b["name"], 0.5)
    gap = a["total_mean"] - b["total_mean"]
    if p >= 0.80:
        call, tone = "clear", "mint"
    elif p >= 0.65:
        call, tone = "lean", "gold"
    else:
        call, tone = "coin flip", "muted"
    if call == "coin flip":
        text = (f"<b>No statistical difference.</b> {a['name']} finishes ahead of "
                f"{b['name']} in {p * 100:.0f}% of simulations, and the mean gap of "
                f"{gap:+.1f} points sits well inside the spread of both. Pick on "
                f"the football, not on this number.")
    else:
        text = (f"<b>{a['name']} is the {call} pick</b>, ahead in {p * 100:.0f}% of "
                f"simulations by an average of {gap:+.1f} points.")
    return {"p": p, "gap": round(gap, 1), "call": call, "tone": tone, "text": text}


def walk_route(spec: Dict, phases: List, proj, board: pd.DataFrame,
               gw_lo: int = 1, gw_hi: int = 10) -> Dict:
    """Week by week, what a chip route actually does.

    Answers the question a route name does not: what the Boost is worth in the
    week it is played, what carrying an all-playing fifteen costs in the weeks
    around it, what the Wildcard changes, and where the free transfers are by the
    time you get there.
    """
    from analytics.gw_projection import best_xi

    bb, wc = spec.get("bench_boost_gw"), spec.get("wildcard_gw")
    names = {}
    for _g, sq in phases:
        names.update({int(r["code"]): str(r["web_name"]) for _, r in sq.iterrows()})

    def squad_at(gw):
        sq = phases[0][1]
        for start, cand in sorted(phases, key=lambda t: t[0]):
            if gw >= start:
                sq = cand
        return sq

    weeks = []
    for gw in range(gw_lo, gw_hi + 1):
        sq = squad_at(gw)
        codes = [int(c) for c in sq["code"]]
        xi = best_xi(sq, proj, gw)
        xi_pts = sum(proj.points(c, gw) for c in codes if c in xi)
        bench_pts = sum(proj.points(c, gw) for c in codes if c not in xi)
        dead = [names.get(c, "?") for c in codes
                if c not in xi and proj.points(c, gw) < 1.0]
        weeks.append({
            "gw": gw, "xi": round(xi_pts, 1), "bench": round(bench_pts, 1),
            "total": round(xi_pts + (bench_pts if bb == gw else 0), 1),
            "boost": bb == gw, "wildcard": wc == gw, "dead_bench": dead,
        })

    # What the Boost returns, against what the bench is worth in a normal week.
    #
    # Note what this is NOT: it is not the cost of carrying an all-playing
    # fifteen. That cost is XI strength given up by spending on the bench, and
    # it needs a second solve to measure · `season_opener.bb_dilution` already
    # does it properly and the Chip route tab shows it. Inventing a cheaper
    # version here would put a confident wrong number on screen.
    #
    # What it DOES answer is the timing question: a bench worth less in the
    # boost week than in an average week means the chip is being played when the
    # bench is at its weakest, which is a reason to move the week.
    boost_week = next((w for w in weeks if w["boost"]), None)
    other = [w for w in weeks if not w["boost"] and (wc is None or w["gw"] < wc)]
    idle = round(float(np.mean([w["bench"] for w in other])), 1) if other else 0.0
    timing = None
    if boost_week and idle > 0.3:
        delta = boost_week["bench"] - idle
        timing = {
            "delta": round(delta, 1),
            "verdict": ("the bench is at its strongest that week"
                        if delta > 1.5 else
                        "the bench is weaker that week than usual · a later Boost "
                        "catches more" if delta < -1.5 else
                        "the bench is about as strong as any other week"),
        }

    # The Wildcard: who goes, who arrives, and what the reset is worth over the
    # six weeks that follow it (the only window it can be judged on).
    wc_change = None
    if wc and len(phases) > 1:
        before = set(int(c) for c in phases[0][1]["code"])
        after = set(int(c) for c in squad_at(wc)["code"])
        hi = min(gw_hi, wc + 5)
        old_sq, new_sq = phases[0][1], squad_at(wc)

        def _window(sq):
            cs = [int(c) for c in sq["code"]]
            return sum(proj.points(c, g) for g in range(wc, hi + 1)
                       for c in cs if c in best_xi(sq, proj, g))

        wc_change = {
            "gw": wc, "out": [names.get(c, "?") for c in before - after],
            "in": [names.get(c, "?") for c in after - before],
            "changes": len(after - before),
            "gain": round(_window(new_sq) - _window(old_sq), 1),
            "window": (wc, hi),
        }

    # Free transfers banked by the reset. Every week you do not transfer adds
    # one, capped at 5, and arriving at a Wildcard with a full bank is the
    # flexibility argument for going early.
    ft_at_wc = min(5, max(0, (wc - 1))) if wc else min(5, gw_hi - 1)

    return {
        "bench_boost_gw": bb, "wildcard_gw": wc, "weeks": weeks,
        "boost_return": boost_week["bench"] if boost_week else None,
        "idle_bench": idle,
        "timing": timing,
        "wildcard": wc_change,
        "ft_at_wildcard": ft_at_wc,
        "total": round(sum(w["total"] for w in weeks), 1),
    }


def compare_drafts(a: Dict, b: Dict, label_a: str = "A", label_b: str = "B") -> Dict:
    """Which draft is better over the window, and the reasons behind the gap."""
    gap = a["total"] - b["total"]
    win, lose = (a, b) if gap >= 0 else (b, a)
    win_lbl, lose_lbl = (label_a, label_b) if gap >= 0 else (label_b, label_a)

    reasons = []

    # 1. The chip. Where it is played is usually the single biggest lever, and
    #    it is the thing the two plans most often differ on.
    if a["bench_boost_gw"] != b["bench_boost_gw"]:
        bb_gap = a["bench_boost_gain"] - b["bench_boost_gain"]
        better = label_a if bb_gap >= 0 else label_b
        reasons.append({
            "kind": "chip",
            "text": (f"Bench Boost: {label_a} plays it in "
                     f"GW{a['bench_boost_gw'] or '-'} for "
                     f"{a['bench_boost_gain']:.1f}, {label_b} in "
                     f"GW{b['bench_boost_gw'] or '-'} for "
                     f"{b['bench_boost_gain']:.1f}. Worth "
                     f"{abs(bb_gap):.1f} more to {better}."),
            "delta": round(bb_gap, 1),
        })
        for d in (a, b):
            wk = next((w for w in d["weeks"] if w["boosted"]), None)
            if wk and wk["dead"]:
                reasons.append({
                    "kind": "warning",
                    "text": (f"{label_a if d is a else label_b} boosts a bench with "
                             f"{len(wk['dead'])} player(s) not expected to play: "
                             f"{', '.join(wk['dead'])}. That is the chip half wasted."),
                    "delta": 0.0,
                })

    # 2. Captaincy over the window.
    cap_gap = a["captain_points"] - b["captain_points"]
    if abs(cap_gap) >= 3:
        reasons.append({
            "kind": "captain",
            "text": (f"Captaincy is worth {abs(cap_gap):.1f} more to "
                     f"{label_a if cap_gap > 0 else label_b} over the window · a "
                     f"stronger armband is a doubled edge every single week."),
            "delta": round(cap_gap, 1),
        })

    # 3. Where the weekly gap actually opened up.
    per_week = [(wa["gw"], round(wa["points"] - wb["points"], 1))
                for wa, wb in zip(a["weeks"], b["weeks"])]
    big = sorted(per_week, key=lambda t: -abs(t[1]))[:2]
    for gw, d in big:
        if abs(d) >= 2:
            reasons.append({
                "kind": "week",
                "text": (f"GW{gw} is the biggest single swing: "
                         f"{abs(d):.1f} to {label_a if d > 0 else label_b}."),
                "delta": d,
            })

    # 4. Money left on the table.
    if abs(a["cost"] - b["cost"]) >= 0.5:
        cheaper = label_a if a["cost"] < b["cost"] else label_b
        reasons.append({
            "kind": "budget",
            "text": (f"{cheaper} spends £{abs(a['cost'] - b['cost']):.1f}m less "
                     f"for that return, which is a transfer of headroom rather "
                     f"than a points difference."),
            "delta": 0.0,
        })

    # 5. Squad overlap · a small gap between near-identical squads is noise.
    shared = len(a["codes"] & b["codes"])
    close = abs(gap) < 6
    verdict = (f"<b>{win_lbl} wins by {abs(gap):.1f} points</b> over the window."
               if not close else
               f"<b>{win_lbl} edges it by {abs(gap):.1f} points</b>, which is inside "
               f"the noise of the projection. Treat these as level and pick on "
               f"the football.")
    return {
        "winner": win_lbl, "loser": lose_lbl, "gap": round(gap, 1),
        "close": close, "verdict": verdict, "reasons": reasons,
        "shared": shared, "differs": 15 - shared,
        "per_week": per_week,
    }
