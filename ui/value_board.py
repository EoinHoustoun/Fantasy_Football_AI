"""Shared 2026-27 value board builder.

Joins archive projections + the price model with FPL's actual 2026-27 prices and
runs the verdict engine. Cached once so both the 26/27 Draft (full board) and the
Playbook (a compact read) share the same computation.
"""
import logging
from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st

from config import LAST_COMPLETE_SEASON, NEXT_SEASON

logger = logging.getLogger(__name__)


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

    # No-history players (promoted clubs, new signings) carry no carryover
    # projection, so they were silently absent from the optimiser · every
    # Coventry, Hull and Ipswich player, including the £4.0m defenders that make
    # a squad affordable. Backfill them from the Scout snapshot when one exists.
    verdicts["projection_source"] = "model"
    load_warnings: List[str] = []
    k = 1.0
    snap = None
    try:
        from analytics.scout_projections import (backfill_projections, load_snapshot,
                                                 match_to_board, model_scale,
                                                 override_no_evidence)
        snap = load_snapshot()
    except Exception as exc:
        logger.warning("Scout snapshot unavailable: %s", exc)
        load_warnings.append("Scout snapshot did not load. Promoted-club players "
                             "may be missing from the pool.")

    if snap is not None:
        try:
            k = model_scale(match_to_board(snap, verdicts)["matched"])
            # A zero-minutes 25/26 row is an EMPTY sample, not a low forecast, and
            # it is worse than no row at all because the backfill below skips it.
            verdicts = override_no_evidence(verdicts, snap, scale=k)
        except Exception as exc:
            logger.warning("Scout scale/override failed: %s", exc)
            load_warnings.append("Scout scaling failed. Second-opinion "
                                 "projections are not in the blend.")

    # Promoted-club players have no Premier League record, so without this every
    # Coventry, Hull and Ipswich player · including the £4.0m defenders that make
    # a squad affordable · is silently absent from the optimiser. A broad
    # `except` here used to swallow that into a log line nobody reads, so the
    # failure is now narrow and surfaced in the UI.
    if snap is not None and scout is not None and not scout.empty:
        try:
            extra = backfill_projections(scout, snap, scale=k)
            if not extra.empty:
                extra = extra[~extra["code"].isin(set(verdicts["code"]))]
            if not extra.empty:
                of = verdicts.set_index("team_id")["opening_factor"].to_dict() \
                    if "opening_factor" in verdicts.columns else {}
                extra["opening_factor"] = extra["team_id"].map(of).fillna(1.0)
                verdicts = pd.concat([verdicts, extra], ignore_index=True, sort=False)
                verdicts = verdicts.sort_values("projected_points", ascending=False) \
                    .reset_index(drop=True)
                # Anyone backfilled is no longer "no data" · drop from the Scout lane.
                scout = scout[~scout["code"].isin(set(extra["code"]))]
                logger.info("backfilled %d no-history players from the Scout snapshot",
                            len(extra))
            else:
                load_warnings.append("No promoted-club players were backfilled. "
                                     "Check the Scout snapshot covers them.")
        except Exception as exc:
            logger.warning("Scout backfill failed: %s", exc)
            load_warnings.append("Promoted-club backfill failed. Coventry, Hull "
                                 "and Ipswich players are missing from the pool.")

    # ── Consensus · blend our carryover model with Scout and FFH ──────────────
    # Three independent reads beat one, and where they disagree is exactly where
    # a point estimate is lying to you. Also lands FFH's expected minutes on the
    # board · the only stated "will he start" signal in the stack.
    verdicts = _add_consensus(verdicts, live_bs)

    # Promoted sides defend more, so their DEFENDERS bank more DEFCON than any
    # carryover model expects · they have no Premier League record to carry over.
    # Derivation, evidence strength and why midfielders get nothing: see
    # analytics/promoted.py. Applied to the consensus because that is the number
    # the page ranks and optimises on, and recorded per row so it is auditable.
    try:
        from analytics.promoted import apply_defcon_bonus, promoted_clubs
        _pc = promoted_clubs(pd.DataFrame(live_bs.get("teams", [])))
        if _pc:
            _col = "consensus_points" if "consensus_points" in verdicts.columns \
                else "projected_points"
            verdicts = apply_defcon_bonus(verdicts, _pc, points_col=_col)
    except Exception as exc:
        logger.warning("promoted DEFCON bonus skipped: %s", exc)
        load_warnings.append("Promoted-club DEFCON adjustment did not apply.")

    bt = dict(trained["backtest"][trained["winner"]])
    bt["model"] = trained["winner"]
    # Threaded through `bt` so a model input failing loudly reaches the page
    # instead of dying in a log line. Callers that ignore it are unaffected.
    bt["load_warnings"] = load_warnings
    return verdicts, scout, bt, validation


