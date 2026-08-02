"""Saved drafts on disk · seeding, saving, deleting, and remembering.

All figures here are INVENTED.
"""
# ── remembering which draft you were on ──────────────────────────────────────

def test_last_used_survives_a_reload(tmp_path, monkeypatch):
    """Session state dies on reload; the picker must not snap to a stranger."""
    import analytics.drafts as D
    monkeypatch.setattr(D, "STORE_PATH", tmp_path / "d.json")
    D.save_draft("Mine", {})
    D.remember_last("mine")
    assert D.last_used() == "mine"


def test_last_used_is_not_returned_as_a_draft(tmp_path, monkeypatch):
    import analytics.drafts as D
    monkeypatch.setattr(D, "STORE_PATH", tmp_path / "d.json")
    D.save_draft("Mine", {})
    D.remember_last("mine")
    assert all(isinstance(d, dict) and "name" in d
               for d in D.load_drafts(seed_presets=False))


def test_remembering_the_same_draft_twice_does_not_rewrite(tmp_path, monkeypatch):
    import analytics.drafts as D
    monkeypatch.setattr(D, "STORE_PATH", tmp_path / "d.json")
    D.save_draft("Mine", {})
    D.remember_last("mine")
    before = (tmp_path / "d.json").stat().st_mtime_ns
    D.remember_last("mine")
    assert (tmp_path / "d.json").stat().st_mtime_ns == before


def test_last_used_is_none_on_a_fresh_store(tmp_path, monkeypatch):
    import analytics.drafts as D
    monkeypatch.setattr(D, "STORE_PATH", tmp_path / "d.json")
    assert D.last_used() is None
