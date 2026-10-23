"""The pre-plan freshness check and confirmed-starter team news."""
import json
import time

from analytics import service as S


def _bs(news_added="2026-10-21T22:00:10Z", deadline="2026-10-23T17:30:00Z"):
    return {"events": [{"id": 8, "is_next": True, "finished": False, "deadline_time": deadline},
                       {"id": 7, "finished": True}],
            "elements": [{"news_added": news_added}, {"news_added": None}]}


def test_freshness_flags_an_old_bootstrap_on_deadline_day(tmp_path, monkeypatch):
    f = tmp_path / "fpl_bootstrap.json"
    f.write_text("{}")
    now = S._parse_ts("2026-10-23T09:30:00Z")
    old = now - 3 * 3600
    import os
    os.utime(f, (old, old))
    monkeypatch.setattr(S, "_source_files", lambda: {"bootstrap": f})
    monkeypatch.setattr(S, "inputs", lambda: {"bootstrap": _bs()})
    out = S.freshness(now=now)
    assert out["sources"]["bootstrap"]["age_min"] == 180
    assert out["stale"] == ["bootstrap"]
    assert out["latest_news"] == "2026-10-21T22:00:10Z"


def test_freshness_is_clean_when_sources_are_new(tmp_path, monkeypatch):
    f = tmp_path / "fpl_bootstrap.json"
    f.write_text("{}")
    monkeypatch.setattr(S, "_source_files", lambda: {"bootstrap": f})
    monkeypatch.setattr(S, "inputs", lambda: {"bootstrap": _bs()})
    out = S.freshness(now=time.time())
    assert out["stale"] == []


def test_confirm_starters_writes_the_file_for_the_next_gw(tmp_path, monkeypatch):
    from analytics import brain
    p = tmp_path / "confirmed_starters.json"
    monkeypatch.setattr(brain, "CONFIRMED_PATH", p)
    monkeypatch.setattr(S, "find_players", lambda names: [222531])
    monkeypatch.setattr(S, "gameweek_info", lambda: {"next_gw": 8})
    out = S.set_confirmed_starters(["Gibbs-White"])
    assert json.loads(p.read_text()) == {"gw": 8, "codes": [222531]}
    assert out["codes"] == [222531]
    assert brain.load_confirmed(8) == {222531}
