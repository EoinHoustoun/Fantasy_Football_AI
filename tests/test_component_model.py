"""Component points model · the properties that make its numbers trustworthy.

The two that matter most and are easiest to break silently:
  · no feature may see a match that had not finished yet
  · defensive-contribution points may not be awarded in seasons before the rule
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analytics.component_model import (ComponentPointsModel, DC_PTS,
                                       DC_RULE_FROM, MAX_CONCEDED,
                                       PLAYER_FEATURES, build_team_form,
                                       prepare)


def _match(season, gw, fixture, code, team, opp, home, mins, pts, gf=0, ga=0,
           position="MID", **extra):
    row = {
        "season": season, "gw": gw, "fixture": fixture, "code": code,
        "team_id": team, "opponent_team": opp, "was_home": home,
        "minutes": mins, "total_points": pts, "goals_scored": gf,
        "goals_conceded": ga, "assists": 0, "saves": 0, "bonus": 0, "bps": 0,
        "yellow_cards": 0, "red_cards": 0, "own_goals": 0,
        "penalties_missed": 0, "penalties_saved": 0, "value": 50,
        "position": position, "player_name": "P%s" % code, "web_name": "P%s" % code,
        "kickoff_time": "2025-08-%02dT12:00:00Z" % min(28, gw),
        "xg": np.nan, "xa": np.nan, "clean_sheets": int(ga == 0),
        "starts": 1 if mins >= 60 else 0,
    }
    row.update(extra)
    return row


def _two_team_season(season="2025-26", n_gw=8, home_goals=2, away_goals=0):
    """A toy league: two clubs, one fixture a gameweek, two players a side."""
    rows = []
    for gw in range(1, n_gw + 1):
        fx = gw
        for code, team, opp, home, scored, conceded in (
                (1, 10, 20, True, home_goals, away_goals),
                (2, 10, 20, True, 0, away_goals),
                (3, 20, 10, False, away_goals, home_goals),
                (4, 20, 10, False, 0, home_goals)):
            rows.append(_match(season, gw, fx, code, team, opp, home,
                               mins=90, pts=2 + scored * 5,
                               gf=scored, ga=conceded))
    return pd.DataFrame(rows)


# ── team ratings ───────────────────────────────────────────────────────────────

def test_team_form_has_exactly_two_sides_per_fixture():
    sides = build_team_form(_two_team_season())
    assert sides.groupby(["season", "fixture"]).size().unique().tolist() == [2]


def test_goals_for_comes_from_the_other_sides_conceded():
    """Own goals land on the right team only if scored is read across the tie."""
    df = _two_team_season(home_goals=3, away_goals=1)
    sides = build_team_form(df)
    home = sides[sides["was_home"]]
    away = sides[~sides["was_home"]]
    assert set(home["scored"].unique()) == {3}
    assert set(home["conceded"].unique()) == {1}
    assert set(away["scored"].unique()) == {1}
    assert set(away["conceded"].unique()) == {3}


def test_ratings_follow_the_club_not_the_reused_team_id():
    """FPL renumbers teams every summer · id 3 was Bournemouth, then Burnley.

    A promoted side inheriting last season's ratings from whoever held its
    number is the kind of error that never throws and quietly reranks defenders.
    """
    old = _two_team_season("2024-25", n_gw=10, home_goals=4, away_goals=0)
    old["team_name"] = np.where(old["was_home"], "Bournemouth", "Everton")
    new = _two_team_season("2025-26", n_gw=4, home_goals=0, away_goals=0)
    new["team_name"] = np.where(new["was_home"], "Burnley", "Everton")

    sides = build_team_form(pd.concat([old, new], ignore_index=True))
    burnley_first = sides[(sides["season"] == "2025-26")
                          & (sides["team_key"] == "Burnley")].nsmallest(1, "gw")
    assert burnley_first["team_matches"].iloc[0] == 0
    assert pd.isna(burnley_first["team_att"].iloc[0]), \
        "a newly promoted club must not inherit the previous holder's form"

    everton_first = sides[(sides["season"] == "2025-26")
                          & (sides["team_key"] == "Everton")].nsmallest(1, "gw")
    assert everton_first["team_matches"].iloc[0] == 10, \
        "a club that stayed up keeps its history across the season boundary"


def test_team_ratings_exclude_the_current_match():
    sides = build_team_form(_two_team_season(n_gw=6, home_goals=2, away_goals=0))
    first = sides[sides["team_matches"] == 0]
    assert first["team_att"].isna().all(), "a team's first match cannot have a prior rating"


# ── no lookahead ───────────────────────────────────────────────────────────────

def test_a_later_haul_cannot_change_an_earlier_rows_features():
    base = _two_team_season(n_gw=6)
    changed = base.copy()
    late = (changed["code"] == 1) & (changed["gw"] == 5)
    changed.loc[late, ["total_points", "goals_scored"]] = [25, 4]

    a = prepare(base)
    b = prepare(changed)
    key = ["season", "gw", "code"]
    a = a[(a["code"] == 1) & (a["gw"] <= 4)].sort_values(key)
    b = b[(b["code"] == 1) & (b["gw"] <= 4)].sort_values(key)

    for col in ("ewm_points", "career_ppg", "ewm_goals90", "ewm_minutes"):
        pd.testing.assert_series_equal(a[col].reset_index(drop=True),
                                       b[col].reset_index(drop=True),
                                       check_names=False)


def test_first_appearance_has_no_history():
    f = prepare(_two_team_season(n_gw=4))
    first = f[(f["code"] == 1) & (f["gw"] == 1)].iloc[0]
    assert pd.isna(first["ewm_points"])
    assert first["career_games"] == 0


# ── assembly ───────────────────────────────────────────────────────────────────

def _stub_model(**fallbacks):
    """A model with no trees · every component answers from its fallback, so the
    scoring assembly can be checked in isolation."""
    m = ComponentPointsModel()
    m.fitted = True
    m.fallbacks = dict(fallbacks)
    return m


def _one_row(position="DEF", dc_rule=1.0):
    row = {f: 0.0 for f in PLAYER_FEATURES}
    row["position"] = position
    row["dc_rule"] = dc_rule
    return pd.DataFrame([row])


def test_defcon_points_are_not_awarded_before_the_rule_existed():
    # A mild conceded rate on purpose · at lam=5 the deduction drives expected
    # points below zero, the clip bites, and the test would measure the clip.
    m = _stub_model(pplay=1.0, p60=1.0, minutes=90.0, dc_hit=1.0, conceded=1.0)
    with_rule = m.predict(_one_row("DEF", dc_rule=1.0))["xp"].iloc[0]
    without = m.predict(_one_row("DEF", dc_rule=0.0))["xp"].iloc[0]
    assert with_rule - without == pytest.approx(DC_PTS, abs=1e-6)


def test_clean_sheet_needs_sixty_minutes():
    """A player certain to appear but not to last is not paid for the shutout."""
    full = _stub_model(pplay=1.0, p60=1.0, minutes=90.0, conceded=0.05, dc_hit=0.0)
    cameo = _stub_model(pplay=1.0, p60=0.0, minutes=20.0, conceded=0.05, dc_hit=0.0)
    assert full.predict(_one_row("DEF"))["xp"].iloc[0] > \
        cameo.predict(_one_row("DEF"))["xp"].iloc[0] + 3


def test_conceded_penalty_matches_the_poisson_expectation():
    lam = 2.0
    m = _stub_model(pplay=1.0, p60=1.0, minutes=90.0, conceded=lam, dc_hit=0.0)
    got = m.predict(_one_row("DEF"))["xp"].iloc[0]

    k = np.arange(0, MAX_CONCEDED + 1)
    from math import lgamma
    pmf = np.exp(-lam + k * np.log(lam) - np.array([lgamma(int(i) + 1) for i in k]))
    expected_pen = float((pmf * np.floor(k / 2.0)).sum())
    expected = 1 + 1 + np.exp(-lam) * 4 - expected_pen   # appearance + CS - penalty
    assert got == pytest.approx(max(0.0, expected), abs=1e-3)


def test_outfield_positions_do_not_take_the_conceded_penalty():
    m = _stub_model(pplay=1.0, p60=1.0, minutes=90.0, conceded=3.0, dc_hit=0.0)
    mid = m.predict(_one_row("MID"))["xp"].iloc[0]
    # 2 appearance points + a small clean-sheet chance, never a deduction
    assert mid >= 2.0


def test_expected_points_are_never_negative():
    m = _stub_model(pplay=0.2, p60=0.05, minutes=8.0, conceded=4.0, yellow=2.0,
                    dc_hit=0.0)
    assert m.predict(_one_row("DEF"))["xp"].iloc[0] >= 0.0


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError):
        ComponentPointsModel().predict(_one_row())


# ── end to end on toy data ─────────────────────────────────────────────────────

def test_fits_and_predicts_on_a_toy_season():
    df = pd.concat([_two_team_season("2024-25", n_gw=20),
                    _two_team_season("2025-26", n_gw=6)], ignore_index=True)
    f = prepare(df)
    train = f[f["season"] == "2024-25"]
    test = f[f["season"] == "2025-26"]
    out = ComponentPointsModel().fit(train).predict(test)
    assert len(out) == len(test)
    assert (out["xp"] >= 0).all()
    assert set(["p60", "exp_minutes", "p_clean_sheet"]).issubset(out.columns)


ARCHIVE = (Path(__file__).resolve().parents[1] / "data" / "cache" / "archive"
           / "gw_archive.parquet")


@pytest.mark.skipif(not ARCHIVE.exists(), reason="archive not built")
def test_predicts_an_unplayed_gameweek_from_real_history():
    """The production path: outcomes stripped from the target week, one summed
    number per player, doubles added and blanks absent."""
    from analytics.component_model import predict_upcoming

    g = pd.read_parquet(ARCHIVE)
    g = g[(g["season"] == "2025-26") & (g["gw"] <= 13)]
    history = g[g["gw"] <= 12]
    upcoming = g[g["gw"] == 13].copy()
    outcomes = ["minutes", "total_points", "goals_scored", "assists", "saves",
                "bonus", "bps", "goals_conceded", "yellow_cards", "red_cards",
                "clean_sheets", "starts", "defensive_contribution", "cbit",
                "cbi", "tackles", "xg", "xa", "xgi", "xgc"]
    for c in outcomes:
        if c in upcoming.columns:
            upcoming[c] = np.nan

    preds, model = predict_upcoming(history, upcoming, min_career_games=3)

    assert not preds.empty
    assert preds["code"].is_unique, "one row per player, doubles summed"
    assert (preds["predicted_pts"] >= 0).all()
    assert preds["predicted_pts"].max() < 25, "a single gameweek has a ceiling"
    # The model must separate starters from reserves at all.
    assert preds["p60"].max() > 0.7
    assert preds["p60"].min() < 0.2

    played = set(upcoming["code"].dropna().astype(int))
    assert set(preds["code"].astype(int)) <= played, \
        "nobody without a fixture may be given a prediction"


def test_dc_rule_flag_tracks_the_season():
    f = prepare(pd.concat([_two_team_season("2024-25", n_gw=3),
                           _two_team_season(DC_RULE_FROM, n_gw=3)],
                          ignore_index=True))
    assert (f.loc[f["season"] == "2024-25", "dc_rule"] == 0).all()
    assert (f.loc[f["season"] == DC_RULE_FROM, "dc_rule"] == 1).all()
