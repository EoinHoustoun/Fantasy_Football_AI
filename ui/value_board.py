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
def build_board(stamp: str = "") -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame],
                                          Optional[dict], Optional[dict]]:
    """Cached wrapper · the work is in `_build_board`.

    Two layers on purpose. Streamlit's cache holds this for the life of a
    process; the disk layer underneath survives a restart AND survives the stamp
    moving, which it does every time an override file is edited. Measured, the
    build is 3.9 seconds and the disk read is about a tenth of that, so an
    override edit used to cost four seconds on the next interaction.
    """
    from data import disk_cache
    payload = disk_cache.cached(
        "value_board", stamp or "nostamp",
        lambda: dict(zip(("verdicts", "scout", "bt", "validation"),
                         _build_board(stamp))))
    disk_cache.prune("value_board")
    return (payload.get("verdicts"), payload.get("scout"),
            payload.get("bt"), payload.get("validation"))


def _build_board(stamp: str = "") -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame],
                                           Optional[dict], Optional[dict]]:
    """Return (verdicts_df, scout_df, price_backtest, projection_validation).

    verdicts_df: every player with a 25/26 projection AND a live price, annotated
    with actual_price, value_score, pricing_surprise, verdict, verdict_reason.
    scout_df: live players with no 25/26 history (promoted / new signings).
    Both are None if the archive has not been built.

    `stamp` is unused inside the body and is the whole point: it is
    `freshness.inputs_stamp()`, so refreshing a Scout or Hub snapshot on disk
    changes the cache key. Without an argument this cached for six hours flat,
    which meant a fresh snapshot did nothing until the TTL expired or the
    sidebar's Refresh Data was pressed. Every downstream cache keys off the
    board, so this one function going stale froze the entire page.
    """
    del stamp  # cache key only
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

    # ── Second rescue · players only the Hub has heard of ────────────────────
    # The Scout backfill above covers promoted clubs, because Scout's table
    # covers them. It does NOT cover a signing from another league, whose Scout
    # row simply does not exist · and a player missing from the board is missing
    # from the optimiser, every table, and the pitch. He does not look like a bad
    # pick, he looks like nothing at all.
    #
    # Runs AFTER the consensus so the Hub's no-record bias can be measured off a
    # finished board rather than assumed. These rows carry no consensus columns
    # of their own (one model cannot be a consensus) and are marked Low.
    if snap is not None and scout is not None and not scout.empty:
        try:
            from data.fetchers.ffhub import (backfill_from_hub,
                                             load_snapshot as _ffh_snap,
                                             no_record_deflator)
            hub_snap = _ffh_snap()
            left = scout[~scout["code"].isin(set(verdicts["code"]))]
            if hub_snap is not None and not left.empty:
                kf = float(verdicts.get("points_scale_to_match",
                                        pd.Series([1.0])).iloc[0] or 1.0)
                extra = backfill_from_hub(
                    left, hub_snap,
                    scale=(1.0 / kf) if kf else 1.0,
                    deflator=no_record_deflator(verdicts))
                if not extra.empty:
                    of = verdicts.set_index("team_id")["opening_factor"].to_dict() \
                        if "opening_factor" in verdicts.columns else {}
                    extra["opening_factor"] = extra["team_id"].map(of).fillna(1.0)
                    # One model is not a consensus · give them the same number
                    # under the name the rest of the page ranks on, so they sort
                    # and solve alongside everyone else without pretending to a
                    # confidence they have not got.
                    extra["consensus_points"] = extra["projected_points"]
                    extra["consensus_lo"] = extra["proj_lo"]
                    extra["consensus_hi"] = extra["proj_hi"]
                    extra["consensus_confidence"] = "Low"
                    extra["n_models"] = 1
                    extra["src_ffh"] = extra["projected_points"]
                    extra["ffh_nailedness"] = extra.get("nailedness")
                    extra["ffh_exp_mins_mean"] = extra.get("exp_mins_mean")
                    verdicts = pd.concat([verdicts, extra], ignore_index=True,
                                         sort=False)
                    scout = scout[~scout["code"].isin(set(extra["code"]))]
        except Exception as exc:
            logger.warning("Hub backfill failed: %s", exc)
            load_warnings.append("Players only the Hub covers (new signings from "
                                 "abroad) are missing from the pool.")

    # Some facts no model prices. A player expected to leave the league scores
    # nothing at all, and that is not a form haircut on OUR projection · it is a
    # statement about the blended number, because Scout and the Hub have not
    # heard either. `pts_mult` only touches our own component, so on a 0.35
    # weight a 0.65 multiplier moves the consensus by about 12%, which is not
    # what the call meant. `availability_mult` applies after the blend.
    try:
        from analytics.projection_overrides import load_overrides
        _av = {int(c): float(a["availability_mult"])
               for c, a in load_overrides().items()
               if a.get("availability_mult") is not None}
        if _av and "consensus_points" in verdicts.columns:
            _m = verdicts["code"].astype(int).map(_av)
            _hit = _m.notna()
            for _c in ("consensus_points", "consensus_lo", "consensus_hi",
                       "projected_points"):
                if _c in verdicts.columns:
                    verdicts.loc[_hit, _c] = (
                        pd.to_numeric(verdicts.loc[_hit, _c], errors="coerce")
                        * _m[_hit]).round(1)
            verdicts["availability_mult"] = _m.fillna(1.0)
            logger.info("availability multiplier applied to %d players", int(_hit.sum()))
        else:
            verdicts["availability_mult"] = 1.0
    except Exception as exc:
        logger.warning("availability overrides skipped: %s", exc)
        verdicts["availability_mult"] = 1.0

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

    # A name you can actually pick. Thirteen `web_name`s are shared by two or
    # three players · Palmer is a Chelsea midfielder AND an Ipswich goalkeeper,
    # Martinez is an Aston Villa keeper AND a Man Utd defender. Anything that
    # resolves a name with `board[board.web_name == n].iloc[0]` therefore picked
    # whichever happened to sort first, so locking "Palmer" could bind a £4.0m
    # keeper. Only the ambiguous ones get a club suffix, so the common case
    # still reads as a plain name.
    verdicts["uniq_name"] = _unique_names(verdicts)

    bt = dict(trained["backtest"][trained["winner"]])
    bt["model"] = trained["winner"]
    # Threaded through `bt` so a model input failing loudly reaches the page
    # instead of dying in a log line. Callers that ignore it are unaffected.
    bt["load_warnings"] = load_warnings
    return verdicts, scout, bt, validation


