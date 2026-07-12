"""
Unit tests for the historical archive normalization (data/processors/archive.py).

Uses synthetic vaastav-shaped frames via monkeypatch · no network.
Run: python -m pytest tests/test_archive.py -q
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.processors import archive as arc


def _players_raw(season):
    """Two real players + one 2024-25 'assistant manager' (element_type 5)."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "code": [101, 202, 909],
        "element_type": [3, 2, 5],
        "first_name": ["Mo", "Virgil", "Pep"],
        "second_name": ["Salah", "van Dijk", "Guardiola"],
        "web_name": ["Salah", "Van Dijk", "Guardiola"],
        "team": [11, 11, 13],
    })


def _merged_gw(season):
    gws = [1, 2, 39, 40] if season == "2019-20" else [1, 2, 3, 4]
    return pd.DataFrame({
        "element": [1, 1, 2, 3],
        "GW": gws,
        "name": ["Mo_Salah_1", "Mo_Salah_1", "Virgil_van_Dijk_2", "Pep_Guardiola_3"],
        "minutes": [90, 85, 90, 0],
        "total_points": [12, 2, 6, 4],
        "goals_scored": [2, 0, 0, 0],
        "assists": [0, 0, 1, 0],
        "clean_sheets": [0, 0, 1, 0],
        "goals_conceded": [1, 2, 0, 0],
        "own_goals": [0, 0, 0, 0],
        "penalties_saved": [0, 0, 0, 0],
        "penalties_missed": [0, 0, 0, 0],
        "saves": [0, 0, 0, 0],
        "yellow_cards": [0, 0, 0, 0],
        "red_cards": [0, 0, 0, 0],
        "bonus": [3, 0, 1, 0],
        "bps": [60, 10, 30, 5],
        "value": [125, 126, 60, 10],
        "selected": [5000000, 5100000, 1000000, 1],
        "transfers_in": [0, 100, 50, 0],
        "transfers_out": [0, 50, 20, 0],
        "fixture": [10, 20, 30, 40],
        "kickoff_time": ["2019-08-10T14:00:00Z"] * 4,
        "was_home": [True, False, True, False],
        "opponent_team": [4, 5, 6, 7],
    })


def _master_team_list():
    return pd.DataFrame({
        "season": ["2019-20", "2019-20", "2024-25", "2024-25"],
        "team": [11, 13, 11, 13],
        "team_name": ["Liverpool", "Man City", "Liverpool", "Man City"],
    })


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(arc, "fetch_players_raw", _players_raw)
    monkeypatch.setattr(arc, "fetch_gw_history", _merged_gw)
    monkeypatch.setattr(arc, "fetch_master_team_list", _master_team_list)


def test_element_to_code_join(patched):
    df = arc._normalize_vaastav_season("2024-25")
    assert set(df["code"].unique()) == {101, 202}
    salah = df[df["code"] == 101]
    assert (salah["player_name"] == "Mo Salah").all()
    assert (salah["position"] == "MID").all()


def test_manager_filter_2024_25(patched):
    """element_type 5 rows (assistant managers) must not survive the join."""
    df = arc._normalize_vaastav_season("2024-25")
    assert 909 not in df["code"].values


def test_covid_gw_remap_2019_20(patched):
    # manager row (GW 40) is filtered by the join; 39 remaps to 30
    df = arc._normalize_vaastav_season("2019-20")
    assert sorted(df["gw"].unique()) == [1, 2, 30]


def test_no_remap_other_seasons(patched):
    df = arc._normalize_vaastav_season("2024-25")
    assert sorted(df["gw"].unique()) == [1, 2, 3]


def test_price_and_nullable_stats(patched):
    df = arc._normalize_vaastav_season("2024-25")
    assert df[df["code"] == 101]["price"].iloc[0] == pytest.approx(12.5)
    # synthetic season has no xG columns → must be NaN, not 0
    assert df["xg"].isna().all()
    assert df["defensive_contribution"].isna().all()


def test_team_names_joined(patched):
    df = arc._normalize_vaastav_season("2024-25")
    assert (df[df["code"] == 101]["team_name"] == "Liverpool").all()


def test_dgw_aggregation(tmp_path, monkeypatch):
    """build_optimizer_input must sum DGW fixtures into one (player, GW) row."""
    gw = pd.DataFrame({
        "season": ["2025-26"] * 3,
        "code": [101, 101, 101],
        "gw": [1, 2, 2],                      # GW2 is a DGW
        "total_points": [5, 8, 9],
        "price": [12.5, 12.5, 12.6],
        "minutes": [90, 90, 88],
        "team_id": [11, 11, 11],
        "team_name": ["Liverpool"] * 3,
        "player_name": ["Mo Salah"] * 3,
        "web_name": ["Salah"] * 3,
        "position": ["MID"] * 3,
    })
    monkeypatch.setattr(arc, "load_gw_archive", lambda: gw)
    out = arc.build_optimizer_input("2025-26")
    gw2 = out[(out["code"] == 101) & (out["gw"] == 2)]
    assert len(gw2) == 1
    assert gw2["points"].iloc[0] == 17


def test_blank_gw_forward_fill(monkeypatch):
    """Players missing a GW stay holdable: 0 pts, price forward-filled."""
    gw = pd.DataFrame({
        "season": ["2025-26"] * 2,
        "code": [101, 101],
        "gw": [1, 3],                          # GW2 blank
        "total_points": [5, 7],
        "price": [12.5, 12.7],
        "minutes": [90, 90],
        "team_id": [11, 11],
        "team_name": ["Liverpool"] * 2,
        "player_name": ["Mo Salah"] * 2,
        "web_name": ["Salah"] * 2,
        "position": ["MID"] * 2,
    })
    monkeypatch.setattr(arc, "load_gw_archive", lambda: gw)
    out = arc.build_optimizer_input("2025-26")
    gw2 = out[(out["code"] == 101) & (out["gw"] == 2)]
    assert len(gw2) == 1
    assert gw2["points"].iloc[0] == 0
    assert gw2["price"].iloc[0] == pytest.approx(12.5)
    assert not gw2["played"].iloc[0]


def test_defcon_points():
    g = pd.DataFrame({
        "position": ["DEF"] * 3,
        "cbit": [12.0, 8.0, 10.0],
        "recoveries": [np.nan] * 3,
        "minutes": [90, 90, 90],
    })
    assert arc._defcon_points(g) == 4.0      # 2 games >= 10

    g_mid = pd.DataFrame({
        "position": ["MID"] * 2,
        "cbit": [8.0, 9.0],
        "recoveries": [5.0, 2.0],            # 13 hits, 11 misses (threshold 12)
        "minutes": [90, 90],
    })
    assert arc._defcon_points(g_mid) == 2.0

    g_old = pd.DataFrame({
        "position": ["DEF"], "cbit": [np.nan], "recoveries": [np.nan], "minutes": [90],
    })
    assert np.isnan(arc._defcon_points(g_old))
