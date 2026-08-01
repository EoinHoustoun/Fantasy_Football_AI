"""Three-model blend · scaling, the zero-sample rule, and confidence.

All figures here are INVENTED. Scout and Hub data are paid third-party feeds
and this repo is public · never reproduce their real numbers.

The zero-sample rule is the one that has already cost a live bug: a Hub zero
means "no minutes in the opening window", not "will score nothing all season",
and blending it as a season projection dragged Saliba to a third of what the
other two models said.
"""
import numpy as np
import pandas as pd

from analytics.consensus import (MIN_NAILEDNESS_FOR_SEASON, MIN_SCALE_SAMPLE,
                                 SEASON_WEIGHTS, build_consensus,
                                 ffh_season_equivalent, robust_scale)


# ── robust_scale ─────────────────────────────────────────────────────────────

def test_scale_is_the_median_ratio():
    ours = pd.Series([70.0, 80.0, 90.0] * 10)
    theirs = pd.Series([100.0, 100.0, 100.0] * 10)
    assert robust_scale(ours, theirs) == 0.8


def test_one_wild_disagreement_does_not_move_the_scale():
    """Median, not mean · that is the whole reason for the choice."""
    n = MIN_SCALE_SAMPLE + 5
    ours = pd.Series([80.0] * n)
    theirs = pd.Series([100.0] * n)
    clean = robust_scale(ours, theirs)
    ours_outlier = ours.copy()
    ours_outlier.iloc[0] = 10000.0
    assert robust_scale(ours_outlier, theirs) == clean


def test_small_sample_refuses_to_scale():
    ours = pd.Series([70.0] * (MIN_SCALE_SAMPLE - 1))
    theirs = pd.Series([100.0] * (MIN_SCALE_SAMPLE - 1))
    assert robust_scale(ours, theirs) == 1.0


def test_low_scoring_players_are_excluded_so_the_ratio_cannot_explode():
    n = MIN_SCALE_SAMPLE + 5
    ours = pd.Series([50.0] * n + [5.0])
    theirs = pd.Series([100.0] * n + [0.01])   # would give a ratio of 500
    assert robust_scale(ours, theirs) == 0.5


# ── the zero-sample rule ─────────────────────────────────────────────────────

def _matched(per_gw, nailedness=None):
    d = {"ffh_pts_per_start": per_gw, "code": range(len(per_gw))}
    if nailedness is not None:
        d["nailedness"] = nailedness
    return pd.DataFrame(d)


def test_a_hub_zero_is_masked_not_extrapolated():
    """Zero means "no minutes in the window". Multiplying it to 38 says the
    player scores nothing all season, which is a category error."""
    out = ffh_season_equivalent(_matched([0.0, 5.0]))
    assert pd.isna(out.iloc[0])
    assert out.iloc[1] > 0


def test_a_barely_playing_player_is_masked_too():
    below = MIN_NAILEDNESS_FOR_SEASON - 0.1
    above = MIN_NAILEDNESS_FOR_SEASON + 0.1
    out = ffh_season_equivalent(_matched([5.0, 5.0], nailedness=[below, above]))
    assert pd.isna(out.iloc[0])
    assert out.iloc[1] > 0


def test_opening_ease_is_divided_back_out():
    """The window is the opening gameweeks, so its points per gameweek carries
    the ease of THOSE fixtures. Straight multiplication would hand a season
    bonus to whoever opens against promoted clubs."""
    m = _matched([5.0, 5.0])
    m["team_id"] = [1, 2]
    easy, hard = ffh_season_equivalent(m, ease_by_team={1: 1.3, 2: 0.8})
    assert easy < hard


def test_pathological_ease_cannot_blow_up_the_division():
    m = _matched([5.0])
    m["team_id"] = [1]
    out = ffh_season_equivalent(m, ease_by_team={1: 0.0001})
    assert np.isfinite(out.iloc[0])


def test_missing_column_returns_all_nan_rather_than_raising():
    out = ffh_season_equivalent(pd.DataFrame({"code": [1, 2]}))
    assert out.isna().all()


# ── build_consensus ──────────────────────────────────────────────────────────

def _board(n=40):
    return pd.DataFrame({
        "code": range(n),
        "projected_points": np.linspace(40.0, 160.0, n),
        "position": ["MID"] * n,
    })


def test_our_model_alone_still_produces_a_consensus():
    """Missing sources are dropped and the weights renormalised · no source
    should need special-casing at the call site."""
    board = _board()
    out, diag = build_consensus(board)
    assert "consensus_points" in out.columns
    assert out["consensus_points"].notna().any()
    assert diag["sources"] == ["ours"]


def test_two_models_agreeing_cannot_reach_high_confidence():
    """High confidence is a claim about three independent reads."""
    board = _board()
    scout = pd.DataFrame({"code": board["code"],
                          "scout_pts": board["projected_points"] * 1.3})
    out, _ = build_consensus(board, scout_matched=scout)
    assert "High" not in set(out["consensus_confidence"].dropna())


