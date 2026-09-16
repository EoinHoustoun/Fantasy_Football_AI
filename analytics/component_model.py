"""Component points model · sandboxed alternative to `analytics/points_model`.

The incumbent regresses a player's TOTAL gameweek points directly. That asks one
squared-error model to learn a mixture of four different processes at once: a
did-he-play Bernoulli, a Poisson goal process, a team-level clean sheet, and a
bonus ranking. Measured on held-out gameweeks it explains essentially none of the
variance among likely starters, which is the only population a manager picks
from.

This model predicts the countable events instead and adds them up with the FPL
scoring table:

    E[pts] = P(play) + P(60+)                      appearance
           + E[goals]   x goal_pts[pos]
           + E[assists] x 3
           + P(clean sheet) x P(60+) x cs_pts[pos]
           - E[floor(conceded / 2)]                 GKP and DEF only
           + E[saves] / 3                           GKP only
           + E[bonus]
           + 2 x P(defensive contribution threshold)
           - E[yellows] - 3 x E[reds]

Three structural differences from the incumbent, each one a measured weakness of
it:

1. **Minutes are their own model.** Two of them: P(60+ minutes) and expected
   minutes. Every rate below is scaled by expected minutes, so a rotation risk is
   priced once, explicitly, instead of being smeared through a points average.
2. **The opponent is inside the model.** The incumbent applies a hand-set
   `1 + (3 - FDR) x 0.15` multiplier after the fact and never sees who the
   opponent is. Here each side of every historical fixture contributes a
   pre-match attack and defence rating (exponentially weighted, strictly past
   matches only), and those ratings are features of the goal, assist and
   conceded models.
3. **It trains on every season we hold, not just the current one.** The incumbent
   fits on this season alone, which is why it cannot exist at all in preseason.

Rates are fitted per 90 with a Poisson objective and minutes as the exposure
weight, so a 20-minute cameo does not carry the same weight as a full match.

Everything is shifted by one match. A row's features are built only from matches
that finished before it. See `prepare()`.

Python 3.8 typing. No Streamlit imports.
"""

from __future__ import annotations

import logging
from math import lgamma
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb

from config import FPL_ASSIST_PTS, FPL_CS_PTS, FPL_GOAL_PTS

logger = logging.getLogger(__name__)

# ── Scoring constants the config does not already carry ───────────────────────
SAVES_PER_POINT = 3
YELLOW_PTS = -1
RED_PTS = -3
OWN_GOAL_PTS = -2
PEN_MISS_PTS = -2
PEN_SAVE_PTS = 5
DC_PTS = 2

# Defensive-contribution thresholds (2025-26 rules). Defenders count
# clearances, blocks, interceptions and tackles; everyone else also counts ball
# recoveries, which is why their bar is higher.
DC_THRESHOLD = {"GKP": 99, "DEF": 10, "MID": 12, "FWD": 12}

# First season the two points were actually awarded.
DC_RULE_FROM = "2025-26"

# A rate fitted on a cameo is mostly noise, so rate models only see rows with a
# real sample of minutes.
MIN_MINUTES_FOR_RATE = 25

# Per-90 rates are clipped before fitting. A player who scores twice in 20
# minutes is a 9-goal-per-90 label that would otherwise dominate the loss.
RATE_CLIP = {"goals": 3.0, "assists": 3.0, "saves": 15.0, "bonus": 3.0,
             "dc": 30.0, "yellow": 2.0}

# Halflife in matches for the exponentially-weighted player form windows.
FORM_HALFLIFE = 3.0
# Halflife in matches for team attack / defence ratings. Longer, because team
# strength moves more slowly than an individual's form.
TEAM_HALFLIFE = 6.0

# Conceded distribution is summed out to here when pricing the -1 per 2 goals.
MAX_CONCEDED = 10

POSITIONS: List[str] = ["GKP", "DEF", "MID", "FWD"]

# Shared tree settings. Deliberately fixed rather than tuned: the point of the
# benchmark is the architecture, and an Optuna search on one arm only would
# flatter it.
_TREE = dict(n_estimators=350, max_depth=5, learning_rate=0.05,
             subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
             reg_lambda=1.5, random_state=42, n_jobs=-1, verbosity=0)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    """A numeric column, or an all-NaN one of the right length when it is absent.

    `pd.to_numeric(df.get(missing))` quietly returns a scalar NaN, which then
    fails on the first Series method. Seasons differ in which columns exist, so
    an absent column is the normal case here, not an error.
    """
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


# ── Team ratings ───────────────────────────────────────────────────────────────

