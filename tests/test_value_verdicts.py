"""Value-verdict engine: actual 2026/27 price vs archive-projected points.

The engine buckets by per-position percentiles, so the fixture seeds a realistic
spread of filler players per position, then drops in four "characters" whose
numbers place them unambiguously in one bucket each.
"""
from typing import Dict, List, Tuple

import pandas as pd

from analytics.value_verdicts import build_value_verdicts, VERDICTS

_TYPE = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}

# Neutral filler pts per position · a gradient so percentiles are meaningful.
_FILLER_PTS = {
    "DEF": [80, 90, 100, 110, 130, 160, 170, 180, 190, 200],
    "MID": [90, 100, 120, 130, 140, 150, 160, 180, 200, 220],
    "FWD": [90, 100, 110, 130, 140, 150, 160, 170, 180, 200],
    "GKP": [90, 100, 110, 120, 130, 140, 150, 160, 170, 180],
}


def _fixtures() -> Tuple[pd.DataFrame, dict]:
    proj_rows: List[Dict] = []
    boot_rows: List[Dict] = []
    code = 100
    for pos, pts_list in _FILLER_PTS.items():
        for pts in pts_list:
            price = round(pts / 20.0, 1)          # value_score ~20, surprise 0
            proj_rows.append({
                "code": code, "web_name": f"F{code}", "position": pos,
                "team_name": "Z", "projected_points": pts,
                "projected_minutes": 2200, "predicted_start_price": price,
                "price_2025_26_end": price, "last_season_points": pts,
                "mins_share": 0.60, "team_short": "ARS", "team_code": 3,
            })
            boot_rows.append({
                "code": code, "now_cost": int(price * 10), "element_type": _TYPE[pos],
                "team": 1, "selected_by_percent": "5.0", "web_name": f"F{code}", "status": "a",
            })
            code += 1

    # Characters (codes 1-4) + one new signing (99) present only in bootstrap.
    chars_proj = [
        {"code": 1, "web_name": "Star", "position": "MID", "team_name": "A",
         "projected_points": 240, "projected_minutes": 3200,
         "predicted_start_price": 12.0, "price_2025_26_end": 12.0,
         "last_season_points": 250, "mins_share": 0.94, "team_short": "ARS", "team_code": 3},
        {"code": 2, "web_name": "Bargain", "position": "DEF", "team_name": "OldClub",
         "projected_points": 150, "projected_minutes": 3000,
         "predicted_start_price": 6.5, "price_2025_26_end": 6.0,
         "last_season_points": 160, "mins_share": 0.88, "team_short": "OLD", "team_code": 99},
        {"code": 3, "web_name": "Tax", "position": "FWD", "team_name": "C",
         "projected_points": 120, "projected_minutes": 2400,
         "predicted_start_price": 8.0, "price_2025_26_end": 8.5,
         "last_season_points": 210, "mins_share": 0.70, "team_short": "CHE", "team_code": 8},
        {"code": 4, "web_name": "Middle", "position": "MID", "team_name": "D",
         "projected_points": 110, "projected_minutes": 2300,
         "predicted_start_price": 6.0, "price_2025_26_end": 6.0,
         "last_season_points": 115, "mins_share": 0.66, "team_short": "EVE", "team_code": 11},
    ]
    chars_boot = [
        {"code": 1, "now_cost": 120, "element_type": 3, "team": 1,
         "selected_by_percent": "55.0", "web_name": "Star", "status": "a"},
        {"code": 2, "now_cost": 50, "element_type": 2, "team": 2,
         "selected_by_percent": "30.0", "web_name": "Bargain", "status": "a"},
        {"code": 3, "now_cost": 95, "element_type": 4, "team": 3,
         "selected_by_percent": "12.0", "web_name": "Tax", "status": "a"},
        {"code": 4, "now_cost": 60, "element_type": 3, "team": 4,
         "selected_by_percent": "8.0", "web_name": "Middle", "status": "a"},
        {"code": 99, "now_cost": 75, "element_type": 3, "team": 5,
         "selected_by_percent": "3.0", "web_name": "Newbie", "status": "a"},
    ]
    proj = pd.DataFrame(proj_rows + chars_proj)
    boot = {
        "elements": boot_rows + chars_boot,
        "teams": [{"id": i, "short_name": s, "name": s + " FC", "code": 100 + i}
                  for i, s in enumerate(["ARS", "AVL", "CHE", "EVE", "COV"], start=1)],
    }
    return proj, boot


