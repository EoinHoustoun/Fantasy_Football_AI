"""Consensus projections · three models, one number, an honest spread.

We now hold three independent reads on 2026-27:

  ours   `analytics/season_projection` · per-90 rate x fitted minutes, carried
         over from 25/26 and regressed across nine season-pairs. Validated at
         Spearman ~0.4 with a +/-38 point average error.
  scout  Fantasy Football Scout's season model (Rate My Team). Independent
         inputs, independent assumptions, season-long horizon.
  ffh    Fantasy Football Hub's predictions tool. Fixture-by-fixture rather than
         season-long, and the only one that publishes EXPECTED MINUTES.

Three things fall out of holding them together, and each is a real improvement
over any one of them:

1. **A blended point estimate.** Averaging independent models beats picking one,
   because their errors are not perfectly correlated. Weights below are set by
   what each model is actually good at, not by how much we like it.
2. **Disagreement as confidence.** Where the three agree, the number is worth
   trusting. Where they scatter, it is a coin flip wearing a decimal point. This
   is a better confidence signal than minutes-sample size alone, because it
   catches the cases where every model is guessing about the same new manager.
3. **A real minutes prior.** Our model infers minutes from last season. FFH
   states them. For a player whose role changed, the stated number is the one
   that is not stale.

Scale is handled before anything is blended. The three models do not agree on
what a season is worth (ours runs around 0.7x Scout's), so a raw comparison
ranks players by that offset instead of by disagreement. Everything below is
rescaled onto OUR scale first via a robust median ratio.
"""
import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# A full Premier League season, in gameweeks.
SEASON_GWS = 38

# Blend weights, and why each is what it is:
#   ours  · the only model validated on this codebase's own backtest, but it is
#           a pure carryover and blind to role change.
#   scout · a genuinely independent season model, the strongest single check we
#           have on a season total.
#   ffh   · match-level and minutes-aware, which makes it the best short-horizon
#           read by some distance. Its SEASON figure is a four-gameweek window
#           extrapolated to 38, and the Hub deliberately does not look far ahead,
#           so it is deliberately the smallest season weight (0.15). None of this
#           touches the per-gameweek numbers, where it is the primary source.
# The Hub earns more than the 0.15 it started with. It is the only source that
# forecasts a specific fixture with stated minutes, it is refreshed by hand so
# it tracks news our carryover model cannot see, and where it has a real record
# to work from it has been the sharpest of the three on minutes. Our own model
# gives up the most, because carryover from last season is the weakest evidence
# about this one.
#
# It does NOT get more weight where it cannot see: a player with no Premier
# League record has the Hub excluded from the season blend entirely, and his
# per-gameweek cells damped, both handled elsewhere in this module and in
# gw_projection.
SEASON_WEIGHTS = {"ours": 0.35, "scout": 0.40, "ffh": 0.25}

# Below this many matched players a scale ratio is noise, so fall back to 1.0
# and say so rather than rescaling everything by an accident.
MIN_SCALE_SAMPLE = 25

# Expected minutes per gameweek, as a share of 90, below which FFH's window is
# reporting availability rather than a scoring rate · see `ffh_season_equivalent`.
MIN_NAILEDNESS_FOR_SEASON = 0.5

# Disagreement -> confidence. The spread is a coefficient of variation across
# the rescaled sources, so it is unit-free and comparable between a 50-point
# defender and a 240-point striker.
SPREAD_TIERS = ((0.12, "High"), (0.25, "Medium"))


def robust_scale(ours: pd.Series, theirs: pd.Series,
                 min_points: float = 40.0) -> float:
    """Median of ours/theirs over players both models rate · our scale vs theirs.

    Median, not mean: one disagreement about a single player should not move the
    scale for everyone. Restricted to players the other model rates above
    `min_points` because the ratio explodes near zero.
    """
    m = pd.DataFrame({"a": pd.to_numeric(ours, errors="coerce"),
                      "b": pd.to_numeric(theirs, errors="coerce")}).dropna()
    m = m[m["b"] >= min_points]
    if len(m) < MIN_SCALE_SAMPLE:
        logger.info("scale sample too small (%d) · using 1.0", len(m))
        return 1.0
    return float((m["a"] / m["b"]).median())