def build_team_form(gw_df: pd.DataFrame) -> pd.DataFrame:
    """Pre-match attack and defence ratings for both sides of every fixture.

    A fixture's two sides are identified by `was_home`, never by `team_id`.
    `team_id` on the archive comes from the end-of-season player lookup, so a
    January transfer would otherwise attribute a player's autumn matches to his
    new club. `opponent_team` is recorded per appearance and is always right.

    Goals for are taken from the OTHER side's goals conceded rather than by
    summing the side's own scorers, so an own goal lands on the correct team.

    Returns one row per (season, fixture, was_home) with the ratings as they
    stood BEFORE that match.
    """
    need = {"season", "fixture", "was_home", "gw", "goals_conceded",
            "opponent_team", "kickoff_time"}
    missing = need - set(gw_df.columns)
    if missing:
        raise ValueError("build_team_form needs columns: %s" % sorted(missing))

    sides = (gw_df.groupby(["season", "fixture", "was_home"], as_index=False)
             .agg(gw=("gw", "max"),
                  conceded=("goals_conceded", "max"),
                  opponent=("opponent_team", lambda s: s.mode().iloc[0]
                            if not s.mode().empty else np.nan),
                  kickoff=("kickoff_time", "max")))

    # The other side of the same fixture: its opponent id IS this side's id, and
    # its goals conceded ARE this side's goals scored.
    other = sides.rename(columns={"was_home": "_wh", "conceded": "scored",
                                  "opponent": "team_id"})
    other["_wh"] = ~other["_wh"].astype(bool)
    sides = sides.merge(other[["season", "fixture", "_wh", "scored", "team_id"]],
                        left_on=["season", "fixture", "was_home"],
                        right_on=["season", "fixture", "_wh"], how="left")
    sides = sides.drop(columns=["_wh"])
    sides = sides.dropna(subset=["team_id"])
    sides["team_id"] = sides["team_id"].astype(int)

    # A club's rating has to follow the CLUB, not the id. FPL renumbers teams
    # alphabetically every summer, so id 3 was Bournemouth in 2024-25 and
    # Burnley in 2025-26. Grouping the exponentially-weighted ratings by id
    # therefore hands each promoted side the form of whoever happened to hold
    # its number last season. Names are stable, so they are the key.
    sides["team_key"] = _team_key(sides, gw_df)

    sides = sides.sort_values(["team_key", "season", "gw", "fixture"])
    g = sides.groupby("team_key")

    def _ewm(s: pd.Series) -> pd.Series:
        return s.shift(1).ewm(halflife=TEAM_HALFLIFE, min_periods=1).mean()

    sides["team_att"] = g["scored"].transform(_ewm)
    sides["team_def"] = g["conceded"].transform(_ewm)
    sides["team_matches"] = g.cumcount()

    # League mean at that point in time, so a rating is relative rather than
    # absolute. Expanding mean over matches already played, shifted.
    by_time = sides.sort_values(["season", "gw", "fixture"])
    league_gf = by_time["scored"].shift(1).expanding(min_periods=20).mean()
    sides["league_gf"] = league_gf.reindex(sides.index)
    sides["league_gf"] = sides["league_gf"].fillna(1.35)

    keep = ["season", "gw", "fixture", "was_home", "team_id", "team_key",
            "team_att", "team_def", "team_matches", "league_gf", "scored",
            "conceded"]
    return sides[keep]


def _team_key(sides: pd.DataFrame, gw_df: pd.DataFrame) -> pd.Series:
    """Map each (season, team_id) to the club's name, falling back to the id.

    The name comes from the modal `team_name` recorded against that id in that
    season. A mid-season transfer misfiles an individual player's club, but it
    cannot move the mode across twenty-odd squad members.
    """
    if "team_name" not in gw_df.columns:
        return sides["season"].astype(str) + "#" + sides["team_id"].astype(str)

    named = gw_df[["season", "team_id", "team_name"]].dropna()
    named = named[named["team_name"].astype(str).str.len() > 0]
    if named.empty:
        return sides["season"].astype(str) + "#" + sides["team_id"].astype(str)

    lookup = (named.groupby(["season", "team_id"])["team_name"]
              .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else ""))
    key = pd.Series(list(zip(sides["season"], sides["team_id"])),
                    index=sides.index).map(lookup)
    fallback = sides["season"].astype(str) + "#" + sides["team_id"].astype(str)
    return key.replace("", np.nan).fillna(fallback)


