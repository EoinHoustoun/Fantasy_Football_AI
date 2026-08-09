"""Derived frames, kept on disk between runs instead of rebuilt every time.

`build_board` costs 3.9 seconds and `build_player_universe` 2.8. Streamlit's
`cache_data` holds them for the life of a process, which is fine until the
process restarts or the content stamp moves · and the stamp moves every time an
override is edited, so a one-line change to a JSON file was costing four seconds
on the next interaction.

Both are pure functions of inputs the app already stamps. So cache the RESULT:
frames go to parquet, everything else to a JSON sidecar, both under the stamp.
A rebuild becomes a disk read of about 150ms.

Two rules this module will not break:

1. **The stamp is the whole key.** A different stamp never reads an older
   payload. There is no TTL and no "close enough" · a wrong number served fast
   is worse than a right number served slowly.
2. **A bad cache is never fatal.** Corrupt file, partial write, a pandas or
   pyarrow version that cannot read yesterday's parquet · all of it falls back
   to building, because the page has to render.

Files live under `data/cache/derived/`, which the `data/cache/*` gitignore rule
already covers. Safe to delete at any time.
"""
import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from config import CACHE_DIR

logger = logging.getLogger(__name__)

STORE = Path(CACHE_DIR) / "derived"

# One writer at a time, for the same reason the drafts store needs one: every
# Streamlit session is a thread in a single process.
_LOCK = threading.RLock()

_MANIFEST = "manifest.json"


def _slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(s))[:80]


def _dir_for(name: str, stamp: str) -> Path:
    return STORE / _slug(name) / _slug(stamp)


def _read(path: Path) -> Optional[Dict[str, Any]]:
    man = path / _MANIFEST
    if not man.exists():
        return None
    try:
        meta = json.loads(man.read_text())
        out: Dict[str, Any] = dict(meta.get("plain", {}))
        for key in meta.get("frames", []):
            out[key] = pd.read_parquet(path / ("%s.parquet" % _slug(key)))
        for key in meta.get("nulls", []):
            out[key] = None
        return out
    except Exception as exc:                 # noqa: BLE001 · see rule 2
        logger.warning("derived cache unreadable at %s, rebuilding: %s", path, exc)
        return None


def _write(path: Path, payload: Dict[str, Any]) -> None:
    """Write through a temp directory, then swap · a half-written cache that
    reads as complete is exactly the failure this whole module must not have."""
    tmp = path.with_name(path.name + ".tmp.%d.%d" % (os.getpid(), threading.get_ident()))
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    frames, nulls, plain = [], [], {}
    try:
        for key, val in payload.items():
            if isinstance(val, pd.DataFrame):
                val.to_parquet(tmp / ("%s.parquet" % _slug(key)), index=False)
                frames.append(key)
            elif val is None:
                nulls.append(key)
            else:
                json.dumps(val)              # raises if it will not round-trip
                plain[key] = val
        (tmp / _MANIFEST).write_text(json.dumps(
            {"frames": frames, "nulls": nulls, "plain": plain}))
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(tmp), str(path))
    except Exception as exc:                 # noqa: BLE001
        logger.warning("could not persist derived cache %s: %s", path, exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cached(name: str, stamp: str, build: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Return `build()`'s payload, from disk when this stamp has been seen.

    `build` returns a dict of {key: DataFrame | None | JSON-able}. Anything else
    is not persisted and the whole payload falls back to being rebuilt, so a
    caller that adds an unserialisable value gets slow, never wrong.
    """
    path = _dir_for(name, stamp)
    hit = _read(path)
    if hit is not None:
        return hit
    payload = build()
    with _LOCK:
        _write(path, payload)
    return payload


def prune(name: str, keep: int = 3) -> None:
    """Drop all but the newest `keep` stamps for one name."""
    root = STORE / _slug(name)
    if not root.exists():
        return
    dirs = sorted((d for d in root.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)