def ffh_season_equivalent(matched: pd.DataFrame,
                          ease_by_team: Optional[Dict] = None) -> pd.Series:
    """Turn FFH's short-window total into a season-equivalent on FFH's own scale.

    The window is the opening gameweeks, so its mean points per gameweek carries
    the ease of THOSE fixtures. Multiplying straight up to 38 would hand a season
    bonus to whoever opens against promoted clubs. Divide the ease back out
    first, using the same fixture-ease model the draft and Chip Planner share, so
    the number means "over a neutral season" rather than "if every week were
    gameweek one".
    """
    if "ffh_pts_per_start" not in matched.columns:
        return pd.Series(np.nan, index=matched.index)
    per_gw = pd.to_numeric(matched["ffh_pts_per_start"], errors="coerce")

    # A zero here is an EMPTY sample, not a forecast. FFH returns zero for
    # anyone it expects no minutes from in the window · injured, suspended, back
    # late from a tournament, or third choice today. Saliba at zero means "not in
    # the opening month", not "will not score a point all season". Blending that
    # as a season projection drags a genuine starter's number to a third of what
    # every other model says. Treat it as missing here and let the per-gameweek
    # view, where "he is not playing" IS the answer, keep the zero.
    blank = per_gw.fillna(0) <= 0
    if "nailedness" in matched.columns:
        # Same argument one step softer. A player FFH expects under ~45 minutes
        # a game from in the window is being told about AVAILABILITY, not about
        # a scoring rate: he is injured, suspended, easing back, or third choice
        # this month. Extrapolating that to 38 gameweeks says Welbeck will score
        # a tenth of what two season models say, which is not a disagreement,
        # it is a category error. Below the cut FFH still drives the per-gameweek
        # view and the early-minutes warning · it just stops voting on a season.
        nailed = pd.to_numeric(matched["nailedness"], errors="coerce").fillna(0)
        blank = blank | (nailed < MIN_NAILEDNESS_FOR_SEASON)
    elif "exp_mins_mean" in matched.columns:
        blank = blank | (pd.to_numeric(matched["exp_mins_mean"], errors="coerce").fillna(0) <= 0)
    per_gw = per_gw.mask(blank)

    season = per_gw * SEASON_GWS
    if ease_by_team and "team_id" in matched.columns:
        ease = matched["team_id"].map(
            lambda t: float(ease_by_team.get(int(t), 1.0) or 1.0))
        # Guard a pathological ease of ~0 from turning into a division blow-up.
        season = season / ease.clip(lower=0.6, upper=1.6)
    return season.round(1)


def _is_echo(board: pd.DataFrame, ours: pd.Series, scout: pd.Series,
             tol: float = 0.15) -> pd.Series:
    """Rows where "our" projection is really the Scout number coming back.

    Two independent signals, either of which is enough:

      * `projection_source == "scout"` · the board says outright that this row
        was backfilled, which is the reliable case.
      * the two numbers are within `tol` points after rescaling · a fallback
        for boards built before that column existed.
    """
    both = ours.notna() & scout.notna()

    # Prefer the column. Scout is rescaled onto our scale before blending, so
    # two genuinely independent projections can land within a rounding step of
    # each other by coincidence · using the numeric test when we have the real
    # answer would throw away a real second opinion.
    if "projection_source" in board.columns:
        return (board["projection_source"].astype(str) == "scout") & both

    return ((ours - scout).abs() <= tol).fillna(False) & both


def _spread_to_confidence(spread: float, n_sources: int) -> str:
    """Confidence from how far the models are apart, not from how many there are.

    A single source is never High: agreement is the evidence, and one model
    cannot agree with anything.
    """
    if n_sources < 2 or not np.isfinite(spread):
        return "Low"
    tier = "Low"
    for cut, label in SPREAD_TIERS:
        if spread <= cut:
            tier = label
            break
    # Two models agreeing is encouraging, not proof · cap them at Medium so
    # "High" always means three independent reads landed in the same place.
    if n_sources < 3 and tier == "High":
        return "Medium"
    return tier


