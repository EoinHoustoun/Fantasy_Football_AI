# My Team Re-platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild My Team's forward-week planner on the 26/27 Draft's engine so one per-gameweek projection, one transfer ledger, one player card and one "is the gap real" test serve both pages.

**Architecture:** A pure `analytics/team_plan.py` owns the real team's plan state keyed by player `code` and delegates the FT ledger to `squad_rules.transfer_ledger`. The Draft's cached projector/fixture builders and its player dialog move into shared `ui/` modules with explicit inputs. My Team's `_planner_fragment` is rewritten on `render_squad_pitch`, `components/ff_table`, `gw_projection`, and `head_to_head`.

**Tech Stack:** Python 3.8 (typing `List/Dict/Optional`, never `list[x]`), Streamlit ≥1.36 with `st.navigation`, pandas, ECharts via `ui/charts.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-my-team-replatform-design.md`

## Global Constraints

- Python 3.8: `from typing import List, Dict, Optional`; no `list[int]`, no walrus-in-comprehension tricks.
- No em dashes anywhere (code, comments, UI copy, commit messages). Use `·`, a comma or a full stop.
- Colours in inline HTML are `var(--ff-*)` tokens; chart/JSON colours go through `theme.fill()`.
- `@st.cache_data` / `@st.cache_resource`: a leading underscore is ONLY for a large frame described by an adjacent hashed `stamp`. `tests/test_cache_keys.py` enforces this statically; new cached functions must pass it.
- Never `st.rerun()` in a plain button handler. Inside `@st.fragment` use `st.rerun(scope="fragment")`; inside `st.dialog` or after a disk write use app-scope `st.rerun()`.
- Any `pitch_click` / `ff_table.render` caller dedupes on the returned `nonce` stored in `session_state`.
- Card HTML passed to `st.markdown` is collapsed to one line.
- Pages never call `st.set_page_config`.
- Git: personal account `EoinHoustoun`; no Co-Authored-By or AI attribution in commit messages. The branch already has unrelated uncommitted work, so every commit step lists its files explicitly with `git add <files>`; never `git add -A`.
- Run the full suite with `python3 -m pytest -q -p no:cacheprovider` (≈90 s). It must stay green after every task.

---

## File map

| File | Responsibility | Status |
|---|---|---|
| `data/fetchers/fpl_api.py` | `get_team_squad` gains a `code` column | modify |
| `analytics/team_plan.py` | Plan/draft state for a real team keyed by `code`; effective squad replay; ledger wrapper; bank | create |
| `analytics/squad_planner.py` | Keeps `PLANS_PATH`, `FT_CAP`, `HIT_COST`, `_read/_write`; loses the duplicated ledger in Task 8 | modify |
| `ui/live_projection.py` | Cached club fixtures, `fixtures_for`, projector, `module_stamp`, `projection()` | create (extracted) |
| `ui/player_card.py` | The Draft's `_player_dialog` and its helpers, parameterised by a `CardCtx` | create (extracted) |
| `views/18_draft_2026_27.py` | Imports the two shared modules; behaviour unchanged | modify |
| `views/00_my_team.py` | `_planner_fragment` rewritten (lines 1414-1801); `_replacement_panel`, `_h2h_dialog`, xP helpers removed | modify |
| `analytics/xp_engine.py`, `analytics/plan_optimizer.py` | Deleted in Task 8 | delete |
| `tests/test_team_plan.py`, `tests/test_live_projection.py`, `tests/test_team_squad_code.py` | New tests | create |
| `CLAUDE.md` | My Team section rewritten; stale notes removed | modify |

---

### Task 1: `code` on the real squad

**Files:**
- Modify: `data/fetchers/fpl_api.py:180-215` (`get_team_squad`)
- Test: `tests/test_team_squad_code.py`

