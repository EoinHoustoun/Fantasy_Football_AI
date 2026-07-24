"""Manual projection overrides: minutes recompute, haircut, nailed/benched."""
import pandas as pd

from analytics.projection_overrides import apply_overrides


def _uni() -> pd.DataFrame:
    return pd.DataFrame([
        # pp90 5.0, injured last year (few minutes) -> low projection
        {"code": 111, "web_name": "Injured", "projected_pp90": 5.0,
         "projected_minutes": 700, "projected_points": 39.0,
         "mins_share": 0.20, "starts_ratio": 0.20},
        # overperformer to haircut
        {"code": 222, "web_name": "Hot", "projected_pp90": 6.0,
         "projected_minutes": 2400, "projected_points": 160.0,
         "mins_share": 0.70, "starts_ratio": 0.90},
        # keeper who became a backup
        {"code": 333, "web_name": "Backup", "projected_pp90": 3.4,
         "projected_minutes": 2400, "projected_points": 90.0,
         "mins_share": 0.70, "starts_ratio": 0.95},
        # untouched
        {"code": 444, "web_name": "Normal", "projected_pp90": 4.0,
         "projected_minutes": 2000, "projected_points": 89.0,
         "mins_share": 0.58, "starts_ratio": 0.60},
    ])


_OVERRIDES = {
    111: {"minutes": 3000, "note": "fit now"},
    222: {"pts_mult": 0.85, "note": "regression"},
    333: {"benched": True, "note": "backup"},
}


def test_minutes_override_recomputes_points_from_pp90(monkeypatch):
    import analytics.projection_overrides as mod
    monkeypatch.setattr(mod, "load_overrides", lambda season=None: _OVERRIDES)
    out = apply_overrides(_uni())
    r = out[out["code"] == 111].iloc[0]
    assert r["projected_minutes"] == 3000
    assert r["projected_points"] == round(5.0 * 3000 / 90.0, 1)   # ~166.7
    assert r["starts_ratio"] > 0.8                                 # now counts as nailed


def test_haircut_scales_points_only(monkeypatch):
    import analytics.projection_overrides as mod
    monkeypatch.setattr(mod, "load_overrides", lambda season=None: _OVERRIDES)
    out = apply_overrides(_uni())
    r = out[out["code"] == 222].iloc[0]
    assert r["projected_points"] == round(160.0 * 0.85, 1)
    assert r["projected_minutes"] == 2400          # unchanged


def test_benched_zeroes_out_minutes(monkeypatch):
    import analytics.projection_overrides as mod
    monkeypatch.setattr(mod, "load_overrides", lambda season=None: _OVERRIDES)
    out = apply_overrides(_uni())
    r = out[out["code"] == 333].iloc[0]
    assert r["projected_minutes"] < 300
    assert r["projected_points"] < 15
    assert r["starts_ratio"] < 0.2


def test_unlisted_player_untouched(monkeypatch):
    import analytics.projection_overrides as mod
    monkeypatch.setattr(mod, "load_overrides", lambda season=None: _OVERRIDES)
    out = apply_overrides(_uni())
    r = out[out["code"] == 444].iloc[0]
    assert r["projected_points"] == 89.0
    assert r["override_note"] == ""


def test_no_overrides_is_a_noop():
    out = apply_overrides(_uni(), season="1999-00")   # no such file
    pd.testing.assert_series_equal(
        out["projected_points"], _uni()["projected_points"])
