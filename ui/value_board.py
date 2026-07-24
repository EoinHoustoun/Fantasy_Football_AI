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

    # Manual overrides · fitness / role / regression the model can't know.
    from analytics.projection_overrides import apply_overrides
    from analytics.projection_confidence import add_confidence
    uni = apply_overrides(uni)
    uni = add_confidence(uni)

    verdicts, scout = build_value_verdicts(uni, fetch_bootstrap())

    bt = dict(trained["backtest"][trained["winner"]])
    bt["model"] = trained["winner"]
    return verdicts, scout, bt, validation


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
                max_attackers_per_club: int = 1):
    """Solve one named draft strategy on ACTUAL prices. Applies the standing
    preference of at most one attack-correlated player per club (DEFCON mids
    exempt). Returns the optimize_squad dict or None."""
    from analytics.squad_milp import optimize_squad

    def _code(name: str):
        m = board[board["web_name"] == name]
        return int(m.iloc[0]["code"]) if not m.empty else None

    haaland, fernandes = _code("Haaland"), _code("B.Fernandes")
    force, exclude, bench = (), (), 0.1
    if "Haaland + Fernandes" in strategy:
        force = tuple(c for c in (haaland, fernandes) if c)
    elif "no Haaland" in strategy:
        force = tuple(c for c in (fernandes,) if c)
        exclude = tuple(c for c in (haaland,) if c)
    elif "Bench Boost" in strategy:
        bench = 1.0

    d = board.rename(columns={"actual_price": "price", "projected_points": "pts"})
    return optimize_squad(d, budget=budget, bench_weight=bench, time_limit=90,
                          force_codes=list(force), exclude_codes=list(exclude),
                          max_attackers_per_club=max_attackers_per_club,
                          defcon_codes=_defcon_codes())