**Interfaces:**
- Produces: `get_team_squad(team_id, gw, bootstrap)` DataFrame gains integer column `code` (FPL's season-stable player code from `bootstrap["elements"][i]["code"]`). Every later task joins the squad to the board on this column.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_squad_code.py
"""The real squad must carry the season-stable `code`, because the Value Board,
projector and player card are all keyed by it. `fpl_id` changes every summer."""
from data.fetchers import fpl_api


BOOT = {
    "elements": [
        {"id": 5, "code": 99001, "web_name": "Saka", "team": 1, "element_type": 3,
         "now_cost": 100, "total_points": 9, "form": "9.0", "selected_by_percent": "40.0",
         "status": "a", "news": ""},
        {"id": 6, "code": 99002, "web_name": "Raya", "team": 1, "element_type": 1,
         "now_cost": 55, "total_points": 6, "form": "6.0", "selected_by_percent": "30.0",
         "status": "a", "news": ""},
    ],
    "teams": [{"id": 1, "name": "Arsenal", "code": 3, "short_name": "ARS"}],
}
PICKS = {"picks": [
    {"element": 6, "position": 1, "is_captain": False, "is_vice_captain": False, "multiplier": 1},
    {"element": 5, "position": 2, "is_captain": True, "is_vice_captain": False, "multiplier": 2},
], "entry_history": {"event": 1}}


def test_squad_carries_code(monkeypatch):
    monkeypatch.setattr(fpl_api, "fetch_team_picks", lambda team_id, gw: PICKS)
    df, _ = fpl_api.get_team_squad(45595, 1, bootstrap=BOOT)
    assert list(df["code"]) == [99002, 99001]
    assert df["code"].dtype.kind == "i"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_team_squad_code.py`
Expected: FAIL with `KeyError: 'code'`

- [ ] **Step 3: Add the column**

In `get_team_squad`, inside the `records.append({...})` dict after `"fpl_id": pick["element"],` add:

```python
            "code":             int(p.get("code", 0) or 0),   # season-stable · joins the board
```

- [ ] **Step 4: Run the test and the fpl_api tests**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_team_squad_code.py tests/test_team_picks_fallback.py`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add data/fetchers/fpl_api.py tests/test_team_squad_code.py
git commit -m "Carry the season-stable player code on the real squad"
```

---

### Task 2: `analytics/team_plan.py` · state, migration, replay

**Files:**
- Create: `analytics/team_plan.py`
- Test: `tests/test_team_plan.py`

**Interfaces:**
- Consumes: `analytics/squad_planner.PLANS_PATH, FT_CAP, HIT_COST, _read, _write` (unchanged).
- Produces:

```python
SCHEMA = 2
Entry = Dict[str, Any]   # {"swaps": {out_code(int): in_code(int)}, "captain": Optional[int], "chip": Optional[str]}

def empty_entry() -> Entry
def normalize(entry: Any, code_by_fpl_id: Optional[Dict[int, int]] = None) -> Entry
def load(team_id: int, code_by_fpl_id: Optional[Dict[int, int]] = None) -> Tuple[Dict[int, Entry], Dict[int, Entry]]   # (plans, drafts), gw keys are int
def save_plan(team_id: int, gw: int, entry: Entry) -> None      # also clears the draft for that gw
def save_draft(team_id: int, gw: int, entry: Entry) -> None
def clear_draft(team_id: int, gw: int) -> None
def clear_all(team_id: int) -> None                             # plans and drafts
def effective_codes(start_codes: List[int], plans: Dict[int, Entry], drafts: Dict[int, Entry], up_to_gw: int) -> List[int]
def swaps_upto(plans, drafts, up_to_gw) -> Dict[int, Dict[int, int]]   # {gw: {out: in}} · draft overrides plan per gw
def chip_at(plans, drafts, gw) -> Optional[str]
def wildcard_gw(plans, drafts, up_to_gw) -> Optional[int]
```

Semantics:
- `normalize` accepts v2 entries, v1 entries (`{"transfers":[{out_id,in_id,...}], "captain", "chip"}`), and legacy bare lists. v1 transfers convert through `code_by_fpl_id`; unknown ids are dropped with `logger.warning`.
- `effective_codes` replays plans for every gw ≤ `up_to_gw` except where a draft exists for that gw (draft wins for its own gw only). A week whose chip is `"FH"` applies only when `gw == up_to_gw`; on later weeks it is skipped, so the squad reverts.
- Order is preserved: an incoming player takes the outgoing player's slot.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_team_plan.py
"""Plan state for the REAL team, keyed by player code like the Draft."""
import json

import pytest

from analytics import team_plan as tp
from analytics import squad_planner as sp


@pytest.fixture(autouse=True)
def tmp_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "PLANS_PATH", tmp_path / "squad_plans.json")
    yield


START = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


def test_normalize_v1_transfers_map_ids_to_codes():
    v1 = {"transfers": [{"out_id": 501, "in_id": 502, "out_name": "A", "in_name": "B"}],
          "captain": 501, "chip": None}
    e = tp.normalize(v1, code_by_fpl_id={501: 9001, 502: 9002})
    assert e == {"swaps": {9001: 9002}, "captain": 9001, "chip": None}


def test_normalize_drops_unknown_ids_and_bare_lists():
    e = tp.normalize([{"out_id": 1, "in_id": 2}], code_by_fpl_id={1: 10})
    assert e == {"swaps": {}, "captain": None, "chip": None}


def test_round_trip_and_schema_tag():
    tp.save_draft(45595, 3, {"swaps": {3: 30}, "captain": 30, "chip": None})
    tp.save_plan(45595, 2, {"swaps": {1: 21}, "captain": None, "chip": "BB"})
    plans, drafts = tp.load(45595)
    assert plans == {2: {"swaps": {1: 21}, "captain": None, "chip": "BB"}}
    assert drafts == {3: {"swaps": {3: 30}, "captain": 30, "chip": None}}
    raw = json.loads(sp.PLANS_PATH.read_text())
    assert raw["schema"] == 2


def test_save_plan_clears_the_draft_for_that_week():
    tp.save_draft(45595, 2, {"swaps": {1: 21}, "captain": None, "chip": None})
    tp.save_plan(45595, 2, {"swaps": {1: 21}, "captain": None, "chip": None})
    _, drafts = tp.load(45595)
    assert 2 not in drafts


def test_effective_codes_replays_saved_weeks_then_draft():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": None},
             3: {"swaps": {2: 22}, "captain": None, "chip": None}}
    drafts = {3: {"swaps": {2: 23}, "captain": None, "chip": None}}
    assert tp.effective_codes(START, plans, drafts, 2)[:2] == [21, 2]
    assert tp.effective_codes(START, plans, drafts, 3)[:2] == [21, 23]   # draft wins for gw3
    assert tp.effective_codes(START, plans, {}, 3)[:2] == [21, 22]
    assert tp.effective_codes(START, plans, drafts, 4)[:2] == [21, 23]   # draft for 3 still applies at 4


def test_free_hit_week_reverts_afterwards():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": "FH"}}
    assert tp.effective_codes(START, plans, {}, 2)[0] == 21
    assert tp.effective_codes(START, plans, {}, 3)[0] == 1


def test_swaps_upto_and_wildcard_gw():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": "WC"},
             4: {"swaps": {5: 55}, "captain": None, "chip": None}}
    assert tp.swaps_upto(plans, {}, 3) == {2: {1: 21}}
    assert tp.wildcard_gw(plans, {}, 5) == 2
    assert tp.chip_at(plans, {}, 4) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_team_plan.py`
Expected: FAIL with `ModuleNotFoundError: analytics.team_plan`

- [ ] **Step 3: Implement**

```python
# analytics/team_plan.py
"""Plan state for the REAL team, keyed by player `code`.

The 26/27 Draft keys everything by the season-stable `code`; My Team used the
season-local `fpl_id` and its own transfer dicts. This module is the one
place the real team's saved weeks and working drafts live, in the Draft's
shape (`swaps = {out_code: in_code}`), so the projector, the ledger and the
player card can be shared without translation.

File: data/cache/squad_plans.json (owned by squad_planner for the path).
  {"schema": 2, "plans": {team: {gw: Entry}}, "drafts": {team: {gw: Entry}}}
Entry = {"swaps": {out_code: in_code}, "captain": code|None, "chip": str|None}
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from analytics import squad_planner as _sp

logger = logging.getLogger(__name__)

SCHEMA = 2
CHIPS = ("BB", "TC", "WC", "FH")
Entry = Dict[str, Any]


def empty_entry() -> Entry:
    return {"swaps": {}, "captain": None, "chip": None}


def normalize(entry: Any, code_by_fpl_id: Optional[Dict[int, int]] = None) -> Entry:
    """Accept v2, v1 ({transfers:[{out_id,in_id}]}) and legacy bare lists."""
    ids = code_by_fpl_id or {}
    if isinstance(entry, list):
        entry = {"transfers": entry, "captain": None, "chip": None}
    if not isinstance(entry, dict):
        return empty_entry()
    out = empty_entry()
    chip = entry.get("chip")
    out["chip"] = chip if chip in CHIPS else None

    if "swaps" in entry:                                   # v2
        out["swaps"] = {int(k): int(v) for k, v in (entry.get("swaps") or {}).items()}
        cap = entry.get("captain")
        out["captain"] = int(cap) if cap is not None else None
        return out

    for t in entry.get("transfers") or []:                 # v1
        o, i = ids.get(int(t.get("out_id", -1))), ids.get(int(t.get("in_id", -1)))
        if o is None or i is None:
            logger.warning("team_plan: dropping v1 transfer with unknown ids %s", t)
            continue
        out["swaps"][o] = i
    cap = entry.get("captain")
    out["captain"] = ids.get(int(cap)) if cap is not None else None
    return out


def _bucket(raw: Dict, kind: str, team_id: int,
            code_by_fpl_id: Optional[Dict[int, int]]) -> Dict[int, Entry]:
    return {int(gw): normalize(e, code_by_fpl_id)
            for gw, e in (raw.get(kind, {}).get(str(team_id), {}) or {}).items()}


def load(team_id: int,
         code_by_fpl_id: Optional[Dict[int, int]] = None) -> Tuple[Dict[int, Entry], Dict[int, Entry]]:
    raw = _sp._read()
    plans = _bucket(raw, "plans", team_id, code_by_fpl_id)
    drafts = _bucket(raw, "drafts", team_id, code_by_fpl_id)
    if raw.get("schema") != SCHEMA and (plans or drafts):
        _store(team_id, plans, drafts)                     # write back as v2 once
    return plans, drafts


def _store(team_id: int, plans: Dict[int, Entry], drafts: Dict[int, Entry]) -> None:
    raw = _sp._read()
    raw["schema"] = SCHEMA
    raw.setdefault("plans", {})[str(team_id)] = {str(g): e for g, e in plans.items()}
    raw.setdefault("drafts", {})[str(team_id)] = {str(g): e for g, e in drafts.items()}
    _sp._write(raw)


def save_plan(team_id: int, gw: int, entry: Entry) -> None:
    plans, drafts = load(team_id)
    plans[int(gw)] = normalize(entry)
    drafts.pop(int(gw), None)
    _store(team_id, plans, drafts)


def save_draft(team_id: int, gw: int, entry: Entry) -> None:
    plans, drafts = load(team_id)
    drafts[int(gw)] = normalize(entry)
    _store(team_id, plans, drafts)


def clear_draft(team_id: int, gw: int) -> None:
    plans, drafts = load(team_id)
    drafts.pop(int(gw), None)
    _store(team_id, plans, drafts)


def clear_all(team_id: int) -> None:
    _store(team_id, {}, {})


# ── Replay ────────────────────────────────────────────────────────────────────

def _entry_for(plans: Dict[int, Entry], drafts: Dict[int, Entry], gw: int) -> Optional[Entry]:
    return drafts.get(gw) or plans.get(gw)


def chip_at(plans, drafts, gw: int) -> Optional[str]:
    e = _entry_for(plans, drafts, int(gw))
    return e.get("chip") if e else None


def swaps_upto(plans, drafts, up_to_gw: int) -> Dict[int, Dict[int, int]]:
    """{gw: {out: in}} for the ledger · Free Hit weeks excluded (no transfers)."""
    out: Dict[int, Dict[int, int]] = {}
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            continue
        e = _entry_for(plans, drafts, gw)
        if e and e.get("chip") != "FH" and e.get("swaps"):
            out[gw] = dict(e["swaps"])
    return out


def wildcard_gw(plans, drafts, up_to_gw: int) -> Optional[int]:
    for gw in sorted(set(plans) | set(drafts)):
        if gw <= int(up_to_gw) and chip_at(plans, drafts, gw) == "WC":
            return gw
    return None


def effective_codes(start_codes: List[int], plans: Dict[int, Entry],
                    drafts: Dict[int, Entry], up_to_gw: int) -> List[int]:
    """The fifteen after every week up to and including `up_to_gw`.

    Draft beats plan for the same week. A Free Hit week applies only when it
    IS the viewed week; afterwards the squad reverts, which is the rule.
    """
    squad = [int(c) for c in start_codes]
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            break
        e = _entry_for(plans, drafts, gw)
        if not e:
            continue
        if e.get("chip") == "FH" and gw != int(up_to_gw):
            continue
        for out, inn in (e.get("swaps") or {}).items():
            if int(out) in squad:
                squad[squad.index(int(out))] = int(inn)
    return squad
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_team_plan.py tests/test_cache_keys.py`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add analytics/team_plan.py tests/test_team_plan.py
git commit -m "Add team_plan · the real team's plan state keyed by player code"
```

---

### Task 3: Ledger and bank on `team_plan`

**Files:**
- Modify: `analytics/team_plan.py`
- Test: `tests/test_team_plan.py` (append)

**Interfaces:**
- Consumes: `analytics.squad_rules.transfer_ledger(swaps, upto_gw, ft_cap, first_paid_gw, start_codes, wildcard_gw)`.
- Produces:

```python
def ledger(plans, drafts, up_to_gw: int, start_codes: List[int], first_gw: int, banked_now: int = 1) -> Dict
    # returns squad_rules.transfer_ledger's dict; `first_gw` is the first planning week (current_gw + 1);
    # `banked_now` is how many free transfers the manager holds going INTO first_gw (FPL's entry has 1 after GW1
    # unless banked); the Draft's ledger accrues 1 per week from first_paid_gw, so we call it with
    # first_paid_gw = first_gw - (banked_now - 1) and pass only swaps at or after first_gw.
def bank_after(bank_now_m: float, price_by_code: Dict[int, float], start_codes, plans, drafts, up_to_gw) -> float
    # bank after every move up to up_to_gw at CURRENT prices (sell price nuances are out of scope)
```

- [ ] **Step 1: Failing tests**

```python
def test_ledger_banks_and_charges_like_the_draft():
    plans = {3: {"swaps": {1: 21, 2: 22, 3: 23}, "captain": None, "chip": None}}
    led = tp.ledger(plans, {}, 3, START, first_gw=2, banked_now=1)
    w = {x["gw"]: x for x in led["weeks"]}
    assert w[2]["used"] == 0 and w[2]["available_before"] == 1
    assert w[3]["available_before"] == 2 and w[3]["used"] == 3
    assert w[3]["hits"] == 1 and led["points_cost"] == 4


def test_ledger_respects_transfers_already_banked():
    plans = {2: {"swaps": {1: 21, 2: 22}, "captain": None, "chip": None}}
    led = tp.ledger(plans, {}, 2, START, first_gw=2, banked_now=2)
    assert led["hits"] == 0


def test_ledger_buy_back_is_free():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": None},
             3: {"swaps": {21: 1}, "captain": None, "chip": None}}
    led = tp.ledger(plans, {}, 3, START, first_gw=2)
    assert led["hits"] == 0


