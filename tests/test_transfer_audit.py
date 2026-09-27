from analytics.transfer_audit import audit, horizon_gains, timing


def _p(**kw):
    base = {"name": "X", "goals": 0, "assists": 0, "xgi": 0.0, "xgi90": 0.2, "luck": 0.0,
            "gws": 5, "starts": 5, "mins_list": [90] * 5, "status": "a", "news": "",
            "penalties": None, "defcon_rate": None, "net_transfers": 0}
    base.update(kw)
    return base


def test_timing_finds_the_later_entry_week():
    out = {6: 5.0, 7: 5.0, 8: 1.0, 9: 1.0}
    inn = {6: 3.0, 7: 3.0, 8: 5.0, 9: 5.0}
    tm = timing(out, inn, friction=2.0)
    assert tm["best_week"] == 8
    assert tm["gain_if_made"][8] == 6.0
    assert tm["now_gain"] == 2.0 and tm["wait_value"] == 4.0


def test_horizon_gains_show_a_late_only_move():
    hz = horizon_gains({6: 5, 7: 5, 8: 1}, {6: 4, 7: 4, 8: 6})
    assert hz[1] < 0 and hz[3] > 0


def test_verdict_waits_when_later_is_worth_more():
    tm = timing({6: 5.0, 7: 5.0, 8: 1.0, 9: 1.0}, {6: 3.0, 7: 3.0, 8: 5.0, 9: 5.0})
    v = audit(_p(), _p(), tm, {1: -2, 3: 2}, None, None, team_gain=4.0)
    assert v["verdict"].startswith("Wait until GW8")


def test_flagged_incoming_player_is_skipped():
    tm = timing({6: 1.0}, {6: 6.0})
    v = audit(_p(), _p(status="i", news="Knee"), tm, {1: 5}, None, None, team_gain=5.0)
    assert v["verdict"] == "Skip"


def test_selling_a_cold_spell_is_flagged():
    tm = timing({6: 3.0}, {6: 6.0})
    v = audit(_p(name="Saka", goals=0, assists=1, xgi=3.5, xgi90=0.7, luck=-2.5), _p(),
              tm, {1: 3}, None, None, team_gain=3.0)
    assert any("running cold" in f["text"] for f in v["flags"])
