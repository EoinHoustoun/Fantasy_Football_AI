"""The pure row builders behind My Team's forward-week pitch and candidate table.

The view itself is a Streamlit script, so the shapes the pitch component and
`ff_table` expect are unit-tested here through `ui/team_pitch_rows.py` instead.
"""
import pandas as pd


class _Proj:
    def points(self, code, gw):
        return {1: 5.0, 2: 3.0}.get(code, 1.0)

    def expected_minutes(self, code, gw):
        return 90.0 if code == 1 else 30.0


def _load_view_helpers():
    from ui import team_pitch_rows as R
    return R


def test_pitch_rows_mark_xi_captain_axed_and_swap_ok():
    R = _load_view_helpers()
    sq = pd.DataFrame([
        {"code": 1, "web_name": "A", "position": "MID", "team_code": 3, "team_short": "ARS",
         "team_id": 1, "actual_price": 8.0, "pens_order": 1},
        {"code": 2, "web_name": "B", "position": "DEF", "team_code": 3, "team_short": "ARS",
         "team_id": 1, "actual_price": 4.5, "pens_order": None},
    ])
    fix = {(1, 2): [("CHE", True, 3.0)]}
    rows = R.pitch_rows(sq, 2, _Proj(), fix, xi={1}, captain=1, axed=[2], sub_from=None,
                        swap_targets={2})
    a, b = rows
    assert a["stat"] == 5.0 and a["is_captain"] and not a["on_bench"] and a["exp_mins"] == 90.0
    assert b["on_bench"] and b["is_axed"] and b["swap_ok"]
    assert a["fixtures"][0]["opp"] == "CHE" and a["fpl_id"] == 1


def test_candidate_rows_price_delta_and_pool_shape():
    R = _load_view_helpers()
    pool = pd.DataFrame([{"code": 9, "web_name": "C", "team_short": "LIV", "position": "MID",
                          "actual_price": 6.0, "consensus_points": 120.0, "team_id": 2,
                          "consensus_confidence": "High", "model_spread": 0.1}])
    out_row = pd.Series({"actual_price": 8.0})
    rows = R.candidate_rows(pool, 2, _Proj(), {}, out_row, "consensus_points",
                            dc_hit_fn=lambda c, p: 40.0, glyph_fn=lambda r: "")
    r = rows[0]
    assert r["d_price"] == -2.0 and r["per_m"] == 20.0 and r["spread"] == 10.0 and r["dc_hit"] == 40.0


def test_pitch_rows_survive_a_player_the_board_does_not_know():
    """A code with no board row still renders · name, zero stat, no crash."""
    R = _load_view_helpers()
    sq = pd.DataFrame([
        {"code": 7, "web_name": "Unknown", "position": "FWD", "team_code": None,
         "team_short": None, "team_id": None, "actual_price": None, "pens_order": None},
    ])
    rows = R.pitch_rows(sq, 3, _Proj(), {}, xi=set(), captain=None, axed=[], sub_from=None,
                        swap_targets=set())
    r = rows[0]
    assert r["price"] == 0.0 and r["team_code"] == 1 and r["on_bench"] is True
    assert r["stat"] == 1.0 and len(r["fixtures"]) == 3