def test_ledger_wildcard_week_is_unlimited():
    plans = {2: {"swaps": {1: 21, 2: 22, 3: 23, 4: 24}, "captain": None, "chip": "WC"}}
    led = tp.ledger(plans, {}, 2, START, first_gw=2)
    assert led["hits"] == 0 and led["wildcard_gw"] == 2


def test_bank_after_prices_moves():
    plans = {2: {"swaps": {1: 21}, "captain": None, "chip": None}}
    prices = {1: 5.0, 21: 6.5}
    assert tp.bank_after(2.0, prices, START, plans, {}, 2) == pytest.approx(0.5)
```

- [ ] **Step 2: Run, expect `AttributeError: ledger`**

- [ ] **Step 3: Implement (append to `analytics/team_plan.py`)**

```python
from analytics.squad_rules import transfer_ledger as _ledger   # top of file, with the other imports


def ledger(plans, drafts, up_to_gw: int, start_codes: List[int],
           first_gw: int, banked_now: int = 1) -> Dict:
    """The Draft's ledger applied to a season already under way.

    `squad_rules.transfer_ledger` accrues one free transfer per week from
    `first_paid_gw`. A manager holding `banked_now` free transfers going into
    `first_gw` is the same as a manager who has been accruing since
    `first_gw - (banked_now - 1)` without spending, so we start it there and
    pass no moves before `first_gw`.
    """
    swaps = {g: s for g, s in swaps_upto(plans, drafts, up_to_gw).items() if g >= int(first_gw)}
    start_paid = int(first_gw) - max(0, int(banked_now) - 1)
    return _ledger(swaps, int(up_to_gw), ft_cap=_sp.FT_CAP, first_paid_gw=start_paid,
                   start_codes=start_codes, wildcard_gw=wildcard_gw(plans, drafts, up_to_gw))


def bank_after(bank_now_m: float, price_by_code: Dict[int, float], start_codes: List[int],
               plans, drafts, up_to_gw: int) -> float:
    squad = [int(c) for c in start_codes]
    bank = float(bank_now_m)
    for gw in sorted(set(plans) | set(drafts)):
        if gw > int(up_to_gw):
            break
        e = _entry_for(plans, drafts, gw)
        if not e or e.get("chip") == "FH":
            continue
        for out, inn in (e.get("swaps") or {}).items():
            if int(out) in squad:
                bank += float(price_by_code.get(int(out), 0.0)) - float(price_by_code.get(int(inn), 0.0))
                squad[squad.index(int(out))] = int(inn)
    return round(bank, 2)
```

Note for the ledger weeks: with `first_paid_gw < first_gw` the returned `weeks` list contains synthetic accrual weeks before `first_gw`. The UI filters `weeks` to `gw >= first_gw`.

- [ ] **Step 4: Run `tests/test_team_plan.py`, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/team_plan.py tests/test_team_plan.py
git commit -m "team_plan · ledger and bank on the Draft's transfer rules"
```

---

### Task 4: Extract `ui/live_projection.py` from the Draft page

**Files:**
- Create: `ui/live_projection.py`
- Modify: `views/18_draft_2026_27.py:516-611` (delete `_club_fixtures`, `_FIX`, `_PROJ_VERSION`, `_module_stamp`, `_projector`, `_fixtures_for`; import them), and every reference to `_FIX`, `_fixtures_for`, `_module_stamp`, `PROJ` construction at ~594-598.
- Test: `tests/test_live_projection.py`

**Interfaces:**
- Produces:

```python
# ui/live_projection.py
PROJ_VERSION = 3
def module_stamp(*mods) -> str
def club_fixtures() -> Dict[Tuple[int, int], List[Tuple[str, bool, float]]]        # @st.cache_data(ttl=6h), body moved verbatim
def fixtures_for(team_id: int, gw: int, n: int = 3, fix: Optional[Dict] = None) -> List[Dict]   # {"opp","home","fdr"} (+ "blank")
def projector(_board, _fix, stamp: str, version: int, code_stamp: str)             # @st.cache_resource, body moved verbatim
def projection(inputs_stamp: str) -> Dict   # {"board","scout","price_bt","validation","pts_col","fix","proj","board_stamp","window"}
```

`projection()` does what the Draft page does inline at lines 428-437 and 594-598: `build_board(inputs_stamp)`, `PTS_COL`, `_freshness.board_stamp(board, PTS_COL)`, `club_fixtures()`, `projector(...)`. It returns `None` for `"proj"` when the board is `None`.

- [ ] **Step 1: Failing test**

```python
# tests/test_live_projection.py
"""The projector builders shared by the Draft and My Team."""
from ui import live_projection as lp


def test_fixtures_for_reads_the_supplied_map_and_pads_blanks():
    fix = {(1, 2): [("ARS", True, 2.0)], (1, 3): [("CHE", False, 4.0), ("LIV", True, 5.0)]}
    out = lp.fixtures_for(1, 2, 3, fix=fix)
    assert out[0] == {"opp": "ARS", "home": True, "fdr": 2.0}
    assert out[1]["opp"] == "CHE" and out[2]["opp"] == "LIV"
    assert lp.fixtures_for(1, 5, 2, fix=fix)[0]["blank"] is True


def test_module_stamp_changes_with_the_module():
    import analytics.gw_projection as g
    s = lp.module_stamp(g)
    assert s.startswith("analytics.gw_projection:")
```

