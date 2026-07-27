"""Shared 2026-27 value board builder.

Joins archive projections + the price model with FPL's actual 2026-27 prices and
runs the verdict engine. Cached once so both the 26/27 Draft (full board) and the
Playbook (a compact read) share the same computation.
"""
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from config import LAST_COMPLETE_SEASON, NEXT_SEASON


@st.cache_data(ttl=6 * 3600, show_spinner="Pricing the board · projections vs actual 26/27 prices…")
def build_board() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame],
                           Optional[dict], Optional[dict]]:
    """Return (verdicts_df, scout_df, price_backtest, projection_validation).

    verdicts_df: every player with a 25/26 projection AND a live price, annotated
    with actual_price, value_score, pricing_surprise, verdict, verdict_reason.
    scout_df: live players with no 25/26 history (promoted / new signings).
    Both are None if the archive has not been built.
    """
    from data.processors.archive import load_season_summary
    from analytics.price_predictor import train_price_model, predict_next_season_prices
    from analytics.season_projection import project_season, validate_projection
    from analytics.value_verdicts import build_value_verdicts
    from data.fetchers.fpl_api import fetch_bootstrap

    summary = load_season_summary()
    if summary is None:
        return None, None, None, None

    trained = train_price_model(summary)
    prices = predict_next_season_prices(summary, trained)
    proj = project_season(summary, LAST_COMPLETE_SEASON)
    validation = validate_projection(summary)

    # Club / shirt identity now comes from the LIVE bootstrap inside the verdict
    # engine (transfers corrected), so we no longer read the stale archive teams.
    uni = proj.merge(prices[["code", "predicted_start_price", "price_2025_26_end"]], on="code")

    # nailed-ness signals used by the verdict engine + scout questions
    ss = (summary[summary["season"] == LAST_COMPLETE_SEASON]
          [["code", "starts_total", "games_played"]].copy())
    uni = uni.merge(ss, on="code", how="left")
    uni["mins_share"] = (uni["projected_minutes"] / 3420.0).clip(0, 1).round(2)
    uni["starts_ratio"] = (uni["starts_total"] / uni["games_played"]).round(2)

    # Defender role (CB/FB) · fullbacks are flagged harder-to-predict downstream.
    from analytics.playbook import _load_defender_roles
    roles = _load_defender_roles(NEXT_SEASON)   # {code: 'CB'|'FB'}
    uni["role"] = uni["code"].map(roles)

    # Club-change flag · a player whose 26/27 club differs from his 25/26 club has
    # an unproven fit in a new system (Senesi to Spurs), so lower his confidence.
    live_bs = fetch_bootstrap()

    def _code_to_club(bs: dict) -> dict:
        tc = {int(t["id"]): int(t.get("code", 0) or 0) for t in bs.get("teams", [])}
        return {int(e["code"]): tc.get(int(e.get("team", 0) or 0), 0) for e in bs.get("elements", [])}

    import json as _json
    from config import CACHE_DIR as _CD
    live_club = _code_to_club(live_bs)
    changed: set = set()
    arch_path = _CD / "archive" / "fpl_bootstrap_2025_26_final.json"
    if arch_path.exists():
        arch_club = _code_to_club(_json.load(open(arch_path)))
        changed = {c for c, lc in live_club.items()
                   if arch_club.get(c) and lc and lc != arch_club[c]}
    uni["changed_club"] = uni["code"].isin(changed)

    # Manual overrides · fitness / role / regression the model can't know.
    from analytics.projection_overrides import apply_overrides
    from analytics.projection_confidence import add_confidence
    uni = apply_overrides(uni)
    uni = add_confidence(uni)

    verdicts, scout = build_value_verdicts(uni, live_bs)

    # Opening-fixtures ease (GW1..gw_hi) per player · for the draft's opening weight.
    from config import OPENING_FIXTURES as _OF
    from data.fetchers.fpl_api import get_fixtures_df, fetch_fixtures
    try:
        fx = get_fixtures_df(fetch_fixtures(), live_bs)
        of = _opening_factors(fx, _OF)
        verdicts["opening_factor"] = verdicts["team_id"].map(of).fillna(1.0).round(3)
    except Exception:
        verdicts["opening_factor"] = 1.0

    bt = dict(trained["backtest"][trained["winner"]])
    bt["model"] = trained["winner"]
    return verdicts, scout, bt, validation


