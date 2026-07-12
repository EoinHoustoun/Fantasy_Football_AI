"""The single seam to the local LLM (Ollama).

Every AI feature in the app calls `generate()` here · pages never import `ollama`
or hit the HTTP API directly. That keeps one place to swap models, change hosts,
add caching, or fall back to cloud later.

Design rules (see the memory reference `reference_ai_viz_integration_playbook`):
  • Availability is detected once and cached · the UI feature-flags off it.
  • Any failure (server down, model missing, timeout, bad JSON) returns None /
    an empty result, never raises · callers render a non-AI fallback.
  • Python 3.8: use typing.Optional/Dict, never `X | None`.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, Optional

import requests

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT, AI_TEMPERATURE

logger = logging.getLogger(__name__)

# Cache the availability probe for the process lifetime of a probe cycle. Streamlit
# reruns re-import this module state, so we also expose is_available() for callers
# that want to cache the result in st.session_state.
_AVAILABILITY_CACHE: Dict[str, Any] = {"checked": False, "up": False}


def is_available(force: bool = False) -> bool:
    """Return True if the Ollama server answers. Cached after the first probe.

    Never raises. A ~2s timeout keeps a dead server from stalling the page.
    """
    if _AVAILABILITY_CACHE["checked"] and not force:
        return bool(_AVAILABILITY_CACHE["up"])
    up = False
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        up = resp.status_code == 200
    except Exception as exc:  # noqa: BLE001 · availability probe must never raise
        logger.info("Ollama not available: %s", exc)
        up = False
    _AVAILABILITY_CACHE["checked"] = True
    _AVAILABILITY_CACHE["up"] = up
    return up


def generate(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    as_json: bool = False,
    timeout: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> Optional[Any]:
    """Generate a completion from the local model.

    Returns the response text (str), or a parsed dict when `as_json=True`.
    Returns None on any failure so callers can fall back cleanly.

    `max_tokens` caps generation length (Ollama `num_predict`) · bounding it keeps
    latency predictable on slower machines.
    """
    if not is_available():
        return None

    options: Dict[str, Any] = {
        "temperature": AI_TEMPERATURE if temperature is None else temperature,
    }
    if max_tokens is not None:
        options["num_predict"] = int(max_tokens)

    payload: Dict[str, Any] = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system:
        payload["system"] = system
    if as_json:
        payload["format"] = "json"

    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=timeout or OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        text = (resp.json() or {}).get("response", "").strip()
    except Exception as exc:  # noqa: BLE001 · never propagate to the UI
        logger.warning("Ollama generate failed: %s", exc)
        return None

    if not text:
        return None
    if not as_json:
        return text
    try:
        return _json.loads(text)
    except Exception as exc:  # noqa: BLE001 · malformed JSON degrades to None
        logger.warning("Ollama JSON parse failed: %s | raw=%s", exc, text[:200])
        return None
