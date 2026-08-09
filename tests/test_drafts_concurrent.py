"""Two browser sessions saving at once must not crash the page.

`_write` staged every save through ONE fixed `saved_drafts.json.tmp`. Two
Streamlit sessions on the draft page raced it: the first renamed the temp file
into place, the second found nothing left to rename and took the whole page down
with a FileNotFoundError. Eoin hit this live on the New draft button.
"""
import json
import threading

import pytest

from analytics import drafts as DR


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "saved_drafts.json"
    monkeypatch.setattr(DR, "STORE_PATH", p)
    return p


def test_concurrent_saves_all_survive(store):
    errors = []

    def _save(i):
        try:
            DR.save_draft("draft %d" % i, {"budget": 100.0}, draft_id="d%d" % i)
        except Exception as exc:            # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_save, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors

    saved = json.loads(store.read_text())
    # Not just "it did not crash". Each save is a read-modify-write, so without
    # a lock round the whole cycle a later writer rebuilds the file from a
    # snapshot taken before the earlier one landed and silently drops it.
    assert [d for d in ("d%d" % i for i in range(12)) if d not in saved] == []


def test_a_stale_temp_file_does_not_block_a_save(store):
    (store.parent / "saved_drafts.json.tmp").write_text("{ truncated")
    DR.save_draft("after the crash", {"budget": 100.0}, draft_id="ok")
    assert "ok" in json.loads(store.read_text())
