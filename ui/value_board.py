"""Shared 2026-27 value board builder.

Joins archive projections + the price model with FPL's actual 2026-27 prices and
runs the verdict engine. Cached once so both the 26/27 Draft (full board) and the
Playbook (a compact read) share the same computation.
"""
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from config import LAST_COMPLETE_SEASON


@st.cache_data(ttl=6 * 3600, show_spinner="Pricing the board · projections vs actual 26/27 prices…")
def build_board() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame],
                           Optional[dict], Optional[dict]]:
    """Return (verdicts_df, scout_df, price_backtest, projection_validation).

    verdicts_df: every player with a 25/26 projection AND a live price, annotated
    with actual_price, value_score, pricing_surprise, verdict, verdict_reason.
    scout_df: live players with no 25/26 history (promoted / new signings).
    Both are None if the archive has not been built.
    """
    from data.processors.archive import load_gw_archive, load_season_summary
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

    arch = load_gw_archive()
    teams = (arch[arch["season"] == LAST_COMPLETE_SEASON]
             .groupby("code")["team_id"].last().reset_index())
    uni = (proj.merge(prices[["code", "predicted_start_price", "price_2025_26_end"]], on="code")
           .merge(teams, on="code"))

    # shirt / colour identity from the archived final bootstrap
    import json as _json
    from config import CACHE_DIR as _CD
    bs_path = _CD / "archive" / "fpl_bootstrap_2025_26_final.json"
    if bs_path.exists():
        with open(bs_path) as f:
            _bs = _json.load(f)
        tc_map = {int(e["code"]): int(e["team_code"]) for e in _bs["elements"]}
        uni["team_code"] = uni["code"].map(tc_map).fillna(1).astype(int)
        ts_map = {int(e["code"]): e.get("team") for e in _bs["elements"]}
        short_by_id = {int(t["id"]): t["short_name"] for t in _bs["teams"]}
        uni["team_short"] = uni["code"].map(ts_map).map(short_by_id)
    else:
        uni["team_code"] = 1
        uni["team_short"] = None

    # nailed-ness signals used by the verdict engine + scout questions
    ss = (summary[summary["season"] == LAST_COMPLETE_SEASON]
          [["code", "starts_total", "games_played"]].copy())
    uni = uni.merge(ss, on="code", how="left")
    uni["mins_share"] = (uni["projected_minutes"] / 3420.0).clip(0, 1).round(2)
    uni["starts_ratio"] = (uni["starts_total"] / uni["games_played"]).round(2)

    verdicts, scout = build_value_verdicts(uni, fetch_bootstrap())

    bt = dict(trained["backtest"][trained["winner"]])
    bt["model"] = trained["winner"]
    return verdicts, scout, bt, validation