def _add_consensus(verdicts: pd.DataFrame, live_bs: dict) -> pd.DataFrame:
    """Attach consensus columns. Never fatal · a missing snapshot just means
    fewer models in the blend, and `build_consensus` renormalises for that."""
    from analytics.consensus import build_consensus

    scout_matched = None
    try:
        from analytics.scout_projections import load_snapshot as _scout_snap, match_to_board as _scout_match
        snap = _scout_snap()
        if snap is not None:
            scout_matched = _scout_match(snap, verdicts)["matched"]
    except Exception as exc:
        logger.warning("Scout leg of the consensus skipped: %s", exc)

    ffh_matched, ease = None, None
    try:
        from data.fetchers.ffhub import load_snapshot as _ffh_snap, match_to_board as _ffh_match, window_gws
        snap = _ffh_snap()
        if snap is not None:
            ffh_matched = _ffh_match(snap, verdicts)["matched"]
            gws = window_gws(snap)
            if gws:
                from analytics.season_opener import opening_ease
                from data.fetchers.fpl_api import fetch_fixtures, get_fixtures_df
                fx = get_fixtures_df(fetch_fixtures(), live_bs)
                oe = opening_ease(fx, gws[0], gws[-1])
                ease = dict(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))
    except Exception as exc:
        logger.warning("FFH leg of the consensus skipped: %s", exc)

    try:
        out, diag = build_consensus(verdicts, scout_matched, ffh_matched, ease)
        logger.info("consensus built · %s", diag)
        return out
    except Exception as exc:
        logger.warning("consensus skipped: %s", exc)
        return verdicts


def _opening_factors(fixtures, cfg: dict) -> dict:
    """team_id -> mean fixture-ease over GW1..gw_hi (>1 easy, <1 hard).

    Thin shim · the implementation lives in `analytics.season_opener` so the
    draft weight and the route comparator cannot drift apart.
    """
    from analytics.season_opener import opening_factors
    return opening_factors(fixtures, cfg)


# Shared draft strategies. A strategy only earns a slot here when it changes the
# OBJECTIVE the solver optimises · the Bench Boost arms weight the bench, which
# no amount of locking players can express.
#
# The premium strategies that used to live here ("Safe · Haaland + Fernandes",
# "Punt · Fernandes, no Haaland") are gone: a premium call is just a LOCK on a
# saved draft, and keeping a second way to say the same thing meant the picker
# on the Draft page and the saved drafts in the comparison disagreed about what
# a draft is. `solve_draft` still understands the old names so a stale saved
# draft keeps working.
DRAFT_STRATEGIES = [
    "⚖️ Optimal value",
    "🔋 Bench Boost GW1",
    "🚀 Bench Boost GW2 → Wildcard GW4",
]

# The aggressive route: Boost in GW2, reset on a Wildcard in GW4. Nothing after
# GW3 matters to this squad because the Wildcard replaces it, so the draft is
# built on GW1-3 fixtures alone and every one of the fifteen has to play.
SPRINT_STRATEGY = "🚀 Bench Boost GW2 → Wildcard GW4"
SPRINT_WINDOW = (1, 3)


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
                opening_map: tuple = (), bench_budget=None,
                force_names: tuple = ()):
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
    `force_names` are players locked into the fifteen · the optimiser builds the
    best squad it can AROUND them. They win over `exclude_names` if a player
    somehow appears in both, because an explicit lock is the stronger intent.
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
        bench = 1.0          # covers both BB GW1 and the GW2 sprint route
    else:
        bench = 0.1

    # Explicit locks are added on top of whatever the strategy already forces, and
    # they beat a veto · picking a player and vetoing him is a mistake, not a rule.
    locks = tuple(c for c in (_code(n) for n in force_names) if c)
    if locks:
        force = tuple(dict.fromkeys(force + locks))
        exclude = tuple(c for c in exclude if c not in set(locks))

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