def _attach_opponent_ratings(sides: pd.DataFrame) -> pd.DataFrame:
    """Add the other side's ratings to each row, as opp_att / opp_def."""
    other = sides[["season", "fixture", "was_home", "team_att", "team_def"]].copy()
    other = other.rename(columns={"team_att": "opp_att", "team_def": "opp_def",
                                  "was_home": "_wh"})
    other["_wh"] = ~other["_wh"].astype(bool)
    out = sides.merge(other, left_on=["season", "fixture", "was_home"],
                      right_on=["season", "fixture", "_wh"], how="left")
    return out.drop(columns=["_wh"])


# ── Player features ────────────────────────────────────────────────────────────

_RATE_SOURCES = [
    ("goals", "goals_scored"), ("assists", "assists"), ("saves", "saves"),
    ("bonus", "bonus"), ("bps", "bps"), ("xg", "xg"), ("xa", "xa"),
    ("yellow", "yellow_cards"),
]

PLAYER_FEATURES: List[str] = [
    "ewm_minutes", "ewm_started", "ewm_points", "mins_last", "started_last",
    "career_ppg", "career_mins", "season_games", "career_games",
    "ewm_goals90", "ewm_assists90", "ewm_saves90", "ewm_bonus90", "ewm_bps90",
    "ewm_xg90", "ewm_xa90", "ewm_yellow90", "ewm_dc90",
    "prev_minutes", "prev_points", "prev_pp90", "prev_mins_per_game",
    "prev_start_rate", "prev_goals90", "prev_assists90", "prev_bps90",
    "prev_cs_rate", "prev_dc90", "prev2_points", "prev2_minutes", "pl_seasons",
    "price_m", "was_home_f",
    "team_att", "team_def", "opp_att", "opp_def", "team_matches", "league_gf",
    "is_gkp", "is_def", "is_mid", "is_fwd",
]

# Everything above that describes the player's recent FORM · a three-match
# halflife window. Correct in-season, and in August it describes last May.
FORM_FEATURES: List[str] = [f for f in PLAYER_FEATURES
                            if f.startswith("ewm_") or f in
                            ("mins_last", "started_last", "season_games")]

# The subset that survives a summer: whole prior seasons, plus the fixture and
# position facts that are known before a ball is kicked. Use this feature set
# for a preseason model · see `scripts/benchmark_gw1_fold.py`.
PRESEASON_FEATURES: List[str] = [f for f in PLAYER_FEATURES
                                 if f not in FORM_FEATURES]


def _prev_season_features(df: pd.DataFrame) -> pd.DataFrame:
    """Whole-season carryover, one row per (code, season), shifted by a season.

    A three-match form window is the right description of a player in November
    and the wrong one in August, where it reports his last few games of May. A
    completed season is a far larger sample of the same quantity, and it is the
    only player evidence that exists before a ball is kicked.

    Returns the frame keyed (code, season_ord) so it can be merged straight back
    on. Every column describes seasons STRICTLY EARLIER than the one on the row.
    """
    played = df["minutes"] > 0
    per = (df.assign(_app=played.astype(float),
                     _start=df["started"].where(played),
                     _cs=_num(df, "clean_sheets").where(played))
           .groupby(["code", "season_ord"], as_index=False)
           .agg(s_minutes=("minutes", "sum"),
                s_points=("total_points", "sum"),
                s_apps=("_app", "sum"),
                s_starts=("_start", "sum"),
                s_goals=("goals_scored", "sum"),
                s_assists=("assists", "sum"),
                s_bps=("bps", "sum"),
                s_cs=("_cs", "sum"),
                s_dc=("dc_actions", "sum")))
    per = per.sort_values(["code", "season_ord"])
    g = per.groupby("code")

    out = per[["code", "season_ord"]].copy()
    prev = {c: g[c].shift(1) for c in
            ("s_minutes", "s_points", "s_apps", "s_starts", "s_goals",
             "s_assists", "s_bps", "s_cs", "s_dc")}

    mins = prev["s_minutes"]
    per90 = (mins / 90.0).replace(0, np.nan)
    apps = prev["s_apps"].replace(0, np.nan)

    out["prev_minutes"] = mins
    out["prev_points"] = prev["s_points"]
    out["prev_pp90"] = prev["s_points"] / per90
    out["prev_mins_per_game"] = mins / 38.0
    out["prev_start_rate"] = prev["s_starts"] / apps
    out["prev_goals90"] = prev["s_goals"] / per90
    out["prev_assists90"] = prev["s_assists"] / per90
    out["prev_bps90"] = prev["s_bps"] / per90
    out["prev_cs_rate"] = prev["s_cs"] / apps
    out["prev_dc90"] = prev["s_dc"] / per90

    # Two seasons back separates a permanent decline from one bad year.
    out["prev2_points"] = g["s_points"].shift(2)
    out["prev2_minutes"] = g["s_minutes"].shift(2)
    # How much Premier League history there is to reason from at all.
    out["pl_seasons"] = g.cumcount()
    return out