def _unique_names(df: pd.DataFrame) -> pd.Series:
    """The name you PICK by · club suffix where shared, plain spelling where accented.

    Two different problems, one column:

    1. Thirteen `web_name`s are shared, so "Palmer" alone is ambiguous.
    2. Nobody types Š. Streamlit's multiselect filters on the visible label and
       does not fold diacritics, so "sesko" finds nothing at all unless the
       plain spelling is IN the label. Hence "Šeško (Sesko)".

    Only the pickers use this column. The pitch, the tables and the player cards
    all render `web_name`, so the accents stay where they belong.
    """
    from analytics.squad_rules import fold_accents

    nm = df["web_name"].astype(str)
    dup = nm.duplicated(keep=False)
    club = df.get("team_short")
    if club is None:
        club = df.get("team_name", pd.Series([""] * len(df), index=df.index))
    out = nm.where(~dup, nm + " (" + club.astype(str).str.slice(0, 3).str.upper() + ")")

    plain = nm.map(fold_accents)
    accented = plain != nm.str.lower()
    return out.where(~accented, out + " (" + plain.str.title() + ")")


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
                force_names: tuple = (), bench_pts_col: Optional[str] = None,
                gw_pts_cols: tuple = (), boost_col: Optional[str] = None,
                min_club_cover: tuple = ()):
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
    `min_club_cover` is a tuple of (team_id, "def"|"att", n) demanding at least
    n players of that side of the pitch from that club · "I want Arsenal
    defensive cover" without naming which Arsenal defender. A tuple, not a list,
    so the Streamlit cache key stays stable.
    `bench_pts_col` names a column holding what each player scores in a Bench
    Boost week. Given one, a benched player is worth exactly that and the
    `bench_weight` fudge is dropped · which is the difference between "buy four
    cheap bodies" and "buy the fifteen that scores most with the chip on".
    """
    from analytics.squad_milp import optimize_squad

    def _code(name: str):
        # `uniq_name` first · `web_name` is shared by up to three players, so
        # matching on it alone could lock or veto a stranger.
        for col in ("uniq_name", "web_name"):
            if col in board.columns:
                m = board[board[col] == name]
                if not m.empty:
                    return int(m.iloc[0]["code"])
        return None

    # A premium call is a LOCK, not a strategy · the old branches that matched
    # "Haaland + Fernandes" and "no Haaland" out of the strategy string became
    # unreachable when those strategies were removed, and hardcoding two player
    # names into the solver was never going to survive a transfer window.
    force, exclude = (), tuple(c for c in (_code(n) for n in exclude_names) if c)
    bench = 1.0 if "Bench Boost" in strategy else 0.1

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
    # The risk blend BEFORE any fixture tilt. Per-gameweek columns already carry
    # each week's fixture in the number itself, so tilting them again would
    # count the same fixture twice · measured, that cost up to 7 points over
    # GW1-3 and made the weekly solve look worse than the fixed one. Risk is
    # about how certain a projection is, not about who the opponent is, so that
    # part does still belong.
    d["_obj_risk"] = d["obj"]

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

    # The bench column has to live on the same scale as the objective, or the
    # risk dial and the opening tilt would silently apply to the XI and not to
    # the bench. Carry each player's own obj/pts ratio across.
    _bcol = None
    if bench_pts_col and bench_pts_col in d.columns:
        # float("nan"), not pd.NA · dividing by pd.NA yields NAType, which
        # astype(float) refuses outright.
        _pts = pd.to_numeric(d["pts"], errors="coerce").replace(0, float("nan"))
        _ratio = pd.to_numeric(d["obj"], errors="coerce") / _pts
        d["_bench_obj"] = (pd.to_numeric(d[bench_pts_col], errors="coerce")
                           .fillna(0.0) * _ratio.fillna(1.0)).round(3)
        _bcol = "_bench_obj"

    # A weekly eleven, when the caller has per-gameweek columns to give.
    #
    # Each week is put on the objective's scale by the player's OWN obj/pts
    # ratio, exactly as the bench column is. Skipping that would apply the risk
    # dial and the opening tilt to the season number while the weekly numbers
    # went through raw, so the two halves of the objective would disagree about
    # what a point is worth.
    if gw_pts_cols:
        _pts = pd.to_numeric(d["pts"], errors="coerce").replace(0, float("nan"))
        _ratio = (pd.to_numeric(d["_obj_risk"], errors="coerce") / _pts).fillna(1.0)
        _cols, _boost = [], None
        for c in gw_pts_cols:
            if c not in d.columns:
                continue
            oc = "_obj_%s" % c
            d[oc] = (pd.to_numeric(d[c], errors="coerce").fillna(0.0) * _ratio).round(3)
            _cols.append(oc)
            if boost_col is not None and c == boost_col:
                _boost = oc
        if _cols:
            return optimize_squad(
                d, budget=budget, time_limit=90,
                gw_pts_cols=_cols, boost_col=_boost,
                force_codes=list(force), exclude_codes=list(exclude),
                max_attackers_per_club=max_attackers_per_club,
                defcon_codes=_defcon_codes(), max_defenders_per_club=1,
                min_club_cover=[tuple(c) for c in min_club_cover],
                bench_budget=bench_budget)

    return optimize_squad(d, budget=budget, pts_col="obj", bench_weight=bench, time_limit=90,
                          force_codes=list(force), exclude_codes=list(exclude),
                          max_attackers_per_club=max_attackers_per_club,
                          defcon_codes=_defcon_codes(),
                          max_defenders_per_club=1,
                          min_club_cover=[tuple(c) for c in min_club_cover],
                          bench_budget=bench_budget,
                          bench_pts_col=_bcol)