def test_actual_price_and_value_score_join_by_code():
    proj, boot = _fixtures()
    df, _ = build_value_verdicts(proj, boot)
    star = df[df["code"] == 1].iloc[0]
    assert star["actual_price"] == 12.0
    assert round(star["value_score"], 1) == round(240 / 12.0, 1)


def test_pricing_surprise_sign():
    proj, boot = _fixtures()
    df, _ = build_value_verdicts(proj, boot)
    assert df[df["code"] == 2].iloc[0]["pricing_surprise"] == 1.5   # FPL below model
    assert df[df["code"] == 3].iloc[0]["pricing_surprise"] == -1.5  # FPL above model


def test_verdict_buckets():
    proj, boot = _fixtures()
    df, _ = build_value_verdicts(proj, boot)
    v = {r["code"]: r["verdict"] for _, r in df.iterrows()}
    assert v[1] == VERDICTS.NECESSITY
    assert v[2] == VERDICTS.VALUE
    assert v[3] == VERDICTS.OVERPRICED
    assert v[4] == VERDICTS.FAIR


def test_new_players_go_to_scout_frame_not_verdicts():
    proj, boot = _fixtures()
    df, scout = build_value_verdicts(proj, boot)
    assert 99 not in set(df["code"])
    assert 99 in set(scout["code"])
    newbie = scout[scout["code"] == 99].iloc[0]
    assert newbie["actual_price"] == 7.5
    assert newbie["verdict"] == VERDICTS.SCOUT


def test_every_verdict_row_has_a_reason():
    proj, boot = _fixtures()
    df, _ = build_value_verdicts(proj, boot)
    assert df["verdict_reason"].str.len().gt(0).all()


def test_live_club_overrides_stale_archive_team():
    # Bargain's archive club is "OLD"/OLDClub, but live bootstrap has team_id 2 = AVL.
    proj, boot = _fixtures()
    df, _ = build_value_verdicts(proj, boot)
    bargain = df[df["code"] == 2].iloc[0]
    assert bargain["team_short"] == "AVL"
    assert bargain["team_name"] == "AVL FC"
    assert bargain["team_id"] == 2


# ── ambiguous names ──────────────────────────────────────────────────────────

def test_a_shared_web_name_gets_a_club_suffix():
    """Palmer is a Chelsea midfielder AND an Ipswich keeper. Resolving a lock by
    bare web_name bound whichever happened to sort first."""
    import pandas as pd
    from ui.value_board import _unique_names
    df = pd.DataFrame({"web_name": ["Palmer", "Palmer", "Haaland"],
                       "team_short": ["CHE", "IPS", "MCI"]})
    out = list(_unique_names(df))
    assert out == ["Palmer (CHE)", "Palmer (IPS)", "Haaland"]


def test_unique_names_are_unique():
    import pandas as pd
    from ui.value_board import _unique_names
    df = pd.DataFrame({"web_name": ["A", "A", "B", "C", "C", "C"],
                       "team_short": ["X", "Y", "X", "P", "Q", "R"]})
    assert len(set(_unique_names(df))) == 6


def test_an_unshared_name_is_left_alone():
    import pandas as pd
    from ui.value_board import _unique_names
    df = pd.DataFrame({"web_name": ["Solo"], "team_short": ["ARS"]})
    assert list(_unique_names(df)) == ["Solo"]


def test_it_survives_a_board_with_no_club_column():
    import pandas as pd
    from ui.value_board import _unique_names
    df = pd.DataFrame({"web_name": ["A", "A"]})
    out = list(_unique_names(df))
    assert len(out) == 2 and all(o.startswith("A") for o in out)