def prepare(gw_df: pd.DataFrame) -> pd.DataFrame:
    """Build the model frame: one row per appearance-opportunity, all features
    computed from strictly earlier matches.

    Safe to call once on the whole archive and then slice by season/gameweek.
    Every feature is either a `shift(1)` window or an expanding statistic that
    excludes the current row, so a later fold's data can never reach an earlier
    row.
    """
    df = gw_df.copy()
    for col in ("gw", "minutes", "total_points", "goals_scored", "assists",
                "saves", "bonus", "bps", "goals_conceded", "yellow_cards",
                "red_cards", "own_goals", "penalties_missed", "penalties_saved",
                "value", "opponent_team", "xg", "xa"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Defensive contribution: the FPL column where the season records it, and
    # the clearances/blocks/interceptions/tackles sum we assembled in the
    # archive everywhere else. Per row, not per frame · picking one source for
    # the whole archive silently zeroed nine seasons.
    df["dc_actions"] = _num(df, "defensive_contribution").fillna(_num(df, "cbit"))

    # The two points themselves only exist from 2025-26. The ACTIONS are a fact
    # about football in every season, so the threshold model trains on all of
    # them, but the points are only added where the rule was in force · without
    # this the model is scored against totals that could not contain them.
    df["dc_rule"] = (df["season"].astype(str) >= DC_RULE_FROM).astype(float)

    # `starts` only exists from 2022-23. Before that, 60 minutes is the proxy.
    started = _num(df, "starts")
    df["started"] = started.where(started.notna(),
                                  (df["minutes"] >= 60).astype(float))

    df["season_ord"] = df["season"].astype(str)
    df = df.sort_values(["code", "season_ord", "gw", "fixture"]).reset_index(drop=True)

    g = df.groupby("code", sort=False)

    def _ewm(s: pd.Series) -> pd.Series:
        return s.shift(1).ewm(halflife=FORM_HALFLIFE, min_periods=1).mean()

    df["ewm_minutes"] = g["minutes"].transform(_ewm)
    df["ewm_started"] = g["started"].transform(_ewm)
    df["ewm_points"] = g["total_points"].transform(_ewm)
    df["mins_last"] = g["minutes"].shift(1)
    df["started_last"] = g["started"].shift(1)
    df["career_ppg"] = g["total_points"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_mins"] = g["minutes"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_games"] = g.cumcount()
    df["season_games"] = df.groupby(["code", "season_ord"], sort=False).cumcount()

    # Per-90 rates, averaged over APPEARANCES only. A blank week is silence
    # about a player's scoring rate, not evidence of a zero rate · it is the
    # minutes model's job to price the blank.
    played = df["minutes"] >= MIN_MINUTES_FOR_RATE
    per90_den = (df["minutes"] / 90.0).where(played)
    for name, src in _RATE_SOURCES + [("dc", "dc_actions")]:
        raw = _num(df, src)
        rate = (raw / per90_den).where(played)
        df["_r_" + name] = rate
        df["ewm_%s90" % name] = df.groupby("code", sort=False)["_r_" + name].transform(_ewm)

    df = df.merge(_prev_season_features(df), on=["code", "season_ord"], how="left")

    df["price_m"] = df["value"] / 10.0
    df["was_home_f"] = df["was_home"].astype(float)

    pos = df["position"].astype(str).str.upper()
    for p in POSITIONS:
        df["is_%s" % p.lower()] = (pos == p).astype(float)
    df["position"] = pos

    # Team ratings, joined on the fixture side rather than on team_id.
    sides = _attach_opponent_ratings(build_team_form(gw_df))
    df = df.merge(sides[["season", "fixture", "was_home", "team_att", "team_def",
                         "opp_att", "opp_def", "team_matches", "league_gf",
                         "conceded"]],
                  on=["season", "fixture", "was_home"], how="left")
    df = df.rename(columns={"conceded": "team_conceded"})

    df = df.drop(columns=[c for c in df.columns if c.startswith("_r_")])
    return df


# ── The model ──────────────────────────────────────────────────────────────────

class ComponentPointsModel(object):
    """Fit the components, then assemble expected points.

    `fit` takes a frame from `prepare()`. `predict` takes another one and
    returns the same index with an `xp` column plus every component, so a UI can
    show WHY a number is what it is.
    """

    def __init__(self, tree_params: Optional[Dict[str, Any]] = None,
                 features: Optional[List[str]] = None):
        self.params = dict(_TREE)
        if tree_params:
            self.params.update(tree_params)
        # `PRESEASON_FEATURES` drops the form window, for the case where the
        # window is describing a season that has ended.
        self.features = list(features) if features else list(PLAYER_FEATURES)
        self.models: Dict[str, Any] = {}
        self.fallbacks: Dict[str, float] = {}
        self.fitted = False

    # ── fitting ────────────────────────────────────────────────────────────────
    def _fit_binary(self, key: str, X: pd.DataFrame, y: pd.Series) -> None:
        y = y.astype(float)
        if len(y) < 200 or y.nunique() < 2:
            self.fallbacks[key] = float(y.mean()) if len(y) else 0.0
            return
        m = xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss",
                              **self.params)
        m.fit(X, y)
        self.models[key] = m

    def _fit_gauss(self, key: str, X: pd.DataFrame, y: pd.Series) -> None:
        if len(y) < 200:
            self.fallbacks[key] = float(y.mean()) if len(y) else 0.0
            return
        m = xgb.XGBRegressor(objective="reg:squarederror", **self.params)
        m.fit(X, y.astype(float))
        self.models[key] = m

    def _fit_rate(self, key: str, X: pd.DataFrame, rate: pd.Series,
                  exposure: pd.Series, clip: float) -> None:
        """Poisson rate model · target is per 90, weighted by minutes played."""
        ok = rate.notna() & exposure.notna() & (exposure > 0)
        if int(ok.sum()) < 200:
            self.fallbacks[key] = float(rate[ok].mean()) if ok.any() else 0.0
            return
        m = xgb.XGBRegressor(objective="count:poisson", **self.params)
        m.fit(X[ok.values], rate[ok].clip(0, clip).astype(float),
              sample_weight=exposure[ok].astype(float))
        self.models[key] = m

    def fit(self, train: pd.DataFrame) -> "ComponentPointsModel":
        X = train[self.features]

        # Stage A · minutes. Fitted on every row, because "did not play" is the
        # outcome being modelled.
        self._fit_binary("p60", X, (train["minutes"] >= 60))
        self._fit_binary("pplay", X, (train["minutes"] > 0))
        self._fit_gauss("minutes", X, train["minutes"].fillna(0.0))

        # Stage B · per-90 rates, conditional on a real sample of minutes.
        played = train["minutes"] >= MIN_MINUTES_FOR_RATE
        exposure = (train["minutes"] / 90.0).where(played)
        for key, src, clip_key in (("goals", "goals_scored", "goals"),
                                   ("assists", "assists", "assists"),
                                   ("saves", "saves", "saves"),
                                   ("bonus", "bonus", "bonus"),
                                   ("dc", "dc_actions", "dc"),
                                   ("yellow", "yellow_cards", "yellow")):
            raw = _num(train, src)
            if raw.notna().sum() == 0:
                self.fallbacks[key] = 0.0
                continue
            rate = (raw / exposure).where(played)
            self._fit_rate(key, X, rate, exposure, RATE_CLIP[clip_key])

        # Stage B2 · the defensive-contribution THRESHOLD, not the action count.
        # Two points land on a step function, and a player who reliably makes
        # nine tackles scores nothing. Only fitted where the season records the
        # actions at all.
        dc_rows = train[train["dc_actions"].notna() & played]
        if len(dc_rows) >= 500:
            thr = dc_rows["position"].map(DC_THRESHOLD).fillna(99)
            self._fit_binary("dc_hit", dc_rows[self.features],
                             (dc_rows["dc_actions"] >= thr))

        # Stage B3 · team goals conceded, one row per fixture side. This is what
        # prices both the clean sheet and the -1 per two conceded, and it is the
        # only place the opponent's attack rating does real work.
        team = train.dropna(subset=["team_conceded"]).drop_duplicates(
            subset=["season", "fixture", "was_home"])
        tf = ["team_att", "team_def", "opp_att", "opp_def", "was_home_f",
              "team_matches", "league_gf"]
        if len(team) >= 200:
            m = xgb.XGBRegressor(objective="count:poisson", **self.params)
            m.fit(team[tf], team["team_conceded"].astype(float))
            self.models["conceded"] = m
        else:
            self.fallbacks["conceded"] = float(
                team["team_conceded"].mean()) if len(team) else 1.35

        self.fitted = True
        return self

    # ── prediction ─────────────────────────────────────────────────────────────
    def _predict_one(self, key: str, X: pd.DataFrame, proba: bool = False) -> np.ndarray:
        m = self.models.get(key)
        if m is None:
            return np.full(len(X), float(self.fallbacks.get(key, 0.0)))
        if proba:
            return m.predict_proba(X)[:, 1]
        return np.clip(m.predict(X), 0, None)

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted:
            raise RuntimeError("ComponentPointsModel.predict before fit")
        X = rows[self.features]
        pos = rows["position"].astype(str).str.upper()

        p60 = self._predict_one("p60", X, proba=True)
        pplay = np.maximum(self._predict_one("pplay", X, proba=True), p60)
        exp_min = np.clip(self._predict_one("minutes", X), 0, 90)
        exposure = exp_min / 90.0

        goals = self._predict_one("goals", X) * exposure
        assists = self._predict_one("assists", X) * exposure
        saves = self._predict_one("saves", X) * exposure
        bonus = self._predict_one("bonus", X) * exposure
        yellow = self._predict_one("yellow", X) * exposure
        dc_hit = self._predict_one("dc_hit", X, proba="dc_hit" in self.models)
        # Absent means "no opinion", and the safe reading of no opinion about a
        # scoring rule is that it applies · a frame built by `prepare` always
        # carries the flag.
        dc_rule = _num(rows, "dc_rule").fillna(1.0).values

        tf = ["team_att", "team_def", "opp_att", "opp_def", "was_home_f",
              "team_matches", "league_gf"]
        if "conceded" in self.models:
            lam = np.clip(self.models["conceded"].predict(rows[tf]), 0.05, 6.0)
        else:
            lam = np.full(len(rows), float(self.fallbacks.get("conceded", 1.35)))

        p_cs = np.exp(-lam)
        # E[floor(conceded / 2)] under Poisson(lam), summed out to MAX_CONCEDED.
        k = np.arange(0, MAX_CONCEDED + 1)
        log_fact = np.array([lgamma(int(i) + 1) for i in k])
        logpmf = (-lam[:, None] + k[None, :] * np.log(lam[:, None])
                  - log_fact[None, :])
        pmf = np.exp(logpmf)
        e_conc_pen = (pmf * np.floor(k / 2.0)[None, :]).sum(axis=1)

        goal_pts = pos.map(FPL_GOAL_PTS).fillna(4).values.astype(float)
        cs_pts = pos.map(FPL_CS_PTS).fillna(0).values.astype(float)
        is_keeper_or_def = pos.isin(["GKP", "DEF"]).values.astype(float)
        is_gkp = (pos == "GKP").values.astype(float)

        xp = (pplay + p60
              + goals * goal_pts
              + assists * FPL_ASSIST_PTS
              + p_cs * p60 * cs_pts
              - e_conc_pen * is_keeper_or_def * p60
              + saves / SAVES_PER_POINT * is_gkp
              + bonus
              + DC_PTS * dc_hit * p60 * dc_rule
              + YELLOW_PTS * yellow)

        out = pd.DataFrame({
            "xp": np.clip(xp, 0, None).round(3),
            "p_play": pplay.round(3), "p60": p60.round(3),
            "exp_minutes": exp_min.round(1),
            "e_goals": goals.round(3), "e_assists": assists.round(3),
            "e_bonus": bonus.round(3), "e_saves": saves.round(2),
            "p_clean_sheet": p_cs.round(3), "e_conceded": lam.round(2),
            "p_defcon": np.asarray(dc_hit).round(3),
        }, index=rows.index)
        return out


