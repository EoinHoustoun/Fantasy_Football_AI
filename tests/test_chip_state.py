from analytics.chip_state import chip_state, half_of


def test_half_boundary():
    assert half_of(19) == 1
    assert half_of(20) == 2


def test_used_first_half_chips_are_removed():
    played = [{"name": "bboost", "event": 1}, {"name": "3xc", "event": 3},
              {"name": "wildcard", "event": 4}]
    s = chip_state(played, planning_gw=6)
    assert s["half"] == 1 and s["gw_lo"] == 6 and s["gw_hi"] == 19
    assert s["remaining"] == ["freehit"]
    assert s["used"] == {"bboost": 1, "3xc": 3, "wildcard": 4}


def test_second_half_resets_the_set():
    played = [{"name": "bboost", "event": 1}, {"name": "wildcard", "event": 22}]
    s = chip_state(played, planning_gw=25)
    assert s["half"] == 2 and s["gw_hi"] == 38
    assert "bboost" in s["remaining"] and "wildcard" not in s["remaining"]


def test_no_history_means_all_chips():
    assert chip_state([], 1)["remaining"] == ["wildcard", "freehit", "bboost", "3xc"]