def build_consensus(board: pd.DataFrame,
                    scout_matched: Optional[pd.DataFrame] = None,
                    ffh_matched: Optional[pd.DataFrame] = None,
                    ease_by_team: Optional[Dict] = None) -> Tuple[pd.DataFrame, Dict]:
    """Blend the available models onto the board.

    `scout_matched` / `ffh_matched` are the frames returned by each source's
    `match_to_board`, or None when that snapshot is absent. Missing sources are
    dropped and the weights renormalised, so the function degrades to "our model
    only" without special-casing anywhere else.

    Returns (board + consensus columns, diagnostics).
    """
    out = board.copy()
    ours = pd.to_numeric(out.get("projected_points"), errors="coerce")

    diag = {"sources": ["ours"], "scale_scout": None, "scale_ffh": None,
            "n_scout": 0, "n_ffh": 0}
    cols = {"ours": ours}

    # ── Scout · season model, rescaled onto ours ──────────────────────────────
    if scout_matched is not None and not scout_matched.empty and "scout_pts" in scout_matched.columns:
        s = scout_matched.set_index("code")["scout_pts"]
        aligned = out["code"].map(s)
        k = robust_scale(ours, aligned)
        cols["scout"] = (aligned * k).round(1)
        diag.update(scale_scout=round(k, 3), n_scout=int(aligned.notna().sum()))
        diag["sources"].append("scout")

    # ── FFH · window model, seasonalised then rescaled onto ours ──────────────
    if ffh_matched is not None and not ffh_matched.empty:
        f = ffh_matched.copy()
        f["_ffh_season"] = ffh_season_equivalent(f, ease_by_team)
        by_code = f.set_index("code")

        # Minutes signals ride along · they are the reason FFH is here at all.
        # Mapped from EVERY matched row, not just the ones that vote on a season
        # total: a player excluded from the blend for having no early minutes is
        # precisely the player whose minutes we most want on screen.
        for src, dst in (("nailedness", "ffh_nailedness"),
                         ("exp_mins_next", "ffh_exp_mins_next"),
                         ("exp_mins_mean", "ffh_exp_mins_mean"),
                         ("mins_volatility", "ffh_mins_volatility"),
                         ("ffh_pts_per_start", "ffh_pts_per_gw")):
            if src in by_code.columns:
                out[dst] = out["code"].map(by_code[src])

        aligned = out["code"].map(by_code["_ffh_season"].dropna())
        k = robust_scale(ours, aligned)
        cols["ffh"] = (aligned * k).round(1)
        diag.update(scale_ffh=round(k, 3), n_ffh=int(aligned.notna().sum()))
        diag["sources"].append("ffh")

        # Thin early minutes is a flag worth showing, even though it is
        # deliberately excluded from the season blend above. It is the earliest
        # warning we get that a player misses the opening weeks · an injury, a
        # suspension, or a late return from a tournament.
        if "ffh_nailedness" in out.columns:
            n = pd.to_numeric(out["ffh_nailedness"], errors="coerce")
            out["ffh_no_early_minutes"] = n.notna() & (n < MIN_NAILEDNESS_FOR_SEASON)

    for name, series in cols.items():
        out["src_%s" % name] = series

    src_names = [n for n in ("ours", "scout", "ffh") if n in cols]
    frame = pd.DataFrame({n: cols[n] for n in src_names})

    # ── One number is not two models ──────────────────────────────────────────
    # A promoted-club or new-signing player has no Premier League record, so
    # "our" projection for him IS the Scout backfill · the same figure arriving
    # twice. Blending it as two independent reads gave Scout 0.85 of the weight
    # instead of 0.45 AND reported three-model confidence off two, so 14
    # promoted-club punts were being shown as "High" on the strength of a single
    # opinion. That is the mechanism behind O'Shea reading too strong.
    #
    # Blank OURS rather than Scout: Scout is the actual source, and keeping the
    # column that is really his own keeps the diagnostics honest.
    if "ours" in frame.columns and "scout" in frame.columns:
        dup = _is_echo(out, frame["ours"], frame["scout"])
        if dup.any():
            frame.loc[dup, "ours"] = np.nan
            out["consensus_echoed_scout"] = dup
            logger.info("consensus: %d players had ours == scout (backfill), "
                        "dropped the duplicate read", int(dup.sum()))

            # And the Hub does not get a SEASON vote on these players either.
            # Its number is a four-gameweek match forecast multiplied out to 38.
            # For someone with no Premier League record that extrapolation is
            # the least reliable figure in the stack, and it shows: measured
            # against Scout, the Hub runs 1.37x on promoted-club players against
            # 0.96x on established ones · 43% high. Nothing about the opening
            # fixtures explains it (ease 0.968 against 0.992); it is the
            # extrapolation itself assuming an opening month holds for a season,
            # when promoted sides fade and rotate.
            #
            # Same principle as the zero-sample rule above: the Hub keeps the
            # per-gameweek view, where it IS a real forecast, and keeps supplying
            # the minutes signal. It just stops voting on a season it cannot see.
            if "ffh" in frame.columns:
                frame.loc[dup, "ffh"] = np.nan
    if "consensus_echoed_scout" not in out.columns:
        out["consensus_echoed_scout"] = False

    # Weighted mean over whatever each row actually has, weights renormalised
    # per row. A player only our model can see keeps our number rather than
    # being penalised for the other two never having heard of him.
    w = pd.Series({n: SEASON_WEIGHTS[n] for n in src_names})
    present = frame.notna()
    wsum = present.mul(w, axis=1).sum(axis=1)
    blended = frame.mul(w, axis=1).sum(axis=1, min_count=1) / wsum.replace(0, np.nan)

    out["consensus_points"] = blended.round(1)
    out["n_models"] = present.sum(axis=1).astype(int)

    # Disagreement · a coefficient of variation so it compares across scales.
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0)
    out["model_spread"] = (std / mean.replace(0, np.nan)).round(3)
    out["consensus_confidence"] = [
        _spread_to_confidence(sp, n)
        for sp, n in zip(out["model_spread"].fillna(np.inf), out["n_models"])]

    # The range is the disagreement made concrete. One model wide of the others
    # is exactly the case where a point estimate lies to you.
    out["consensus_lo"] = (frame.min(axis=1)).round(0)
    out["consensus_hi"] = (frame.max(axis=1)).round(0)

    # Our season numbers sit on our own compressed scale. The per-match model
    # speaks in real FPL points ("Haaland, 7.9 this week"), so anything that
    # mixes the two on one screen needs a conversion. Carried as a column
    # because Streamlit's cache does not preserve DataFrame.attrs.
    out["points_scale_to_match"] = round(
        1.0 / diag["scale_ffh"], 4) if diag.get("scale_ffh") else 1.0

    diag["coverage"] = {
        "all_three": int((out["n_models"] == 3).sum()),
        "two": int((out["n_models"] == 2).sum()),
        "ours_only": int((out["n_models"] == 1).sum()),
    }
    return out, diag


def biggest_disagreements(board: pd.DataFrame, n: int = 20,
                          min_points: float = 60.0) -> pd.DataFrame:
    """Where the models fall out · the shortlist worth a human read.

    Filtered to players at least one model rates highly, because two models
    disagreeing about a fourth-choice fullback is not a decision.
    """
    need = {"consensus_points", "model_spread", "n_models"}
    if not need.issubset(board.columns):
        return pd.DataFrame()
    d = board[(board["n_models"] >= 2)
              & (board["consensus_hi"] >= min_points)].copy()
    if d.empty:
        return d
    d["gap"] = (d["consensus_hi"] - d["consensus_lo"]).round(0)
    keep = [c for c in ("web_name", "team_name", "position", "actual_price",
                        "src_ours", "src_scout", "src_ffh", "consensus_points",
                        "gap", "model_spread", "consensus_confidence",
                        "ffh_nailedness")
            if c in d.columns]
    return d.nlargest(n, "model_spread")[keep]
