"""The bootstrap must be part of the cache key, now that caches outlive the process.

`inputs_stamp` watched only the hand-refreshed snapshots. The FPL bootstrap
carries live prices, injury status and team news, and the board and the universe
are both built from it · so a bootstrap refresh changed nothing on screen.

That was survivable while every cache died with the process. `data.disk_cache`
persists a build across restarts, so a board keyed on a stamp blind to the
bootstrap could serve yesterday's injury flags indefinitely.
"""
from analytics import freshness


def test_the_bootstrap_is_watched():
    assert any("bootstrap" in str(p).lower() for p in freshness._paths().values()), \
        "inputs_stamp is blind to the bootstrap, so live prices and injury news " \
        "cannot invalidate a persisted board"


def test_a_bootstrap_refresh_moves_the_stamp(tmp_path, monkeypatch):
    fake = tmp_path / "fpl_bootstrap.json"
    fake.write_text("{}")
    monkeypatch.setattr(freshness, "_paths", lambda: {"Bootstrap": fake})
    before = freshness.inputs_stamp()
    import os, time
    os.utime(fake, (time.time() + 60, time.time() + 60))
    assert freshness.inputs_stamp() != before
