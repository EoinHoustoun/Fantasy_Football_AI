"""Opponent-adjusted team scoring rates · the F Pred idea, on FF's own data.

The conceded model (`ComponentPointsModel`, stage B3) rates a side from an EWM
of GOALS, with no allowance for who those goals came against. That makes it
carry finishing luck (Brighton 2026-27: 5 conceded from 10.2 xGA) and
over-forecast clean sheets by 1.5 to 4 points a season.

This fits the Poisson core of F Pred's Dixon-Coles instead:

    xG_for(team v opp) ~ Poisson(exp(c + att[team] + def[opp] + home * h))

on xG where it exists (from 2022-23, the side's xG is the opponent keepers'
`xgc`), goals before that, with a 14-week exponential decay. The rate a side
CONCEDES is the opponent's scoring rate.

Walk-forward at team level (docs/research/fpred_team_rates.md, 105 anchors,
7,926 sides) found F Pred's version better on clean sheets and goals conceded
in every season, and a 50/50 geometric blend with the engine the most robust.
`blend` is that combination; `config.TEAM_RATE_BLEND` sets the weight (0 = off).
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

DECAY_WEEKS = 14.0
WINDOW_DAYS = 730          # older matches weigh under 0.6% at 14 weeks' decay
RIDGE = 1.0                # shrinks thin-history sides toward the league average
FULL_WEIGHT_MATCHES = 5    # a side needs this many matches in the window for the full blend


class Rates(object):
    def __init__(self, att: Dict[str, float], dfn: Dict[str, float],
                 const: float, home: float, n: Dict[str, int]):
        self.att, self.dfn, self.const, self.home, self.n = att, dfn, const, home, n

    def scoring(self, team: str, opp: str, was_home: bool) -> Optional[float]:
        if team not in self.att or opp not in self.dfn:
            return None
        return float(np.exp(self.const + self.att[team] + self.dfn[opp]
                            + (self.home if was_home else 0.0)))

    def conceded(self, team: str, opp: str, was_home: bool) -> Optional[float]:
        """Expected goals `team` concedes against `opp`."""
        return self.scoring(opp, team, not was_home)

    def matches(self, team: str) -> int:
        return int(self.n.get(team, 0))


def fit(sides: pd.DataFrame, as_of: Optional[pd.Timestamp] = None) -> Rates:
    """Fit on fixture sides: team_key, opp_key, was_home, kickoff, xg_for
    (NaN where unknown) and goals_for. Only sides with an outcome count."""
    s = sides.reset_index(drop=True)
    s["y"] = pd.to_numeric(s["xg_for"], errors="coerce")
    s["y"] = s["y"].fillna(pd.to_numeric(s.get("goals_for"), errors="coerce"))
    s = s.dropna(subset=["y", "team_key", "opp_key", "kickoff"])
    ko = pd.to_datetime(s["kickoff"], utc=True)
    ref = pd.Timestamp(as_of) if as_of is not None else ko.max()
    if ref.tzinfo is None:
        ref = ref.tz_localize("UTC")
    age = (ref - ko).dt.days
    s = s[(age >= 0) & (age <= WINDOW_DAYS)]
    age = age[s.index]
    if s.empty:
        return Rates({}, {}, 0.0, 0.0, {})
    w = np.exp(-age.values / (DECAY_WEEKS * 7.0))

    teams = sorted(set(s["team_key"]) | set(s["opp_key"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    ti = s["team_key"].map(idx).values
    oi = s["opp_key"].map(idx).values
    hm = s["was_home"].astype(float).values
    y = s["y"].astype(float).values

    def nll(p):
        c, h, a, d = p[0], p[1], p[2:2 + n], p[2 + n:]
        eta = c + a[ti] + d[oi] + h * hm
        mu = np.exp(eta)
        f = np.sum(w * (mu - y * eta)) + 0.5 * RIDGE * (a @ a + d @ d)
        r = w * (mu - y)
        g = np.empty_like(p)
        g[0], g[1] = r.sum(), (r * hm).sum()
        g[2:2 + n] = np.bincount(ti, r, n) + RIDGE * a
        g[2 + n:] = np.bincount(oi, r, n) + RIDGE * d
        return f, g

    p0 = np.zeros(2 + 2 * n)
    p0[0] = np.log(max(np.average(y, weights=w), 1e-3))
    res = minimize(nll, p0, jac=True, method="L-BFGS-B")
    p = res.x
    played = s.groupby("team_key").size()
    return Rates({t: float(p[2 + i]) for t, i in idx.items()},
                 {t: float(p[2 + n + i]) for t, i in idx.items()},
                 float(p[0]), float(p[1]),
                 {t: int(played.get(t, 0)) for t in teams})


def blend_weight(weight: float, n_team: int, n_opp: int) -> float:
    """Full weight once both sides have FULL_WEIGHT_MATCHES in the window."""
    return float(weight) * min(1.0, min(n_team, n_opp) / float(FULL_WEIGHT_MATCHES))


def blend(engine: np.ndarray, rate: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Geometric blend of two conceded rates; a missing rate keeps the engine's."""
    engine = np.asarray(engine, float)
    rate = np.asarray(rate, float)
    weight = np.where(np.isnan(rate), 0.0, np.asarray(weight, float))
    safe = np.where(np.isnan(rate), engine, np.clip(rate, 0.05, 6.0))
    return np.exp((1 - weight) * np.log(engine) + weight * np.log(safe))


def fixture_sides(gw_df: pd.DataFrame) -> pd.DataFrame:
    """One row per (season, fixture, was_home) with names, kickoff, goals for
    and xG for, from the player-gameweek frame `cm.prepare` is built from.

    A side's xG FOR is the other side's keepers' summed `xgc` (a keeper's xGC
    is the team's while he is on the pitch). Before 2022-23 it is NaN and the
    fit falls back to goals.
    """
    from analytics import component_model as cm
    sides = cm.build_team_form(gw_df)
    ko = (gw_df.groupby(["season", "fixture"])["kickoff_time"].max()
          .rename("kickoff").reset_index())
    sides = sides.merge(ko, on=["season", "fixture"], how="left")
    other = sides[["season", "fixture", "was_home", "team_key"]].rename(
        columns={"team_key": "opp_key", "was_home": "_wh"})
    other["_wh"] = ~other["_wh"].astype(bool)
    sides = sides.merge(other, left_on=["season", "fixture", "was_home"],
                        right_on=["season", "fixture", "_wh"], how="left").drop(columns="_wh")
    if "xgc" in gw_df.columns:
        g = gw_df[(gw_df["position"].astype(str).str.upper() == "GKP")
                  & (pd.to_numeric(gw_df["minutes"], errors="coerce") > 0)]
        g = g.assign(_x=pd.to_numeric(g["xgc"], errors="coerce"))
        xgc = (g.groupby(["season", "fixture", "was_home"])["_x"]
               .agg(lambda v: v.sum() if v.notna().any() else np.nan)
               .rename("xgc_side").reset_index())
        # this side's xG for = the OTHER side's keepers' xGC
        xgc["was_home"] = ~xgc["was_home"].astype(bool)
        sides = sides.merge(xgc.rename(columns={"xgc_side": "xg_for"}),
                            on=["season", "fixture", "was_home"], how="left")
    else:
        sides["xg_for"] = np.nan
    sides["goals_for"] = sides["scored"]
    sides["kickoff"] = pd.to_datetime(sides["kickoff"], utc=True, errors="coerce")
    return sides