# ── Convenience ────────────────────────────────────────────────────────────────

def fit_predict(train: pd.DataFrame, test: pd.DataFrame,
                tree_params: Optional[Dict[str, Any]] = None,
                features: Optional[List[str]] = None
                ) -> Tuple[pd.DataFrame, "ComponentPointsModel"]:
    """Fit on `train`, score `test`. Both come from `prepare()`."""
    model = ComponentPointsModel(tree_params, features).fit(train)
    return model.predict(test), model


# ── Live prediction ────────────────────────────────────────────────────────────

def active_season() -> str:
    """The season we are currently in, as the archive labels it ("2026-27").

    Derived from the date on the same July cutover the Understat fetcher uses,
    so the two cannot disagree about which season is live.
    """
    from datetime import date

    today = date.today()
    start = today.year if today.month >= 7 else today.year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def build_history(current_season: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Every completed match we hold, in the archive's canonical schema.

    The ten-season archive plus, when the live season is not in it yet, the
    current season normalised from the same vaastav source the archive is built
    from. Returns None when the archive has not been built.
    """
    from data.processors.archive import (_normalize_vaastav_season,
                                         load_gw_archive)

    archive = load_gw_archive()
    if archive is None:
        logger.warning("gw archive missing · run scripts/build_archive.py")
        return None

    if current_season and current_season not in set(archive["season"].unique()):
        try:
            live = _normalize_vaastav_season(current_season)
            if live is not None and not live.empty:
                archive = pd.concat([archive, live], ignore_index=True)
                logger.info("history: archive + %d live rows from %s",
                            len(live), current_season)
        except Exception as exc:  # noqa: BLE001 · a missing live season is normal
            logger.warning("live season %s unavailable: %s", current_season, exc)
    return archive


def upcoming_rows(players_df: pd.DataFrame, fixtures_df: pd.DataFrame,
                  season: str, gw: int) -> pd.DataFrame:
    """One row per (player, fixture) for an unplayed gameweek.

    Shaped like a played match with the outcomes left empty, so `prepare` can
    build the same features for it that it builds for history. Doubles produce
    two rows and blanks produce none, which is what makes the sum over a
    gameweek correct without any special casing.
    """
    fx = fixtures_df[fixtures_df["gameweek"] == int(gw)]
    if fx.empty:
        return pd.DataFrame()

    sides = []
    for _, f in fx.iterrows():
        fid = int(f.get("fixture_id", f.name))
        sides.append((int(f["home_team_id"]), int(f["away_team_id"]), True, fid))
        sides.append((int(f["away_team_id"]), int(f["home_team_id"]), False, fid))

    by_team: Dict[int, List] = {}
    for team, opp, home, fid in sides:
        by_team.setdefault(team, []).append((opp, home, fid))

    rows = []
    for _, p in players_df.iterrows():
        tid = p.get("team_id")
        if pd.isna(tid):
            continue
        for opp, home, fid in by_team.get(int(tid), []):
            rows.append({
                "season": season, "code": p.get("code"), "gw": int(gw),
                "fixture": fid, "team_id": int(tid), "opponent_team": opp,
                "was_home": home, "position": p.get("position"),
                "value": float(p.get("price", 0) or 0) * 10.0,
                "player_name": p.get("name") or p.get("web_name"),
                "web_name": p.get("web_name"), "team_name": p.get("team"),
                "kickoff_time": None, "element": p.get("fpl_id"),
                "minutes": np.nan, "total_points": np.nan,
            })
    out = pd.DataFrame(rows)
    return out.dropna(subset=["code"]) if not out.empty else out


def predict_upcoming(history: pd.DataFrame, upcoming: pd.DataFrame,
                     min_career_games: int = 3,
                     tree_params: Optional[Dict[str, Any]] = None
                     ) -> Tuple[pd.DataFrame, "ComponentPointsModel"]:
    """Fit on everything played, score an unplayed gameweek.

    The two frames are prepared TOGETHER so the upcoming rows inherit the same
    rolling windows and team ratings as the history they follow. No outcome from
    an upcoming row can leak backwards: every feature is a shift or an expanding
    statistic, and those rows carry no outcomes to leak.

    Doubles are summed per player and blanks fall out as no row at all.
    """
    if upcoming is None or upcoming.empty:
        return pd.DataFrame(), ComponentPointsModel(tree_params)

    combined = pd.concat([history, upcoming], ignore_index=True, sort=False)
    frame = prepare(combined)

    is_future = frame["minutes"].isna() & frame["total_points"].isna()
    train = frame[~is_future]
    train = train[train["career_games"] >= min_career_games]
    test = frame[is_future].copy()

    model = ComponentPointsModel(tree_params).fit(train)
    comps = model.predict(test)

    # Only the two identity columns come across. The prepared frame carries the
    # archive's own `xp` column (FPL's published expected points), which collides
    # with this model's output column name and turns the aggregation below into a
    # DataFrame-of-two-columns.
    test = pd.concat([test[["code", "career_games"]].reset_index(drop=True),
                      comps.reset_index(drop=True)], axis=1)

    thin = test["career_games"] < min_career_games
    if thin.any():
        logger.info("%d upcoming rows have under %d career appearances · "
                    "their numbers are a positional prior, not a read",
                    int(thin.sum()), min_career_games)
    test["thin_history"] = thin

    agg = (test.groupby("code", as_index=False)
           .agg(predicted_pts=("xp", "sum"),
                fixtures=("xp", "size"),
                p60=("p60", "mean"),
                exp_minutes=("exp_minutes", "sum"),
                e_goals=("e_goals", "sum"),
                e_assists=("e_assists", "sum"),
                e_bonus=("e_bonus", "sum"),
                p_clean_sheet=("p_clean_sheet", "mean"),
                p_defcon=("p_defcon", "mean"),
                thin_history=("thin_history", "max")))
    agg["predicted_pts"] = agg["predicted_pts"].round(2)
    return agg.sort_values("predicted_pts", ascending=False).reset_index(drop=True), model


# Gameweeks held out of training to produce the accuracy figures the Predictions
# page prints. Small, because the point of the model is more training data.
HOLDOUT_GWS = 3


def _holdout_metrics(frame: pd.DataFrame, season: str,
                     tree_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Honest out-of-sample error on the last few completed gameweeks.

    Reported for the whole pool AND for likely starters. The second is the one
    worth reading: a model can look strong on the first by getting the reserves'
    zeroes right, which is not a decision anybody makes.
    """
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    played = frame[frame["total_points"].notna() & (frame["season"] == season)]
    if played.empty:
        return {"rmse": float("nan"), "mae": float("nan"), "r2": float("nan"),
                "train_gws": (0, 0), "test_gws": (0, 0), "n_train": 0, "n_test": 0}

    gws = sorted(played["gw"].unique())
    test_gws = gws[-HOLDOUT_GWS:]
    hist = frame[frame["total_points"].notna()]
    train = hist[~((hist["season"] == season) & (hist["gw"].isin(test_gws)))]
    test = played[played["gw"].isin(test_gws)]
    if len(train) < 2000 or len(test) < 100:
        return {"rmse": float("nan"), "mae": float("nan"), "r2": float("nan"),
                "train_gws": (int(gws[0]), int(gws[-1])),
                "test_gws": (int(test_gws[0]), int(test_gws[-1])),
                "n_train": int(len(train)), "n_test": int(len(test))}

    pred = ComponentPointsModel(tree_params).fit(train).predict(test)["xp"].values
    y = test["total_points"].values
    out = {
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "mae": float(mean_absolute_error(y, pred)),
        "r2": float(r2_score(y, pred)),
        "train_gws": (int(gws[0]), int(test_gws[0]) - 1),
        "test_gws": (int(test_gws[0]), int(test_gws[-1])),
        "n_train": int(len(train)), "n_test": int(len(test)),
        "model": "component",
    }
    starters = test["ewm_minutes"] >= 60
    if int(starters.sum()) >= 100:
        ys, ps = y[starters.values], pred[starters.values]
        out["starters"] = {
            "rmse": float(np.sqrt(mean_squared_error(ys, ps))),
            "mae": float(mean_absolute_error(ys, ps)),
            "r2": float(r2_score(ys, ps)),
            "n": int(starters.sum()),
        }
    pos_rmse = {}
    for pos in POSITIONS:
        sel = (test["position"] == pos).values
        if sel.sum() >= 30:
            pos_rmse[pos] = float(np.sqrt(mean_squared_error(y[sel], pred[sel])))
    out["pos_rmse"] = pos_rmse
    return out


def run_pipeline(players_df: pd.DataFrame, current_gw: int,
                 fixtures_df: Optional[pd.DataFrame] = None,
                 season: Optional[str] = None,
                 target_gw: Optional[int] = None,
                 min_career_games: int = 3
                 ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Drop-in alternative to `points_model.run_pipeline`.

    Returns (predictions, metrics) with the columns the Predictions and Free Hit
    pages already read, so the flag is the only difference between the two
    models from a page's point of view.
    """
    season = season or active_season()
    target_gw = int(target_gw or (int(current_gw) + 1))

    if fixtures_df is None:
        from data.fetchers.fpl_api import get_fixtures_df
        fixtures_df = get_fixtures_df()

    history = build_history(season)
    if history is None or history.empty:
        raise RuntimeError("component model has no history to train on")

    upcoming = upcoming_rows(players_df, fixtures_df, season, target_gw)
    if upcoming.empty:
        raise RuntimeError("no fixtures found for GW%d" % target_gw)

    preds, _ = predict_upcoming(history, upcoming, min_career_games)

    # The pages join on these · same set the incumbent's predictions carry.
    cols = ["code", "web_name", "team", "team_id", "team_code", "team_short",
            "position", "price", "ownership", "status", "form", "total_points",
            "fpl_xgi_per90"]
    have = [c for c in cols if c in players_df.columns]
    out = preds.merge(players_df[have].drop_duplicates("code"), on="code",
                      how="left")
    out["base_predicted_pts"] = out["predicted_pts"]
    if "status" in out.columns:
        out = out[out["status"].fillna("a") == "a"]
    out = out.sort_values("predicted_pts", ascending=False).reset_index(drop=True)

    frame = prepare(pd.concat([history, upcoming], ignore_index=True, sort=False))
    metrics = _holdout_metrics(frame, season)
    metrics["target_gw"] = target_gw
    return out, metrics
