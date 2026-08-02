"""Week-to-week noise · measured on the archive, not guessed.

The old model was `sd = sqrt(mean * 2.4)`, which makes the coefficient of
variation FALL as a player gets better. Reality does not do that: measured cv is
close to flat at about 0.78 from two points a week to eight. The consequence of
getting this wrong is one-directional · a premium's swing is understated, so
every draft comparison that turns on a premium reads as more certain than it is.
"""
import numpy as np

from analytics.head_to_head import MATCH_CV, match_sd


def _sim_cv(mu, rate_cv=0.20, n=60000, seed=7):
    """Total simulated cv for a player, rate draw and match noise together."""
    rng = np.random.default_rng(seed)
    rate = np.clip(rng.normal(1.0, rate_cv, n), 0.15, 2.2)
    wk = np.maximum(mu * rate + rng.normal(0.0, float(match_sd(mu)), n), 0.0)
    return wk.std() / wk.mean()


def test_the_spread_is_close_to_flat_across_scoring_levels():
    """The bug being fixed: cv used to collapse from 0.76 to 0.56 as mu rose."""
    cvs = [_sim_cv(mu) for mu in (3.0, 4.0, 5.0, 8.0)]
    assert max(cvs) - min(cvs) < 0.10


def test_it_matches_the_measured_buckets_with_real_sample_size():
    """n=78, 106 and 51 at 2.5-3.5, 3.5-4.5 and 4.5-6.0 points a week."""
    for mu, measured in ((3.0, 0.78), (4.0, 0.80), (5.0, 0.77)):
        assert abs(_sim_cv(mu) - measured) < 0.05


def test_a_premium_is_wider_than_the_old_model_said():
    old = np.sqrt(8.0 * 2.4)
    assert match_sd(8.0) > old * 1.3


def test_sd_rises_with_the_mean():
    assert match_sd(2.0) < match_sd(5.0) < match_sd(10.0)


def test_a_zero_projection_has_no_spread():
    """Nothing to be uncertain about, and a negative sd would crash the draw."""
    assert match_sd(0.0) == 0.0


def test_it_accepts_an_array():
    out = match_sd(np.array([[1.0, 4.0], [9.0, 0.0]]))
    assert out.shape == (2, 2) and out[1, 1] == 0.0


def test_the_proportional_term_dominates_at_scale():
    """At a big projection the square-root floor should be a small correction,
    not the shape of the curve · that was the old model's mistake."""
    assert match_sd(20.0) / (MATCH_CV * 20.0) < 1.05
