"""Scout snapshot join · name folding, club aliases, and honest unmatched rows."""
import pandas as pd
import pytest

from analytics.scout_projections import (
    coverage, disagreements, load_snapshot, match_to_board, model_scale,
    normalise_name)


def test_normalise_folds_accents_and_punctuation():
    assert normalise_name("B.Fernandes") == "bfernandes"
    assert normalise_name("Joao Pedro") == "joao pedro"
    assert normalise_name("Aït-Nouri") == "ait nouri"
    assert normalise_name("Šesko") == "sesko"
    assert normalise_name("Estêvao") == "estevao"


def test_normalise_folds_letters_nfkd_leaves_alone():
    """Odegaard broke the join before CHAR_ALIASES · o-slash is a letter, not an accent."""
    assert normalise_name("Ødegaard") == normalise_name("Odegaard")
    assert normalise_name("Groß") == "gross"


def _snapshot(tmp_path, rows):
    p = tmp_path / "scout.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def test_load_snapshot_missing_file_returns_none(tmp_path):
    assert load_snapshot(tmp_path / "nope.csv") is None


def test_load_snapshot_missing_columns_returns_none(tmp_path):
    p = _snapshot(tmp_path, [{"name": "X", "team": "ARS"}])
    assert load_snapshot(p) is None


def test_load_snapshot_maps_brighton_alias(tmp_path):
    p = _snapshot(tmp_path, [{"name": "Wieffer", "team": "BRI", "pos": "DEF",
                              "price": 5.0, "mins": 2546, "pts": 144.5, "value": 28.9}])
    df = load_snapshot(p)
    assert df is not None
    assert df.iloc[0]["team_short"] == "BHA"


def _board():
    return pd.DataFrame([
        {"code": 1, "web_name": "Ødegaard", "team_short": "ARS", "position": "MID",
         "actual_price": 6.5, "projected_points": 130.0, "proj_lo": 110.0,
         "proj_hi": 150.0, "confidence": "Medium", "override_note": ""},
        {"code": 2, "web_name": "Wieffer", "team_short": "BHA", "position": "DEF",
         "actual_price": 5.0, "projected_points": 90.0, "proj_lo": 80.0,
         "proj_hi": 100.0, "confidence": "Low", "override_note": ""},
    ])


def _scout(tmp_path):
    return load_snapshot(_snapshot(tmp_path, [
        {"name": "Odegaard", "team": "ARS", "pos": "MID", "price": 6.5,
         "mins": 2931, "pts": 160.2, "value": 24.7},
        {"name": "Wieffer", "team": "BRI", "pos": "DEF", "price": 5.0,
         "mins": 2546, "pts": 144.5, "value": 28.9},
        {"name": "Nobody", "team": "ARS", "pos": "FWD", "price": 4.5,
         "mins": 2000, "pts": 50.0, "value": 11.1},
    ]))


def test_match_joins_across_alias_and_accent(tmp_path):
    res = match_to_board(_scout(tmp_path), _board())
    assert sorted(res["matched"]["web_name"]) == ["Wieffer", "Ødegaard"]


def test_unmatched_rows_are_returned_not_dropped(tmp_path):
    res = match_to_board(_scout(tmp_path), _board())
    assert list(res["unmatched"]["scout_name"]) == ["Nobody"]
    cov = coverage(res)
    assert cov["total"] == 3 and cov["matched"] == 2
    assert "Nobody" in cov["unmatched_names"]


def test_model_scale_is_the_median_ratio(tmp_path):
    """Ours runs below Scout's · the scale must be measured, not assumed to be 1."""
    res = match_to_board(_scout(tmp_path), _board())
    k = model_scale(res["matched"])
    # Odegaard 130/160.2 = 0.811, Wieffer 90/144.5 = 0.623 · median of two
    assert k == pytest.approx((130 / 160.2 + 90 / 144.5) / 2, abs=0.01)


def test_disagreements_rank_on_scale_adjusted_residual_not_raw_gap(tmp_path):
    """A gap that is purely the global scale offset is NOT a disagreement.

    Raw delta would rank Wieffer (+54.5) above Odegaard (+30.2). After removing
    the shared scale the ordering must be driven by the residual instead.
    """
    res = match_to_board(_scout(tmp_path), _board())
    d = disagreements(res["matched"], min_delta=0.0)
    assert "residual" in d.columns
    assert d["abs_residual"].is_monotonic_decreasing if "abs_residual" in d.columns \
        else d["residual"].abs().is_monotonic_decreasing
    # residual = ours - scout * scale, and the two players straddle the scale
    for _, r in d.iterrows():
        assert r["residual"] == pytest.approx(
            r["projected_points"] - r["expected_ours"], abs=0.11)


def test_scale_offset_alone_produces_no_disagreement(tmp_path):
    """Two players who differ from us by exactly the same ratio must both vanish."""
    board = pd.DataFrame([
        {"code": 1, "web_name": "A", "team_short": "ARS", "position": "MID",
         "actual_price": 6.0, "projected_points": 80.0, "proj_lo": 70.0,
         "proj_hi": 90.0, "confidence": "High", "override_note": ""},
        {"code": 2, "web_name": "B", "team_short": "ARS", "position": "DEF",
         "actual_price": 5.0, "projected_points": 40.0, "proj_lo": 30.0,
         "proj_hi": 50.0, "confidence": "High", "override_note": ""},
    ])
    snap = load_snapshot(_snapshot(tmp_path, [
        {"name": "A", "team": "ARS", "pos": "MID", "price": 6.0,
         "mins": 3000, "pts": 160.0, "value": 26.7},
        {"name": "B", "team": "ARS", "pos": "DEF", "price": 5.0,
         "mins": 3000, "pts": 80.0, "value": 16.0},
    ]))
    d = disagreements(match_to_board(snap, board)["matched"], min_delta=1.0)
    assert d.empty      # both exactly 0.5x · pure scale, zero residual


def test_disagreements_ignore_bench_players_by_minutes(tmp_path):
    res = match_to_board(_scout(tmp_path), _board())
    assert disagreements(res["matched"], min_delta=0.0, min_mins=3000).empty

