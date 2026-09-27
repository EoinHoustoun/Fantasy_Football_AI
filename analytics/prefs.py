"""Small personal preferences that should survive a restart (e.g. the league
last viewed), in data/cache/ff_prefs.json. Gitignored; never holds anything
sensitive."""
import json
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "ff_prefs.json"


def get(key: str, default: Any = None) -> Any:
    try:
        return json.loads(PATH.read_text()).get(key, default)
    except Exception:  # noqa: BLE001
        return default


def set(key: str, value: Any) -> None:  # noqa: A001 · mirrors get
    try:
        data = json.loads(PATH.read_text()) if PATH.exists() else {}
    except Exception:  # noqa: BLE001
        data = {}
    if data.get(key) == value:
        return
    data[key] = value
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data))
