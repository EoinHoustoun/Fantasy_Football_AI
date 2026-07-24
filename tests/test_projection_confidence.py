"""Projection confidence tiers + honest ranges."""
import pandas as pd

from analytics.projection_confidence import add_confidence


def _df() -> pd.DataFrame:
    return pd.DataFrame([
        {"web_name": "FullSeason", "projected_points": 200.0,
         "last_season_minutes": 3000.0, "override_note": ""},
        {"web_name": "PartSeason", "projected_points": 100.0,
         "last_season_minutes": 1800.0, "override_note": ""},
        {"web_name": "SmallSample", "projected_points": 80.0,
         "last_season_minutes": 600.0, "override_note": ""},
        {"web_name": "Overridden", "projected_points": 175.0,
         "last_season_minutes": 3200.0, "override_note": "fit again, assumed nailed"},
    ])


def test_tiers_from_minutes_and_override():
    out = add_confidence(_df())
    c = {r["web_name"]: r["confidence"] for _, r in out.iterrows()}
    assert c["FullSeason"] == "High"
    assert c["PartSeason"] == "Medium"
    assert c["SmallSample"] == "Low"
    # big sample, but an override is an assumption -> capped at Low
    assert c["Overridden"] == "Low"


def test_range_widens_as_confidence_drops():
    out = add_confidence(_df())
    hi = out[out["web_name"] == "FullSeason"].iloc[0]
    lo = out[out["web_name"] == "Overridden"].iloc[0]
    hi_width = (hi["proj_hi"] - hi["proj_lo"]) / hi["projected_points"]
    lo_width = (lo["proj_hi"] - lo["proj_lo"]) / lo["projected_points"]
    assert lo_width > hi_width
    assert hi["proj_lo"] < 200 < hi["proj_hi"]


def test_missing_override_column_is_ok():
    df = _df().drop(columns=["override_note"])
    out = add_confidence(df)
    assert out[out["web_name"] == "FullSeason"].iloc[0]["confidence"] == "High"


def test_fullback_is_downgraded_one_tier_with_note():
    df = _df().copy()
    df["role"] = ["FB", "CB", "", ""]   # FullSeason is a fullback
    out = add_confidence(df)
    fb = out[out["web_name"] == "FullSeason"].iloc[0]
    cb = out[out["web_name"] == "PartSeason"].iloc[0]
    assert fb["confidence"] == "Medium"          # High -> Medium
    assert "fullback" in fb["confidence_note"]
    assert cb["confidence"] == "Medium" and cb["confidence_note"] == ""   # CB untouched


def test_changed_club_downgrades_confidence():
    df = _df().copy()
    df["changed_club"] = [True, False, False, False]   # FullSeason moved clubs
    out = add_confidence(df)
    moved = out[out["web_name"] == "FullSeason"].iloc[0]
    assert moved["confidence"] == "Medium"             # High -> Medium
    assert "new club" in moved["confidence_note"]
