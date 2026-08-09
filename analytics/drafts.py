"""Named drafts · save a squad plan, then put it up against the others.

A draft here is not a list of fifteen players. It is the RECIPE that produces
them: the strategy, the players you insisted on, the budget and risk dials, and
the chip plan. Storing the recipe rather than the squad means a saved draft stays
correct when prices move or a projection updates, which is the whole point of
comparing them in early August.

Two parts to a draft, and they are independent on purpose:

  the squad     strategy + locks + vetoes + budget/risk/opening/minutes dials
  the chip plan which gameweek the Bench Boost and the Wildcard are played

That split is what lets "Optimal" and "Optimal, Bench Boost GW2 into Wildcard
GW4" be two comparable drafts built on the same fifteen. The chip plan changes
what the squad is WORTH without changing who is in it.

Saved to `data/cache/saved_drafts.json`, which is gitignored.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import CACHE_DIR

logger = logging.getLogger(__name__)

STORE_PATH = Path(CACHE_DIR) / "saved_drafts.json"

# Defaults every draft inherits unless it overrides them.
BASE = {
    "strategy": "⚖️ Optimal value",
    "locks": [],
    "vetoes": [],
    "budget": 100.0,
    "risk": 0.3,
    "opening": 0.35,
    "minutes_gate": 0.5,
    "cap_attackers": False,   # 1 attacker per club · off by default
    # Club cover · [[team_id, "def"|"att", n], ...]. "At least one Arsenal
    # defensive asset" without naming which one. Part of the recipe, so it has
    # to round-trip through save/load like any other constraint.
    "cover": [],
    "bench_boost_gw": None,
    "wildcard_gw": None,
    # An explicit fifteen, saved as player codes. When present the planner uses
    # it verbatim instead of re-solving · which is the whole point of saving a
    # team you built by hand. Absent means "solve this recipe", which is what a
    # preset does.
    "squad": None,
}

# The three squads worth arguing about this pre-season, each with the three chip
# plans that are actually on the table. Nine drafts, but only three solves: the
# chip plan is priced on top of a squad rather than baked into it.
_SQUADS = [
    ("Optimal", []),
    ("Optimal + Mosquera + Haaland", ["Mosquera", "Haaland"]),
    ("Optimal + Fernandes + Mosquera + Haaland",
     ["B.Fernandes", "Mosquera", "Haaland"]),
]
# Each chip plan carries the STRATEGY that builds a squad capable of it. Planning
# a Bench Boost while solving for the best XI gives you a bench that cannot score,
# which is the chip half wasted before it is played. The GW2 route additionally
# builds on GW1-3 fixtures only, because the Wildcard at GW4 throws the squad away.
_CHIPS = [
    ("", None, None, "⚖️ Optimal value"),
    ("BB2 → WC4", 2, 4, "🚀 Bench Boost GW2 → Wildcard GW4"),
    ("BB1 → WC4", 1, 4, "🔋 Bench Boost GW1"),
]

# Routes worth arguing about, all on the Optimal squad. The chip question is
# largely separable from the squad question, so varying it on one squad answers
# it without multiplying the picker by three.
#
# What each one is actually testing:
#   BB1 → WC4   boost immediately, reset before the bench money goes stale
#   BB1 → WC6   same boost, but carry the all-playing fifteen two weeks longer
#   BB2 → WC4   one week of information before boosting
#   BB3 → WC6   let the openers settle, boost into a known-good week
#   WC4 only    no Boost at all · the control arm for "is the Boost worth it"
#   BB1 only    boost and never reset · the control arm for "is the reset worth it"
_ROUTES = [
    ("Route · BB1 → WC6", 1, 6, "🔋 Bench Boost GW1"),
    ("Route · BB3 → WC6", 3, 6, "🔋 Bench Boost GW1"),
    ("Route · WC4, no Boost", None, 4, "⚖️ Optimal value"),
    ("Route · BB1, no Wildcard", 1, None, "🔋 Bench Boost GW1"),
]


def preset_drafts() -> List[Dict[str, Any]]:
    """The one draft a new install starts from.

    There used to be thirteen · three squads across three chip plans plus four
    route experiments · and they were noise. A preset is a STARTING POINT, and
    thirteen starting points is none: you cannot tell which is yours, the picker
    needs a scroll, and every comparison is against a squad nobody chose.

    So: one draft, one constraint (the two players Eoin will always own), no
    chips and no vetoes. Everything else is something the user decides and
    saves as their own draft, which is the workflow the page is built around.
    """
    return [dict(BASE, id="optimal", name="Optimal",
                 locks=["Haaland", "Mosquera"],
                 strategy="\u2696\ufe0f Optimal value",
                 bench_boost_gw=None, wildcard_gw=None, preset=True)]

def _slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    s = "".join(keep)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")[:60]


def _read() -> Dict[str, Any]:
    if not STORE_PATH.exists():
        return {}
    try:
        with open(STORE_PATH) as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.warning("saved drafts unreadable, starting fresh: %s", exc)
        return {}


# Streamlit runs every browser session as a thread in ONE process, so two tabs
# on the draft page read-modify-write this store concurrently. The lock covers
# the whole cycle, not just the write · without it the later save is built from
# a snapshot taken before the earlier one landed, and silently drops it.
_STORE_LOCK = threading.RLock()


def _write(raw: Dict[str, Any]) -> None:
    """Write atomically · a truncated file loses every saved draft.

    A bare open(..., "w") truncates first. If anything interrupts the dump the
    file is left empty, `_read` returns {} and `load_drafts` re-seeds the
    presets over the top, silently destroying the user's work. Write a temp file
    in the same directory and rename it, which is atomic on POSIX.

    The temp name carries the pid and thread id. It used to be one fixed
    `saved_drafts.json.tmp` for every writer, so two sessions saving at once
    raced: the first renamed the file into place and the second found nothing
    left to rename, taking the whole page down with a FileNotFoundError.
    """
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(
        ".json.%d.%d.tmp" % (os.getpid(), threading.get_ident()))
    try:
        with open(tmp, "w") as fh:
            json.dump(raw, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STORE_PATH)
    finally:
        # A failed dump must not leave its scratch file behind.
        try:
            os.unlink(tmp)
        except OSError:
            pass


# Keys in the store that are bookkeeping rather than drafts.
_META = ("_seeded", "_last")


def load_drafts(seed_presets: bool = True) -> List[Dict[str, Any]]:
    """Every saved draft, newest last. Seeds the presets on first run only.

    A `_seeded` marker means the presets have been laid down once already, so a
    draft the user deleted stays deleted instead of reappearing every session.
    """
    with _STORE_LOCK:
        raw = _read()
        if seed_presets and not raw.get("_seeded"):
            for d in preset_drafts():
                raw.setdefault(d["id"], d)
            raw["_seeded"] = True
            _write(raw)
        return [v for k, v in raw.items()
                if k not in _META and isinstance(v, dict)]


def last_used() -> Optional[str]:
    """The draft id the user was last on, or None.

    Session state dies on a hard reload, so without this the picker snapped back
    to whichever draft sorted first and you had to find yours again every time.
    """
    v = _read().get("_last")
    return str(v) if isinstance(v, str) else None


def remember_last(draft_id: str) -> None:
    with _STORE_LOCK:
        raw = _read()
        if raw.get("_last") == str(draft_id):
            return      # no write, no fsync, on every rerun
        raw["_last"] = str(draft_id)
        _write(raw)



def save_draft(name: str, spec: Dict[str, Any],
               draft_id: Optional[str] = None,
               allow_clear: Tuple[str, ...] = ()) -> str:
    """Create or overwrite a draft. Returns its id.

    Saving the same name twice UPDATES that draft rather than making a second
    one, because the working loop is build, save, tweak, save again.
    """
    with _STORE_LOCK:
        return _save_draft_locked(name, spec, draft_id, allow_clear)


def _save_draft_locked(name: str, spec: Dict[str, Any],
                       draft_id: Optional[str],
                       allow_clear: Tuple[str, ...]) -> str:
    raw = _read()
    did = draft_id or _slug(name)
    existing = raw.get(did) if isinstance(raw.get(did), dict) else {}
    entry = dict(BASE)
    # Start from what is already stored, so a save that carries no `squad` (a
    # recipe-only save from another surface) UPDATES the recipe rather than
    # nulling a fifteen the user built by hand. Only an explicit squad replaces
    # a stored one.
    entry.update({k: v for k, v in existing.items() if k in BASE})
    entry.update({k: v for k, v in spec.items() if k in BASE and v is not None})
    # Ignoring None protects a stored fifteen from a recipe-only save, but it
    # also makes some fields impossible to CLEAR. `allow_clear` names the ones
    # where None is a real instruction · taking a chip off a plan, for one.
    for k in allow_clear:
        if k in BASE and k in spec:
            entry[k] = spec[k]
    entry.update({"id": did, "name": name, "preset": False})
    raw[did] = entry
    _write(raw)
    logger.info("saved draft %s (%s)", did, "with an explicit squad"
                if entry.get("squad") else "recipe only")
    return did


def has_squad(spec: Dict[str, Any]) -> bool:
    """True when this draft carries a hand-built fifteen."""
    sq = spec.get("squad")
    return bool(sq) and len(sq) == 15


def delete_draft(draft_id: str) -> bool:
    with _STORE_LOCK:
        raw = _read()
        if draft_id in raw:
            del raw[draft_id]
            _write(raw)
            return True
        return False


def reset_to_presets() -> None:
    """Wipe everything and lay the presets down again."""
    raw = {"_seeded": True}
    for d in preset_drafts():
        raw[d["id"]] = d
    _write(raw)


def describe(d: Dict[str, Any]) -> str:
    """One line a human can scan in a picker."""
    bits = []
    if d.get("locks"):
        bits.append("locks " + ", ".join(d["locks"]))
    chips = []
    if d.get("bench_boost_gw"):
        chips.append("BB GW%d" % d["bench_boost_gw"])
    if d.get("wildcard_gw"):
        chips.append("WC GW%d" % d["wildcard_gw"])
    if chips:
        bits.append(" then ".join(chips))
    if float(d.get("budget", 100.0)) != 100.0:
        bits.append("£%.1fm" % d["budget"])
    if has_squad(d):
        bits.insert(0, "your fifteen")
    return " · ".join(bits) or "no locks, no chips"