def test_disagreement_lowers_confidence():
    board = _board()
    agree = pd.DataFrame({"code": board["code"],
                          "scout_pts": board["projected_points"] * 1.3})
    out_agree, _ = build_consensus(board, scout_matched=agree)

    noisy = agree.copy()
    rng = np.random.default_rng(11)
    noisy["scout_pts"] = noisy["scout_pts"] * rng.uniform(0.4, 2.2, len(noisy))
    out_noisy, _ = build_consensus(board, scout_matched=noisy)

    assert out_noisy["model_spread"].mean() > out_agree["model_spread"].mean()


def test_consensus_sits_between_the_models_it_blends():
    board = _board()
    scout = pd.DataFrame({"code": board["code"],
                          "scout_pts": board["projected_points"] * 2.0})
    out, _ = build_consensus(board, scout_matched=scout)
    # Scout is rescaled onto our scale before blending, so the result must not
    # run away above the higher input.
    both = pd.concat([board["projected_points"],
                      board["projected_points"] * 2.0], axis=1)
    assert (out["consensus_points"] <= both.max(axis=1) + 1e-6).all()


def test_weights_are_a_sane_distribution():
    assert abs(sum(SEASON_WEIGHTS.values()) - 1.0) < 1e-9
    assert all(0 < w < 1 for w in SEASON_WEIGHTS.values())


def test_board_is_not_mutated():
    board = _board()
    before = board["projected_points"].tolist()
    build_consensus(board)
    assert board["projected_points"].tolist() == before


# ── one number is not two models ─────────────────────────────────────────────

def _backfilled_board(n=40):
    """A board where the promoted-club rows were filled FROM Scout, so our
    projection is Scout's number arriving a second time."""
    b = _board(n)
    b["projection_source"] = ["model"] * (n - 10) + ["scout"] * 10
    return b


def test_a_backfilled_row_does_not_count_scout_twice():
    """This is the O'Shea bug: a promoted-club player has no Premier League
    record, so "ours" IS the Scout backfill. Blending both gave Scout 0.85 of
    the weight instead of 0.45."""
    b = _backfilled_board()
    scout = pd.DataFrame({"code": b["code"], "scout_pts": b["projected_points"]})
    out, _ = build_consensus(b, scout_matched=scout)
    back = out[out["projection_source"] == "scout"]
    assert back["consensus_echoed_scout"].all()
    assert (back["n_models"] == 1).all()


def test_an_ordinary_row_still_counts_both_models():
    b = _backfilled_board()
    scout = pd.DataFrame({"code": b["code"],
                          "scout_pts": b["projected_points"] * 1.3})
    out, _ = build_consensus(b, scout_matched=scout)
    normal = out[out["projection_source"] == "model"]
    assert not normal["consensus_echoed_scout"].any()
    assert (normal["n_models"] >= 2).all()


def test_a_backfilled_row_cannot_report_high_confidence():
    """Three-model confidence off one opinion counted twice was telling us a
    promoted-club punt was a safe pick."""
    b = _backfilled_board()
    scout = pd.DataFrame({"code": b["code"], "scout_pts": b["projected_points"]})
    ffh = pd.DataFrame({"code": b["code"],
                        "ffh_pts_per_start": [5.0] * len(b),
                        "nailedness": [0.9] * len(b)})
    out, _ = build_consensus(b, scout_matched=scout, ffh_matched=ffh)
    back = out[out["projection_source"] == "scout"]
    assert "High" not in set(back["consensus_confidence"])


def test_the_hub_does_not_vote_on_a_season_it_cannot_see():
    """Measured at 1.37x Scout on promoted-club players against 0.96x on
    established ones. A four-gameweek window multiplied to 38 is the least
    reliable number in the stack for someone with no Premier League record."""
    b = _backfilled_board()
    scout = pd.DataFrame({"code": b["code"], "scout_pts": b["projected_points"]})
    ffh = pd.DataFrame({"code": b["code"],
                        "ffh_pts_per_start": [9.0] * len(b),   # wildly high
                        "nailedness": [0.95] * len(b)})
    out, _ = build_consensus(b, scout_matched=scout, ffh_matched=ffh)
    back = out[out["projection_source"] == "scout"]
    # consensus must equal the Scout number, untouched by the inflated Hub read
    assert (back["consensus_points"] - back["src_scout"]).abs().max() < 0.11


def test_the_hub_still_supplies_minutes_for_backfilled_players():
    """It stops voting on a season · it does not stop being useful."""
    b = _backfilled_board()
    scout = pd.DataFrame({"code": b["code"], "scout_pts": b["projected_points"]})
    ffh = pd.DataFrame({"code": b["code"],
                        "ffh_pts_per_start": [5.0] * len(b),
                        "nailedness": [0.9] * len(b)})
    out, _ = build_consensus(b, scout_matched=scout, ffh_matched=ffh)
    back = out[out["projection_source"] == "scout"]
    assert back["ffh_nailedness"].notna().all()
