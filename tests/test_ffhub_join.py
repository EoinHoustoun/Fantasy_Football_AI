"""Hub snapshot join · name plus CLUB, and the fixture parsing around it.

All figures and player names here are INVENTED. The Hub snapshot is paid
third-party data, is gitignored, and must never be reproduced in a public repo.

The rule worth protecting: the join key is name AND club. FPL web_names collide
across clubs (two Silvas, two Sanchezes), and a name-only join hands one player
another player's projection without any error to notice.
"""
import pandas as pd

from data.fetchers.ffhub import match_to_board, parse_fixture, per_gw_frame


def _snap(rows):
    return pd.DataFrame(rows)


def _board(rows):
    return pd.DataFrame(rows)


# ── the club half of the key ─────────────────────────────────────────────────

def test_same_name_at_two_clubs_does_not_cross_over():
    snap = _snap([
        {"name": "J.Silva", "team": "Redtown", "pred": 100.0, "pps": 4.0},
        {"name": "J.Silva", "team": "Bluefield", "pred": 40.0, "pps": 1.5},
    ])
    board = _board([
        {"web_name": "J.Silva", "team_name": "Redtown", "code": 1},
        {"web_name": "J.Silva", "team_name": "Bluefield", "code": 2},
    ])
    m = match_to_board(snap, board)["matched"].set_index("code")
    assert m.loc[1, "ffh_pred"] == 100.0
    assert m.loc[2, "ffh_pred"] == 40.0


def test_a_player_who_moved_club_does_not_match_his_old_row():
    """A transfer must show as unmatched rather than silently importing the
    projection made for him at a different club."""
    snap = _snap([{"name": "A.Mover", "team": "Redtown", "pred": 120.0, "pps": 5.0}])
    board = _board([{"web_name": "A.Mover", "team_name": "Bluefield", "code": 7}])
    assert match_to_board(snap, board)["matched"].empty


def test_match_rate_is_reported():
    snap = _snap([{"name": "A.One", "team": "Redtown", "pred": 90.0, "pps": 3.0}])
    board = _board([
        {"web_name": "A.One", "team_name": "Redtown", "code": 1},
        {"web_name": "B.Two", "team_name": "Redtown", "code": 2},
    ])
    assert match_to_board(snap, board)["rate"] == 0.5


def test_empty_inputs_return_an_empty_result_not_an_exception():
    for snap, board in ((None, _board([])), (_snap([]), None),
                        (pd.DataFrame(), pd.DataFrame())):
        out = match_to_board(snap, board)
        assert out["matched"].empty
        assert out["rate"] == 0.0


def test_accents_fold_so_a_real_player_still_matches():
    """Both feeds write the compact "B.Name" form, so the case that actually
    bites is an accent on one side and not the other."""
    snap = _snap([{"name": "A.Martínez", "team": "Redtown",
                   "pred": 150.0, "pps": 6.0}])
    board = _board([{"web_name": "A.Martinez", "team_name": "Redtown", "code": 3}])
    assert len(match_to_board(snap, board)["matched"]) == 1


def test_per_gw_columns_come_across():
    snap = _snap([{"name": "A.One", "team": "Redtown", "pos": "MID", "pred": 90.0, "pps": 3.0,
                   "gw1_pts": 5.0, "gw1_min": 88.0, "gw1_opp": "BLU(H)"}])
    board = _board([{"web_name": "A.One", "team_name": "Redtown", "code": 1}])
    m = match_to_board(snap, board)["matched"]
    assert m.iloc[0]["gw1_pts"] == 5.0
    assert m.iloc[0]["gw1_min"] == 88.0


# ── fixture labels ───────────────────────────────────────────────────────────

def test_home_and_away_are_read_from_the_label():
    home = parse_fixture("BLU(H)")
    away = parse_fixture("BLU(A)")
    assert home and home["home"] is True
    assert away and away["home"] is False


def test_an_unparseable_label_returns_none_rather_than_guessing():
    assert parse_fixture(None) is None
    assert parse_fixture("") is None
    assert parse_fixture("not a fixture") is None


def test_stray_whitespace_still_parses():
    """Defensive · a formatting change upstream should degrade to a parsed
    fixture, not a silently blank run."""
    assert parse_fixture("BLU (H)") == {"opp": "BLU", "home": True}


# ── per-gameweek reshape ─────────────────────────────────────────────────────

def test_per_gw_frame_is_one_row_per_player_gameweek():
    snap = _snap([{"name": "A.One", "team": "Redtown", "pos": "MID", "pred": 90.0, "pps": 3.0,
                   "gw1_pts": 5.0, "gw1_min": 88.0, "gw1_opp": "BLU(H)",
                   "gw2_pts": 4.0, "gw2_min": 70.0, "gw2_opp": "GRN(A)"}])
    out = per_gw_frame(snap)
    assert set(out["gw"]) == {1, 2}
    assert len(out) == 2
    row1 = out[out["gw"] == 1].iloc[0]
    assert row1["pts"] == 5.0
    assert row1["exp_mins"] == 88.0


def test_per_gw_frame_survives_a_snapshot_with_no_gameweek_columns():
    snap = _snap([{"name": "A.One", "team": "Redtown", "pos": "MID",
                   "pred": 90.0, "pps": 3.0}])
    out = per_gw_frame(snap)
    assert out.empty or "gw" in out.columns
