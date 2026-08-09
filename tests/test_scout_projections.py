"""Scout snapshot join · name folding, club aliases, and honest unmatched rows.

All figures here are INVENTED. The real snapshot is paid third-party data
and is gitignored · never reproduce it in a public repo.
"""
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
                              "price": 5.0, "mins": 2500, "pts": 200.0, "value": 40.0}])
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
         "mins": 3000, "pts": 250.0, "value": 41.7},
        {"name": "Wieffer", "team": "BRI", "pos": "DEF", "price": 5.0,
         "mins": 2500, "pts": 200.0, "value": 40.0},
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
    # 130/250 = 0.52, 90/200 = 0.45 · median of two. Figures are invented:
    # the repo is public and the real snapshot is paid third-party data.
    assert k == pytest.approx((130 / 250.0 + 90 / 200.0) / 2, abs=0.01)


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
    # above every fixture's minutes, so nobody survives the filter
    assert disagreements(res["matched"], min_delta=0.0, min_mins=3200).empty



# ── surname rescue · a missing second opinion is a silent, one-sided error ───

def test_an_initial_prefixed_name_still_joins():
    """FPL writes a clash as "M.Fernandes"; Scout drops the initial. The exact
    key misses and the player loses BOTH second opinions while his number still
    wears a three-model badge. All figures INVENTED."""
    import pandas as pd
    from analytics.scout_projections import match_to_board
    scout = pd.DataFrame({
        "scout_name": ["Fernandes"], "team_short": ["TOT"], "pos": ["MID"],
        "join_key": ["fernandes"], "scout_pts": [100.0], "scout_mins": [2900],
        "scout_price": [6.0]})
    board = pd.DataFrame({
        "code": [1], "web_name": ["M.Fernandes"], "team_short": ["TOT"],
        "position": ["MID"], "actual_price": [6.0], "projected_points": [110.0]})
    out = match_to_board(scout, board)
    assert len(out["matched"]) == 1
    assert int(out["matched"].iloc[0]["code"]) == 1


def test_an_ambiguous_surname_is_left_unmatched():
    """Two Fernandes at the same club in the same position · a wrong join
    silently attributes another player's projection, which is worse than a
    missing one."""
    import pandas as pd
    from analytics.scout_projections import match_to_board
    scout = pd.DataFrame({
        "scout_name": ["Fernandes"], "team_short": ["TOT"], "pos": ["MID"],
        "join_key": ["fernandes"], "scout_pts": [100.0], "scout_mins": [2900],
        "scout_price": [6.0]})
    board = pd.DataFrame({
        "code": [1, 2], "web_name": ["M.Fernandes", "J.Fernandes"],
        "team_short": ["TOT", "TOT"], "position": ["MID", "MID"],
        "actual_price": [6.0, 5.0], "projected_points": [110.0, 90.0]})
    out = match_to_board(scout, board)
    assert len(out["matched"]) == 0


def test_a_different_club_is_not_rescued():
    import pandas as pd
    from analytics.scout_projections import match_to_board
    scout = pd.DataFrame({
        "scout_name": ["Fernandes"], "team_short": ["MUN"], "pos": ["MID"],
        "join_key": ["fernandes"], "scout_pts": [100.0], "scout_mins": [2900],
        "scout_price": [6.0]})
    board = pd.DataFrame({
        "code": [1], "web_name": ["M.Fernandes"], "team_short": ["TOT"],
        "position": ["MID"], "actual_price": [6.0], "projected_points": [110.0]})
    assert len(match_to_board(scout, board)["matched"]) == 0


def test_surname_key_handles_both_spellings():
    from analytics.scout_projections import surname_key
    assert surname_key("M.Fernandes") == surname_key("Fernandes") == "fernandes"
    assert surname_key("B.Fernandes") == "fernandes"
    assert surname_key("Haaland") == "haaland"


# ── Letters that are not accents ─────────────────────────────────────────────

def test_non_decomposable_letters_fold_rather_than_vanish():
    """A letter with no NFKD decomposition is DELETED by ascii-ignore, not folded.

    Kadıoğlu is the case that bit: the Hub writes "F.Kadıoğlu" with a Turkish
    dotless i, Scout writes plain "F.Kadioglu". NFKD folds the ğ but leaves the
    ı alone, and `encode("ascii", "ignore")` then drops it, so one source keyed
    on "fkadoglu" and the other on "fkadioglu". Two keys, one player, no join ·
    and nothing errored. He simply had one fewer model than his badge claimed.
    """
    from analytics.scout_projections import normalise_name
    for turkish, plain in (("F.Kadıoğlu", "F.Kadioglu"),
                           ("Kadıoğlu", "Kadioglu"),
                           ("Şahin", "Sahin"),
                           ("İlkay", "Ilkay")):
        assert normalise_name(turkish) == normalise_name(plain), turkish
    # The letter must be PRESENT, not merely consistent · "kadoglu" on both
    # sides would also be equal and would still be the wrong key.
    assert normalise_name("F.Kadıoğlu") == "fkadioglu"


def test_other_undecomposable_letters_are_covered():
    from analytics.scout_projections import normalise_name
    for odd, plain in (("Ødegaard", "Odegaard"), ("Łukasz", "Lukasz"),
                       ("Þór", "Thor"), ("Đorđe", "Dorde")):
        assert normalise_name(odd) == normalise_name(plain), odd


def test_surname_fallback_folds_the_same_way():
    """The surname rescue must not reintroduce the bug it exists to fix."""
    from analytics.scout_projections import surname_key
    assert surname_key("F.Kadıoğlu") == surname_key("F.Kadioglu") == "kadioglu"