- [ ] **Step 2: Run, expect `ModuleNotFoundError`**

- [ ] **Step 3: Create the module** by MOVING the Draft's code. Signature changes only where noted.

```python
# ui/live_projection.py
"""The per-gameweek projector and fixture runs, shared by the Draft and My Team.

Moved out of views/18_draft_2026_27.py so the two pages build ONE projector
with ONE cache-key discipline. See the docstrings that travelled with each
function for why the keys look the way they do.
"""
import os
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

PROJ_VERSION = 3


def module_stamp(*mods) -> str:
    """mtime of each module's source · a cache key that notices a code edit."""
    bits = []
    for m in mods:
        try:
            bits.append("%s:%s" % (m.__name__, os.path.getmtime(m.__file__)))
        except Exception:
            bits.append(getattr(m, "__name__", "?"))
    return "|".join(bits)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def club_fixtures() -> Dict:
    # body moved verbatim from views/18_draft_2026_27.py `_club_fixtures`
    ...


def fixtures_for(team_id: int, gw: int, n: int = 3, fix: Optional[Dict] = None) -> List[Dict]:
    fix = club_fixtures() if fix is None else fix
    out = []
    for g in range(gw, gw + n):
        fx = fix.get((int(team_id), g), [])
        if not fx:
            out.append({"opp": "BLANK", "blank": True, "fdr": 3, "home": True})
            continue
        for opp, home, fdr in fx:
            out.append({"opp": opp, "home": home, "fdr": fdr})
    return out[:n]


@st.cache_resource(show_spinner=False)
def projector(_board: pd.DataFrame, _fix: Dict, stamp: str, version: int, code_stamp: str):
    # docstring and body moved verbatim from the Draft's `_projector`
    from analytics import gw_projection
    return gw_projection.build(_board, _fix)


def projection(inputs_stamp: str) -> Dict:
    from analytics import freshness
    from analytics import gw_projection as gwp
    from ui.value_board import build_board
    board, scout, price_bt, validation = build_board(inputs_stamp)
    if board is None:
        return {"board": None, "proj": None, "fix": {}, "pts_col": None,
                "board_stamp": "", "window": [], "scout": scout,
                "price_bt": price_bt, "validation": validation}
    pts_col = "consensus_points" if "consensus_points" in board.columns else "projected_points"
    fix = club_fixtures()
    board_stamp = freshness.board_stamp(board, pts_col)
    proj = projector(board, fix, board_stamp, PROJ_VERSION, module_stamp(gwp))
    return {"board": board, "scout": scout, "price_bt": price_bt, "validation": validation,
            "pts_col": pts_col, "fix": fix, "proj": proj, "board_stamp": board_stamp,
            "window": proj.window}
```

- [ ] **Step 4: Rewire the Draft page.** Replace lines 516-611 with:

```python
from ui import live_projection as LP
_FIX = LP.club_fixtures()
_module_stamp = LP.module_stamp
_PROJ_VERSION = LP.PROJ_VERSION


def _fixtures_for(team_id: int, gw: int, n: int = 3) -> List[Dict]:
    return LP.fixtures_for(team_id, gw, n, fix=_FIX)
```

and replace the projector construction (`PROJ = _projector(board, _FIX, BOARD_STAMP, _PROJ_VERSION, _module_stamp(_gwp_mod))`) with `PROJ = LP.projector(board, _FIX, BOARD_STAMP, _PROJ_VERSION, _module_stamp(_gwp_mod))`. Delete the local `_projector` definition. Keep `board, scout, price_bt, _validation = build_board(...)` as is (the Draft needs `scout`/`price_bt` too; `projection()` is for My Team).

- [ ] **Step 5: Run the suite and the cache-key test**

Run: `python3 -m pytest -q -p no:cacheprovider`
Expected: all PASS. `tests/test_cache_keys.py` walks every module; `projector`'s `_board/_fix` underscores must be on its allowlist if the test keys by function name (check the allowlist in that file and move the entry from the Draft's `_projector` to `ui.live_projection.projector`).

- [ ] **Step 6: Browser check** the Draft page (`http://localhost:8510/draft_2026_27`): pitch renders with fixtures and points, no traceback in the server log.

- [ ] **Step 7: Commit**

```bash
git add ui/live_projection.py views/18_draft_2026_27.py tests/test_live_projection.py tests/test_cache_keys.py
git commit -m "Extract the projector and fixture builders into ui/live_projection"
```

---

### Task 5: Extract the player card into `ui/player_card.py`

**Files:**
- Create: `ui/player_card.py`
- Modify: `views/18_draft_2026_27.py` (functions at 2310-2334, 2406-2521, 2521-2843, 2843-2918, 2920-3064, 3068, 3158-3183; `DEFCON = _defcon_per90()` at 652)

**Interfaces:**
- Produces:

```python
@dataclass
class CardCtx:
    board: pd.DataFrame
    proj: Any                      # GwProjection
    pts_col: str
    fix: Dict                      # club_fixtures map
    defcon: pd.DataFrame           # per-90 DEFCON table (was the Draft's DEFCON global)
    scout: Optional[pd.DataFrame]  # Scout snapshot frame the Draft passes to _profile
    board_stamp: str
    on_replace: Optional[Callable[[int], None]] = None   # footer button · None hides it
    on_compare: Optional[Callable[[int], None]] = None
    on_captain: Optional[Callable[[int], None]] = None   # My Team adds "Captain for GWn"
    captain_gw: Optional[int] = None

def open_player_card(ctx: CardCtx, code: int) -> None    # the @st.dialog("Player", width="large")
def profile(ctx: CardCtx, code: int) -> Dict            # was _profile
def set_piece_line(row) -> str                          # was _set_piece_line
def setpiece_glyphs(row) -> str                         # was _setpiece_glyphs
def conf_color(v)                                       # was _conf_color
def dc_hit(ctx: CardCtx, code: int, pos: str) -> Optional[float]   # was _dc_hit
```

Approach: move each helper verbatim, replacing the page globals `board`, `PROJ`, `PTS_COL`, `DEFCON`, `BOARD_STAMP`, `_FIX` with `ctx.board`, `ctx.proj`, `ctx.pts_col`, `ctx.defcon`, `ctx.board_stamp`, `ctx.fix`, and `_fixtures_for(...)` with `LP.fixtures_for(..., fix=ctx.fix)`. Cached helpers keyed on `stamp` (`_position_ranks(stamp)`) keep their signature; the caller passes `ctx.board_stamp`. The footer buttons call `ctx.on_replace(code)` / `ctx.on_compare(code)` when set; add a third button `⭐ Captain for GW{ctx.captain_gw}` when `ctx.on_captain` is set.

The Draft page keeps thin wrappers:

```python
from ui import player_card as PC
CARD = PC.CardCtx(board=board, proj=PROJ, pts_col=PTS_COL, fix=_FIX, defcon=DEFCON,
                  scout=scout, board_stamp=BOARD_STAMP,
                  on_replace=_push_axe, on_compare=_push_compare)
def _player_dialog(code: int) -> None: PC.open_player_card(CARD, code)
_dc_hit = lambda code, pos: PC.dc_hit(CARD, code, pos)
_setpiece_glyphs, _conf_color, _set_piece_line = PC.setpiece_glyphs, PC.conf_color, PC.set_piece_line
```