def _opening_factors(fixtures, cfg: dict) -> dict:
    """team_id -> mean fixture-ease over GW1..gw_hi (>1 easy, <1 hard).

    Thin shim · the implementation lives in `analytics.season_opener` so the
    draft weight and the route comparator cannot drift apart.
    """
    from analytics.season_opener import opening_factors
    return opening_factors(fixtures, cfg)


# Shared draft strategies · used by the 26/27 Draft page and the Chip Planner.
DRAFT_STRATEGIES = [
    "⚖️ Optimal value",
    "🛡️ Safe · Haaland + Fernandes",
    "🎲 Punt · Fernandes, no Haaland",
    "🔋 Bench Boost GW1",
]


def _defcon_codes() -> list:
    """DEFCON mids exempt from the one-attacker-per-club rule (editable JSON)."""
    import json
    from config import ROOT_DIR, NEXT_SEASON
    path = ROOT_DIR / "assets" / f"defcon_players_{NEXT_SEASON.replace('-', '_')}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [int(k) for k in raw if not str(k).startswith("_")]


@st.cache_data(ttl=6 * 3600, show_spinner="Solving optimal squad on actual prices (exact MILP)…")
def solve_draft(board: pd.DataFrame, strategy: str, budget: float = 100.0,
                risk: float = 0.3, exclude_names: tuple = (), opening: float = 0.0,
                max_attackers_per_club: int = 1,
                opening_map: tuple = (), bench_budget=None):
    """Solve one named draft strategy on ACTUAL prices.

    `risk` (0-1) sets the objective: 0 maximises the MEAN projection (upside),
    1 maximises the confidence FLOOR (safety) · in between blends them, so
    wide-range punts (low-confidence, fullbacks) get discounted as risk rises.
    `opening` (0-1) leans the objective toward players with soft GW1-6 fixtures,
    so the squad holds up longer before transfers. `exclude_names` are players to
    veto. Also applies the standing rule of at most one attack-correlated player
    per club (DEFCON mids exempt).

    `opening_map` is an optional ((team_id, factor), ...) tuple that REPLACES the
    board's stock GW1-6 factors · the route comparator uses it to build a squad
    for the fixtures that follow a wildcard rather than the ones before it. A
    tuple, not a dict, so the Streamlit cache key stays stable.
    `bench_budget` caps total bench spend, which is what makes a cheap-bench arm
    genuinely cheap rather than just unweighted.
    """
    from analytics.squad_milp import optimize_squad

    def _code(name: str):
        m = board[board["web_name"] == name]
        return int(m.iloc[0]["code"]) if not m.empty else None

    haaland, fernandes = _code("Haaland"), _code("B.Fernandes")
    is_safe = "Haaland + Fernandes" in strategy
    force, exclude = (), tuple(c for c in (_code(n) for n in exclude_names) if c)
    if is_safe:
        force = tuple(c for c in (haaland, fernandes) if c)
        bench = 0.2                      # a bench that actually plays
    elif "no Haaland" in strategy:
        force = tuple(c for c in (fernandes,) if c)
        exclude = exclude + tuple(c for c in (haaland,) if c)
        bench = 0.1
    elif "Bench Boost" in strategy:
        bench = 1.0
    else:
        bench = 0.1

    d = board.rename(columns={"actual_price": "price", "projected_points": "pts"})
    r = max(0.0, min(1.0, float(risk)))
    ow = max(0.0, min(1.0, float(opening)))
    d["obj"] = d["pts"] * (1.0 - r) + d["proj_lo"].fillna(d["pts"]) * r

    # A window-specific map wins over the board's stock GW1-6 factors, and it
    # implies the caller wants the tilt applied even when the slider is at zero.
    if opening_map:
        om = {int(t): float(f) for t, f in opening_map}
        of = d["team_id"].map(om).fillna(1.0)
        w = ow if ow > 0 else 1.0
        d["obj"] = d["obj"] * ((1.0 - w) + w * of)
    elif ow > 0 and "opening_factor" in d.columns:
        of = d["opening_factor"].fillna(1.0)
        d["obj"] = d["obj"] * ((1.0 - ow) + ow * of)

    return optimize_squad(d, budget=budget, pts_col="obj", bench_weight=bench, time_limit=90,
                          force_codes=list(force), exclude_codes=list(exclude),
                          max_attackers_per_club=max_attackers_per_club,
                          defcon_codes=_defcon_codes(),
                          max_defenders_per_club=1,
                          bench_budget=bench_budget)