where `_push_axe(code)` and `_push_compare(code)` are the two bodies currently inside the dialog footer (append to `_sk("draft_axe")` / `_sk("cmp_players")` and `st.rerun()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_card.py
import pandas as pd
from ui import player_card as PC


def test_set_piece_glyphs_and_line_survive_extraction():
    row = pd.Series({"pens_order": 1, "corners_order": 2, "fk_order": None})
    assert "Pen" in PC.set_piece_line(row) or "⚽" in PC.setpiece_glyphs(row)


def test_card_ctx_is_plain_data():
    ctx = PC.CardCtx(board=pd.DataFrame(), proj=None, pts_col="consensus_points", fix={},
                     defcon=pd.DataFrame(), scout=None, board_stamp="s")
    assert ctx.on_replace is None and ctx.captain_gw is None
```

(Adjust the first assertion to the actual output of the moved `set_piece_line` for that row; read the function before asserting.)

- [ ] **Step 2: Run, expect import failure**

- [ ] **Step 3: Move the code as described.** Delete the originals from the Draft page. Keep `DEFCON = _defcon_per90()` on the page (it feeds `CardCtx`).

- [ ] **Step 4: Full suite green; browser check the Draft: open a player card from the pitch and from the pool table, all five panels render, Replace and Compare still work.**

- [ ] **Step 5: Commit**

```bash
git add ui/player_card.py views/18_draft_2026_27.py tests/test_player_card.py
git commit -m "Extract the player card from the Draft page so My Team can open it"
```

---

### Task 6: Rewrite My Team's planner fragment

**Files:**
- Modify: `views/00_my_team.py` (replace lines 1414-1801 `_planner_fragment`; replace the scrubber helpers' dependence on drafts at 1419-1433; delete `_xp_horizon_cached`/`_xp_horizon` at 983-1014 and `_replacement_panel` at 714-980 and `_h2h_dialog` at 1017-1125 in Task 8, not here)
- Test: `tests/test_my_team_planner_rows.py` for the pure row builder

**Interfaces:**
- Consumes: Task 1 `code`; Task 2/3 `team_plan`; Task 4 `LP.projection`, `LP.fixtures_for`; Task 5 `PC.CardCtx`, `PC.open_player_card`, `PC.dc_hit`, `PC.setpiece_glyphs`, `PC.conf_color`; `analytics.squad_rules.legal_swaps, is_legal_xi`; `analytics.gw_projection.best_xi`; `analytics.head_to_head.week_band`; `components.pitch_view.render_squad_pitch`; `components.ff_table` (`render`, `col_*`); `analytics.grading.bench_boost_grade`.
- Produces (module-level in the view, pure and testable):

```python
def _pitch_rows(sq: pd.DataFrame, gw: int, proj, fix: Dict, xi: set, captain: Optional[int],
                axed: List[int], sub_from: Optional[int], swap_targets: set) -> List[Dict]
def _candidate_rows(pool: pd.DataFrame, gw: int, proj, fix: Dict, out_row: Optional[pd.Series],
                    pts_col: str, dc_hit_fn, glyph_fn) -> List[Dict]
def _sk(name: str) -> str        # f"{name}::team{team_id}"
```

Session keys (all through `_sk`): `axe` (List[int]), `sub_from` (Optional[int]), `xi_override` (Dict[int, set]), `pitch_nonce`, `table_nonce`, `compare_pair` (Optional[Tuple[int,int]]).

- [ ] **Step 1: Failing test for the row builders**

```python
# tests/test_my_team_planner_rows.py
import importlib.util, pathlib
import pandas as pd


class _Proj:
    def points(self, code, gw): return {1: 5.0, 2: 3.0}.get(code, 1.0)
    def expected_minutes(self, code, gw): return 90.0 if code == 1 else 30.0


def _load_view_helpers():
    """The view is a Streamlit script; import only the pure helpers by exec'ing
    the module up to the `# ── PLANNER` marker is fragile, so the helpers live in
    ui/team_pitch_rows.py instead (see Step 3)."""
    from ui import team_pitch_rows as R
    return R


def test_pitch_rows_mark_xi_captain_axed_and_swap_ok():
    R = _load_view_helpers()
    sq = pd.DataFrame([
        {"code": 1, "web_name": "A", "position": "MID", "team_code": 3, "team_short": "ARS",
         "team_id": 1, "actual_price": 8.0, "pens_order": 1},
        {"code": 2, "web_name": "B", "position": "DEF", "team_code": 3, "team_short": "ARS",
         "team_id": 1, "actual_price": 4.5, "pens_order": None},
    ])
    fix = {(1, 2): [("CHE", True, 3.0)]}
    rows = R.pitch_rows(sq, 2, _Proj(), fix, xi={1}, captain=1, axed=[2], sub_from=None, swap_targets={2})
    a, b = rows
    assert a["stat"] == 5.0 and a["is_captain"] and not a["on_bench"] and a["exp_mins"] == 90.0
    assert b["on_bench"] and b["is_axed"] and b["swap_ok"]
    assert a["fixtures"][0]["opp"] == "CHE" and a["fpl_id"] == 1


def test_candidate_rows_price_delta_and_pool_shape():
    R = _load_view_helpers()
    pool = pd.DataFrame([{"code": 9, "web_name": "C", "team_short": "LIV", "position": "MID",
                          "actual_price": 6.0, "consensus_points": 120.0, "team_id": 2,
                          "consensus_confidence": "High", "model_spread": 0.1}])
    out_row = pd.Series({"actual_price": 8.0})
    rows = R.candidate_rows(pool, 2, _Proj(), {}, out_row, "consensus_points",
                            dc_hit_fn=lambda c, p: 40.0, glyph_fn=lambda r: "")
    r = rows[0]
    assert r["d_price"] == -2.0 and r["per_m"] == 20.0 and r["spread"] == 10.0 and r["dc_hit"] == 40.0
```

- [ ] **Step 2: Run, expect `ModuleNotFoundError: ui.team_pitch_rows`**

- [ ] **Step 3: Create `ui/team_pitch_rows.py`** (pure; the view imports it):

```python
"""Row builders for My Team's forward-week pitch and candidate table.

Pure functions so the shapes the pitch and ff_table expect are unit-tested
without Streamlit. Mirrors the Draft's `planner()` dicts and `_pool_rows`.
"""
from typing import Callable, Dict, List, Optional

import pandas as pd

from ui import live_projection as LP


def pitch_rows(sq: pd.DataFrame, gw: int, proj, fix: Dict, xi: set,
               captain: Optional[int], axed: List[int], sub_from: Optional[int],
               swap_targets: set) -> List[Dict]:
    players = []
    for _, r in sq.iterrows():
        code = int(r["code"])
        players.append({
            "web_name": r["web_name"], "position": r["position"],
            "team_code": int(r.get("team_code", 1) or 1),
            "team_short": r.get("team_short"),
            "on_bench": code not in xi,
            "is_captain": code == captain,
            "price": float(r.get("actual_price") or 0),
            "fixtures": LP.fixtures_for(int(r.get("team_id", 0) or 0), gw, 3, fix=fix),
            "fpl_id": code,
            "stat": round(float(proj.points(code, gw)), 1), "stat_dp": 1,
            "exp_mins": proj.expected_minutes(code, gw),
            "penalties_order": r.get("pens_order"),
            "is_axed": code in axed, "allow_axe": True, "allow_bench": True,
            "is_sub_source": sub_from == code,
            "swap_ok": code in swap_targets,
        })
    return players


def candidate_rows(pool: pd.DataFrame, gw: int, proj, fix: Dict,
                   out_row: Optional[pd.Series], pts_col: str,
                   dc_hit_fn: Callable, glyph_fn: Callable) -> List[Dict]:
    rows = []
    out_price = float(out_row.get("actual_price") or 0) if out_row is not None else 0.0
    for _, a in pool.iterrows():
        code = int(a["code"])
        price = float(a["actual_price"])
        season = float(a.get(pts_col) or 0)
        spread = a.get("model_spread")
        rows.append({
            "code": code, "web_name": a["web_name"],
            "team_short": a.get("team_short", ""), "position": a["position"],
            "actual_price": price,
            "d_price": round(price - out_price, 1) if out_row is not None else 0.0,
            "run": LP.fixtures_for(int(a.get("team_id", 0) or 0), gw, 3, fix=fix),
            "gw_pts": proj.points(code, gw),
            "mins": proj.expected_minutes(code, gw),
            "season": season,
            "per_m": season / price if price else 0.0,
            "confidence": a.get("consensus_confidence", a.get("confidence", "")),
            "spread": round(float(spread) * 100, 0) if pd.notna(spread) else None,
            "dc_hit": dc_hit_fn(code, str(a["position"])),
            "setp": glyph_fn(a),
        })
    return rows
```

Note: the pitch key `"fpl_id"` is what `pitch_click` reports back as `id`; we put the `code` there on purpose, exactly as the Draft does.

- [ ] **Step 4: Run the row tests, expect PASS**

- [ ] **Step 5: Rewrite `_planner_fragment` in `views/00_my_team.py`.** Replace the whole function (1414-1801). Page-level setup that must exist BEFORE the pitch tab (put it right after the squad enrichment, ~line 377):

```python
# ── Shared projection (the Draft's engine) ─────────────────────────────────────
from analytics import freshness as _freshness
from analytics import team_plan as TP
from analytics import squad_rules as SR
from analytics.gw_projection import best_xi
from analytics.head_to_head import week_band
from analytics.grading import bench_boost_grade
from ui import live_projection as LP
from ui import player_card as PC
from ui import team_pitch_rows as ROWS
from components import ff_table as T
from components.pitch_view import render_squad_pitch
from components.team_identity import player_photo_url

_LIVE = LP.projection(_freshness.inputs_stamp())
BOARD, PROJ, PTS_COL, FIX = _LIVE["board"], _LIVE["proj"], _LIVE["pts_col"], _LIVE["fix"]
_CODE_BY_ID = {int(p["id"]): int(p["code"]) for p in bs["elements"]}
_PRICE_BY_CODE = {int(p["code"]): float(p["now_cost"]) / 10 for p in bs["elements"]}


def _sk(name: str) -> str:
    return f"{name}::team{team_id}"


for _k, _v in (("axe", []), ("sub_from", None), ("xi_override", {}), ("pitch_nonce", None),
               ("table_nonce", None), ("compare_pair", None)):
    st.session_state.setdefault(_sk(_k), _v)
```

`squad_df` joins the board: `squad_b = squad_df.merge(BOARD.drop(columns=[c for c in BOARD.columns if c in squad_df.columns and c != "code"]), on="code", how="left")`; players missing from the board get `actual_price = price` and render with stat 0.

The fragment:

```python
@st.fragment
def _planner_fragment(view_gw: int) -> None:
    if PROJ is None:
        st.error("Archive not built · run `python scripts/build_archive.py` first.")
        return
    plans, drafts = TP.load(team_id, _CODE_BY_ID)
    entry = dict(drafts.get(view_gw) or plans.get(view_gw) or TP.empty_entry())
    start_codes = [int(c) for c in squad_df["code"]]
    codes_now = TP.effective_codes(start_codes, plans, drafts, view_gw)
    sq = BOARD[BOARD["code"].isin(codes_now)].copy()
    missing = [c for c in codes_now if c not in set(sq["code"])]
    if missing:
        st.warning(f"{len(missing)} player(s) have no projection on the board; shown at 0.")
    sq = sq.set_index("code").reindex(codes_now).reset_index()   # keep slot order

    # ── XI, captain, chip ─────────────────────────────────────────────────
    pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
    xi = set(st.session_state[_sk("xi_override")].get(view_gw) or best_xi(sq, PROJ, view_gw))
    chip = entry.get("chip")
    playing = [c for c in xi if (PROJ.expected_minutes(c, view_gw) or 0) >= 45]
    captain = entry.get("captain") or (max(playing, key=lambda c: PROJ.points(c, view_gw)) if playing else None)
    xi_pts = sum(PROJ.points(c, view_gw) for c in xi) + (PROJ.points(captain, view_gw) if captain else 0) * (2 if chip == "TC" else 1)
    bench_pts = sum(PROJ.points(c, view_gw) for c in codes_now if c not in xi)
    if chip == "BB":
        xi_pts += bench_pts
    band = week_band(list(xi), PROJ, BOARD, view_gw, captain=captain)
    n_match, n_asked = PROJ.coverage(codes_now, view_gw)

    # ── Money strip ────────────────────────────────────────────────────────
    banked_now = int(st.session_state.get("banked_fts", 1))
    led = TP.ledger(plans, drafts, view_gw, start_codes, first_gw=_plan_first, banked_now=banked_now)
    wk = next((w for w in led["weeks"] if w["gw"] == view_gw), None)
    bank_m = TP.bank_after(bank_m_now, _PRICE_BY_CODE, start_codes, plans, drafts, view_gw)
    _money_strip(wk, led, bank_m, xi_pts, band, bench_pts, chip, n_match, n_asked)

    # ── Pitch ──────────────────────────────────────────────────────────────
    axed = [int(c) for c in st.session_state[_sk("axe")]]
    sub_from = st.session_state[_sk("sub_from")]
    swap_targets = set(SR.legal_swaps(sub_from, xi, codes_now, pos_by)) if sub_from is not None else set()
    rows = ROWS.pitch_rows(sq, view_gw, PROJ, FIX, xi, captain, axed, sub_from, swap_targets)
    click = render_squad_pitch(rows, stat_label="xP", interactive=True, compact=True,
                               xi_total_override=round(xi_pts, 1),
                               total_label="SQUAD" if chip == "BB" else "XI",
                               key=_sk("pitch"))
    click = _dedupe(click, _sk("pitch_nonce"))
    if click:
        _handle_pitch_click(click, view_gw, xi, codes_now, pos_by, sub_from, swap_targets, entry)

    # ── Axe queue and candidates ──────────────────────────────────────────
    if axed:
        _transfer_desk(axed, sq, view_gw, entry, bank_m, codes_now)

    _save_row(view_gw, entry, plans, drafts, start_codes, codes_now)
```

with these helpers defined above it in the view (full bodies, no placeholders):

```python
def _dedupe(click, nonce_key: str):
    if not click:
        return None
    if click.get("nonce") == st.session_state.get(nonce_key):
        return None
    st.session_state[nonce_key] = click.get("nonce")
    return click


def _handle_pitch_click(click, gw, xi, codes_now, pos_by, sub_from, swap_targets, entry):
    action, cid = click.get("action"), int(click.get("id") or 0)
    if action == "detail":
        _open_card(cid, gw)
    elif action in ("axe", "unaxe"):
        cur = [int(c) for c in st.session_state[_sk("axe")]]
        if action == "axe" and cid not in cur:
            cur.append(cid)
        elif action == "unaxe" and cid in cur:
            cur.remove(cid)
        st.session_state[_sk("axe")] = cur
        st.rerun(scope="fragment")
    elif action == "bench":
        if sub_from == cid:
            st.session_state[_sk("sub_from")] = None
        elif sub_from is not None and cid in swap_targets:
            new_xi = (set(xi) - {sub_from}) | {cid} if sub_from in xi else (set(xi) - {cid}) | {sub_from}
            if SR.is_legal_xi(new_xi, pos_by):
                st.session_state[_sk("xi_override")][gw] = new_xi
            st.session_state[_sk("sub_from")] = None
        else:
            st.session_state[_sk("sub_from")] = cid
        st.rerun(scope="fragment")


def _open_card(code: int, gw: int) -> None:
    def _replace(c):
        cur = [int(x) for x in st.session_state[_sk("axe")]]
        if c not in cur:
            cur.append(c)
        st.session_state[_sk("axe")] = cur
        st.rerun()

    def _compare(c):
        axed = st.session_state[_sk("axe")]
        st.session_state[_sk("compare_pair")] = (int(axed[0]), int(c)) if axed else None
        st.rerun()

    def _captain(c):
        plans, drafts = TP.load(team_id, _CODE_BY_ID)
        e = dict(drafts.get(gw) or plans.get(gw) or TP.empty_entry())
        e["captain"] = int(c)
        TP.save_draft(team_id, gw, e)
        st.rerun()

    ctx = PC.CardCtx(board=BOARD, proj=PROJ, pts_col=PTS_COL, fix=FIX, defcon=DEFCON,
                     scout=_LIVE["scout"], board_stamp=_LIVE["board_stamp"],
                     on_replace=_replace, on_compare=_compare, on_captain=_captain, captain_gw=gw)
    PC.open_player_card(ctx, code)
```

`DEFCON` on My Team: import `_defcon_per90` by moving it from the Draft to `ui/player_card.py` as `defcon_per90(stamp)` in Task 5 (it is `@st.cache_data`; give it the `board_stamp` argument). Both pages call `PC.defcon_per90(board_stamp)`.

Money strip (HTML tiles in one line, tokens only):

```python
def _money_strip(wk, led, bank_m, xi_pts, band, bench_pts, chip, n_match, n_asked):
    free_before = wk["available_before"] if wk else led["available_now"]
    used = wk["used"] if wk else 0
    hits = wk["hits"] if wk else 0
    tiles = [
        ("Free", f"{free_before}", "var(--ff-mint)", f"bank of {led['cap']}"),
        ("Moves", f"{used}", "var(--ff-text)", "this week"),
        ("Hits", f"−{hits * 4}" if hits else "0", "var(--ff-red)" if hits else "var(--ff-text)", f"{hits} × −4"),
        ("Bank", f"£{bank_m:.1f}m", "var(--ff-cyan)", "after moves"),
        ("XI xP", f"{xi_pts:.0f}", "var(--ff-gold)", f"{band['lo']:.0f}–{band['hi']:.0f} · 80%"),
        ("Bench", f"{bench_pts:.1f}", "var(--ff-text)", bench_boost_grade(bench_pts)["label"] if chip == "BB" else "not boosted"),
        ("Forecasts", f"{n_match}/{n_asked}", "var(--ff-text)", "on match forecasts"),
    ]
    html = "<div style='display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px 0;'>" + "".join(
        f"<div style='flex:1;min-width:110px;background:var(--ff-card);border:1px solid var(--ff-line);"
        f"border-radius:12px;padding:10px 12px;'><div class='ff-label'>{lab}</div>"
        f"<div class='ff-display' style='font-size:22px;color:{col};'>{val}</div>"
        f"<div style='font-size:11px;color:var(--ff-muted2);'>{sub}</div></div>"
        for lab, val, col, sub in tiles) + "</div>"
    st.markdown("".join(seg.strip() for seg in html.splitlines()), unsafe_allow_html=True)
```

Check `week_band`'s returned keys before using `lo`/`hi` (read `analytics/head_to_head.py:821-860`); use whatever it returns. Same for `bench_boost_grade`'s dict.

Transfer desk:

```python
def _transfer_desk(axed, sq, gw, entry, bank_m, codes_now):
    names = {int(r["code"]): r["web_name"] for _, r in sq.iterrows()}
    st.markdown(f"**Replacing:** " + " · ".join(names.get(c, str(c)) for c in axed))
    target = axed[0]
    out_row = sq[sq["code"] == target].iloc[0]
    pooled = bank_m + sum(float(sq[sq["code"] == c].iloc[0]["actual_price"]) for c in axed)
    pool = BOARD[(BOARD["position"] == out_row["position"]) & (~BOARD["code"].isin(codes_now))
                 & (BOARD["actual_price"] <= pooled)].copy()
    pool = pool.sort_values(PTS_COL, ascending=False).head(60)
    rows = ROWS.candidate_rows(pool, gw, PROJ, FIX, out_row, PTS_COL,
                               dc_hit_fn=lambda c, p: PC.dc_hit(_CARD_CTX, c, p),
                               glyph_fn=PC.setpiece_glyphs)
    cols = [T.col_face("code", url_fn=player_photo_url),
            T.col_player("web_name", "Player", sub="team_short", action="inspect"),
            T.col_chip("position", "Pos", color_fn=theme.pos_color),
            T.col_num("actual_price", "£m", fmt="%.1f"),
            T.col_num("d_price", "Δ£m", fmt="%+.1f",
                      color_fn=lambda v: theme.fill("mint") if v <= 0 else theme.fill("red")),
            T.col_run("run", f"GW{gw}-{gw + 2}"),
            T.col_num("gw_pts", f"GW{gw}", fmt="%.1f"),
            T.col_num("mins", "Mins", fmt="%.0f", empty="no forecast",
                      color_fn=lambda v: theme.fill("red") if v < 45 else None),
            T.col_num("dc_hit", "DEFCON", fmt="%.0f%%", empty="-"),
            T.col_html("setp", ""),
            T.col_num("season", "Season", fmt="%.0f"),
            T.col_num("per_m", "Per £m", fmt="%.1f"),
            T.col_num("spread", "±", fmt="%.0f%%", empty="-"),
            T.col_chip("confidence", "Conf.", color_fn=PC.conf_color),
            T.col_action("code", "swap", "Swap in")]
    click = _dedupe(T.render(rows, cols, key=_sk("cands"), max_height=440), _sk("table_nonce"))
    if click:
        cid = int(click.get("id") or 0)
        if click.get("action") == "inspect":
            _open_card(cid, gw)
        elif click.get("action") == "swap":
            e = dict(entry); e["swaps"] = dict(e.get("swaps") or {}); e["swaps"][target] = cid
            TP.save_draft(team_id, gw, e)
            st.session_state[_sk("axe")] = [c for c in axed if c != target]
            st.rerun(scope="fragment")
```

`_CARD_CTX` is a page-level `PC.CardCtx(...)` built once with no callbacks (for `dc_hit`); `_open_card` builds the one with callbacks.

Save row (Monte Carlo is added in Task 7; here only the buttons):

```python
def _save_row(gw, entry, plans, drafts, start_codes, codes_now):
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.6])
    chip = c4.selectbox("Chip", ["None", "BB", "TC", "WC", "FH"], key=_sk(f"chip{gw}"),
                        index=["None", "BB", "TC", "WC", "FH"].index(entry.get("chip") or "None"))
    if chip != (entry.get("chip") or "None"):
        e = dict(entry); e["chip"] = None if chip == "None" else chip
        TP.save_draft(team_id, gw, e); st.rerun(scope="fragment")
    if c1.button(f"💾 Save GW{gw} plan", key=_sk(f"save{gw}"), type="primary"):
        TP.save_plan(team_id, gw, entry); st.rerun()
    if c2.button("↩ Reset to saved", key=_sk(f"reset{gw}")):
        TP.clear_draft(team_id, gw); st.session_state[_sk("axe")] = []; st.rerun()
    if c3.button("🧹 Clear this week", key=_sk(f"clear{gw}")):
        TP.save_plan(team_id, gw, TP.empty_entry()); st.session_state[_sk("axe")] = []; st.rerun()
```

Delete in the same edit: the "✨ Optimise my next 5 weeks", "🧠 Analyse my plan" buttons and `_plan_summary_dialog`/`_plan_review_dialog`, and the `_xp_gw_map` / `xp_for_gw` usage. The scrubber (1376-1405) stays; the call site becomes `_planner_fragment(view_gw)`.

- [ ] **Step 6: Full suite green, then browser pass on `/my_team`:** scrub to GW3; the pitch shows fixtures + xP + minutes; ✕ two players; sign replacements from the table; money strip shows 1 free, 2 moves, −4; save; step back to GW2 (original squad); forward to GW4 (moves persist); reload page (persisted from disk).

- [ ] **Step 7: Commit**

```bash
git add ui/team_pitch_rows.py views/00_my_team.py tests/test_my_team_planner_rows.py
git commit -m "Rebuild the My Team planner on the Draft's projector, ledger and tables"
```

---

### Task 7: Compare and "is the gap real"

**Files:**
- Modify: `views/00_my_team.py` (`_save_row`, new `_compare_dialog`, new cached `_gap_sim`)
- Test: `tests/test_my_team_gap.py`

**Interfaces:**
- Consumes: `head_to_head.simulate_drafts(entries, proj, board, gw_lo, gw_hi, n_sims, seed)`, `head_to_head.significance(a, b)`, `head_to_head.player_profile/compare_players/verdict`.
- Produces: `ui/team_gap.py::gap_entries(board, codes_now, codes_after, gw) -> List[Dict]` (pure) and `ui/team_gap.py::gap_verdict(sim) -> Dict` (pure).

- [ ] **Step 1: Failing test**

```python
# tests/test_my_team_gap.py
import pandas as pd
from ui import team_gap as G


def test_gap_entries_shape():
    board = pd.DataFrame({"code": [1, 2, 3], "position": ["MID"] * 3, "web_name": list("abc")})
    ents = G.gap_entries(board, [1, 2], [1, 3], gw=4)
    assert [e["name"] for e in ents] == ["Current squad", "After these moves"]
    assert ents[0]["phases"][0][0] == 4 and list(ents[1]["phases"][0][1]["code"]) == [1, 3]
    assert ents[0]["bench_boost_gw"] is None


def test_gap_verdict_reads_pairwise_probability():
    sim = {"drafts": [{"name": "Current squad", "total_mean": 50.0, "beats": {"After these moves": 0.3}},
                      {"name": "After these moves", "total_mean": 54.0, "beats": {"Current squad": 0.7}}]}
    v = G.gap_verdict(sim)
    assert v["call"] == "lean" and v["gap"] == 4.0
```

- [ ] **Step 2: Run, expect import failure**

- [ ] **Step 3: Implement `ui/team_gap.py`**

```python
"""Is the gap real? · current squad vs the squad after this week's moves."""
from typing import Dict, List

import pandas as pd

from analytics.head_to_head import significance


def gap_entries(board: pd.DataFrame, codes_now: List[int], codes_after: List[int], gw: int) -> List[Dict]:
    def _sq(codes):
        return board[board["code"].isin(codes)].set_index("code").reindex(codes).reset_index()
    return [{"name": "Current squad", "phases": [(int(gw), _sq(codes_now))], "bench_boost_gw": None},
            {"name": "After these moves", "phases": [(int(gw), _sq(codes_after))], "bench_boost_gw": None}]


def gap_verdict(sim: Dict) -> Dict:
    d = {x["name"]: x for x in sim.get("drafts", [])}
    return significance(d["After these moves"], d["Current squad"])
```

- [ ] **Step 4: Wire into the view.** Above `_save_row`:

```python
@st.cache_data(show_spinner=False, ttl=1800)
def _gap_sim(gw: int, now: tuple, after: tuple, board_stamp: str) -> Dict:
    from analytics.head_to_head import simulate_drafts
    from ui.team_gap import gap_entries
    ents = gap_entries(BOARD, list(now), list(after), gw)
    return simulate_drafts(ents, PROJ, BOARD, gw, min(38, gw + 4), n_sims=1500)
```

In `_save_row`, before the buttons, when `entry["swaps"]` is non-empty:

```python
    codes_before = TP.effective_codes(start_codes, plans, {}, gw - 1)
    sim = _gap_sim(gw, tuple(sorted(codes_before)), tuple(sorted(codes_now)), _LIVE["board_stamp"])
    v = gap_verdict(sim)
    st.markdown(f"<div style='border-left:3px solid var(--ff-{v['tone']});padding:8px 12px;'>"
                f"{v['text']} <span style='color:var(--ff-muted2);'>(GW{gw}–{min(38, gw + 4)}, 1,500 sims, shared noise)</span></div>",
                unsafe_allow_html=True)
```

(`tone` values are `mint|gold|muted`; all three exist as `--ff-*` tokens. Check `ui/theme.py` and map `muted` → `muted2` if only that exists.)

Compare dialog, replacing the old `_h2h_dialog`:

```python
@st.dialog("Head to head", width="large")
def _compare_dialog(a_code: int, b_code: int, gw: int) -> None:
    from analytics.head_to_head import player_profile, compare_players, verdict
    rows = {c: BOARD[BOARD["code"] == c].iloc[0] for c in (a_code, b_code)}
    profs = [player_profile(rows[c], pts_col=PTS_COL, defcon=DEFCON, proj=PROJ, from_gw=gw, horizon=6)
             for c in (a_code, b_code)]
    cmp = compare_players(profs)
    v = verdict(cmp, profs)
    st.markdown(f"**{v['headline']}**  \n{v['detail']}")
    # radar off cmp["axes"] / totals · reuse charts.radar_option exactly as the Draft's Players tab does (views/18_draft_2026_27.py ~4011-4060)
```

Copy the Draft's radar block from its Players tab verbatim (it already uses `cmp` and `profs`). Open the dialog at the top of `_planner_fragment` when `st.session_state[_sk("compare_pair")]` is set, then clear the key.

- [ ] **Step 5: Suite green; browser: axe a player, open the card of a candidate, Compare, verdict + radar render; sign; the gap line reads coin flip / lean / clear.**

- [ ] **Step 6: Commit**

```bash
git add ui/team_gap.py views/00_my_team.py tests/test_my_team_gap.py
git commit -m "My Team · head-to-head on the shared engine and a shared-noise gap test before saving"
```

---

### Task 8: Cleanup, deletions, docs

**Files:**
- Delete: `analytics/xp_engine.py`, `analytics/plan_optimizer.py`, their tests (`grep -l "xp_engine\|plan_optimizer" tests/`)
- Modify: `views/00_my_team.py` (delete `_replacement_panel` 714-980, `_h2h_dialog` 1017-1125, `_xp_horizon_cached`/`_xp_horizon` 983-1014, Edit Squad mode 1851-1996 if it only used `_replacement_panel`; otherwise leave it and note it in CLAUDE.md as legacy), `analytics/squad_planner.py` (delete `free_transfers_for`, `hit_cost`, `effective_squad`, `bank_after`, `total_hits` and their tests once `grep -rn` shows no callers), `CLAUDE.md`
- Test: the full suite

- [ ] **Step 1: Find remaining callers**

Run: `grep -rn "xp_engine\|plan_optimizer\|_replacement_panel\|_h2h_dialog\|free_transfers_for\|effective_squad\|hit_cost\|total_hits" --include='*.py' . | grep -v "^./tests/"`
Expected: only definitions inside the files being deleted or edited.

- [ ] **Step 2: Delete and remove imports.** Delete the dead tests too.

- [ ] **Step 3: Full suite and cache-key test green.**

- [ ] **Step 4: CLAUDE.md.** Replace the "My Team pitch planner (2026-07)" section's xP paragraph ("xP comes from `analytics/xp_engine.py` ...") and the "✨ Optimise my next 5 weeks" paragraph with:

```
**My Team runs on the Draft's engine (2026-08-28).** Forward weeks use
`ui/live_projection.projection()` (one projector, one cache key), plan state in
`analytics/team_plan.py` keyed by player `code` (schema 2 in
`data/cache/squad_plans.json`; v1 migrates on load), the FT ledger from
`squad_rules.transfer_ledger` via `team_plan.ledger`, the pitch through
`render_squad_pitch` with rows from `ui/team_pitch_rows.py`, candidates through
`components/ff_table`, the shared player card `ui/player_card.py`, head-to-head
from `analytics/head_to_head.py`, and a shared-noise Monte Carlo (`ui/team_gap.py`)
next to Save. `xp_engine` and `plan_optimizer` are gone; the multi-week optimiser
returns on the new projector (separate spec).
```

Also delete the stale line "`views/00_my_team.py` `_scored_universe(_players)` still has this shape and is unfixed" and fix the doc drift noting `gw_projection.bench_boost_value` (it does not exist; the live equivalent is `grading.bench_boost_grade`).

- [ ] **Step 5: Browser regression on Home, My Team (history week, current week, future week), Draft, Chip Planner. No tracebacks in the server log.**

- [ ] **Step 6: Commit**

```bash
git add -u analytics views ui tests CLAUDE.md
git commit -m "Retire the old My Team xP engine and planner; document the shared stack"
```

(`-u` stages only tracked, modified/deleted files under those paths; confirm with `git status` that nothing from the unrelated working set is included before committing, and unstage anything that is.)

---

## Self-review

- Spec §3.1 → Tasks 2-3. §3.2 → Task 4. §3.3 + §4 items 1-4, 7 → Task 6. §4 items 5-6 → Task 7. §6 migration → Task 2 (`normalize`, schema tag), guards → Task 6 (`PROJ is None`), key namespacing → `_sk` in Task 6. §7 testing → each task; browser passes in Tasks 4, 5, 6, 7, 8. §8 cleanup → Task 8.
- Names used consistently: `TP.load/save_plan/save_draft/clear_draft/effective_codes/ledger/bank_after/empty_entry`, `LP.projection/fixtures_for/club_fixtures/projector/module_stamp`, `PC.CardCtx/open_player_card/dc_hit/setpiece_glyphs/conf_color/defcon_per90`, `ROWS.pitch_rows/candidate_rows`, `team_gap.gap_entries/gap_verdict`.
- Two places the implementer must read before asserting: `week_band` return keys and `bench_boost_grade` return keys (Task 6 says so explicitly).
