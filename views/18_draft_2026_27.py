"""
2026-27 Draft · the pitch is the planner.

One view does the work: fifteen shirts carrying the opening run and this week's
expected points, and one table of who you could have instead. Everything that is
analysis rather than planning sits behind tabs, because a planning surface with
six panels open is a worse planning surface.

Three model reads sit behind every number (`analytics/consensus.py`): our
carryover projection, Fantasy Football Scout's season model, and Fantasy
Football Hub's fixture-by-fixture predictions. Where they agree the number is
worth trusting; where they scatter the card says so. FFH also states EXPECTED
MINUTES, which is why a World Cup returnee shows a warning rather than a
confident projection.

Every colour here is a `--ff-*` variable, never a literal, so the page follows
the light/dark switch without knowing which theme is on.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

from analytics import opening_plan as OPLAN
from analytics import squad_rules as SR
from components import ff_table as T
from components.animations import inject_global_animations
from components.pitch_view import render_squad_pitch
from components.team_identity import face_html, player_photo_url, team_dot
from config import NEXT_SEASON
from analytics.value_verdicts import VERDICTS
from ui import charts
from ui import player_card as PC
from ui import theme
from ui.theme import var as V

inject_global_animations()

POS_ORDER = SR.POS_ORDER
CARD = (f"background:{V('card')};border:1px solid {V('line')};"
        f"border-radius:14px;padding:14px 16px;")

SQUAD_LIMITS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MINIMUMS = SR.XI_MINIMUMS
MAX_GW = 19

VERDICT_META = {
    VERDICTS.NECESSITY: ("gold", "Elite projection, template-owned. Build around them."),
    VERDICTS.VALUE: ("mint", "FPL priced them below their projected return. Load up."),
    VERDICTS.OVERPRICED: ("red", "Big tag, pedigree, but the projection doesn't earn it."),
    VERDICTS.FAIR: ("muted", "Priced about right."),
    VERDICTS.SCOUT: ("cyan", "No 25/26 history. Scout the depth chart before committing."),
}
CONF_TOKEN = {"High": "mint", "Medium": "orange", "Low": "red"}


# ── Small helpers ─────────────────────────────────────────────────────────────
def _num_safe(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _one_line(html: str) -> str:
    """Collapse card HTML to a single line, without eating words.

    A whitespace-only line (left by an empty interpolation) makes Streamlit's
    markdown parser stop passing raw HTML through and escape the rest of the
    card. See CLAUDE.md rule 6b.

    The subtlety is the join. Concatenating stripped lines welds prose that
    happened to wrap ("costs 0.6 pts a" + "gameweek" -> "pts agameweek"), which
    is how a real copy bug reached the Bench Boost card. Joining with a space
    instead would insert visible gaps between inline elements like fixture
    chips. So: a space only where a word meets a word, nothing anywhere else.
    """
    out = ""
    for seg in html.splitlines():
        seg = seg.strip()
        if not seg:
            continue
        # A space is owed whenever the PREVIOUS line ended mid-prose. What comes
        # next may be another word or an inline tag ("is <b>3.4</b>"); either
        # way the sentence needs the gap. When the previous line ended on a tag
        # ("</span>") no space is owed, which is what keeps chips flush.
        if out and (out[-1].isalnum() or out[-1] in ",.;:!?") \
                and (seg[0].isalnum() or seg[0] == "<"):
            out += " "
        out += seg
    return out


def _sec(title: str, sub: str = "", icon: str = "") -> None:
    """A section rule. `sub` is a one-line lead, set in the same block rather
    than as a caption underneath, so a section reads as one thing."""
    ico = (theme.icon(icon, 16, V("muted")) + " ") if icon else ""
    lead = (f'<div style="font-size:12.5px;font-weight:400;color:{V("muted")};'
            f'margin:-2px 0 10px;max-width:70ch;line-height:1.5;">{sub}</div>'
            if sub else "")
    st.markdown(_one_line(
        f'<div style="display:flex;align-items:center;gap:11px;margin:24px 0 6px;">'
        f'{ico}'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:0.2em;'
        f'text-transform:uppercase;color:{V("muted")};white-space:nowrap;">{title}</div>'
        f'<div style="flex:1;height:1px;background:{V("line")};"></div></div>{lead}'),
        unsafe_allow_html=True)


def _tiles(items: List) -> None:
    """A row of live stat tiles. Every number moves the moment a control does,
    so the effect of a change is legible instead of guessed at."""
    st.markdown(_one_line(
        '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 12px;">'
        + "".join(
            f'<div style="{CARD}flex:1;min-width:104px;padding:12px 14px;">'
            f'<div style="font-size:9.5px;font-weight:600;letter-spacing:0.14em;'
            f'color:{V("muted2")};text-transform:uppercase;">{lab}</div>'
            f'<div class="ff-display" style="font-size:23px;font-weight:800;'
            f'color:{V(tok)};margin:3px 0 1px;">{val}</div>'
            f'<div style="font-size:11px;font-weight:400;color:{V("muted")};">{sub}</div></div>'
            for lab, val, sub, tok in items)
        + "</div>"), unsafe_allow_html=True)


def _strip(items: List) -> str:
    """A compact icon strip for constraints · money, transfers, cost.

    Lighter than the stat tiles on purpose. These are things you GLANCE at while
    doing something else, so they get one line each rather than a card.
    """
    cells = []
    for item in items:
        # Four fields is the plain strip; five adds a sub-line under the number,
        # which is where a graded stat puts its rank or its threshold.
        if len(item) == 5:
            icon_name, label, value, sub, tok = item
        else:
            (icon_name, label, value, tok), sub = item, ""
        sub_html = (f'<div style="font-size:10px;font-weight:400;color:{V("muted2")};'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'{sub}</div>' if sub else "")
        cells.append(
            f'<div style="display:flex;align-items:center;gap:9px;flex:1;'
            f'min-width:150px;padding:9px 12px;border-right:1px solid {V("line")};">'
            f'{theme.icon(icon_name, 19, V(tok))}'
            f'<div style="min-width:0;">'
            f'<div style="font-size:9.5px;font-weight:600;letter-spacing:0.1em;'
            f'text-transform:uppercase;color:{V("muted2")};white-space:nowrap;">{label}</div>'
            f'<div class="ff-display" style="font-size:17px;font-weight:800;'
            f'color:{V(tok)};line-height:1.25;">{value}</div>{sub_html}</div></div>')
    return _one_line(
        f'<div style="display:flex;flex-wrap:wrap;background:{V("card")};'
        f'border:1px solid {V("line")};border-radius:12px;margin:2px 0 12px;'
        f'overflow:hidden;">' + "".join(cells) + '</div>')


def _changes_summary(ledger: Dict) -> str:
    """Every transfer made, week by week, with what it cost.

    The question this answers is "what did I actually do", so it reads as a list
    of moves rather than a table of state: who left, who arrived, free or -4.
    """
    weeks = [w for w in ledger["weeks"] if w["used"]]
    if not weeks:
        return _one_line(
            f'<div style="{CARD}color:{V("muted")};font-size:13px;">'
            f'No transfers yet. The opening fifteen is the draft itself, so it '
            f'costs nothing.</div>')
    names = dict(zip(board["code"].astype(int), board["web_name"]))
    prices = dict(zip(board["code"].astype(int), board["actual_price"]))
    blocks = []
    for w in weeks:
        rows = []
        # `moves` is the NET change for the week: who actually left and who
        # actually arrived. A player sold and bought back appears in neither.
        _pairs = list(zip(w["moves"].get("out", []), w["moves"].get("in", [])))
        for i, (out, inn) in enumerate(_pairs):
            # On a Wildcard every move is free however many you make · the
            # week has no allowance to run out of.
            free = w.get("wildcard") or i < w["free_used"]
            tag = ("WILDCARD" if w.get("wildcard") else "FREE" if free else "-4")
            tok = "mag" if w.get("wildcard") else "mint" if free else "red"
            delta = float(prices.get(int(inn), 0)) - float(prices.get(int(out), 0))
            rows.append(
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:7px 0;border-top:1px solid {V("line")};font-size:13px;">'
                f'<span style="color:{V("red")};font-weight:600;min-width:104px;">'
                f'{names.get(int(out), "?")}</span>'
                f'{theme.icon("arrow_forward", 15, V("muted2"))}'
                f'<span style="color:{V("mint")};font-weight:700;min-width:104px;">'
                f'{names.get(int(inn), "?")}</span>'
                f'<span style="color:{V("muted")};font-size:12px;">'
                f'{delta:+.1f}m</span>'
                f'<span style="margin-left:auto;background:{V("chip-bg")};'
                f'color:{V(tok)};border-radius:5px;padding:2px 8px;font-size:10px;'
                f'font-weight:800;letter-spacing:0.06em;">{tag}</span></div>')
        plural = "s" if w["used"] != 1 else ""
        cost_txt = (" · costs %d pts" % w["cost"]) if w["cost"] else ""
        meta = ("%d move%s on the Wildcard · unlimited, free" % (w["used"], plural)
                if w.get("wildcard") else
                "%d move%s, %d free available%s"
                % (w["used"], plural, w["available_before"], cost_txt))
        blocks.append(
            f'<div style="margin-bottom:14px;">'
            f'<div style="display:flex;align-items:baseline;gap:8px;">'
            f'<span class="ff-display" style="font-size:15px;font-weight:800;'
            f'color:{V("text")};">Gameweek {w["gw"]}</span>'
            f'<span style="font-size:11px;color:{V("muted2")};">{meta}</span></div>'
            + "".join(rows) + '</div>')
    total = ledger["points_cost"]
    total_txt = ("-%d points" % total) if total else "nothing, all free"
    foot = (f'<div style="border-top:1px solid {V("line")};padding-top:9px;'
            f'font-size:13px;color:{V("text")};font-weight:600;">'
            f'Total cost: <span style="color:{V("red") if total else V("mint")};">'
            f'{total_txt}</span></div>')
    return _one_line(f'<div style="{CARD}">' + "".join(blocks) + foot + '</div>')


# ── Draft identities ──────────────────────────────────────────────────────────
# A compared draft needs an identity that survives being referred to five times
# on one screen. A name does not: it is long, it repeats, and in a legend it gets
# truncated to the half that is identical. A letter plus a shape plus a colour
# does, and it lets every surface point at the same object cheaply.
#
# The shape matters as much as the colour · it is what keeps the comparison
# readable for a colour-blind reader and in a greyscale screenshot.
# V1, V2, V3 rather than A, B, C. A version number is what these actually are ·
# successive attempts at the same squad · and it reads as an id you can say out
# loud without having to remember which letter was which.
_ID_TOKENS = ["mint", "gold", "cyan", "mag", "orange", "red"]
_ID_SHAPES = ["circle", "square", "change_history", "diamond", "hexagon", "star"]


def _draft_identities(names: List[str]) -> Dict[str, Dict]:
    out = {}
    for i, nm in enumerate(names):
        out[nm] = {"letter": "V%d" % (i + 1),
                   "token": _ID_TOKENS[i % len(_ID_TOKENS)],
                   "shape": _ID_SHAPES[i % len(_ID_SHAPES)],
                   "colour": theme.fill(_ID_TOKENS[i % len(_ID_TOKENS)])}
    return out


def _badge(ident: Dict, size: int = 22) -> str:
    """The version chip that stands in for a draft anywhere it is referenced.

    Sized for TWO characters now that it reads V1 rather than A · a square built
    for one glyph crops the digit off the second.
    """
    return (f'<span style="display:inline-grid;place-items:center;'
            f'min-width:{int(size * 1.35)}px;height:{size}px;padding:0 4px;'
            f'border-radius:7px;flex-shrink:0;'
            f'background:{ident["colour"]};color:#06251A;'
            f'font-family:var(--ff-display);font-size:{int(size * 0.5)}px;'
            f'font-weight:900;line-height:1;letter-spacing:-0.02em;'
            f'box-shadow:0 2px 6px rgba(0,0,0,0.25);">{ident["letter"]}</span>')


def _identity_row(names: List[str], ids: Dict) -> str:
    """The key: which letter is which draft, stated once at the top."""
    cards = []
    for nm in names:
        i = ids[nm]
        spec = _SAVED_BY_NAME.get(nm, {})
        chips = []
        if spec.get("bench_boost_gw"):
            chips.append(f"BB{spec['bench_boost_gw']}")
        if spec.get("wildcard_gw"):
            chips.append(f"WC{spec['wildcard_gw']}")
        sub = " · ".join(chips) if chips else "no chips"
        cards.append(
            f'<div style="display:flex;align-items:center;gap:9px;flex:1;'
            f'min-width:190px;background:{V("card")};border:1px solid {V("line")};'
            f'border-left:3px solid {i["colour"]};border-radius:11px;'
            f'padding:9px 12px;">'
            f'{_badge(i)}'
            f'<div style="min-width:0;">'
            f'<div style="font-size:12.5px;font-weight:700;color:{V("text")};'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" '
            f'title="{nm}">{nm}</div>'
            f'<div style="font-size:10.5px;color:{V("muted")};">{sub}</div>'
            f'</div></div>')
    return _one_line('<div style="display:flex;gap:9px;flex-wrap:wrap;'
                     'margin:2px 0 6px;">' + "".join(cards) + "</div>")


def _band_tone(d: Dict, leader: Dict) -> str:
    """green / amber / red, on the same rule the verdicts already use.

    `p` is how often the LEADER finishes ahead of this draft, so:

      under 0.65  · a coin flip with the leader · still in contention  · green
      0.65-0.80   · the leader leans ahead                             · amber
      0.80+       · the leader is clearly ahead                        · red

    Those are the same cuts `significance()` uses to call a draft comparison,
    so a band and a verdict can never disagree.
    """
    if d["name"] == leader["name"]:
        return "green"
    p = leader.get("beats", {}).get(d["name"], 0.5)
    if p >= 0.80:
        return "red"
    if p >= 0.65:
        return "amber"
    return "green"


def _range_bands(ranked: List[Dict], colour: Dict, window,
                 boost_by: Optional[Dict] = None) -> str:
    """Outcome ranges as thin rules · overlap is the answer.

    Drawn by hand rather than in ECharts: a floating bar (lo to hi with a tick
    at the mean) is awkward to encode in a charting library and easy to get
    subtly wrong, and here the whole point is that the reader can see at a
    glance whether two ranges overlap. Absolute positioning makes that exact.

    Thin rules rather than thick blocks so fourteen drafts fit on one screen,
    and three colours rather than fourteen so the picture reads before the
    labels do.
    """
    TONE = {"green": "mint", "amber": "gold", "red": "red"}
    lo_all = min(d["total_lo"] for d in ranked)
    hi_all = max(d["total_hi"] for d in ranked)
    span = (hi_all - lo_all) or 1.0
    pad = span * 0.04
    lo_all, hi_all = lo_all - pad, hi_all + pad
    span = hi_all - lo_all

    def pct(v):
        return (v - lo_all) / span * 100.0

    leader = ranked[0]
    best = leader["total_mean"]
    rows = []
    for d in ranked:
        c = V(TONE[_band_tone(d, leader)])
        left, width = pct(d["total_lo"]), pct(d["total_hi"]) - pct(d["total_lo"])
        bb = (boost_by or {}).get(d["name"])
        bb_chip = (f'<span title="Bench Boost played in GW{bb}" '
                   f'style="background:{V("cyan")};color:#04222B;border-radius:4px;'
                   f'padding:0 4px;font-size:8.5px;font-weight:900;margin-left:5px;'
                   f'letter-spacing:0.04em;">BB{bb}</span>' if bb else "")
        rows.append(
            f'<div style="display:grid;grid-template-columns:170px 1fr 66px;'
            f'align-items:center;gap:10px;margin-bottom:5px;">'
            f'<div style="font-size:11.5px;font-weight:600;color:{V("text")};'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" '
            f'title="{d["name"]}">{d["ident"]["letter"]} {d["short"]}{bb_chip}</div>'
            f'<div style="position:relative;height:12px;">'
            f'<div style="position:absolute;top:5px;left:0;right:0;height:2px;'
            f'background:{V("line")};"></div>'
            f'<div style="position:absolute;top:5px;left:{left:.2f}%;'
            f'width:{width:.2f}%;height:2px;background:{c};opacity:0.85;"></div>'
            f'<div style="position:absolute;top:0;left:{left:.2f}%;width:1px;'
            f'height:12px;background:{c};opacity:0.55;"></div>'
            f'<div style="position:absolute;top:0;left:{pct(d["total_hi"]):.2f}%;'
            f'width:1px;height:12px;background:{c};opacity:0.55;"></div>'
            f'<div style="position:absolute;top:-1px;'
            f'left:{pct(d["total_mean"]):.2f}%;width:3px;height:14px;'
            f'background:{c};border-radius:2px;"></div></div>'
            f'<div class="ff-display" style="font-size:13px;font-weight:800;'
            f'color:{c};text-align:right;white-space:nowrap;">'
            f'{d["total_mean"]:.0f}'
            f'<span style="font-size:9.5px;font-weight:600;color:{V("muted2")};'
            f'margin-left:4px;">{d["total_mean"] - best:+.0f}</span></div></div>')
    return _one_line(
        f'<div style="{CARD}padding:14px 16px;">' + "".join(rows)
        + f'<div style="display:flex;justify-content:space-between;'
        f'font-size:10px;color:{V("muted2")};margin-top:6px;'
        f'padding-top:6px;border-top:1px solid {V("line")};">'
        f'<span>{lo_all:.0f}</span>'
        f'<span>points GW{window[0]}-{window[1]} · '
        f'<span style="color:{V("mint")};">green in contention</span> · '
        f'<span style="color:{V("gold")};">amber behind</span> · '
        f'<span style="color:{V("red")};">red clearly behind</span></span>'
        f'<span>{hi_all:.0f}</span></div></div>')


# ── Substitution rules ────────────────────────────────────────────────────────
# A legal XI is exactly one keeper plus at least three defenders, two midfielders
# and one forward. That leaves four free slots, so a 3-4-3, a 3-5-2, a 4-4-2 and
# a 5-2-3 are all legal and a 2-5-3 is not. Every swap on the pitch is checked
# against this rather than assumed, which is what lets the bench highlight only
# the players who can actually come on.



def _click(value, state_key: str) -> Optional[Dict]:
    """Dedupe a bidirectional component's click on its nonce.

    Both the pitch and the tables replay their LAST value on EVERY rerun, so
    without this a popup reopens (or a swap re-fires) whenever an unrelated
    control moves. See CLAUDE.md rule 4b.
    """
    if not value or not isinstance(value, dict):
        return None
    if value.get("nonce") == st.session_state.get(state_key):
        return None
    st.session_state[state_key] = value.get("nonce")
    return value


# ── Board ─────────────────────────────────────────────────────────────────────
from config import DRAFT_BAR_FLOORS, DRAFT_UI

POOL_PAGE = int(DRAFT_UI["pool_page"])
# Two squads side by side get half the width each, so the pitch is scaled down
# as a whole rather than just narrowed · see `pitch_view.render_squad_pitch`.
COMPARE_SCALE = 0.78
PRICE_BAND = float(DRAFT_UI["price_band"])
CONVICTION_FREE = float(DRAFT_UI["conviction_free"])
CONVICTION_REAL = float(DRAFT_UI["conviction_real"])
# POOL_FLOOR, GRADE_GOOD/FAIR and SEASON_MINUTES moved to ui/player_card.py ·
# their only readers were the player card's grading helpers.

from analytics import freshness as _freshness
from ui.value_board import (SPRINT_STRATEGY, SPRINT_WINDOW, build_board,
                            solve_draft)

board, scout, price_bt, _validation = build_board(_freshness.inputs_stamp())
if board is None:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

HAS_CONSENSUS = "consensus_points" in board.columns
PTS_COL = "consensus_points" if HAS_CONSENSUS else "projected_points"
# Pickable names · `web_name` is shared by up to three players (Palmer is a
# Chelsea midfielder and an Ipswich keeper), so a lock, a veto or a
# comparison chosen by bare name could bind the wrong man. `uniq_name` adds
# a club suffix only where it has to.
NAME_COL = "uniq_name" if "uniq_name" in board.columns else "web_name"
NAMES = sorted(board[NAME_COL].tolist())


def _new_draft_defaults() -> Dict:
    """Eoin's standing opening assumptions, as a draft spec.

    Team SHORT codes in config are resolved to live `team_id`s here · club ids
    are reassigned between seasons, so a hardcoded integer would quietly point
    at a different club. A veto or lock naming somebody not on this season's
    board is dropped rather than carried as a dead string.
    """
    from config import NEW_DRAFT_DEFAULTS as _D
    _short_to_id = {str(r.team_short): int(r.team_id)
                    for r in board[["team_short", "team_id"]]
                    .dropna().drop_duplicates().itertuples()}
    _names = set(board[NAME_COL].astype(str))
    return {
        "bench_boost_gw": _D["bench_boost_gw"],
        "wildcard_gw": _D["wildcard_gw"],
        "locks": [n for n in _D["locks"] if n in _names],
        # A banned price band is expanded into vetoes here, so every downstream
        # surface (solver, multiselect, saved draft) sees one list of ruled-out
        # players rather than a second rule it has to remember to apply.
        "vetoes": ([n for n in _D["vetoes"] if n in _names]
                   + [n for n in (SR.banned_price_names(
                       board, _D.get("ban_price_bands", ()), NAME_COL,
                       exempt=_D.get("price_band_exempt", ()))
                       + SR.below_floor_names(
                           board, _D.get("min_price_by_position", {}), NAME_COL))
                      if n in _names]),
        "cover": [[_short_to_id[t], k, n] for t, k, n in _D["cover"]
                  if t in _short_to_id],
        "attack_cap_exempt": [_short_to_id[t]
                              for t in _D.get("attack_cap_exempt", ())
                              if t in _short_to_id],
        "max_price_band": [list(b) for b in _D.get("max_price_band", ())],
        "cap_attackers": bool(_D.get("cap_attackers", False)),
    }
_NAME_SET = set(NAMES)

# Drafts saved before the pick names changed hold the bare `web_name`, so a
# veto on "Šeško" would silently vanish from the multiselect and then vanish
# from the file on the next save. Losing a user's veto without telling them is
# the worst kind of bug, so old names are translated forward instead.
_BY_WEB: Dict[str, List[str]] = {}
for _w_nm, _u_nm in zip(board["web_name"], board[NAME_COL]):
    _BY_WEB.setdefault(str(_w_nm), []).append(str(_u_nm))


def _pick_names(saved: Optional[List[str]]) -> List[str]:
    """Saved player names, translated onto the current pick names."""
    out = []
    for n in (saved or []):
        if n in _NAME_SET:
            out.append(n)
            continue
        cands = _BY_WEB.get(str(n), [])
        if len(cands) == 1:
            out.append(cands[0])        # unambiguous · just re-spelled
        elif cands:
            # The name was shared even then, so we cannot know which one was
            # meant. Keep the most valuable, which is almost always the intent.
            _best = board[board["web_name"] == n].nlargest(1, PTS_COL)
            out.append(str(_best.iloc[0][NAME_COL]) if not _best.empty else cands[0])
    return out

# A model input that fails to load used to die in a log line. The Scout backfill
# is the one that matters: without it every Coventry, Hull and Ipswich player
# leaves the pool, and a squad built from what remains looks perfectly normal.
for _w in (price_bt or {}).get("load_warnings", []):
    st.warning(_w, icon=":material/warning:")


from ui import live_projection as LP

_FIX = LP.club_fixtures()
_module_stamp = LP.module_stamp
_PROJ_VERSION = LP.PROJ_VERSION


def _fixtures_for(team_id: int, gw: int, n: int = 3) -> List[Dict]:
    return LP.fixtures_for(team_id, gw, n, fix=_FIX)


# Content stamp, not len(board). Refreshing a snapshot or editing an override
# almost never changes the row COUNT, so keying on length served the stale
# projection for the whole TTL after the exact edit meant to change it.

BOARD_STAMP = _freshness.board_stamp(board, PTS_COL)

from analytics import gw_projection as _gwp_mod
PROJ = LP.projector(board, _FIX, BOARD_STAMP, _PROJ_VERSION,
                     _module_stamp(_gwp_mod))
MATCH_WINDOW = PROJ.window


# DEFCON per-90, set-piece glyphs and the player evidence card itself now live
# in `ui/player_card.py`, shared with My Team. `DEFCON` and `MISS_EARLY` stay
# page globals because other tabs read them directly.
DEFCON = PC.defcon_per90(BOARD_STAMP)

MISS_EARLY = PC.miss_early_codes()


# ── Snapshot freshness ────────────────────────────────────────────────────────
# Scout and Hub are hand-refreshed one-shot files. A six-week-old Hub export
# drives the whole per-gameweek view, and until now nothing on screen said so.
_FRESH = _freshness.sources()
_FRESH_STATE = _freshness.worst_state(_FRESH)
_FRESH_TOKEN = {"fresh": "mint", "ageing": "gold",
                "stale": "orange", "missing": "red"}[_FRESH_STATE]
_FRESH_TITLE = " · ".join(
    "%s %s" % (r["name"], _freshness.age_label(r["days"])) for r in _FRESH)

# Name the file that is oldest. An unlabelled "5d ago" reads as "all the data
# is five days old" when it meant the Scout snapshot only · the Hub was eight
# hours old at the time. That mis-read sent us chasing a refresh that was not
# needed, so the chip now says WHICH source it is reporting.
_OLDEST = max((r for r in _FRESH if r["days"] is not None),
              key=lambda r: r["days"], default=None)
_FRESH_LABEL = ("%s %s" % (_OLDEST["name"], _freshness.age_label(_OLDEST["days"]))
                if _OLDEST else "no snapshots")


# ── Hero ──────────────────────────────────────────────────────────────────────
# A single compact line rather than a 40px hero. The sidebar already says which
# page this is, and every pixel above the pitch is a pixel the pitch does not get.
_HERO = _one_line(f"""
<div class="fplh-animate-in" style="display:flex;align-items:center;gap:12px;
     flex-wrap:wrap;padding:0 0 6px;font-family:'Inter',sans-serif;">
  <div class="ff-display ff-hero-title" style="font-size:24px;font-weight:900;
       color:{V('text')};">{NEXT_SEASON} Draft</div>
  <span title="{_FRESH_TITLE}" style="background:{V('chip-bg')};
    border:1px solid {V(_FRESH_TOKEN)};color:{V(_FRESH_TOKEN)};font-size:9.5px;
    font-weight:800;letter-spacing:0.12em;padding:3px 9px;border-radius:20px;
    text-transform:uppercase;">{_FRESH_LABEL}</span>
  <span style="background:{V('chip-bg')};border:1px solid {V('mint')};
    color:{V('mint')};font-size:9.5px;font-weight:800;letter-spacing:0.12em;
    padding:3px 9px;border-radius:20px;text-transform:uppercase;">
    Live prices · {'3 models' if HAS_CONSENSUS else '1 model'}</span>
</div>""")


# ── Controls ──────────────────────────────────────────────────────────────────
# The picker is the SAVED DRAFTS, not a hardcoded strategy list. One place to
# define a draft means the thing you plan on the pitch and the thing you compare
# in the A/B tab are the same object, and a draft you delete disappears from
# both. Premium decisions are expressed as locks on a saved draft rather than as
# bespoke strategies, which is why there is no "no Haaland" mode any more: that
# is just Optimal without him in the locks.
from analytics import drafts as DR

_SAVED = DR.load_drafts()
_SAVED_BY_NAME = {d["name"]: d for d in _SAVED}

if not _SAVED:
    # The "restore the presets" button it used to point at is gone, and so is
    # the panel that held it. Say what actually fixes this.
    st.warning("No saved drafts. Delete `data/cache/saved_drafts.json` and "
               "reload · the Optimal preset is laid down on first run.")
    st.stop()


def _draft_label(name: str) -> str:
    """A short, scannable pill label.

    The draft is the primary object on this page, so its selector has to be
    readable at a glance rather than a dropdown you open to find out what you
    picked. Three moves: an icon that says WHAT KIND of draft it is, a squad name
    cut to its distinguishing part, and the chip plan kept intact because that is
    usually the thing that differs.
    """
    spec = _SAVED_BY_NAME[name]
    head, _, chip = name.partition(" · ")
    if DR.has_squad(spec):
        icon = ":material/bookmark:"          # a fifteen you built
    elif head.startswith("Route"):
        icon = ":material/science:"           # a chip-route experiment
        head = head.replace("Route · ", "")
    elif spec.get("locks"):
        icon = ":material/lock:"              # a premium call
    else:
        icon = ":material/balance:"           # the plain optimum
    # The abbreviations existed to squeeze thirteen near-identical preset names
    # onto pills ("Optimal + Fernandes + Mosquera + Haaland"). With one preset
    # and user-named drafts, a name is just a name · mangling "Optimal" into
    # "Base" made the only draft on the page unrecognisable.
    squad = head
    return f"{icon} {squad} {chip}".strip() if chip else f"{icon} {squad}"


def _draft_group(name: str) -> str:
    """Which family a draft belongs to · the same distinction the icon makes."""
    spec = _SAVED_BY_NAME[name]
    if DR.has_squad(spec):
        return "Mine"
    if name.startswith("Route"):
        return "Routes"
    if spec.get("locks"):
        return "Locked"
    return "Base"


# Your own drafts first · a preset is a starting point, the one you built is the
# one you came back for.
_all_opts = sorted(list(_SAVED_BY_NAME),
                   key=lambda n: (bool(_SAVED_BY_NAME[n].get("preset")),
                                  not DR.has_squad(_SAVED_BY_NAME[n]), n))

# Fourteen pills of near-identical text ("+Fern+Mosq+Haal BB1 → WC4" against
# "+Fern+Mosq+Haal BB2 → WC4") force you to read every one to find the one you
# want. Grouping means reading a category first and four pills after it. The
# groups are derived from the draft data, not a second hardcoded list.
_hero, _ctrl = st.columns([4, 1])
with _hero:
    st.markdown(_HERO, unsafe_allow_html=True)
with _ctrl:
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ── The workflow, stated ──────────────────────────────────────────────────────
# A page with a dropdown, a popover, a pitch, a table and seven tabs gives no
# clue what order to do things in. The steps are numbered here and the same
# numbers appear on the controls themselves, so the page reads as a sequence
# rather than a wall of options. It marks where you ARE rather than pretending
# to be a wizard · everything stays reachable at any time.
def _workflow_rail(step: int) -> None:
    steps = [
        ("Start a draft", "playlist_add_check", "new, or pick an old one"),
        ("Tune it", "tune", "who you want, the dials, the chips"),
        ("It generates", "bolt", "the squad rebuilds as you tune"),
        ("Tweak and name it", "sports_soccer", "swap by hand, then save"),
        ("Compare", "compare_arrows", "against your other drafts"),
    ]
    cells = []
    for i, (label, icon, sub) in enumerate(steps, start=1):
        on = i == step
        done = i < step
        tok = "mint" if on else ("cyan" if done else "muted2")
        cells.append(
            f'<div style="display:flex;align-items:center;gap:8px;flex:1;'
            f'min-width:104px;padding:6px 8px;border-radius:8px;'
            f'background:{V("chip-bg") if on else "transparent"};'
            f'border:1px solid {V("mint") if on else V("line")};">'
            f'<span style="display:inline-grid;place-items:center;width:20px;'
            f'height:20px;border-radius:6px;flex-shrink:0;'
            f'background:{V(tok)};color:#06251A;font-family:var(--ff-display);'
            f'font-size:11px;font-weight:900;">{i}</span>'
            f'<div style="min-width:0;">'
            f'<div style="font-size:11px;font-weight:700;color:'
            f'{V("text") if on else V("muted")};white-space:nowrap;">{label}</div>'
            + (f'<div style="font-size:9px;color:{V("muted2")};white-space:nowrap;'
               f'overflow:hidden;text-overflow:ellipsis;">{sub}</div>' if on else "")
            + '</div></div>')
    st.markdown(_one_line(
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px;">'
        + "".join(cells) + '</div>'), unsafe_allow_html=True)


_workflow_rail(1)

# ── Draft selector ────────────────────────────────────────────────────────────
# One dropdown, grouped, with the facts about the selection beside it rather
# than under it. Fifteen pills across the top was a rail you had to read every
# item of; a grouped list is one glance and a scroll.
def _draft_group(name: str) -> str:
    spec = _SAVED_BY_NAME[name]
    if DR.has_squad(spec):
        return "Mine"
    if name.startswith("Route"):
        return "Routes"
    if spec.get("locks"):
        return "Locked"
    return "Base"


def _plain_label(name: str) -> str:
    """The pill label with its icon markup removed, for plain-text widgets."""
    import re as _re
    return _re.sub(r":material/[a-z_]+:\s*", "", _draft_label(name)).strip()


_GROUP_ORDER = ["Mine", "Locked", "Base", "Routes"]
_GROUP_ICON = {"Mine": "bookmark", "Locked": "lock",
               "Base": "balance", "Routes": "science"}
_opts = sorted(_all_opts, key=lambda n: (_GROUP_ORDER.index(_draft_group(n)), n))

# Selecting a draft you just created cannot be done by writing to the widget's
# own key · Streamlit refuses once the widget exists, and the whole create flow
# died on that. The wanted name is stashed instead and applied HERE, before the
# selectbox is built, which is the only legal moment.
_want = st.session_state.pop("_want_draft", None)
if _want and _want in _opts:
    st.session_state["planner_draft"] = _want

_default = st.session_state.get("planner_draft")
if _default not in _opts:
    # Session state dies on a hard reload, so fall back to the draft you were
    # last on rather than to whichever one happens to sort first.
    _by_id = {d["id"]: d["name"] for d in _SAVED}
    _default = _by_id.get(DR.last_used() or "", None)
    if _default not in _opts:
        _default = _opts[0]

# Three columns, not four-plus-a-nested-two. The chips and Delete used to share
# a quarter of the row and then split it again, which left Delete about 50px
# wide · the browser rendered it one letter per line, under a trash icon, on top
# of the chips. The chips get their own full-width line below instead, where
# they can wrap the way chips are supposed to.
_sel_col, _new_col, _act_col = st.columns([5, 2, 1])
with _sel_col:
    _pick = st.selectbox(
        "1 · Which draft", _opts, index=_opts.index(_default), key="planner_draft",
        help="Start from Optimal, tune it, then save it under your own name.",
        # Plain text · st.selectbox does not render Material icon markup, and a
        # literal ":material/lock:" in the closed dropdown is worse than none.
        # The group prefix already says what kind of draft it is.
        format_func=_plain_label)
with _new_col:
    # No name box here. You do not know what a draft IS until you have tuned it
    # and looked at the fifteen, so being made to name it first is a question
    # asked at the worst possible moment. It gets a working title, and the name
    # is the last step, down at Save · which is also where you are looking.
    st.markdown('<div style="height:26px;"></div>', unsafe_allow_html=True)
    if st.button(":material/add: New draft", use_container_width=True,
                 key="new_draft_top",
                 help="Starts a copy of the draft you are on, so you tune from "
                      "where you are. You name it at the end, when you save."):
        _base = _SAVED_BY_NAME[_pick if _pick in _SAVED_BY_NAME else _default]
        _taken = {d["id"] for d in _SAVED}
        _n = 1
        while ("untitled-%d" % _n) in _taken:
            _n += 1
        _new_id, _new_name = "untitled-%d" % _n, "Untitled draft %d" % _n
        _fresh = {k: _base.get(k) for k in DR.BASE if k != "squad"}
        # A new draft starts from the standing plan, not from whatever the last
        # draft happened to be tuned to · see config.NEW_DRAFT_DEFAULTS.
        _fresh.update(_new_draft_defaults())
        DR.save_draft(_new_name, _fresh, draft_id=_new_id,
                      allow_clear=("bench_boost_gw", "wildcard_gw"))
        st.session_state["_want_draft"] = _new_name
        st.session_state["just_created"] = True
        st.rerun()
if _pick is None:
    _pick = _default
_spec = _SAVED_BY_NAME[_pick]

# ── Working state, scoped to the selected draft ───────────────────────────────
# Transfers, the axed player, manual XI picks and the viewed gameweek all belong
# to ONE draft. Held under bare keys they leaked across drafts: switching preset
# carried the previous draft's transfers onto the new fifteen, so the pitch
# showed a squad that no draft had ever specified. Scoped by draft id the same
# way the dials are, which also means flipping back to a draft finds your work
# where you left it.
#
# This block sits ABOVE the solve on purpose. The Bench Boost week is now part
# of the OBJECTIVE, not a thing you switch on afterwards, so the optimiser has
# to know it before it picks anybody.
_DRAFT_ID = str(_spec["id"])
DR.remember_last(_DRAFT_ID)     # no-op unless it actually changed

# A preset cannot be written to, but you should still be able to TRY a chip
# week on one. The override lives in session state, scoped to the draft, and a
# custom draft also persists it so "whatever it is left as is what it saves".
_BB_UNSET = "unset"


def _sk(name: str) -> str:
    """Session-state key for `name` under the ACTIVE draft."""
    return f"{name}::{_DRAFT_ID}"


def _effective_boost_gw():
    v = st.session_state.get(_sk("bb_override"), _BB_UNSET)
    return _spec.get("bench_boost_gw") if v == _BB_UNSET else v


_DRAFT_STATE_DEFAULTS = {
    "draft_swaps": dict,      # {gw: {out_code: in_code}}
    "draft_axe": list,   # ORDERED codes marked out · fills slots first-in-first-out
    "draft_bench": set,
    "sub_from": lambda: None,  # player tapped to be subbed
    "xi_override": dict,      # {gw: set(codes)} manual XI
    "draft_gw": lambda: 1,
}

for _n, _factory in _DRAFT_STATE_DEFAULTS.items():
    st.session_state.setdefault(_sk(_n), _factory())

# The facts about THIS draft, as chips. A selector that only echoes its own
# label teaches you nothing.
# `preset` is the authoritative flag. Falling through to "Preset" because a
# draft had no saved fifteen labelled every draft the user had just made as one
# of ours, and presets cannot be saved to · so the label contradicted the
# buttons next to it.
# Short enough for a chip · this column is about 190px with the sidebar open,
# and a long label wrapped into five stacked words. It says what KIND of draft
# this is, not whether it is saved · a recipe that has been saved still has no
# fifteen on it, and reading "not saved yet" right after pressing Save is a lie.
_kind, _kind_why = (
    ("Saved fifteen", "A team you built by hand. Shown exactly as saved.")
    if DR.has_squad(_spec) else
    ("Route", "A chip-route experiment.")
    if _spec["name"].startswith("Route") else
    ("Preset", "One of ours. Tune it and save a copy under your own name.")
    if _spec.get("preset") else
    ("Recipe", "Re-solved from your settings every time, so it stays right "
               "when prices and projections move. Press Save this team below "
               "to freeze the fifteen."))
_chips = [(_GROUP_ICON[_draft_group(_pick)], _kind, "mint", _kind_why)]
if _spec.get("locks"):
    _chips.append(("lock", "%d locked" % len(_spec["locks"]), "gold",
                   "Must-have players: " + ", ".join(_spec["locks"])))
if _spec.get("bench_boost_gw"):
    _chips.append(("battery_charging_full", "BB GW%d" % _spec["bench_boost_gw"],
                   "cyan", "Bench Boost planned for GW%d · all fifteen score "
                           "that week." % _spec["bench_boost_gw"]))
if _spec.get("wildcard_gw"):
    _chips.append(("playing_cards", "WC GW%d" % _spec["wildcard_gw"], "mag",
                   "Wildcard planned for GW%d, so this fifteen is built for "
                   "GW1-%d." % (_spec["wildcard_gw"], _spec["wildcard_gw"] - 1)))
if len(_chips) == 1:
    _chips.append(("block", "no chips", "muted2",
                   "No Bench Boost or Wildcard planned on this draft."))

with _act_col:
    st.markdown('<div style="height:26px;"></div>', unsafe_allow_html=True)
    # Icon only. The word never fitted, and a bin needs no caption.
    if st.button(":material/delete:", use_container_width=True, key="del_draft",
                 disabled=bool(_spec.get("preset")),
                 help=("Presets cannot be deleted." if _spec.get("preset")
                       else "Delete this draft.")):
        st.session_state["confirm_delete"] = _spec["id"]

# The chips get a full-width line of their own, so they wrap like chips instead
# of stacking into a tower in a 90px column.
st.markdown(_one_line(
    '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 10px;">'
    + "".join(
        f'<span title="{_why}" style="display:inline-flex;align-items:center;'
        f'gap:4px;background:{V("chip-bg")};color:{V(_tok)};border-radius:6px;'
        f'padding:3px 8px;font-size:10px;font-weight:800;'
        f'letter-spacing:0.05em;text-transform:uppercase;cursor:help;'
        f'white-space:nowrap;">'
        f'{theme.icon(_ic, 13, V(_tok))}{_lab}</span>'
        for _ic, _lab, _tok, _why in _chips)
    + '</div>'), unsafe_allow_html=True)

# Deleting is one click away but never one click · a saved fifteen is work.
if st.session_state.get("confirm_delete") == _spec["id"]:
    _w1, _w2, _w3 = st.columns([4, 1, 1])
    with _w1:
        st.warning("Delete **%s**? This cannot be undone." % _spec["name"])
    with _w2:
        if st.button("Delete", type="primary", use_container_width=True,
                     key="del_yes"):
            DR.delete_draft(_spec["id"])
            st.session_state.pop("confirm_delete", None)
            st.session_state.pop("planner_draft", None)
            st.rerun()
    with _w3:
        if st.button("Keep", use_container_width=True, key="del_no"):
            st.session_state.pop("confirm_delete", None)
            st.rerun()


# Step 2 lives inline rather than behind a popover, and opens by itself the
# moment you create a draft · naming a squad and then being left on the same
# screen with no obvious next move is where the old flow lost people. It stays
# open while you tune and remembers that you closed it.
_just_made = st.session_state.pop("just_created", False)
if _just_made:
    st.session_state["tune_open"] = True
_open_controls = st.expander(
    "2 · Tune this draft  ·  who you want, who you do not, and the dials",
    expanded=bool(st.session_state.get("tune_open", False)))

with _open_controls:
    mode = _spec.get("strategy", "⚖️ Optimal value")

    # The dials start from the chosen draft and are overrides from there. Keying
    # them on the draft id is what makes them re-read when you switch draft
    # rather than carrying the previous one's settings across.
    _k = _spec["id"]

    # Who you want and who you do not comes FIRST. It is the reason anyone opens
    # this panel, and it was below five sliders nobody had an opinion about.
    l1, l2 = st.columns(2)
    with l1:
        locked = st.multiselect(
            ":material/lock: Must have · these go in no matter what",
            options=NAMES,
            default=_pick_names(_spec.get("locks")),
            key=f"lock_{_k}",
            help="A lock beats a veto. This is where a premium call lives: "
                 "locking Haaland IS the Haaland draft.")
    with l2:
        excluded = st.multiselect(
            ":material/block: Do not want · never pick these",
            options=NAMES,
            default=_pick_names(_spec.get("vetoes")),
            key=f"veto_{_k}",
            help="Anyone you are not convinced by · a club in turmoil, a player "
                 "you think is leaving, an unproven signing.")

    st.markdown(_one_line(
        f'<div style="font-size:10.5px;color:{V("muted")};margin:2px 0 8px;">'
        f'The dials below are fine at their defaults. Change them only when you '
        f'have a reason.</div>'), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        budget = st.slider("Budget (£m)", 95.0, 105.0,
                           float(_spec.get("budget", 100.0)), 0.5, key=f"bud_{_k}")
    with c2:
        risk = st.slider("Risk · Upside ↔ Safety", 0.0, 1.0,
                         float(_spec.get("risk", 0.3)), 0.05, key=f"risk_{_k}",
                         help="0 maximises the mean projection. 1 maximises the "
                              "confidence floor · low-confidence punts and fullbacks "
                              "get discounted as you slide right.")
    with c3:
        opening = st.slider("Opening fixtures GW1-6", 0.0, 1.0,
                            float(_spec.get("opening", 0.35)), 0.05, key=f"open_{_k}",
                            help="Playbook Q15 measured this as WEAK (r = -0.38 and "
                                 "weakening) while team quality persists at r = +0.53 · "
                                 "a tie-breaker, not a reason to pick someone.")
    m1, m2 = st.columns(2)
    with m1:
        minutes_gate = st.slider(
            "Weight early minutes", 0.0, 1.0,
            float(_spec.get("minutes_gate", 0.5)) if MATCH_WINDOW else 0.0, 0.05,
            disabled=not MATCH_WINDOW, key=f"gate_{_k}",
            help="Discounts players the match model expects almost no minutes from "
                 "in the opening weeks · World Cup returnees, injuries, third "
                 "choices. At 0 the optimiser will happily draft a man who is not "
                 "playing.")
    with m2:
        # Off by default. It was costing real points without earning them: the
        # unconstrained optimum already spreads across clubs on its own, so the
        # cap only ever bit when a deliberate pick ran into it (two Man Utd
        # midfielders on the softest opening run in the league). Kept as a
        # toggle because the diversification argument is still sound when you
        # are picking a whole season rather than a three-week sprint.
        cap_attackers = st.checkbox(
            "Limit to 1 attacker per club",
            value=bool(_spec.get("cap_attackers", False)), key=f"capatt_{_k}",
            help="Off by default. When on, at most one midfielder or forward per "
                 "club, so a bad week for that club cannot sink two picks. It "
                 "costs points whenever you deliberately want two.")
        two_att = not cap_attackers

    # ── "I want cover from this club" ────────────────────────────────────────
    # Locking a NAMED player answers a question you often cannot answer: which
    # Arsenal defender starts GW1. This states only the exposure you want and
    # lets the optimiser buy it the cheapest legal way, which is the better
    # trade whenever your conviction is about a CLUB rather than a person.
    #
    # Defensive cover is keeper-or-defender because both cash the same clean
    # sheet; attacking cover is midfielder-or-forward because both cash goals.
    _clubs = (board[["team_id", "team_name"]].dropna().drop_duplicates()
              .sort_values("team_name"))
    _club_name = {int(r.team_id): str(r.team_name) for r in _clubs.itertuples()}
    _name_club = {v: k for k, v in _club_name.items()}
    _saved_cover = list(_spec.get("cover") or [])

    # A plain section, not an expander · this block already lives inside one and
    # Streamlit refuses to nest them.
    with st.container():
        st.markdown(_one_line(
            f'<div style="font-size:11px;font-weight:800;letter-spacing:0.16em;'
            f'text-transform:uppercase;color:{V("muted")};margin:10px 0 2px;">'
            f'Cover from a club</div>'
            f'<div style="font-size:12px;color:{V("muted")};margin-bottom:6px;">'
            f'Demand exposure to a club without naming the player. Defensive '
            f'counts keepers and defenders; attacking counts midfielders and '
            f'forwards.</div>'), unsafe_allow_html=True)
        _def_default = [_club_name[t] for t, k, _n in _saved_cover
                        if k == "def" and t in _club_name]
        _att_default = [_club_name[t] for t, k, _n in _saved_cover
                        if k == "att" and t in _club_name]
        cc1, cc2 = st.columns(2)
        with cc1:
            _def_clubs = st.multiselect(
                "At least one defensive asset from", list(_name_club),
                default=_def_default, key=f"covdef_{_k}",
                help="A goalkeeper OR a defender from each club chosen.")
        with cc2:
            _att_clubs = st.multiselect(
                "At least one attacking asset from", list(_name_club),
                default=_att_default, key=f"covatt_{_k}",
                help="A midfielder OR a forward from each club chosen.")
        cover = tuple([(int(_name_club[c]), "def", 1) for c in _def_clubs]
                      + [(int(_name_club[c]), "att", 1) for c in _att_clubs])
        if cover:
            st.caption("These are hard constraints · if no legal squad satisfies "
                       "them the solve fails rather than quietly ignoring one.")

    # ── The chip that changes the objective ───────────────────────────────
    # A Bench Boost you have already decided on is not something to switch on
    # after the squad exists · it changes what "best fifteen" MEANS. Without it
    # the optimiser buys eleven players and four cheap seat-fillers, which is
    # correct for a normal week and wrong for the week all fifteen score.
    # Declared here, it goes straight into the objective below.
    # "off" rather than None as the no-chip option. A selectbox whose value is
    # set to None shows its PLACEHOLDER, not the None entry, so clearing the
    # chip from the pitch left the box reading "Choose an option".
    _OFF = "off"
    _gw_opts = [_OFF] + list(range(1, MAX_GW + 1))
    _fmt_gw = lambda g: "Not playing it" if g == _OFF else "GW%d" % g
    _as_gw = lambda g: None if g == _OFF else int(g)
    b1, b2, b3 = st.columns([2, 2, 3])
    with b1:
        # The pitch's "Boost GWn" button stashes its choice here · applied
        # before the box is built, which is the only legal moment.
        if "_want_bb" in st.session_state:
            _w = st.session_state.pop("_want_bb")
            st.session_state[f"bbweek_{_k}"] = _OFF if _w is None else int(_w)
        _bb_now = _effective_boost_gw()
        boost_gw = _as_gw(st.selectbox(
            ":material/battery_charging_full: Bench Boost week", _gw_opts,
            index=_gw_opts.index(_bb_now) if _bb_now in _gw_opts else 0,
            format_func=_fmt_gw, key=f"bbweek_{_k}",
            help="Set it here and the optimiser builds the fifteen that scores "
                 "most WITH the boost, not an eleven plus four seat-fillers. "
                 "Leave it off and bench money is treated as dead money."))
    with b2:
        # The wildcard week is the other half of the same decision · it sets how
        # long you own this squad, and therefore how many weeks the bench has to
        # be carried against the one week it pays.
        _wc_now = _spec.get("wildcard_gw")
        wildcard_gw = _as_gw(st.selectbox(
            ":material/playing_cards: Wildcard week", _gw_opts,
            index=_gw_opts.index(_wc_now) if _wc_now in _gw_opts else 0,
            format_func=_fmt_gw, key=f"wcweek_{_k}",
            help="Wildcarding at GW4 means this fifteen only has to be good for "
                 "GW1-3, so the optimiser scores it over those weeks instead of "
                 "a season you are going to tear up."))
        # The horizon is this number, read the other way round. It gets its own
        # line because "3 gameweeks" is what you plan in, but NOT its own widget
        # · two controls owning one value is how they drift apart.
        _wc_win = SR.plan_window(wildcard_gw)
        st.markdown(_one_line(
            f'<div style="font-size:11px;color:{V("muted")};margin-top:-6px;">'
            + (f'Plan horizon · <b style="color:{V("text")};">'
               f'{_wc_win[1] - _wc_win[0] + 1} gameweeks</b> '
               f'(GW{_wc_win[0]}-{_wc_win[1]})' if _wc_win
               else 'Plan horizon · the full season')
            + '</div>'), unsafe_allow_html=True)
    with b3:
        _win_hi = _wc_win[1] if _wc_win else None
        if boost_gw and _win_hi:
            _msg = (f'Built for <b style="color:{V("cyan")};">GW1-{_win_hi}</b> '
                    f'with all fifteen scoring in <b style="color:{V("cyan")};">'
                    f'GW{boost_gw}</b>. The bench is priced at exactly what it '
                    f'earns · full value that week, nothing in the others.')
        elif boost_gw:
            _msg = (f'All fifteen score in <b style="color:{V("cyan")};">'
                    f'GW{boost_gw}</b>. With no wildcard week set the squad is '
                    f'still scored over a whole season, so one boosted week '
                    f'barely moves it. Set a wildcard week to make it bite.')
        elif _win_hi:
            _msg = (f'Built for <b style="color:{V("cyan")};">GW1-{_win_hi}</b> '
                    f'only. The bench is dead money · the optimiser spends as '
                    f'little on it as the rules allow.')
        else:
            _msg = ('No chips. The bench is worth a token fraction of a starter '
                    'and the squad is scored over the full season.')
        st.markdown(_one_line(
            f'<div style="font-size:11.5px;color:{V("muted")};padding-top:30px;">'
            f'{_msg}</div>'), unsafe_allow_html=True)
    # Keep the gameweek stepper's toggle and this control as ONE fact.
    st.session_state[_sk("bb_override")] = boost_gw

    # ── Keep it ───────────────────────────────────────────────────────────
    # The loop is: tune, watch the squad change below, keep it. Saving ONTO the
    # draft you are on is the common case and used to be impossible here · you
    # could only ever fork a new one, so every tweak spawned another draft.
    st.markdown(f'<div style="height:1px;background:{V("line")};margin:14px 0 10px;"></div>',
                unsafe_allow_html=True)

    _cur_spec = {
        "strategy": mode, "locks": list(locked), "vetoes": list(excluded),
        "budget": float(budget), "risk": float(risk), "opening": float(opening),
        "minutes_gate": float(minutes_gate), "cap_attackers": bool(cap_attackers),
        # Cover is a constraint, so changing it makes the draft dirty like any
        # other. Compared as lists · the widget yields tuples.
        "cover": [list(c) for c in cover],
        "bench_boost_gw": boost_gw,
        "wildcard_gw": wildcard_gw,
    }
    _changed = any(_cur_spec[k] != _spec.get(k) for k in
                   ("locks", "vetoes", "budget", "risk", "opening",
                    "minutes_gate", "cap_attackers", "bench_boost_gw",
                    "wildcard_gw"))

    # ONE button here, and no name box. The naming step lives at the bottom, on
    # the fifteen you are looking at · asking for a name up here, before the
    # squad exists, was the confusing part. "Save as a copy" is gone too: the
    # New draft button already copies, so there were two ways to fork.
    _s1, _s2, _s3 = st.columns([3, 2, 2])
    with _s2:
        # A saved fifteen is frozen on purpose · the dials must not silently
        # rebuild a squad you picked by hand. But the only way out of that freeze
        # was to VETO someone, so "just optimise it from my settings" was a thing
        # the page could not do. This is that button. It proposes, it does not
        # overwrite · the diff and the confirmation come later.
        #
        # The solve cannot happen here: `solve_opening` and `_LIVE_SPEC` are
        # built further down the script. So this raises a flag the same way the
        # pitch's "Boost GWn" button does, and the solve reads it in place.
        if DR.has_squad(_spec):
            _win_lbl = ("GW%d-%d" % _wc_win) if _wc_win else "the season"
            if st.button(":material/auto_awesome: Optimise for %s" % _win_lbl,
                         use_container_width=True, key="ctrl_optimise",
                         help="Rebuild all fifteen from the dials above. Vetoing "
                              "a player frees his money for the whole squad, so "
                              "the answer can be a more expensive signing paid "
                              "for by downgrading someone else."):
                st.session_state["_want_optimise"] = True
    with _s1:
        st.markdown(_one_line(
            f'<div style="font-size:11.5px;color:{V("mint") if _changed else V("muted")};'
            f'padding-top:8px;">'
            + ("Changed. The squad below has already updated · press Keep to "
               "hold these settings on <b>%s</b>, or name and save the fifteen "
               "at the bottom." % _spec["name"] if _changed
               else "Nothing changed yet. Move a dial and the squad below "
                    "rebuilds straight away.")
            + '</div>'), unsafe_allow_html=True)
    with _s3:
        if st.button(":material/save: Keep these settings",
                     use_container_width=True, key="ctrl_save_same",
                     disabled=bool(_spec.get("preset")) or not _changed,
                     help=("A preset cannot be written to · press New draft to "
                           "start your own from it." if _spec.get("preset") else
                           "Store the dials on this draft. The fifteen is saved "
                           "separately, at the bottom.")):
            DR.save_draft(_spec["name"], _cur_spec, draft_id=_spec["id"],
                          allow_clear=("bench_boost_gw", "wildcard_gw"))
            st.toast("Settings kept on %s" % _spec["name"], icon="✅")
            st.rerun()



@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _window_map(lo: int, hi: int) -> tuple:
    from analytics.season_opener import opening_ease
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    fx = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())
    oe = opening_ease(fx, lo, hi)
    return tuple(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _tuned_board_cached(gate: float, stamp: str) -> pd.DataFrame:
    return _tuned_board_impl(gate)


def _tuned_board(gate: float) -> pd.DataFrame:
    """Cached wrapper. The body copies the whole board, reads the overrides
    JSON off disk and maps a lambda over every row · once per rerun was bad
    enough, and the compare tab did it again per draft being compared."""
    return _tuned_board_cached(round(float(gate), 4), BOARD_STAMP)


def _tuned_board_impl(gate: float) -> pd.DataFrame:
    """The board the solver sees · consensus points, minutes-gated and
    availability-adjusted.

    Two corrections here, both of which the optimiser got wrong before.

    **A missing match-model row is not a nailed starter.** `ffh_nailedness` is
    NaN for 148 players (the Hub simply has no row for them), and filling that
    with 1.0 handed every one of them a perfect minutes score · the least certain
    players got the biggest benefit of the doubt. It now falls back to our own
    fitted `mins_share`, which is at least an estimate rather than an assumption.

    **A hand-entered absence has to reach the solver.** `miss_gws` was only
    applied per gameweek, so the season objective never saw it and the optimiser
    kept drafting a player it had itself scored at zero for the opening weeks
    (Garner, out for GW1-2). The haircut below is proportional to the share of
    the OPENING WINDOW he misses, not of the season: a draft is built for the
    start, and missing a third of the opening is a third of the reason you own
    him early.
    """
    from config import OPENING_FIXTURES

    d = board.copy()
    if PTS_COL != "projected_points":
        d["projected_points"] = d[PTS_COL]

    if gate > 0 and "ffh_nailedness" in d.columns:
        share = pd.to_numeric(d.get("mins_share"), errors="coerce").clip(0, 1)
        nail = pd.to_numeric(d["ffh_nailedness"], errors="coerce")
        # A hand-entered EARLY-minutes call outranks the match model, the same
        # way a hand-entered absence does. The Hub had Foden at 32 minutes a
        # game while an explicit call sat in the overrides file being ignored.
        #
        # Only `early_nailedness` does this, never a season-minutes override.
        # Mosquera starts while Saliba is injured and loses the place when he
        # returns · his season minutes are deliberately low, and letting that
        # gate the OPENING window marked him down in the weeks he is certain to
        # play, which is the opposite of the truth.
        if "early_nailedness" in d.columns:
            hand = pd.to_numeric(d["early_nailedness"], errors="coerce")
            nail = hand.combine_first(nail)
        nail = nail.fillna(share).fillna(0.75)
        factor = (1.0 - gate) + gate * nail.clip(0.0, 1.0)
        for c in ("projected_points", "proj_lo"):
            if c in d.columns:
                d[c] = (d[c] * factor).round(1)

    try:
        from analytics.projection_overrides import load_overrides
        window = max(1, int(OPENING_FIXTURES.get("gw_hi", 6)))
        miss = {int(c): [int(g) for g in adj.get("miss_gws", [])]
                for c, adj in load_overrides().items() if adj.get("miss_gws")}
        if miss:
            hair = d["code"].astype(int).map(
                lambda c: 1.0 - min(1.0, len([g for g in miss.get(c, [])
                                              if g <= window]) / window))
            for c in ("projected_points", "proj_lo"):
                if c in d.columns:
                    d[c] = (d[c] * hair.fillna(1.0)).round(1)
    except Exception as exc:
        logging.getLogger(__name__).warning("availability haircut skipped: %s", exc)
    return d


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _window_board(_base: pd.DataFrame, lo: int, hi: int, stamp: str) -> pd.DataFrame:
    """The board scored on the WINDOW you will actually own this squad for.

    If you wildcard at GW4 then the opening fifteen only has to be good for
    GW1-3, and a season total is the wrong objective for it. This is not the
    same as scaling season points by fixture ease: a player nailed for the
    opening weeks but rotated later (Mosquera starts while Saliba is injured)
    has a LOW season number, so ease-scaling cannot rescue him. Only summing
    his actual expected points across GW1-3 can.

    The confidence floor is rescaled by each player's own ratio so the risk
    dial keeps meaning the same thing.
    """
    d = _base.copy()
    codes = [int(c) for c in d["code"]]
    run = PROJ.matrix(codes, list(range(int(lo), int(hi) + 1))).sum(axis=1)
    run = d["code"].astype(int).map(run).fillna(0.0).round(2)

    # `solve_draft` optimises `projected_points`, so THAT is the column that has
    # to become the window total · setting only the consensus column leaves the
    # solver quietly maximising a season it is never going to play, which is the
    # exact bug this function exists to fix.
    # float("nan"), not pd.NA · replacing into a float column with pd.NA flips
    # the whole Series to object, and astype(float) then refuses the NAType.
    # Latent until a snapshot refresh first gave somebody a season total of
    # exactly 0, which is what makes the replace fire at all. Same fix and same
    # reason as `value_board.solve_draft`.
    season = pd.to_numeric(d[PTS_COL], errors="coerce").replace(0, float("nan"))
    ratio = (run / season).astype(float).clip(0, 5).fillna(0.0)
    if "proj_lo" in d.columns:
        # The floor keeps its RELATIVE distance from the mean, so the risk dial
        # still means "prefer the safer projection" over the window.
        d["proj_lo"] = (pd.to_numeric(d["proj_lo"], errors="coerce") * ratio).round(2)
    d["projected_points"] = run
    d[PTS_COL] = run
    return d


def solve_opening(spec: Dict) -> Optional[Dict]:
    """Cached wrapper · the solve is in `_solve_opening_uncached`.

    This is a MILP, and it used to run on EVERY app rerun. Clicking a player's
    shirt is an app rerun, so opening the card re-solved the fifteen it had just
    solved. Measured on the real page: 41 SECONDS for that one click, against
    161ms for the identical solve with the CPU free · the gap is this solve
    competing with the eight background ceiling MILPs the page kicks off.

    The spec and the board fully determine the answer, so a rerun that changes
    neither can reuse it.
    """
    return _solve_opening_cached(SR.spec_key(spec), BOARD_STAMP, spec)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=64)
def _solve_opening_cached(key: str, stamp: str, _spec: Dict) -> Optional[Dict]:
    """`key` and `stamp` ARE the cache key · `_spec` is along for the ride.

    Streamlit rebuilds the spec dict from widgets every run, so letting it hash
    the dict would miss on insertion order alone. Hence the underscore: `key`
    (from `SR.spec_key`) already describes the spec exactly, and `stamp`
    re-solves when the board moves under an unchanged spec. This is the one
    sanctioned use of the underscore · a value fully described by an adjacent
    hashed argument.
    """
    del key, stamp
    # Foreground · the ceiling warm steps aside for this. Without the gate, the
    # eight background MILPs turned this solve from 4 seconds into 41.
    from analytics import solver_gate
    with solver_gate.foreground():
        return _solve_opening_uncached(_spec)


def _solve_opening_uncached(spec: Dict) -> Optional[Dict]:
    """The opening fifteen for a draft spec, built the ONE way.

    Both the planner at the top of the page and the side-by-side comparison go
    through here. They used to build squads differently: the planner scored the
    window you actually own the squad for and priced a declared Bench Boost into
    the objective, while the comparison re-solved on a SEASON board with neither.
    The same saved draft therefore showed one fifteen at the top of the page and
    a different one below it, which makes every comparison a lie.

    An explicit saved fifteen wins over all of it · re-solving a team the user
    built by hand compares something they never chose.
    """
    codes = spec.get("squad")
    if codes and len(codes) == 15:
        have = [int(c) for c in codes if int(c) in set(board["code"].astype(int))]
        if len(have) == 15:
            sq = board[board["code"].isin(have)].copy()
            sq = sq.set_index("code").reindex(have).reset_index()
            sq["price"] = sq["actual_price"]
            sq["pts"] = sq[PTS_COL]
            sq["is_captain"] = False
            return {"squad": sq, "explicit": True}

    b = _tuned_board(float(spec.get("minutes_gate", 0.5)))
    win = SR.plan_window(spec.get("wildcard_gw"))
    omap, ow = (), float(spec.get("opening", 0.35))
    if win:
        b = _window_board(b, win[0], win[1], BOARD_STAMP)
    elif spec.get("strategy") == SPRINT_STRATEGY:
        omap, ow = _window_map(*SPRINT_WINDOW), 1.0

    strategy = spec.get("strategy") or "⚖️ Optimal value"
    cap = None if not spec.get("cap_attackers") else 1

    _cover = tuple(tuple(c) for c in (spec.get("cover") or ()))
    # Clubs released from the one-attacker-per-club rule. Falls back to the
    # standing config list so a draft saved before the setting existed still
    # gets Eoin's current rule rather than the old one.
    _uncapped = tuple(int(t) for t in (spec.get("attack_cap_exempt")
                                       or _new_draft_defaults().get("attack_cap_exempt")
                                       or ()))
    _bands = tuple(tuple(b) for b in (spec.get("max_price_band")
                                      or _new_draft_defaults().get("max_price_band")
                                      or ()))
    # None is a MEANING here ("no cap"), not a missing value, so this cannot use
    # `or` the way the tuples above do · a missing key falls back to the config
    # default, and an explicit None stays None.
    _maxdef = (spec["max_defenders_per_club"] if "max_defenders_per_club" in spec
               else _new_draft_defaults().get("max_defenders_per_club", 1))

    def _arm(frame, bench_col):
        return solve_draft(frame, strategy, float(spec.get("budget", 100.0)),
                           float(spec.get("risk", 0.3)),
                           tuple(spec.get("vetoes", [])), ow,
                           force_names=tuple(spec.get("locks", [])),
                           opening_map=omap, max_attackers_per_club=cap,
                           min_club_cover=_cover,
                           attack_cap_exempt=_uncapped, max_price_band=_bands,
                           max_defenders_per_club=_maxdef,
                           bench_pts_col=bench_col)

    def _weekly(frame, gw_cols, boost_col):
        return solve_draft(frame, strategy, float(spec.get("budget", 100.0)),
                           float(spec.get("risk", 0.3)),
                           tuple(spec.get("vetoes", [])), ow,
                           force_names=tuple(spec.get("locks", [])),
                           opening_map=omap, max_attackers_per_club=cap,
                           min_club_cover=_cover,
                           attack_cap_exempt=_uncapped, max_price_band=_bands,
                           max_defenders_per_club=_maxdef,
                           gw_pts_cols=gw_cols, boost_col=boost_col)

    bb = spec.get("bench_boost_gw")
    gws = list(range(win[0], win[1] + 1)) if win else []

    # A weekly eleven, whenever there is a window to field one over.
    #
    # The fixed-lineup solve maximises the sum of fifteen window totals, but
    # only eleven of them score in any week. Two players whose good weeks
    # alternate (8/2/8 and 1/7/1) field 23 over three gameweeks while a flatter
    # pair with far higher totals (5/7/5 and 5/5/7) fields only 19. The old
    # objective preferred the flatter pair every time. It matters most in GW1,
    # where every pick is being asked to deliver on the same afternoon.
    #
    # Fall back rather than fail: this is a bigger MILP, and a squad from the
    # older model beats no squad at all.
    if gws:
        try:
            out = OPLAN.solve_window(b, PROJ, gws, int(bb) if bb else None, _weekly)
            if out:
                return out
        except Exception as exc:   # noqa: BLE001 · never lose the page to the solver
            logger.warning("weekly-lineup solve failed, using the fixed lineup: %s", exc)

    if bb and gws and int(bb) in gws:
        return OPLAN.solve_plan(b, PROJ, gws, int(bb), _arm)
    return _arm(b, None)


SOLVE_BOARD = _tuned_board(minutes_gate)
_omap, _oweight = (), opening


# An early Wildcard changes what "optimal" MEANS. Score the opening squad over
# the weeks you will actually own it, not over a season you are going to tear up.
# The TUNED week, not the saved one · the dial has to move the squad before you
# save, or you are tuning blind.
_wc = wildcard_gw
OPT_WINDOW = SR.plan_window(_wc)
if OPT_WINDOW:
    SOLVE_BOARD = _window_board(SOLVE_BOARD, OPT_WINDOW[0], OPT_WINDOW[1],
                                BOARD_STAMP)
elif mode == SPRINT_STRATEGY:
    _omap, _oweight = _window_map(*SPRINT_WINDOW), 1.0

if OPT_WINDOW:
    st.markdown(_one_line(
        f'<div style="display:flex;align-items:center;gap:8px;font-size:12.5px;'
        f'margin:-2px 0 8px;">{theme.icon("target", 15, V("cyan"))}'
        f'<span style="color:{V("text")};">Built for '
        f'<b>GW{OPT_WINDOW[0]}-{OPT_WINDOW[1]}</b> only, because you wildcard at '
        f'GW{_wc}. <span style="color:{V("muted")};">A player who fades later '
        f'costs you nothing here, so form and nailed minutes in the opening '
        f'weeks are worth more than a season total.</span></span></div>'),
        unsafe_allow_html=True)

_SAVED_SQUAD = None
# A saved fifteen is deliberately frozen · it is the squad you built by hand and
# the dials must not silently rebuild it under you. But a VETO is not a dial. It
# names a specific player and says "never pick this one", and leaving him sitting
# in the squad made the control look broken: you added him to "Do not want" and
# nothing happened at all.
#
# So a veto that lands on the saved fifteen re-solves the WHOLE squad from the
# settings · it does not evict that one player and force the other fourteen back
# in. Banning a £15.5m striker frees £15.5m, and the right answer is almost never
# "the same fourteen plus the best £15.5m replacement". It is a different squad:
# the money goes wherever it buys most, which is what the optimiser is for.
# Preserving fourteen slots would be trading points for familiarity.
_EVICTED: List[str] = []
if DR.has_squad(_spec):
    _codes = [int(c) for c in _spec["squad"] if int(c) in set(board["code"].astype(int))]
    if len(_codes) == 15:
        _veto_codes = set(board[board[NAME_COL].isin(excluded)]["code"].astype(int))
        _bad = [c for c in _codes if c in _veto_codes]
        if _bad:
            _by_code = board.set_index("code")[NAME_COL]
            _EVICTED = [str(_by_code.get(c, c)) for c in _bad]
        else:
            _SAVED_SQUAD = _codes

# The LIVE spec · the dials as they are right now, which is what tuning means.
# It goes through `solve_opening` exactly like a saved draft does in the
# comparison, so the two can never drift apart again.
_LIVE_SPEC = {
    "strategy": mode, "locks": list(locked), "vetoes": list(excluded),
    "budget": float(budget), "risk": float(risk), "opening": float(opening),
    "minutes_gate": float(minutes_gate), "cap_attackers": bool(cap_attackers),
    "bench_boost_gw": boost_gw, "wildcard_gw": wildcard_gw, "squad": None,
    "cover": list(cover),
}

# A declared Bench Boost week enters the OBJECTIVE, not a post-hoc weighting.
# `plan_bench` is what each player is worth in that one week, which is exactly
# what a benched player earns under the chip · zero in every other week. The
# MILP then trades bench quality against XI quality on real points instead of
# the 0.1-of-a-starter fudge, and no bench points TARGET is needed: chasing a
# target is a constraint, and a constraint can only ever build a worse fifteen.
def _solve_arm(frame, bench_col):
    return solve_draft(frame, mode, budget, risk, tuple(excluded), _oweight,
                       force_names=tuple(locked), opening_map=_omap,
                       max_attackers_per_club=None if two_att else 1,
                       min_club_cover=tuple(cover),
                       bench_pts_col=bench_col)


_plan_gws = (list(range(OPT_WINDOW[0], OPT_WINDOW[1] + 1)) if OPT_WINDOW else [])

res = None
if _SAVED_SQUAD is None:
    res = solve_opening(_LIVE_SPEC)
# The eviction is deliberately silent. The squad visibly changes and the vetoed
# player is visibly gone · a banner restating that was noise on every rerun.
if _SAVED_SQUAD is None and res is None:
    why = ""
    if locked:
        lk = board[board[NAME_COL].isin(locked)]
        spend = float(lk["actual_price"].sum())
        over = {p: n for p, n in lk["position"].value_counts().to_dict().items()
                if n > SQUAD_LIMITS.get(p, 15)}
        if over:
            why = (" You locked more players in a position than a squad allows: "
                   + ", ".join(f"{n}x {p}" for p, n in over.items()) + ".")
        elif spend > budget - (15 - len(locked)) * 4.0:
            why = (f" Your locks cost £{spend:.1f}m, leaving under £4.0m a head for "
                   f"the remaining {15 - len(locked)} · that cannot be filled.")

    # No guessing. Relax one rule at a time and report which one actually
    # unblocks it · "likely a club limit" sent a user hunting for money when
    # the real cause was two forced Man Utd midfielders against a
    # one-attacker-per-club rule.
    if not why:
        try:
            from analytics.squad_milp import diagnose_infeasible
            _d = SOLVE_BOARD.rename(
                columns={"actual_price": "price", "projected_points": "pts"})
            _cause = diagnose_infeasible(
                _d, budget=budget, pts_col="pts",
                force_codes=[int(c) for c in
                             board[board[NAME_COL].isin(locked)]["code"]],
                exclude_codes=[int(c) for c in
                               board[board[NAME_COL].isin(excluded)]["code"]],
                max_attackers_per_club=None if two_att else 1)
            if _cause:
                why = " The binding constraint is %s." % _cause
        except Exception:
            logger.exception("infeasibility diagnosis failed")

    st.error("No legal squad fits these settings." + why
             + " Change that one thing rather than the budget.")
    st.stop()

if _SAVED_SQUAD is not None:
    SOLVED = board[board["code"].isin(_SAVED_SQUAD)].copy()
    SOLVED = SOLVED.set_index("code").reindex(_SAVED_SQUAD).reset_index()
    SOLVED["price"] = SOLVED["actual_price"]
    SOLVED["pts"] = SOLVED[PTS_COL]
    SOLVED["is_captain"] = False
else:
    SOLVED = res["squad"]

# ── Say whether this is THE best fifteen or merely a good one ────────────────
# `optimize_squad` already returns `proven_optimal`, and nothing has ever read
# it. When CBC hits its time limit it returns the best squad it found so far
# and the page presented that exactly like a proven optimum · so "is this
# actually the best?" was a question the interface could not answer. It can now.
_PROVEN = bool(res.get("proven_optimal", True)) if isinstance(res, dict) else True
if not _PROVEN:
    st.warning(
        "**This is the best fifteen the solver found, not a proven optimum.** "
        "It ran out of time before it could prove no better squad exists, which "
        "usually means the pool is very large or the constraints are unusual. "
        "Narrowing the pool (raise the minutes gate) or locking one more player "
        "normally gets it to a proven answer.")


# ── Optimise · rebuild a saved fifteen from the dials ────────────────────────
# The freeze at the top of this file is right: a squad you built by hand must not
# silently rebuild under you. But it left no way to ASK for a rebuild short of
# vetoing someone, so the dials looked broken. The button in the tuning panel
# raises `_want_optimise` and this is where it lands, because `solve_opening` and
# `_LIVE_SPEC` only exist by here.
#
# `_LIVE_SPEC["squad"]` is already None, so `solve_opening` re-solves from the
# dials rather than handing the saved fifteen straight back. Nothing about the
# optimiser needed changing · only a way to reach it.
def _optimise_now() -> None:
    from components.loading import LINES_SOLVER, fpl_loader
    try:
        with fpl_loader("Rebuilding all fifteen", LINES_SOLVER):
            out = solve_opening(_LIVE_SPEC)
    except Exception:                        # noqa: BLE001
        logger.exception("optimise solve failed")
        st.session_state["_optimise_error"] = (
            "The solver failed on these settings. Nothing has changed.")
        return
    if not out or out.get("squad") is None or out["squad"].empty:
        # Never open an empty dialog · name the constraint that blocked it, the
        # same way the auto-solve path does.
        why = ""
        try:
            from analytics.squad_milp import diagnose_infeasible
            _d = SOLVE_BOARD.rename(
                columns={"actual_price": "price", "projected_points": "pts"})
            why = diagnose_infeasible(
                _d, budget=budget, pts_col="pts",
                force_codes=[int(c) for c in
                             board[board[NAME_COL].isin(locked)]["code"]],
                exclude_codes=[int(c) for c in
                               board[board[NAME_COL].isin(excluded)]["code"]],
                max_attackers_per_club=None if two_att else 1) or ""
        except Exception:                    # noqa: BLE001
            logger.exception("infeasibility diagnosis failed")
        st.session_state["_optimise_error"] = (
            "No legal fifteen fits these settings."
            + (" The binding constraint is %s." % why if why else ""))
        return
    st.session_state["_optimise_result"] = {
        "codes": [int(c) for c in out["squad"]["code"]],
        "proven": bool(out.get("proven_optimal", True)),
    }


if st.session_state.pop("_want_optimise", False):
    _optimise_now()

if "_optimise_error" in st.session_state:
    st.error(st.session_state.pop("_optimise_error"))


@st.dialog("Optimise squad", width="large")
def _optimise_dialog(proposal: Dict) -> None:
    _after = proposal["codes"]
    _before = _SAVED_SQUAD or [int(c) for c in SOLVED["code"]]
    _price = {int(r["code"]): float(r["actual_price"])
              for _, r in board.iterrows()}
    # `web_name`, not NAME_COL · `uniq_name` carries the picker's disambiguators
    # and renders as "Sangaré (NFO) (Sangare)" in a table that has its own price
    # column to tell two players apart.
    _name = board.set_index("code")["web_name"].to_dict()
    d = SR.squad_diff(_before, _after, _price)

    _win_lbl = ("GW%d-%d" % OPT_WINDOW) if OPT_WINDOW else "the season"
    _chip = (" · Boost GW%d" % boost_gw) if boost_gw else ""
    st.markdown(_one_line(
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:baseline;gap:10px;margin-bottom:10px;">'
        f'<span style="font-size:12px;color:{V("muted")};">{_win_lbl}{_chip}</span>'
        f'<span style="font-size:11px;color:{V("mint") if proposal["proven"] else V("orange")};">'
        + ("Proven optimal" if proposal["proven"]
           else "Best found, not proven optimal")
        + '</span></div>'), unsafe_allow_html=True)

    if not d["out"]:
        st.success("Your fifteen is already the optimal squad for these settings.")
    else:
        _rows = []
        for i in range(max(len(d["out"]), len(d["in"]))):
            _o = d["out"][i] if i < len(d["out"]) else None
            _i = d["in"][i] if i < len(d["in"]) else None
            _rows.append({
                "Out": _name.get(_o, "code %s" % _o) if _o is not None else "",
                "£m out": round(_price.get(_o, 0.0), 1) if _o is not None else None,
                "In": _name.get(_i, "code %s" % _i) if _i is not None else "",
                "£m in": round(_price.get(_i, 0.0), 1) if _i is not None else None,
            })
        st.dataframe(pd.DataFrame(_rows), hide_index=True,
                     use_container_width=True)

    # A saved code the board no longer carries is named, never quietly dropped.
    if d["unpriced"]:
        st.warning("Not on the current board, so priced at nothing: "
                   + ", ".join(str(_name.get(c, c)) for c in d["unpriced"]))

    _sq_after = board[board["code"].isin(_after)].copy()
    _sq_before = board[board["code"].isin(_before)].copy()
    if _plan_gws:
        _pts_a = OPLAN.plan_total(_sq_after, PROJ, _plan_gws, boost_gw)
        _pts_b = OPLAN.plan_total(_sq_before, PROJ, _plan_gws, boost_gw)
        _delta = _pts_a - _pts_b
        st.markdown(_one_line(
            f'<div style="display:flex;gap:22px;font-size:12.5px;margin-top:6px;">'
            f'<span style="color:{V("muted")};">Spend '
            f'<b style="color:{V("text")};">£{d["spend_before"]:.1f}m → '
            f'£{d["spend_after"]:.1f}m</b></span>'
            f'<span style="color:{V("muted")};">{_win_lbl} '
            f'<b style="color:{V("text")};">{_pts_b:.1f} → {_pts_a:.1f}</b></span>'
            f'<span style="color:{V("mint") if _delta >= 0 else V("red")};">'
            f'<b>{_delta:+.1f}</b></span></div>'), unsafe_allow_html=True)

    _c1, _c2 = st.columns(2)
    with _c1:
        if st.button("Use this fifteen", type="primary",
                     use_container_width=True, key="opt_accept",
                     disabled=not d["out"]):
            DR.save_draft(_spec["name"], dict(_LIVE_SPEC, squad=_after),
                          draft_id=_spec["id"],
                          allow_clear=("bench_boost_gw", "wildcard_gw"))
            st.session_state.pop("_optimise_result", None)
            _reset_draft_state()
            st.toast("Optimised fifteen saved to %s" % _spec["name"], icon="✨")
            st.rerun()
    with _c2:
        if st.button("Keep mine", use_container_width=True, key="opt_reject"):
            st.session_state.pop("_optimise_result", None)
            st.rerun()


# The dialog is OPENED further down, after `_reset_draft_state` exists · it
# clears pending swaps, and swaps queued against the old fifteen mean nothing
# once the squad underneath them has been replaced.


# ── Which week to Boost · solve every option and rank them ───────────────────
# With a Wildcard at GW4 the opening plan is a small, closed question: Boost in
# GW1, GW2, GW3, or not at all. Four candidates. Each one gets its OWN optimal
# fifteen, because the best squad for a GW1 Boost is not the best squad for a
# GW2 one, and each is then scored the same honest way over the window. Nothing
# after the Wildcard counts, because that squad is torn up.
@st.cache_data(ttl=3600, show_spinner=False)
def _search_boost_week(spec_json: str, cands: tuple, stamp: str) -> Dict:
    import json as _json
    spec = _json.loads(spec_json)
    gws = list(range(1, int(spec["wildcard_gw"])))

    def _arm(frame, bench_col):
        return solve_draft(frame, spec.get("strategy") or "⚖️ Optimal value",
                           float(spec["budget"]), float(spec["risk"]),
                           tuple(spec["vetoes"]), float(spec["opening"]),
                           force_names=tuple(spec["locks"]), opening_map=(),
                           max_attackers_per_club=(None if not spec["cap_attackers"]
                                                   else 1),
                           max_defenders_per_club=spec.get(
                               "max_defenders_per_club",
                               _new_draft_defaults().get("max_defenders_per_club", 1)),
                           bench_pts_col=bench_col)

    base = _window_board(_tuned_board(float(spec["minutes_gate"])),
                         1, gws[-1], stamp)
    out = OPLAN.best_boost_week(base, PROJ, gws, _arm, candidates=list(cands))
    # The squads are DataFrames and do not survive the cache usefully · the
    # ranking and the weekly totals are what the page draws.
    return {"boost_gw": out.get("boost_gw"),
            "ranked": [{k: v for k, v in r.items() if k != "squad"}
                       for r in out.get("ranked", [])]}


# Shown even when the draft carries a hand-saved fifteen · "which week should I
# Boost" is still the question, and the honest answer needs the squad rebuilt
# for each option. It never overwrites the saved team; it only tells you what
# the settings above would produce.
if wildcard_gw and int(wildcard_gw) > 1:
    import json as _json_mod
    _cands = tuple(range(1, int(wildcard_gw)))
    _spec_key = _json_mod.dumps(_LIVE_SPEC, sort_keys=True, default=str)

    _r1, _r2 = st.columns([2, 5])
    with _r1:
        _find = st.button(":material/auto_awesome: Best Boost week",
                          use_container_width=True, key="findbb",
                          help="Builds a separate optimal fifteen for every "
                               "Boost week and for no Boost at all, then scores "
                               "each over GW1-%d and ranks them." % _cands[-1])
    with _r2:
        st.markdown(_one_line(
            f'<div style="font-size:11.5px;color:{V("muted")};padding-top:8px;">'
            f'Tries no Boost and GW{_cands[0]} to GW{_cands[-1]}, a full solve '
            f'each, on the settings above. The squad is rebuilt for every '
            f'option · the best fifteen for a GW1 Boost is not the best fifteen '
            f'for a GW2 one.'
            + ('<br><b>Your saved fifteen is not touched</b> · this solves from '
               'the settings, so treat it as a second opinion.'
               if _SAVED_SQUAD is not None else '')
            + '</div>'), unsafe_allow_html=True)

    if _find:
        with st.spinner("Solving every opening plan…"):
            st.session_state["bb_search"] = _search_boost_week(
                _spec_key, _cands, BOARD_STAMP)
            st.session_state["bb_search_key"] = _spec_key

    _found = st.session_state.get("bb_search")
    _stale = st.session_state.get("bb_search_key") != _spec_key
    if _found and _found.get("ranked"):
        _lbl = (lambda g: "No Boost" if g is None else "Boost GW%d" % g)
        _rk = _found["ranked"]
        _win = _rk[0]
        _gap = (_win["total"] - _rk[1]["total"]) if len(_rk) > 1 else 0.0
        _call = ("a clear call" if _gap >= 4.0 else
                 "a slight lean" if _gap >= 1.0 else "a coin flip")
        st.markdown(_one_line(
            f'<div style="{CARD}border-left:3px solid '
            f'{V("orange") if _stale else V("mint")};padding:11px 14px;'
            f'margin:8px 0 6px;font-size:13px;color:{V("text")};'
            f'line-height:1.6;">'
            + ("<b>Settings have changed since this ran.</b> " if _stale else "")
            + f'<b>{_lbl(_win["boost_gw"])}</b> wins over '
              f'GW1-{_cands[-1]} with <b>{_win["total"]:.1f}</b> points'
            + (f', {_gap:+.1f} on the next best · <b>{_call}</b>.'
               if len(_rk) > 1 else '.')
            + (f' The chip is worth <b>{_win["boost_gain"]:.1f}</b> in the week '
               f'it is played.' if _win["boost_gw"] else '')
            + '</div>'), unsafe_allow_html=True)

        _rows = []
        for r in _rk:
            row = {"plan": _lbl(r["boost_gw"]), "total": r["total"],
                   "chip": r["boost_gain"] if r["boost_gw"] else 0.0}
            for w in r["per_week"]:
                row["gw%d" % w["gw"]] = w["total"]
            _rows.append(row)
        _bcols = [T.col_text("plan", "Plan"),
                  T.col_num("total", "GW1-%d" % _cands[-1], fmt="%.1f")]
        for _g in _cands:
            _bcols.append(T.col_num("gw%d" % _g, "GW%d" % _g, fmt="%.1f"))
        _bcols.append(T.col_num("chip", "Chip worth", fmt="%.1f"))
        T.render(_rows, _bcols, key="bbsearch", max_height=230)

        if st.button(":material/check: Use %s" % _lbl(_win["boost_gw"]),
                     key="usebb", disabled=_win["boost_gw"] == boost_gw,
                     help="Sets the Bench Boost week to the winner. Everything "
                          "below rebuilds around it."):
            st.session_state["_want_bb"] = _win["boost_gw"]
            st.rerun()

if locked and res is not None:
    # What the conviction actually costs · the same solve without the locks. This
    # is the whole Fernandes question: owning him is only wrong if spreading his
    # money returns more.
    # Solved the SAME way as the locked squad · comparing a bench-aware squad
    # against a bench-blind one would price the chip, not the conviction.
    # Solve the unlocked squad through the SAME entry point, so it gets the same
    # weekly-lineup treatment, the same board and the same rules. Building it a
    # different way handicaps it and prices the method, not the conviction.
    free = solve_opening(dict(_LIVE_SPEC, locks=[]))

    lk = board[board[NAME_COL].isin(locked)]
    spend = float(lk["actual_price"].sum())

    # ── Score BOTH squads with one metric, computed here ─────────────────────
    # This used to read `res["xi_points"] - free["xi_points"]` whenever either
    # result lacked `plan_total` · and `solve_window`, the weekly-lineup path
    # that now produces most squads, does not set it. Those two keys do not mean
    # the same thing: the weekly solver's `xi_points` is GW1's eleven ALONE,
    # while a fixed-lineup solve on a windowed board reports the eleven's total
    # over the WHOLE window. Subtracting a one-week number from a three-week one
    # reported locking Haaland at "about 116 points", which is most of the
    # window's entire score and was never a real figure.
    #
    # `plan_total` re-scores a finished squad over the plan · same fifteen, same
    # gameweeks, same chip, best eleven each week. It does not care how either
    # squad was solved, which is exactly the property this comparison needs.
    def _plan_score(r):
        if not r or "squad" not in r:
            return None
        if _plan_gws:
            return float(OPLAN.plan_total(r["squad"], PROJ, _plan_gws,
                                          int(boost_gw) if boost_gw else None))
        return float(r.get("plan_total", r.get("xi_points", 0.0)))

    _mine, _theirs = _plan_score(res), _plan_score(free)
    cost = None if (_mine is None or _theirs is None) else (_mine - _theirs)
    _tok = ("mint" if (cost is None or cost > CONVICTION_FREE)
            else "orange" if cost > CONVICTION_REAL else "red")
    # Say what it MEANS, not what it measures. "-36 XI pts vs the free optimum ·
    # an expensive conviction" is a description of an arithmetic operation; the
    # reader wants to know whether insisting on these players is costing them.
    _names = ", ".join(locked)
    _pts = (lambda n: "%.1f point%s" % (abs(n), "" if abs(n) == 1 else "s"))
    # Name the horizon. "116 points" with no window attached reads like a season
    # number, and a three-gameweek total only runs to about 190 in the first
    # place · a cost has to be quotable against the thing it is a share of.
    _horizon = ("over GW%d-%d" % (_plan_gws[0], _plan_gws[-1])
                if _plan_gws else "on this week's eleven")
    if cost is None:
        _line = f"You have insisted on {_names}."
    elif cost >= 0:
        _line = (f"Insisting on {_names} costs you nothing {_horizon} · the "
                 f"optimiser would pick them anyway. Keep them.")
    elif cost > CONVICTION_FREE:
        _line = (f"Insisting on {_names} costs about {_pts(cost)} {_horizon}, "
                 f"out of roughly {_theirs:.0f}. That is noise · keep them.")
    elif cost > CONVICTION_REAL:
        _line = (f"Insisting on {_names} costs about {_pts(cost)} {_horizon}, "
                 f"out of roughly {_theirs:.0f}. Worth it if you believe in "
                 f"them more than the model does.")
    else:
        _line = (f"Insisting on {_names} costs about {_pts(cost)} {_horizon}, "
                 f"out of roughly {_theirs:.0f}. That is a real price · the "
                 f"money would do more spread around.")
    st.markdown(_one_line(
        f'<div style="display:flex;align-items:flex-start;gap:8px;'
        f'font-size:12.5px;margin:-4px 0 8px;">'
        f'{theme.icon("lock", 15, V(_tok))}'
        f'<span style="color:{V("text")};">{_line} '
        f'<span style="color:{V("muted")};">They take £{spend:.1f}m of your '
        f'£{budget:.0f}m, leaving £{budget - spend:.1f}m for the other '
        f'{15 - len(locked)} players.</span></span></div>'),
        unsafe_allow_html=True)

def _reset_draft_state(**overrides) -> None:
    """Clear this draft's working state. Other drafts keep theirs."""
    for _name, _make in _DRAFT_STATE_DEFAULTS.items():
        if _name in overrides:
            st.session_state[_sk(_name)] = overrides[_name]
        elif _name != "draft_gw":       # the viewed week survives a squad reset
            st.session_state[_sk(_name)] = _make()


# Open the optimise confirmation here, not where it is defined · accepting calls
# `_reset_draft_state`, which only exists from this point on.
if "_optimise_result" in st.session_state:
    _optimise_dialog(st.session_state["_optimise_result"])


def _squad_from_codes(codes: List[int]) -> pd.DataFrame:
    rows = board[board["code"].isin(codes)].copy()
    rows = rows.set_index("code").reindex(codes).reset_index()
    rows["price"] = rows["actual_price"]
    rows["pts"] = rows[PTS_COL]
    return rows


def _current_squad(gw: Optional[int] = None) -> pd.DataFrame:
    """The solved fifteen with every transfer made UP TO this gameweek applied.

    Transfers are keyed by the gameweek they happen in, so stepping back through
    the weeks shows the squad as it was, not as it ends up.
    """
    if gw is None:
        gw = int(st.session_state.get(_sk("draft_gw"), 1))
    codes = [int(c) for c in SOLVED["code"]]
    for g in sorted(int(k) for k in st.session_state[_sk("draft_swaps")]):
        if g > int(gw):
            break
        for out, inn in st.session_state[_sk("draft_swaps")][g].items():
            if int(out) in codes:
                codes[codes.index(int(out))] = int(inn)
    return _squad_from_codes(codes)


# ── The weekly ceiling, warmed before you ask for it ─────────────────────────
# Every gameweek's ceiling is its own MILP, about 650 ms, and it was solved the
# first time you STEPPED to that week. So the gameweek stepper · the control you
# press most on this page · paid for a solver run on every new week, and the
# pitch sat there while it ran.
#
# Two changes. The results now live in a process-level memo rather than only in
# Streamlit's cache, so a background thread can fill it; and a daemon thread
# fills the opening window at import, the same shape as `model_store.prewarm_async`.
# By the time a human has read the page the weeks they are about to step through
# are already solved. Nothing regresses if the thread is slow or dies: a miss
# still computes synchronously, exactly as before.
# `@st.cache_resource` because a page script is re-executed top to bottom on
# EVERY rerun · a plain module-level dict here was silently recreated each time,
# so the background solver kept writing into a dict nobody would ever read again
# and the ceiling never appeared. cache_resource hands back the same object for
# the life of the process, which is the only place a cross-rerun memo can live.
@st.cache_resource(show_spinner=False)
def _ceiling_store() -> Dict:
    return {"done": {}, "running": set(), "warmed": False}


_CEILING_STORE = _ceiling_store()
_CEILING: Dict = _CEILING_STORE["done"]
_CEILING_RUNNING: set = _CEILING_STORE["running"]
# The weeks a draft is actually stepped through. Warming all 38 would spend
# 25 seconds of CPU on gameweeks nobody opens before wildcarding.
WARM_GWS = 8


def _perfect_week_uncached(gw: int, budget: float) -> float:
    from analytics.squad_milp import optimize_squad
    d = board.rename(columns={"actual_price": "price"}).copy()
    d["pts"] = [round(PROJ.points(int(c), int(gw)), 2) for c in d["code"]]
    # bench_weight 0 · a Free Hit bench scores nothing, and letting it count
    # would raise the ceiling with points nobody can actually take.
    res = optimize_squad(d, budget=float(budget), pts_col="pts",
                         bench_weight=0.0, time_limit=25)
    return float(res["xi_points"]) if res else 0.0


def _ceiling_now(gw: int, budget: float, stamp: str):
    """This week's ceiling IF it is already solved, else None · never blocks.

    The ceiling is a MILP per gameweek and it was on the interaction path: a
    measured 5.0 of the 5.4 seconds a gameweek step took was spent right here,
    with the pitch not yet drawn. Nobody is waiting to read a percentage · they
    are waiting to see the team.

    So this returns whatever is known now and starts the solve in the background
    if it is not. The pitch draws immediately with a placeholder in the score
    slot, and `_ceiling_watcher` swaps the real number in when it lands.
    """
    key = (int(gw), round(float(budget), 1), str(stamp))
    if key in _CEILING:
        return _CEILING[key]
    if key not in _CEILING_RUNNING:
        _CEILING_RUNNING.add(key)

        def _run():
            from analytics import solver_gate
            try:
                with solver_gate.background():
                    _CEILING[key] = _perfect_week_uncached(int(gw), float(budget))
            except Exception:  # noqa: BLE001 · a benchmark must never break a page
                logger.warning("ceiling solve failed for GW%d", gw)
                _CEILING[key] = 0.0
            finally:
                _CEILING_RUNNING.discard(key)

        threading.Thread(target=_run, name="ff-ceiling-%d" % gw,
                         daemon=True).start()
    return None


def _perfect_week(gw: int, budget: float, stamp: str) -> float:
    """The most any legal £100m squad could score in this one gameweek.

    A Free Hit with perfect foresight, in other words: build a fresh fifteen
    knowing only this week's projections, play the best eleven, captain the
    best of them. It is the ceiling a real squad is measured against, and it
    moves week to week with the fixtures · which is the point. 60 points in a
    week where the ceiling is 70 is a good squad; 60 where the ceiling is 110
    means you own the wrong players for those fixtures.
    """
    key = (int(gw), round(float(budget), 1), str(stamp))
    if key not in _CEILING:
        _CEILING[key] = _perfect_week_uncached(int(gw), float(budget))
    return _CEILING[key]


def _warm_ceilings_async(budget: float, stamp: str) -> None:
    """Solve the opening weeks' ceilings in the background, once per process."""
    if _CEILING_STORE.get("warmed"):
        return
    _CEILING_STORE["warmed"] = True

    def _run():
        from analytics import solver_gate
        for g in range(1, min(int(MAX_GW), WARM_GWS) + 1):
            key = (int(g), round(float(budget), 1), str(stamp))
            if key in _CEILING:
                continue
            try:
                # Gated per week, not once for the whole loop · a solve that
                # starts while the page is idle must still yield before the
                # next one if a human has begun waiting in the meantime.
                with solver_gate.background():
                    _CEILING[key] = _perfect_week_uncached(g, budget)
            except Exception:  # noqa: BLE001 · a warm-up must never break a page
                logger.warning("ceiling warm failed for GW%d", g)
                return

    threading.Thread(target=_run, name="ff-ceiling-warm", daemon=True).start()

# Kick the weekly-ceiling warm as soon as the board and the budget are known.
# Daemon thread, once per process, best-effort · see `_warm_ceilings_async`.
_warm_ceilings_async(float(budget), BOARD_STAMP)


def _transfer_ledger(upto_gw: int) -> Dict:
    """This draft's free transfers and hits. Rules live in analytics.

    The drafted fifteen is passed in so moves count NET: sell Virgil for
    Gabriel, change your mind and buy Virgil back, and you have made no
    transfer and spent nothing.
    """
    from analytics.squad_planner import FT_CAP
    return SR.transfer_ledger(st.session_state[_sk("draft_swaps")],
                              upto_gw, ft_cap=FT_CAP,
                              start_codes=[int(c) for c in SOLVED["code"]],
                              wildcard_gw=wildcard_gw)


# ── Player evidence ───────────────────────────────────────────────────────────
# `_profile` is defined further down as a one-line wrapper around
# `ui.player_card.profile`, once `CARD_CTX` exists · kept as the page's public
# alias by controller ruling (Task 5, ruling 2).
def _profile_window(code: int, from_gw: int, horizon: int) -> Dict:
    """A profile scored over the window being planned, not over a season."""
    from analytics.head_to_head import player_profile
    row = board[board["code"] == int(code)]
    if row.empty:
        return {}
    return player_profile(row.iloc[0], PTS_COL, DEFCON, PROJ,
                          from_gw=int(from_gw), horizon=int(horizon))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _points_cuts(horizon: int, stamp: str = "") -> Dict:
    """Per-position red/amber/green cut points, fitted to this board.

    Derived rather than hardcoded so the colours stay meaningful as prices and
    projections move, and computed once because the comparison redraws often.
    """
    from analytics import grading
    gws = list(range(1, max(2, int(horizon)) + 1))
    return grading.points_cuts(grading.sample_from_projection(board, PROJ, gws))


def _run_chips(fixtures: List[Dict]) -> str:
    """A fixture run as FDR-coloured chips."""
    if not fixtures:
        return f'<span style="color:{V("muted2")};font-size:11px;">no fixtures</span>'
    out = []
    for fx in fixtures:
        if fx.get("blank"):
            out.append('<span style="background:rgba(128,128,128,0.5);color:var(--ff-text);'
                       'border-radius:4px;padding:2px 6px;font-size:10px;'
                       'font-weight:800;">BLK</span>')
            continue
        c = theme.FDR_COLORS.get(int(round(float(fx.get("fdr", 3) or 3))), "#FFD60A")
        side = "(H)" if fx.get("home") else "(A)"
        out.append(f'<span style="background:{c};color:#000;border-radius:4px;'
                   f'padding:2px 6px;font-size:10px;font-weight:800;">'
                   f'{fx.get("opp", "?")}{side}</span>')
    return ('<div style="display:flex;gap:4px;flex-wrap:wrap;">'
            + "".join(out) + '</div>')


def _week_bars(prof: Dict, cuts: Dict) -> str:
    """Per-gameweek projected points as bars, coloured by how good the score
    actually is FOR THAT POSITION.

    A flat cut looks decisive and is quietly wrong: keepers cluster (sd 0.65)
    while forwards spread (sd 1.82), so 4.5 is an ordinary week for a forward
    and an excellent one for a keeper.
    """
    from analytics import grading
    weeks = prof.get("weeks") or []
    if not weeks:
        return f'<div style="{CARD}padding:11px;color:{V("muted2")};">No forecast.</div>'
    top = max(max(weeks), 1.0) * 1.12
    rows = []
    from analytics.gw_projection import SRC_MANUAL
    for i, v in enumerate(weeks):
        gw = prof["gw_from"] + i
        band = grading.band_of(v, prof["position"], cuts)
        col = V(grading.BAND_TOKENS[band])
        pct = max(2.0, min(100.0, v / top * 100))
        # A week you set by hand is not a forecast and must never be read as
        # one · Foden's GW2 and GW3 are a minutes call, not the match model.
        _hand = (prof.get("code") is not None
                 and PROJ.source(int(prof["code"]), gw) == SRC_MANUAL)
        rows.append(
            f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;">'
            f'<span style="font-size:9.5px;font-weight:700;color:{V("muted2")};'
            f'width:30px;flex-shrink:0;">GW{gw}</span>'
            f'<div style="flex:1;height:14px;background:{V("chip-bg")};'
            f'border-radius:4px;overflow:hidden;">'
            f'<div style="width:{pct:.0f}%;height:100%;background:{col};'
            f'opacity:0.82;border-radius:4px;"></div></div>'
            + (f'<span title="Set by hand, not modelled" style="font-size:10px;'
               f'color:{V("gold")};flex-shrink:0;">✎</span>' if _hand else "")
            + f'<span class="ff-display" style="font-size:12px;font-weight:800;'
            f'color:{col};width:32px;text-align:right;flex-shrink:0;">'
            f'{v:.1f}</span></div>')
    return (f'<div style="{CARD}padding:11px 12px;">'
            f'<div style="font-size:11px;font-weight:700;color:{V("text")};'
            f'margin-bottom:6px;">{prof["name"]}</div>' + "".join(rows) + '</div>')


def _push_axe(code: int) -> None:
    _cur = list(st.session_state[_sk("draft_axe")])
    if int(code) not in _cur:
        _cur.append(int(code))
    st.session_state[_sk("draft_axe")] = _cur
    st.rerun()


def _push_compare(code: int) -> None:
    row = board[board["code"] == int(code)]
    if row.empty:
        return
    cur = list(st.session_state.get("cmp_players", []))
    name = str(row.iloc[0]["web_name"])
    if name not in cur:
        st.session_state["cmp_players"] = (cur + [name])[-3:]
    st.session_state["cmp_pick"] = st.session_state["cmp_players"]
    st.rerun()


CARD_CTX = PC.CardCtx(
    board=board, proj=PROJ, pts_col=PTS_COL, fix=_FIX, defcon=DEFCON,
    scout=scout, board_stamp=BOARD_STAMP,
    on_replace=_push_axe, on_compare=_push_compare,
    in_squad=lambda code: int(code) in set(_current_squad()["code"].astype(int)))


def _profile(code: int) -> Dict:
    return PC.profile(CARD_CTX, code)


def _player_dialog(code: int) -> None:
    # Refreshed live, immediately before each open · `CARD_CTX` itself is built
    # once at module scope, but the viewed gameweek is fragment-scoped session
    # state, so baking it into CARD_CTX at construction time would go stale on
    # a fragment-only rerun (CLAUDE.md rule 5). Assigning it here reads the
    # current value at call time regardless of when CARD_CTX was built.
    CARD_CTX.current_gw = int(st.session_state.get(_sk("draft_gw"), 1))
    PC.open_player_card(CARD_CTX, code)


_dc_hit = lambda code, pos: PC.dc_hit(CARD_CTX, code, pos)
_setpiece_glyphs, _conf_color, _set_piece_line = (
    PC.setpiece_glyphs, PC.conf_color, PC.set_piece_line)


# ── Table columns ─────────────────────────────────────────────────────────────
def _bar_max(rows, key: str, floor_key: str) -> float:
    """Bar scale from the data on screen, never a literal.

    The maxima were hardcoded at 190 / 32 / 110 and drift every time prices or
    projections move · a bar pinned to a stale ceiling stops meaning anything.
    The floor stops a sparse table rendering one full-width bar and calling it
    a comparison.
    """
    vals = [float(r.get(key) or 0.0) for r in rows] if rows else []
    return max(max(vals) * 1.05 if vals else 0.0,
               float(DRAFT_BAR_FLOORS.get(floor_key, 1.0)))


def _pool_cols(gw: int, with_delta: bool = False,
               rows: Optional[List[Dict]] = None) -> List[Dict]:
    cols = [
        T.col_face("code", url_fn=player_photo_url),
        T.col_player("web_name", "Player", sub="team_short", action="inspect"),
        T.col_chip("position", "Pos", color_fn=theme.pos_color),
        T.col_num("actual_price", "£m", fmt="%.1f"),
    ]
    if with_delta:
        cols.append(T.col_num(
            "d_price", "Δ£m", fmt="%+.1f",
            color_fn=lambda v: theme.fill("mint") if v <= 0 else theme.fill("red")))
    cols += [
        T.col_run("run", f"GW{gw}-{gw + 2}"),
        T.col_num("gw_pts", f"GW{gw}", fmt="%.1f"),
        # The match model has no row for 148 players. A bare dot there reads as
        # a rendering bug rather than the real answer, which is that nobody has
        # forecast his minutes.
        T.col_num("mins", "Mins", fmt="%.0f", empty="no forecast",
                  color_fn=lambda v: theme.fill("red") if v < 45 else None),
        # A threshold stat, so show how often it converts and grade it against
        # the bar rather than printing a mean nobody can price.
        T.col_num("dc_hit", "DEFCON", fmt="%.0f%%", empty="-",
                  color_fn=lambda v: theme.fill("mint") if v >= 50
                  else theme.fill("gold") if v >= 30 else theme.fill("muted2")),
        T.col_html("setp", ""),
        T.col_bar("season", "Season",
                  max_value=_bar_max(rows, "season", "season")),
        T.col_num("per_m", "Per £m", fmt="%.1f"),
        T.col_num("spread", "±", fmt="%.0f%%", empty="-",
                  color_fn=lambda v: theme.fill("mint") if v <= 12
                  else theme.fill("gold") if v <= 25 else theme.fill("red")),
        T.col_chip("confidence", "Conf.", color_fn=_conf_color),
    ]
    if with_delta:
        cols.append(T.col_action("code", "swap", "Swap in"))
    return cols


def _pool_rows(frame: pd.DataFrame, gw: int,
               out_row: Optional[pd.Series] = None) -> List[Dict]:
    rows = []
    for _, a in frame.iterrows():
        code = int(a["code"])
        price = float(a["actual_price"])
        season = float(a.get(PTS_COL) or 0)
        rows.append({
            "code": code, "web_name": a["web_name"],
            "team_short": a.get("team_short", ""), "position": a["position"],
            "actual_price": price,
            "d_price": price - float(out_row.get("actual_price") or 0) if out_row is not None else 0,
            "run": _fixtures_for(int(a.get("team_id", 0) or 0), gw, 3),
            "gw_pts": PROJ.points(code, gw),
            "mins": PROJ.expected_minutes(code, gw),
            "season": season,
            "per_m": season / price if price else 0,
            "confidence": a.get("consensus_confidence", a.get("confidence", "")),
            # How far the three models are apart, where the decision is made
            # rather than three tabs away. A point estimate the models fight
            # over is the one worth a second look.
            "spread": (round(float(a["model_spread"]) * 100, 0)
                       if pd.notna(a.get("model_spread")) else None),
            # DEFCON pays at a THRESHOLD, so the hit rate is what converts.
            # A mean of 9.9 and a mean of 9.9 can be worth very different
            # points depending on how often the player actually clears 10.
            "dc_hit": _dc_hit(code, str(a["position"])),
            "setp": _setpiece_glyphs(a),
        })
    return rows


# ── The planner ───────────────────────────────────────────────────────────────
def _xi_for(sq: pd.DataFrame, gw: int) -> set:
    """Best XI for this gameweek, honouring forced benchings.

    A forced bench that would break the formation is ignored rather than
    silently producing an illegal side.
    """
    from analytics.gw_projection import best_xi
    pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
    manual = st.session_state[_sk("xi_override")].get(int(gw))
    if manual:
        manual = {int(c) for c in manual if int(c) in pos_by}
        if SR.is_legal_xi(manual, pos_by):
            return manual
    forced = set(st.session_state[_sk("draft_bench")])
    pool = sq[~sq["code"].astype(int).isin(forced)]
    counts = pool["position"].value_counts().to_dict()
    if forced and len(pool) >= 11 and all(counts.get(p, 0) >= n
                                          for p, n in XI_MINIMUMS.items()):
        xi = best_xi(pool, PROJ, gw)
        if len(xi) == 11:
            return xi
    return best_xi(sq, PROJ, gw)


def _candidates(sq: pd.DataFrame, out_code: int, bank: float) -> pd.DataFrame:
    """Who you could actually have instead · affordable, legal, best first."""
    row = board[board["code"] == out_code]
    if row.empty:
        return pd.DataFrame()
    row = row.iloc[0]
    ceiling = float(row.get("actual_price") or 0) + bank
    clubs = sq[sq["code"] != out_code]["team_id"].value_counts().to_dict()
    alt = board[(board["position"] == str(row["position"]))
                & (board["actual_price"] <= ceiling)
                & (~board["code"].isin(sq["code"]))].copy()
    # A swap that breaks the 3-per-club limit is not actually available.
    return alt[alt["team_id"].map(lambda t: clubs.get(t, 0)) < 3]


def _candidates_multi(sq: pd.DataFrame, out_codes: List[int], budget: float,
                      positions: List[str]) -> pd.DataFrame:
    """Replacements for SEVERAL marked players at once.

    Everyone in the requested positions who is not already in the squad and
    would not break the 3-per-club limit. Affordability is judged per row
    afterwards rather than filtered here, because a player you cannot afford is
    worth seeing greyed out · it tells you what freeing more money would buy.
    """
    outs = {int(c) for c in out_codes}
    keep = sq[~sq["code"].isin(outs)]
    clubs = keep["team_id"].value_counts().to_dict()
    alt = board[(board["position"].isin(list(positions)))
                & (~board["code"].isin(keep["code"]))
                & (~board["code"].isin(outs))].copy()
    return alt[alt["team_id"].map(lambda t: clubs.get(t, 0)) < 3]


# A one-second heartbeat that exists only to notice the ceiling arriving.
# It draws nothing · a fragment cannot rerun its parent, so when the number
# lands it asks for a single app rerun and then gets out of the way. The team is
# already on screen throughout; this only swaps a placeholder for a percentage.
#
# TWO guards, and both are load-bearing. A `run_every` fragment keeps executing
# with the arguments it was CREATED with, so stepping through gameweeks leaves a
# trail of live watchers still asking about weeks you have left · measured, that
# was five extra app reruns of 1-2.5s each after a single step. So a watcher
# stands down if it is no longer about the week on screen, and fires at most one
# rerun per (week, budget, board) whatever happens.
@st.fragment(run_every="1s")
def _ceiling_watcher(gw: int, budget: float, stamp: str) -> None:
    if int(st.session_state.get(_sk("draft_gw"), gw)) != int(gw):
        return
    seen = "_ceil_shown_%d_%s_%s" % (int(gw), round(float(budget), 1), stamp)
    if st.session_state.get(seen):
        return
    if _ceiling_now(gw, budget, stamp) is not None:
        st.session_state[seen] = True
        st.rerun()


@st.fragment
def planner() -> None:
    gw = int(st.session_state[_sk("draft_gw")])
    sq = _current_squad(gw)
    axed = [int(c) for c in st.session_state[_sk("draft_axe")]]
    ledger = _transfer_ledger(gw)

    # ── Gameweek stepper ─────────────────────────────────────────────────────
    # The Compact toggle needs room for a switch, a label and a help icon · at
    # 2/13 of the row it broke "Compact" into "Com" / "pact".
    nav = st.columns([1, 1, 3, 3, 3, 2])
    with nav[0]:
        if st.button("◀", use_container_width=True, disabled=gw <= 1,
                     help="Previous gameweek"):
            st.session_state[_sk("draft_gw")] = max(1, gw - 1)
            st.rerun(scope="fragment")
    with nav[1]:
        if st.button("▶", use_container_width=True, disabled=gw >= MAX_GW,
                     help="Next gameweek"):
            st.session_state[_sk("draft_gw")] = min(MAX_GW, gw + 1)
            st.rerun(scope="fragment")
    with nav[2]:
        st.markdown(_one_line(
            f'<div class="ff-display" style="font-size:20px;font-weight:900;'
            f'color:{V("text")};line-height:38px;white-space:nowrap;">GW {gw}'
            f'<span style="font-size:11px;font-weight:600;color:{V("muted2")};'
            f'margin-left:6px;">of {MAX_GW}</span></div>'), unsafe_allow_html=True)
    with nav[3]:
        # Set the Bench Boost on the week you are looking at, and press again to
        # take it off. Whatever it is left as is what the draft saves, so the
        # chip is planned where you can see its effect rather than in a menu.
        _bb_set = _effective_boost_gw()
        _bb_here = _bb_set is not None and int(_bb_set) == int(gw)
        _bb_label = (f":material/bolt: Boost on GW{gw}" if _bb_here
                     else f":material/bolt: 3 · Boost GW{gw}")
        if st.button(_bb_label, use_container_width=True,
                     type="primary" if _bb_here else "secondary",
                     key=f"bb_{_DRAFT_ID}_{gw}",
                     help=("Playing the Bench Boost this week · press again to "
                           "take it off." if _bb_here else
                           f"Play the Bench Boost in GW{gw}. All fifteen score, "
                           f"so the squad total jumps by whatever the bench is "
                           f"worth that week.")):
            _new_bb = None if _bb_here else int(gw)
            st.session_state[_sk("bb_override")] = _new_bb
            # The Tune panel's selectbox is the SAME fact and owns its own key,
            # which cannot be written to now that the widget exists. Stash it
            # and let the panel apply it before it builds the box next run,
            # otherwise the panel's stale value overwrites this on the rerun.
            st.session_state["_want_bb"] = _new_bb
            _spec["bench_boost_gw"] = _new_bb
            # Deliberately NOT written to disk here. The chip week is a tuning
            # dial like every other one now, and one rule beats two: nothing is
            # saved until you press Save. This button used to write straight
            # through, so a chip you were only trying out was already committed
            # while the dials next to it still said "unsaved changes".
            st.rerun()
    with nav[4]:
        compact = st.toggle("Compact", value=True, key="pitch_compact",
                            help="Shrinks the shirts so the fifteen and the bench "
                                 "fit a laptop screen without scrolling.")
    with nav[5]:
        if st.session_state[_sk("draft_swaps")] or st.session_state[_sk("draft_bench")]:
            if st.button("↺ Reset squad", use_container_width=True):
                _reset_draft_state()
                st.rerun(scope="fragment")

    xi = _xi_for(sq, gw)
    cost = float(pd.to_numeric(sq["actual_price"], errors="coerce").sum())
    bank = float(budget) - cost
    codes = [int(c) for c in sq["code"]]

    # ── Money and transfers, above everything else ───────────────────────────
    # These two are the constraints every decision on this page runs into, so
    # they sit at the top rather than in a panel the user has to go and find.
    _ft = ledger["available_now"]
    _this_week = next((w for w in ledger["weeks"] if w["gw"] == gw), None)
    _made = _this_week["used"] if _this_week else 0

    # Axing a player frees his sale price, and THAT is the number you shop with.
    _in_squad = set(sq["code"].astype(int))
    _freed = float(sum(
        float(board[board["code"] == c].iloc[0]["actual_price"])
        for c in axed if c in _in_squad))
    _spend = bank + _freed
    _bank_label = ("To spend" if _freed else "In the bank")
    _bank_sub = (f"£{bank:.1f}m banked + £{_freed:.1f}m freed" if _freed
                 else "unspent")
    # A Wildcard week has unlimited transfers and costs nothing, so a count of
    # "2 of 5" and a hit warning are both wrong there · it is the one week the
    # constraint does not exist, and the tile should say so rather than making
    # you remember it.
    _wild_now = wildcard_gw is not None and int(wildcard_gw) == int(gw)
    if gw <= 1:
        _ft_val, _ft_sub, _ft_tok = "Draft week", "the draft is free", "muted"
    elif _wild_now:
        _ft_val, _ft_sub, _ft_tok = "∞", "Wildcard · move anyone, free", "mag"
    else:
        _ft_val = f"{_ft} of {ledger['cap']}"
        _ft_sub = "banked, cap %d" % ledger["cap"]
        _ft_tok = "mint" if _ft else "orange"

    st.markdown(_strip([
        ("savings", "Squad value", f"£{cost:.1f}m", "of your budget", "text"),
        ("account_balance", _bank_label, f"£{_spend:.1f}m", _bank_sub,
         "mint" if _spend >= 0 else "red"),
        ("swap_horiz", "Free transfers", _ft_val, _ft_sub, _ft_tok),
        ("shopping_cart", "Made this week", str(_made) if gw > 1 else "-",
         ("free on the Wildcard" if _wild_now else "transfers") if gw > 1
         else "no transfers in GW1",
         "text" if not _made else ("mag" if _wild_now else "cyan")),
        ("trending_down", "Points spent",
         f"-{ledger['points_cost']}" if ledger["points_cost"] else "0",
         "on hits so far", "red" if ledger["points_cost"] else "muted"),
    ]), unsafe_allow_html=True)
    # The armband is worth more than most transfers, so the XI total has to
    # count it. Highest projected starter, gated on actually being expected to
    # play · a captain who does not start scores you nothing twice.
    _cap_pool = [c for c in codes if c in xi
                 and (PROJ.expected_minutes(c, gw) is None
                      or (PROJ.expected_minutes(c, gw) or 0) >= 45)]
    captain = max(_cap_pool or [c for c in codes if c in xi],
                  key=lambda c: PROJ.points(c, gw), default=None)

    xi_pts = sum(PROJ.points(c, gw) for c in codes if c in xi)
    cap_bonus = PROJ.points(captain, gw) if captain is not None else 0.0
    xi_pts += cap_bonus
    bench_pts = sum(PROJ.points(c, gw) for c in codes if c not in xi)

    # A Bench Boost is worth what the bench actually scores, so in the week the
    # draft plays it the fifteen all count. Without this a draft that spends a
    # chip read exactly the same as one that did not, which is the opposite of
    # the point: the whole reason to carry a playing bench is the week it pays.
    boost_gw = _effective_boost_gw()
    boost_on = boost_gw is not None and int(boost_gw) == int(gw)
    if boost_on:
        xi_pts += bench_pts

    # Is this bench worth the chip? Graded against a fixed target rather than
    # against other benches · the chip is played once, so what matters is
    # whether THIS week clears the bar.
    from analytics.grading import bench_boost_grade
    _bb_grade = bench_boost_grade(bench_pts)

    # An 80% band, not a Monte Carlo · this tile redraws on every click.
    from analytics.head_to_head import week_band
    _band = week_band([c for c in codes if c in xi], PROJ, board, gw,
                      captain=captain)
    dead = [r["web_name"] for _, r in sq.iterrows()
            if int(r["code"]) in xi and PROJ.points(int(r["code"]), gw) < 1.5]
    hit, n = PROJ.coverage(codes, gw)

    # Which bench players could legally come on for the armed player. Only these
    # get lit on the pitch, so the formation rule is visible rather than enforced
    # after the fact.
    sub_from = st.session_state[_sk("sub_from")]
    pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
    all_codes = [int(c) for c in sq["code"]]
    swap_targets = set()
    if sub_from is not None and sub_from in pos_by:
        if sub_from in xi:
            swap_targets = set(SR.legal_swaps(sub_from, xi, all_codes, pos_by))
        else:
            # A benched player was tapped: light every starter he could replace.
            swap_targets = {c for c in xi
                            if SR.is_legal_xi((set(xi) - {c}) | {sub_from}, pos_by)}

    players = []
    for _, r in sq.iterrows():
        code = int(r["code"])
        players.append({
            "web_name": r["web_name"], "position": r["position"],
            "team_code": int(r.get("team_code", 1) or 1),
            "team_short": r.get("team_short"),
            "on_bench": code not in xi,
            "is_captain": code == captain,
            "price": float(r["actual_price"]),
            "fixtures": _fixtures_for(int(r.get("team_id", 0) or 0), gw, 3),
            "fpl_id": code, "stat": round(PROJ.points(code, gw), 1), "stat_dp": 1,
            "exp_mins": PROJ.expected_minutes(code, gw),
            "penalties_order": r.get("pens_order"),
            "is_axed": code in axed, "allow_axe": True, "allow_bench": True,
            "is_sub_source": sub_from == code,
            "swap_ok": code in swap_targets,
        })

    # ── Squad score · your week against the best week available ──────────────
    # A raw total tells you nothing on its own: 60 is excellent in a hard week
    # and poor in an easy one. This is what you scored as a share of what a
    # perfect £100m Free Hit would have scored on the same fixtures, so it says
    # "wrong players for these games" in a way a total cannot. A Bench Boost can
    # push it past 100, and should · the ceiling is an eleven and you played
    # fifteen.
    _perfect = _ceiling_now(int(gw), float(budget), BOARD_STAMP)
    _pending = _perfect is None
    _score = (100.0 * xi_pts / _perfect) if (_perfect or 0) > 0 else 0.0
    _score_tok = ("mint" if _score >= 88 else "gold" if _score >= 78
                  else "orange" if _score >= 68 else "red")
    _score_sub = ("best possible was %.0f" % _perfect if _perfect
                  else "working out this week's ceiling…" if _pending
                  else "no ceiling available")
    if boost_on and _score > 100:
        _score_sub = "over the eleven-man ceiling · Boost"

    click = _click(render_squad_pitch(
        players, stat_label=f"GW{gw}", title_right=f"{NEXT_SEASON} · GW{gw}",
        interactive=True, compact=compact,
        # Same number as the XI tile · the pitch would otherwise sum the cards
        # and quietly drop the captain's double.
        xi_total_override=round(xi_pts, 1),
        total_label="SQUAD" if boost_on else "XI",
        # Beside the total, where you are already looking · the total on its
        # own cannot tell you whether 79.7 is a good week or a wasted one.
        score_pct=_score if _perfect else None, score_colour=theme.fill(_score_tok),
        score_pending=_pending,
        key="draft_pitch"), "_pitch_nonce")
    if _pending:
        _ceiling_watcher(int(gw), float(budget), BOARD_STAMP)
    if click:
        action, cid = click.get("action"), int(click.get("id") or 0)
        if action == "detail":
            _player_dialog(cid)
        elif action in ("axe", "unaxe"):
            # ✕ marks a player out and ✕ again takes him off the list, so several
            # can be queued and filled one by one from the table.
            _cur = [int(c) for c in st.session_state[_sk("draft_axe")]]
            if action == "axe" and cid not in _cur:
                _cur.append(cid)
            elif action == "unaxe" and cid in _cur:
                _cur.remove(cid)
            st.session_state[_sk("draft_axe")] = _cur
            st.rerun(scope="fragment")
        elif action == "bench":
            # First tap arms the swap, second tap completes it. Tapping the armed
            # player again cancels, which is the only way out that does not need
            # a separate control.
            if sub_from == cid:
                st.session_state[_sk("sub_from")] = None
            elif sub_from is not None and cid in swap_targets:
                new_xi = (set(xi) - {sub_from}) | {cid} if sub_from in xi \
                    else (set(xi) - {cid}) | {sub_from}
                pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
                if SR.is_legal_xi(new_xi, pos_by):
                    st.session_state[_sk("xi_override")][int(gw)] = new_xi
                st.session_state[_sk("sub_from")] = None
            else:
                st.session_state[_sk("sub_from")] = cid
            st.rerun(scope="fragment")

    if sub_from is not None:
        st.info(f"Swapping **{sq[sq['code'] == sub_from]['web_name'].iloc[0]}**. "
                f"Tap a glowing kit to bring him on, or tap him again to cancel.")

    # ── Save this fifteen ────────────────────────────────────────────────────
    # Save sits ON the planner, beside the team it saves. Burying it in a
    # settings popover meant the thing you built and the thing you saved were
    # different objects: the popover stored the RECIPE, which re-solves to
    # something else tomorrow, while what you actually want kept is the fifteen
    # on screen, swaps and all.
    # THE naming step. By the time you are here you have tuned it, watched it
    # generate and tweaked it by hand, so you finally know what to call it. A
    # draft made from the New draft button arrives as "Untitled draft n" and
    # gets renamed IN PLACE here · same id, so the transfers and the viewed week
    # you have been working on come with it.
    _untitled = str(_spec["id"]).startswith("untitled-")
    _is_mine = not _spec.get("preset")
    _cur_fifteen = {
        "strategy": mode, "locks": list(locked), "vetoes": list(excluded),
        "budget": float(budget), "risk": float(risk),
        "opening": float(opening), "minutes_gate": float(minutes_gate),
        "cap_attackers": bool(cap_attackers),
        "cover": [list(c) for c in cover],
        "bench_boost_gw": _spec.get("bench_boost_gw"),
        "wildcard_gw": _spec.get("wildcard_gw"),
        "squad": [int(c) for c in sq["code"]],
    }
    # Wider save columns · "Name and save" broke over two lines at 2/9.
    _s1, _s2, _s3, _s4 = st.columns([3, 3, 2, 2])
    with _s1:
        _save_as = st.text_input(
            "Draft name", value="" if (_untitled or not _is_mine) else _spec["name"],
            placeholder=("Name it, then save" if _untitled
                         else "Name this draft to save it"),
            key="planner_save_name", label_visibility="collapsed")
    _typed = _save_as.strip()
    _same = _typed == _spec.get("name")
    _clash = (_typed in _SAVED_BY_NAME
              and _SAVED_BY_NAME[_typed]["id"] != _spec["id"])
    with _s2:
        _label = (":material/save: Update" if (_is_mine and _same and not _untitled)
                  else ":material/bookmark_add: Name and save")
        # Deliberately NOT disabled on an empty name. A disabled button swallows
        # the click that was meant to commit the name you just typed, so you had
        # to click twice. Validate here instead.
        _save_hit = st.button(_label, use_container_width=True, type="primary",
                              key="planner_save_go",
                              help="Saves the fifteen exactly as it is on the "
                                   "pitch, swaps and all, along with the dials. "
                                   "Typing a different name RENAMES this draft "
                                   "everywhere · the comparison follows it.")
        if _save_hit and not _typed:
            st.warning("Give it a name first.")
        elif _save_hit and _clash:
            st.warning("**%s** is already taken. Pick another name." % _typed)
        elif _save_hit:
            # Rename in place when this draft is one of yours · a new id would
            # orphan the old one and lose the working state with it. The id
            # never changes, so every surface that points at this draft (the
            # comparison, the last-used memory, the session keys) follows the
            # new name for free.
            _keep_id = _spec["id"] if _is_mine else None
            DR.save_draft(_typed, _cur_fifteen, draft_id=_keep_id)
            st.session_state["_want_draft"] = _typed
            # The transfers are now baked into the saved fifteen, so replaying
            # them on top would apply every move twice.
            _reset_draft_state()
            st.toast(f"Saved {_typed}", icon="✅")
            st.rerun()
    with _s3:
        # Forking, kept · it is how you try a change without losing the version
        # that works, and then put the two side by side. The New draft button
        # copies the RECIPE; this copies the fifteen you are looking at, swaps
        # and all, which is a different and more useful thing at this point.
        _copy_hit = st.button(":material/content_copy: Copy",
                              use_container_width=True, key="planner_copy_go",
                              help="Keeps this draft as it is and stores what is "
                                   "on the pitch under the name you typed, as a "
                                   "new draft. Then compare the two.")
        if _copy_hit and not _typed:
            st.warning("Type the name for the copy first.")
        elif _copy_hit and (_same or _typed in _SAVED_BY_NAME):
            st.warning("A copy needs a name of its own · **%s** is taken."
                       % _typed)
        elif _copy_hit:
            DR.save_draft(_typed, _cur_fifteen)      # new id, original untouched
            st.session_state["_want_draft"] = _typed
            _reset_draft_state()
            st.toast(f"Copied to {_typed}", icon="✅")
            st.rerun()
    with _s4:
        show_changes = st.toggle("Summary of changes", value=False,
                                 key="show_changes")
    if show_changes:
        st.markdown(_changes_summary(ledger), unsafe_allow_html=True)

    # Rank is relative, so the players you SKIPPED are half the position.
    from analytics.template import punt_meter, verdict_line as _punt_line
    _punt = punt_meter(board, [int(c) for c in codes])
    _punt_tok = {"maverick": "red", "differential": "gold",
                 "template": "cyan"}.get(_punt["level"], "muted")

    _tiles([
        ("Spend", f"£{cost:.1f}m", f"£{bank:.1f}m banked", "mint"),
        (f"{'Squad' if boost_on else 'XI'} · GW{gw}", f"{xi_pts:.0f}",
         (f"Boost on · +{bench_pts:.1f} from the bench" if boost_on
          else f"p10 {_band['lo']:.0f} · p90 {_band['hi']:.0f}"),
         "mint" if boost_on else "gold"),
        ("Squad score", "···" if _pending else f"{_score:.0f}%",
         _score_sub, "muted2" if _pending else _score_tok),
        (f"Bench · GW{gw}", f"{bench_pts:.1f}", _bb_grade["call"],
         _bb_grade["token"]),
        ("Non-starters", str(len(dead)),
         ", ".join(dead)[:30] if dead else "everyone plays", "red" if dead else "muted2"),
        ("Forecast", f"{hit}/{n}", "on match forecasts" if hit else "fixture shape",
         "mint" if hit >= n * 0.8 else "orange"),
        ("Template risk", _punt["level"].title(),
         f"{_punt['n']} skipped · -{_punt['downside']:.0f} if they haul", _punt_tok),
    ])

    # The bet, spelled out. A template skip pays small and often and loses big
    # and rarely, which is a fine way to win a mini-league and a terrible thing
    # to do by accident.
    if _punt["n"]:
        _worst = " · ".join(f"{w['name']} {w['own']:.0f}% (-{w['cost']:.0f})"
                            for w in _punt["worst"][:4])
        st.markdown(_one_line(
            f'<div style="{CARD}border-left:3px solid {V(_punt_tok)};'
            f'padding:11px 14px;margin:0 0 12px;">'
            f'<div style="font-size:12.5px;color:{V("text")};line-height:1.55;">'
            f'{_punt_line(_punt)}</div>'
            f'<div style="font-size:11px;color:{V("muted")};margin-top:5px;">'
            f'Biggest exposures · {_worst}</div></div>'), unsafe_allow_html=True)


    # ── One table: replacements when someone is marked, otherwise the pool ───
    _open = [c for c in axed if c in set(sq["code"].astype(int))]
    if _open:
        _out_rows = [board[board["code"] == c].iloc[0] for c in _open]
        _freed = float(sum(float(r["actual_price"]) for r in _out_rows))
        _budget = _freed + bank
        _slots = [str(r["position"]) for r in _out_rows]

        _sec(f"4 · Replacing {len(_open)} player{'' if len(_open) == 1 else 's'}",
             f"£{_freed:.1f}m freed · £{_budget:.1f}m to spend. A signing fills "
             f"the first open slot of his position. Unaffordable players stay "
             f"visible but greyed out.", icon="swap_horiz")

        # The queue, so it is obvious who is out and who is next to be filled.
        _q = []
        for _i, _r in enumerate(_out_rows):
            _nxt = _i == 0
            _q.append(
                f'<div style="display:flex;align-items:center;gap:8px;'
                f'background:{V("card")};border:1px solid '
                f'{V("mint") if _nxt else V("line")};border-radius:9px;'
                f'padding:6px 10px;">'
                f'{face_html(int(_r["code"]), int(_r.get("team_code", 1) or 1), _r["position"] == "GKP", 26)}'
                f'<div><div style="font-size:12px;font-weight:700;color:{V("text")};">'
                f'{_r["web_name"]}</div>'
                f'<div style="font-size:9.5px;color:{V("muted2")};">'
                f'{_r["position"]} · £{float(_r["actual_price"]):.1f}m'
                f'{" · next" if _nxt else ""}</div></div></div>')
        st.markdown(_one_line(
            '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">'
            + "".join(_q) + '</div>'), unsafe_allow_html=True)

        # ── Filters ──────────────────────────────────────────────────────────
        _f1, _f2, _f3, _f4 = st.columns([2, 2, 2, 2])
        with _f1:
            _pos_opts = sorted(set(_slots), key=POS_ORDER.index)
            _pos_f = st.segmented_control(
                "Slot", _pos_opts, default=_pos_opts[0] if len(_pos_opts) == 1 else None,
                key="cand_pos", label_visibility="collapsed",
                help="Which open slot you are filling.")
        with _f2:
            _q_name = st.text_input("Search", key="cand_name", placeholder="Search",
                                    label_visibility="collapsed")
        with _f3:
            _max_p = st.slider("Max £m", 3.5, 16.0, min(16.0, round(_budget + 0.5, 1)),
                               0.5, key="cand_price")
        with _f4:
            _sort = st.selectbox(
                "Rank by", [f"GW{gw}", f"Next 4 GWs", "Season", "Per £m"],
                index=1, key="cand_sort", label_visibility="collapsed")

        _want = [_pos_f] if _pos_f else _pos_opts
        alt = _candidates_multi(sq, _open, _budget, _want)
        if _q_name.strip():
            # Accent-blind · "sesko" has to find "Šeško".
            _q = SR.fold_accents(_q_name.strip())
            alt = alt[alt["web_name"].map(SR.fold_accents).str.contains(
                _q, na=False, regex=False)]
        alt = alt[alt["actual_price"] <= _max_p]

        if alt.empty:
            st.info("Nothing matches those filters.")
        else:
            # Three gameweeks, not four · with the Wildcard at GW4 the fourth
            # column is a week this squad will not exist for, and it was
            # quietly pulling the ranking toward players who peak after the
            # squad gets torn up.
            _hi4 = min(38, gw + 2)

            # The top three as cards, before the list. Twenty-two rows is a
            # research tool; three cards is an answer, and an answer is what you
            # want the moment you take someone out. These went missing in the
            # multi-axe rewrite because one set of cards did not obviously map
            # onto several open slots · it does, as long as they name the slot
            # they fill, which is the first open one of that position.
            _t3 = alt.assign(_r=[PROJ.run_total(int(c), gw, _hi4)
                                 for c in alt["code"]]).nlargest(3, "_r")
            _cards = []
            for _rank, (_, _c) in enumerate(_t3.iterrows(), start=1):
                _cc = int(_c["code"])
                _tok = ["mint", "gold", "cyan"][_rank - 1]
                # Priced against the player he would actually replace, not
                # against the first one you happened to mark.
                _slot = next((r for r in _out_rows
                              if str(r["position"]) == str(_c["position"])),
                             _out_rows[0])
                _d_price = float(_c["actual_price"]) - float(_slot["actual_price"])
                _runs = _fixtures_for(int(_c.get("team_id", 0) or 0), gw, 3)
                _chips = "".join(
                    f'<span style="background:{theme.FDR_COLORS.get(int(round(float(f.get("fdr", 3)))), "#FFD60A")};'
                    f'color:#000;border-radius:4px;padding:1px 5px;font-size:9px;'
                    f'font-weight:900;">{str(f.get("opp", "?"))[:3]}'
                    f'{"(H)" if f.get("home") else "(A)"}</span>' for f in _runs)
                _mins = PROJ.expected_minutes(_cc, gw)
                # The SAME ceiling the table below uses · bank plus what the
                # player he replaces sells for. `_budget` already includes the
                # freed money, so adding the slot price to it counted the sale
                # twice and marked a player affordable who is not.
                _afford = (float(_c["actual_price"])
                           <= bank + float(_slot["actual_price"]) + 1e-9)
                _cards.append(
                    f'<div style="{CARD}flex:1;min-width:200px;'
                    f'border-top:3px solid {V(_tok)};'
                    f'{"" if _afford else "opacity:0.45;"}">'
                    f'<div style="display:flex;align-items:center;gap:9px;margin-bottom:7px;">'
                    f'<span style="display:inline-grid;place-items:center;width:21px;'
                    f'height:21px;border-radius:7px;background:{V(_tok)};color:#06251A;'
                    f'font-family:var(--ff-display);font-size:12px;font-weight:900;">'
                    f'{_rank}</span>'
                    f'{face_html(_cc, int(_c.get("team_code", 1) or 1), _c["position"] == "GKP", 32)}'
                    f'<div style="min-width:0;flex:1;">'
                    f'<div style="font-size:13px;font-weight:700;color:{V("text")};'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'{_c["web_name"]}</div>'
                    f'<div style="font-size:10px;color:{V("muted")};'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'for {_slot["web_name"]} · £{float(_c["actual_price"]):.1f}m '
                    f'({_d_price:+.1f})</div></div></div>'
                    f'<div style="display:flex;gap:3px;margin-bottom:7px;">{_chips}</div>'
                    f'<div style="display:flex;justify-content:space-between;gap:6px;">'
                    f'<div><div class="ff-display" style="font-size:16px;font-weight:800;'
                    f'color:{V(_tok)};">{float(_c["_r"]):.1f}</div>'
                    f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                    f'color:{V("muted2")};">GW{gw}-{_hi4}</div></div>'
                    f'<div><div class="ff-display" style="font-size:16px;font-weight:800;'
                    f'color:{V("text")};">{PROJ.points(_cc, gw):.1f}</div>'
                    f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                    f'color:{V("muted2")};">GW{gw}</div></div>'
                    f'<div><div class="ff-display" style="font-size:16px;font-weight:800;'
                    f'color:{V("text")};">'
                    f'{("%.0f" % _mins) if _mins is not None else "-"}</div>'
                    f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                    f'color:{V("muted2")};">mins</div></div></div>'
                    + ("" if _afford else
                       f'<div style="font-size:10px;color:{V("red")};margin-top:6px;">'
                       f'Too dear for this slot</div>')
                    + '</div>')
            st.markdown(_one_line(
                '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 10px;">'
                + "".join(_cards) + '</div>'), unsafe_allow_html=True)
            if _sort.startswith("GW"):
                alt = alt.assign(_k=[PROJ.points(int(c), gw) for c in alt["code"]])
            elif _sort.startswith("Next"):
                _m = PROJ.matrix([int(c) for c in alt["code"]],
                                 list(range(gw, _hi4 + 1))).sum(axis=1)
                alt = alt.assign(_k=alt["code"].astype(int).map(_m).fillna(0.0))
            elif _sort == "Season":
                alt = alt.assign(_k=alt[PTS_COL])
            else:
                alt = alt.assign(_k=alt[PTS_COL] / alt["actual_price"].clip(lower=0.1))

            _n_match = len(alt)
            _shown_key = _sk("cand_shown")
            st.session_state.setdefault(_shown_key, POOL_PAGE)
            _lim = min(int(st.session_state[_shown_key]), _n_match)

            _page = alt.nlargest(_lim, "_k")
            rows = _pool_rows(_page, gw, _out_rows[0])
            _run4 = PROJ.matrix([int(c) for c in _page["code"]],
                                list(range(gw, _hi4 + 1))).sum(axis=1)
            # What each row would cost given the slot it fills, so "affordable"
            # means affordable AFTER the player it replaces is sold.
            _price_by = dict(zip(board["code"].astype(int), board["actual_price"]))
            _slot_price = {p: max((float(r["actual_price"]) for r in _out_rows
                                   if str(r["position"]) == p), default=0.0)
                           for p in _pos_opts}
            for _r in rows:
                _r["horizon"] = round(float(_run4.get(int(_r["code"]), 0.0)), 1)
                _ceiling = bank + _slot_price.get(_r["position"], 0.0)
                _r["_unavailable"] = float(_r["actual_price"]) > _ceiling + 1e-9
            _cols = _pool_cols(gw, with_delta=True, rows=rows)
            _cols.insert(-1, T.col_bar("horizon", f"GW{gw}-{_hi4}",
                                       max_value=_bar_max(rows, "horizon", "season"),
                                       color="gold", fmt="%.1f"))
            _cols[-1] = T.col_action("code", "swap", "Sign", disabled_key="_unavailable",
                                     disabled_glyph="Too dear")
            pick = _click(T.render(rows, _cols, key="cand_tbl", max_height=380),
                          "_cand_nonce")
            if pick and pick.get("action") == "swap":
                _in = int(pick["id"])
                _inpos = str(board[board["code"] == _in].iloc[0]["position"])
                # First open slot of that position · the queue order is the
                # order they were marked, which is the order a user expects.
                _target = next((c for c in _open
                                if str(board[board["code"] == c].iloc[0]["position"])
                                == _inpos), None)
                if _target is not None:
                    st.session_state[_sk("draft_swaps")].setdefault(int(gw), {})[
                        int(_target)] = _in
                    st.session_state[_sk("draft_axe")] = [
                        c for c in st.session_state[_sk("draft_axe")]
                        if int(c) != int(_target)]
                    st.rerun(scope="fragment")

            _p1, _p2, _p3 = st.columns([3, 1, 1])
            with _p1:
                st.markdown(_one_line(
                    f'<div style="font-size:11.5px;color:{V("muted")};padding:6px 2px;">'
                    f'Showing <b style="color:{V("text")};">{_lim}</b> of '
                    f'<b style="color:{V("text")};">{_n_match}</b> candidates.</div>'),
                    unsafe_allow_html=True)
            with _p2:
                # Always rendered · see the note on the pool's paging below.
                _rest = max(0, _n_match - _lim)
                if st.button("Show %d more" % min(POOL_PAGE, _rest) if _rest
                             else "All %d shown" % _n_match,
                             use_container_width=True, key="cand_more",
                             disabled=not _rest):
                    st.session_state[_shown_key] = _lim + POOL_PAGE
                    st.rerun(scope="fragment")
            with _p3:
                if st.button("Clear marks", use_container_width=True, key="cand_cancel"):
                    st.session_state[_sk("draft_axe")] = []
                    st.rerun(scope="fragment")
    else:
        _sec("4 · The pool", "Everyone you could pick, ranked for this gameweek. "
                         "Mark a player with × on the pitch to see only his replacements.")
        # Position as buttons, not a typed multiselect · four options should
        # never need typing. The horizon slider is the important one: "best next
        # week" and "best over the next eight" are different questions and the
        # table should answer whichever one you are actually asking.
        f1, f2 = st.columns([3, 2])
        with f1:
            pos_f = st.segmented_control(
                "Position", POS_ORDER, selection_mode="multi", default=[],
                key="pool_pos", label_visibility="collapsed")
        with f2:
            horizon = st.slider(
                "Points over the next N gameweeks", 1, 8, 3, key="pool_horizon",
                help="Ranks the table on expected points over this many "
                     "gameweeks from the one you are viewing. Drop it to 1 for a "
                     "one-week punt, raise it for a keeper.")
        f3, f4, f5 = st.columns([2, 2, 2])
        with f3:
            name_q = st.text_input("Search", key="pool_name",
                                   placeholder="Search a player",
                                   label_visibility="collapsed")
        with f4:
            club_f = st.multiselect(
                "Club", sorted(board["team_name"].dropna().unique().tolist()),
                default=[], key="pool_club", label_visibility="collapsed",
                placeholder="Any club")
        with f5:
            max_price = st.slider("Max price (£m)", 3.5, 16.0, 16.0, 0.5,
                                  key="pool_price")

        pool = board[(board["actual_price"] <= max_price)
                     & (~board["code"].isin(sq["code"]))]
        if pos_f:
            pool = pool[pool["position"].isin(list(pos_f))]
        if club_f:
            pool = pool[pool["team_name"].isin(club_f)]
        if name_q.strip():
            # Accent-blind · see SR.fold_accents. "sesko" finds "Šeško".
            _pq = SR.fold_accents(name_q.strip())
            pool = pool[pool["web_name"].map(SR.fold_accents).str.contains(
                _pq, na=False, regex=False)]
        _hi_gw = min(38, gw + horizon - 1)
        # One matrix beats a Python sum per player per gameweek on every
        # keystroke, and it is computed once instead of twice (the survivors
        # were re-totalled row by row straight afterwards).
        _run = PROJ.matrix([int(c) for c in pool["code"]],
                           list(range(gw, _hi_gw + 1))).sum(axis=1)
        pool = pool.assign(_k=pool["code"].astype(int).map(_run).fillna(0.0))

        # A fixed slice with no count reads as "these are the options". Say how
        # many matched, and let the list grow when it is not enough.
        _n_matched = len(pool)
        _shown_key = _sk("pool_shown")
        st.session_state.setdefault(_shown_key, POOL_PAGE)
        _pool_limit = min(int(st.session_state[_shown_key]), _n_matched)

        rows = _pool_rows(pool.nlargest(_pool_limit, "_k"), gw)
        for _r in rows:
            _r["horizon"] = round(float(_run.get(int(_r["code"]), 0.0)), 1)
        _cols = _pool_cols(gw, rows=rows)
        _cols.insert(-1, T.col_bar(
            "horizon", f"GW{gw}-{_hi_gw}" if horizon > 1 else f"GW{gw}",
            max_value=max([r["horizon"] for r in rows] or [1]) * 1.05, color="gold",
            fmt="%.1f"))
        if pool.empty:
            st.info("Nothing matches those filters.")
        else:
            pick = _click(T.render(rows, _cols, key="pool_tbl", max_height=360),
                          "_pool_nonce")
            if pick and pick.get("action") == "inspect":
                _player_dialog(int(pick["id"]))

            _c1, _c2 = st.columns([3, 1])
            with _c1:
                st.markdown(_one_line(
                    f'<div style="font-size:11.5px;color:{V("muted")};'
                    f'padding:6px 2px;">Showing <b style="color:{V("text")};">'
                    f'{_pool_limit}</b> of <b style="color:{V("text")};">'
                    f'{_n_matched}</b> players who match'
                    f'{" your filters" if (pos_f or club_f or name_q.strip()) else ""}'
                    f'.</div>'), unsafe_allow_html=True)
            with _c2:
                # Both buttons ALWAYS render, disabled when they do not apply.
                # Swapping one widget for a different key at the same spot, or
                # dropping it entirely, changes the element tree between fragment
                # runs · Streamlit's frontend then gets a delta for a node it has
                # not got and dies with "Bad message format · cannot read
                # properties of undefined (reading 'setIn')". It showed up on the
                # LAST page, which is exactly where this branch flipped.
                _rest = max(0, _n_matched - _pool_limit)
                if st.button("Show %d more" % min(POOL_PAGE, _rest) if _rest
                             else "All %d shown" % _n_matched,
                             use_container_width=True, key="pool_more",
                             disabled=not _rest):
                    st.session_state[_shown_key] = _pool_limit + POOL_PAGE
                    st.rerun(scope="fragment")
                if st.button("Show fewer", use_container_width=True,
                             key="pool_fewer", disabled=_pool_limit <= POOL_PAGE):
                    st.session_state[_shown_key] = POOL_PAGE
                    st.rerun(scope="fragment")


planner()


# ── Analysis ──────────────────────────────────────────────────────────────────
_workflow_rail(5)
_sec("5 · Compare and read", "Everything that informs the draft, without "
                             "crowding the squad above.", icon="insights")

# Material icons throughout · the sidebar and every tile already use them, and
# mixing emoji into the tab strip was the one place the page changed alphabet.
# One word each. Seven long labels did not fit a laptop and the last tab sat
# off the right edge with no way to reach it · and "Compare players" inside a
# section called "Compare and read" says the same word twice anyway.
tab_cmp, tab_ab, tab_verdict, tab_models, tab_wc, tab_route, tab_all = st.tabs(
    [":material/balance: Players",
     ":material/compare_arrows: Drafts",
     ":material/target: Verdicts",
     ":material/handshake: Models",
     ":material/playing_cards: Wildcard",
     ":material/alt_route: Chip route",
     ":material/table_rows: Everyone"])


# ── Compare players ───────────────────────────────────────────────────────────
with tab_cmp:
    st.session_state.setdefault("cmp_players", [])
    _c1, _c2 = st.columns([3, 1])
    with _c1:
        picks = st.multiselect(
            "Players", options=NAMES, default=st.session_state["cmp_players"],
            max_selections=3, key="cmp_pick", label_visibility="collapsed",
            placeholder="Pick two or three players to compare",
            help="The ⚖ button on a player's card adds them here.")
    with _c2:
        cmp_h = st.slider("Over the next", 1, 12, 6, key="cmp_horizon",
                          help="The window the verdict is judged on. A season "
                               "total cannot separate a nailed 4.2 a week from "
                               "a punt who posts 8 twice and blanks four times.")
    st.session_state["cmp_players"] = picks

    if len(picks) < 2:
        st.info("Pick two or three players. Everything below is judged on the "
                "window you choose, not on a season total.")
    else:
        from analytics import grading
        from analytics.head_to_head import compare_players, verdict

        _cmp_gw = int(st.session_state.get(_sk("draft_gw"), 1))
        profs = [_profile_window(int(board[board[NAME_COL] == nm].iloc[0]["code"]),
                                 _cmp_gw, cmp_h) for nm in picks]
        cmp = compare_players(profs)
        vd = verdict(cmp, profs)

        # ── The answer, first ────────────────────────────────────────────────
        st.markdown(_one_line(
            f'<div style="{CARD}border-left:4px solid {V(vd["tone"])};'
            f'margin:2px 0 14px;padding:14px 16px;">'
            f'<div style="font-size:9.5px;font-weight:800;letter-spacing:0.16em;'
            f'text-transform:uppercase;color:{V(vd["tone"])};margin-bottom:5px;">'
            f'{"No real difference" if vd["call"] == "same" else "Verdict"}</div>'
            f'<div style="font-size:15px;color:{V("text")};line-height:1.6;">'
            f'{vd["headline"]}</div>'
            + (f'<div style="font-size:13.5px;color:{V("muted")};line-height:1.6;'
               f'margin-top:6px;">{vd["detail"]}</div>' if vd["detail"] else "")
            + '</div>'), unsafe_allow_html=True)

        # ── The numbers that decide it, per player ───────────────────────────
        _cuts = _points_cuts(cmp_h, BOARD_STAMP)
        head = st.columns(len(profs))
        for col, p in zip(head, profs):
            with col:
                _is_pick = vd.get("pick") == p["name"]
                _mins = p.get("exp_mins_pg")
                _mins_txt = ("no forecast" if _mins is None or pd.isna(_mins)
                             else f"{_mins:.0f} min a game")
                _band = grading.band_of(p.get("per_gw"), p["position"], _cuts)
                st.markdown(_one_line(
                    f'<div style="{CARD}text-align:center;padding:14px 12px;'
                    + (f'border:2px solid {V(vd["tone"])};' if _is_pick else "")
                    + f'">'
                    f'<div style="display:flex;justify-content:center;margin-bottom:6px;">'
                    f'{face_html(p["code"], p["team_code"], p["position"] == "GKP", 58)}</div>'
                    f'<div class="ff-display" style="font-size:18px;font-weight:900;'
                    f'color:{V("text")};">{p["name"]}</div>'
                    f'<div style="font-size:11px;color:{V("muted")};margin-bottom:9px;">'
                    f'{p["team"]} · {p["position"]} · £{p["price"]:.1f}m</div>'
                    f'<div class="ff-display" style="font-size:30px;font-weight:900;'
                    f'color:{V(grading.BAND_TOKENS[_band])};line-height:1;">'
                    f'{p.get("run", 0):.1f}</div>'
                    f'<div style="font-size:10px;font-weight:600;letter-spacing:0.1em;'
                    f'text-transform:uppercase;color:{V("muted2")};margin-top:3px;">'
                    f'pts GW{p["gw_from"]}-{p["gw_to"]}</div>'
                    f'<div style="display:flex;justify-content:space-around;'
                    f'margin-top:10px;padding-top:9px;border-top:1px solid {V("line")};">'
                    f'<div><div class="ff-display" style="font-size:15px;font-weight:800;'
                    f'color:{V("text")};">{p.get("per_gw", 0):.2f}</div>'
                    f'<div style="font-size:9px;color:{V("muted2")};">a week</div></div>'
                    f'<div><div class="ff-display" style="font-size:15px;font-weight:800;'
                    f'color:{V("text")};">{p.get("run_per_m", 0):.1f}</div>'
                    f'<div style="font-size:9px;color:{V("muted2")};">per £m</div></div>'
                    f'<div><div class="ff-display" style="font-size:15px;font-weight:800;'
                    f'color:{V("text")};">{_mins_txt.split(" ")[0]}</div>'
                    f'<div style="font-size:9px;color:{V("muted2")};">mins/game</div></div>'
                    f'</div></div>'), unsafe_allow_html=True)

        # ── Week by week, coloured by how good that score really is ──────────
        _sec(f"Week by week, GW{profs[0]['gw_from']}-{profs[0]['gw_to']}",
             grading.band_label(profs[0]["position"], _cuts)
             if len({p["position"] for p in profs}) == 1
             else "Colours are set per position · a 4.5 is an ordinary week for a "
                  "forward and an excellent one for a keeper.",
             icon="bar_chart")
        _wk_cols = st.columns(len(profs))
        for col, p in zip(_wk_cols, profs):
            with col:
                st.markdown(_week_bars(p, _cuts), unsafe_allow_html=True)

        # ── Fixtures, side by side ───────────────────────────────────────────
        _sec("The run", "Same weeks, both players, so a fixture swing is obvious.",
             icon="calendar_month")
        _fx_cols = st.columns(len(profs))
        for col, p in zip(_fx_cols, profs):
            with col:
                _fx = _fixtures_for(
                    int(board[board["code"] == p["code"]].iloc[0].get("team_id", 0) or 0),
                    p["gw_from"], min(cmp_h, 8))
                st.markdown(_one_line(
                    f'<div style="{CARD}padding:11px 12px;">'
                    f'<div style="font-size:11px;font-weight:700;color:{V("text")};'
                    f'margin-bottom:7px;">{p["name"]}</div>'
                    + _run_chips(_fx) + '</div>'), unsafe_allow_html=True)

        # ── Shape and the full metric table ──────────────────────────────────
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            axes = cmp["axes"]
            if axes:
                inds = [{"name": a["label"], "max": 1.0} for a in axes]
                series = []
                for i, p in enumerate(profs):
                    vals = [(a["scaled"][i] if a["scaled"][i] is not None else 0)
                            for a in axes]
                    col = theme.fill(["mint", "gold", "cyan"][i % 3])
                    series.append((p["name"], [round(v, 3) for v in vals], col, 0.16))
                charts.render(charts.radar_compare_option(inds, series),
                              height="330px", key="cmp_radar")
        with cc2:
            gws = list(range(profs[0]["gw_from"], profs[0]["gw_to"] + 1))
            series = []
            for i, p in enumerate(profs):
                pts = [(g, round(PROJ.points(p["code"], g), 2)) for g in gws]
                series.append((p["name"], pts, theme.fill(["mint", "gold", "cyan"][i % 3])))
            charts.render(charts.multi_line_option(series, x_name="Gameweek",
                                                   y_name="Expected points"),
                          height="330px", key="cmp_run")

        rows = []
        for a in cmp["axes"]:
            row = {"axis": a["label"].replace("next N GWs",
                                              f"GW{profs[0]['gw_from']}-{profs[0]['gw_to']}"),
                   "why": a["why"]}
            for i, p in enumerate(profs):
                v = a["values"][i]
                row["p%d" % i] = "n/a" if v is None or pd.isna(v) else (
                    "%.0f%%" % (v * 100) if a["key"] == "defcon" else
                    "%.0f'" % v if a["key"] == "exp_mins_pg" else
                    "%.2f" % v if a["key"] in ("per_90", "agreement", "fixtures") else
                    "%.1f" % v)
                if i == a["best"]:
                    row["p%d" % i] = "◆ " + row["p%d" % i]
            rows.append(row)
        cols = [T.col_text("axis", "Metric"),
                T.col_text("why", "What it tells you")]
        cols[1:1] = [T.col_text("p%d" % i, p["name"], align=T.ALIGN_NUM)
                     for i, p in enumerate(profs)]
        T.render(rows, cols, key="cmp_table", row_key="axis", max_height=340)
        st.caption("◆ marks the better number on that row. The final column is why "
                   "the row matters, so a lead on a metric that does not decide "
                   "anything reads as exactly that.")


# ── Compare drafts ────────────────────────────────────────────────────────────
with tab_ab:
    from analytics import drafts as DR
    from analytics.head_to_head import build_phases, significance, simulate_drafts

    st.caption("Whole squads, each scored over the same window **with its own chip "
               "plan**. A Bench Boost in GW1 and one in GW2 are different plans, not "
               "the same squad twice, and a Wildcard rebuilds the squad on the "
               "fixtures that follow it.")

    saved = DR.load_drafts()
    by_id = {d["id"]: d for d in saved}

    # Saving and deleting live in step 1 and step 2, next to the controls they
    # act on. A second copy of them down here offered its own Bench Boost and
    # Wildcard pickers with a different range, and a button restoring nine
    # presets that no longer exist · three ways to do one thing, two of them wrong.

    # ── Pick which to compare ────────────────────────────────────────────────
    default = [d["name"] for d in saved][:4]
    # No number · the page already numbers 1 to 5, and a second "1" three
    # sections down reads as a contradiction rather than a sub-step.
    _sec("Choose the drafts", icon="checklist")

    # Selecting thirteen drafts one at a time is not a choice anyone wants to
    # make. Three shortcuts cover how the list is actually used: everything,
    # just the ones you built, and clear.
    _q1, _q2, _q3, _q4 = st.columns([2, 2, 2, 3])
    _all = [d["name"] for d in saved]
    _mine = [d["name"] for d in saved if not d.get("preset")]
    with _q1:
        if st.button(f":material/select_all: Compare all {len(_all)}",
                     use_container_width=True, key="ab_all"):
            st.session_state["ab_picks"] = _all
            st.rerun()
    with _q2:
        if st.button(":material/bookmark: Just mine", use_container_width=True,
                     key="ab_mine", disabled=len(_mine) < 2,
                     help="Only the drafts you saved yourself."):
            st.session_state["ab_picks"] = _mine
            st.rerun()
    with _q3:
        if st.button(":material/backspace: Clear", use_container_width=True,
                     key="ab_clear"):
            st.session_state["ab_picks"] = []
            st.rerun()

    picks = st.multiselect(
        "Drafts to compare", options=_all,
        default=st.session_state.get("ab_picks", default), key="ab_picks",
        label_visibility="collapsed",
        placeholder="Pick two or more drafts",
        help="Everything is simulated on the same draws, so shared players cancel "
             "and the comparison narrows to the picks that differ.")

    # Every chosen draft gets an identity that holds across the whole tab: a
    # letter, a shape and a colour. A green box with a name in it tells you
    # nothing and looks like a tag; a lettered badge lets the ranked table, the
    # lines, the win bars and the squad columns all refer to the same thing
    # without re-reading a long name each time.
    _ids = _draft_identities(picks)
    if picks:
        st.markdown(_identity_row(picks, _ids), unsafe_allow_html=True)

    _sec("Set the window", icon="tune")
    wc1, wc2, wc3 = st.columns([3, 2, 2])
    with wc1:
        window = st.slider("Score over gameweeks", 1, MAX_GW, (1, 8), key="ab_window")
    with wc2:
        n_sims = st.select_slider("Simulations", [500, 1500, 4000], value=1500,
                                  key="ab_sims",
                                  help="More simulations narrow the bands. 1500 is "
                                       "plenty to separate anything that is real.")
    with wc3:
        st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
        run_ab = st.button(":material/play_arrow: Run comparison", type="primary",
                           use_container_width=True, key="ab_go",
                           disabled=len(picks) < 2)

    if not saved:
        st.info("No saved drafts. Save one above, or restore the presets.")
    elif len(picks) < 2:
        st.info("Pick at least two drafts.")
    elif run_ab or st.session_state.get("_ab_ready") == (tuple(picks), window, n_sims):
        st.session_state["_ab_ready"] = (tuple(picks), window, n_sims)
        name_to_id = {d["name"]: d["id"] for d in saved}
        specs = [by_id[name_to_id[n]] for n in picks]

        # Stepping a gameweek in the side-by-side triggers a full rerun, and
        # re-solving nine MILPs plus 1500 simulations for a fixture change nobody
        # asked to recompute would make the stepper unusable. Cache the run
        # against what it actually depends on.
        _ab_key = (tuple(picks), window, int(n_sims), BOARD_STAMP)
        _cached = st.session_state.get("_ab_cache")
        _reuse = bool(_cached and _cached.get("key") == _ab_key and not run_ab)
        entries = _cached["entries"] if _reuse else []
        sim = _cached["sim"] if _reuse else None
        if not _reuse:
            with st.spinner("Solving squads and simulating the window…"):
                entries = []
                for spec in specs:
                    # Phase 2 only · the squad you rebuild ON the wildcard, which
                    # is scored on the fixtures that FOLLOW it. Phase 1 comes
                    # from `solve_opening`, the same call the planner makes, so a
                    # draft cannot show one fifteen at the top of the page and a
                    # different one down here.
                    def _solve(strategy, ow, omap, _s=spec):
                        return solve_draft(
                            _tuned_board(float(_s.get("minutes_gate", 0.5))),
                            strategy or "⚖️ Optimal value", float(_s.get("budget", 100.0)),
                            float(_s.get("risk", 0.3)), tuple(_s.get("vetoes", [])), ow,
                            force_names=tuple(_s.get("locks", [])), opening_map=omap,
                            max_attackers_per_club=None if not _s.get("cap_attackers") else 1,
                            max_defenders_per_club=_s.get(
                                "max_defenders_per_club",
                                _new_draft_defaults().get("max_defenders_per_club", 1)))

                    phases = build_phases(spec, _solve, _window_map, window[0], window[1],
                                          board=board, first=solve_opening(spec))
                    if not phases:
                        st.warning(f"**{spec['name']}** has no feasible squad · skipped.")
                        continue
                    # The solver returns `price`; the simulation wants the board's
                    # own column names, so carry `actual_price` through.
                    phases = [(g, sq.merge(board[["code", "actual_price"]], on="code",
                                           how="left"))
                              for g, sq in phases]
                    entries.append({"name": spec["name"], "phases": phases,
                                    "bench_boost_gw": spec.get("bench_boost_gw")})

                sim = (simulate_drafts(entries, PROJ, board, window[0], window[1],
                                       n_sims=int(n_sims))
                       if len(entries) >= 2 else None)
                st.session_state["_ab_cache"] = {"key": _ab_key, "entries": entries,
                                                 "sim": sim}

        if sim is None:
            st.error("Need at least two feasible drafts to compare.")
            ranked = []
        else:
            ranked = sorted(sim["drafts"], key=lambda d: -d["total_mean"])
            # Chart labels: keep the chip plan, which is what usually differs,
            # and keep the NAME. The old abbreviations were built for thirteen
            # near-identical preset names and rewrote "Optimal" as "Base", so the
            # chart named a draft that appeared nowhere else on the page. The
            # picker's label dropped them for exactly this reason; this copy of
            # the same code was missed.
            for d in ranked:
                head, _, chip = d["name"].partition(" · ")
                d["short"] = (f"{head} {chip}" if chip else head)[:26]
        if ranked:
            # The leader is mint. Anyone still in the fight (beats it in at least
            # 35% of simulations) is gold. Everyone clearly behind goes grey, so
            # the chart shows the SHORTLIST rather than a rainbow of nine.
            colour = {nm: _ids[nm]["colour"] for nm in _ids}
            for d in ranked:
                colour.setdefault(d["name"], theme.fill("muted2"))
                d["ident"] = _ids.get(d["name"], {"letter": "?", "colour": colour[d["name"]]})

            # ── The call ─────────────────────────────────────────────────────────
            top, second = ranked[0], ranked[1]
            sig = significance(top, second)
            # The headline states the ACTION, not the statistic. A user reading
            # this wants to know what to do; the numbers underneath say why.
            if sig["call"] == "coin flip":
                headline, sub = "Too close to call", "Either is a defensible pick"
            else:
                headline, sub = f"Pick {top['ident']['letter']} · {top['short']}", (
                    f"ahead in {sig['p'] * 100:.0f}% of simulations")
            st.markdown(_one_line(
                f'<div style="{CARD}border-left:4px solid {V(sig["tone"])};margin:12px 0;">'
                f'<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;'
                f'margin-bottom:6px;">'
                f'<div class="ff-display" style="font-size:26px;font-weight:900;'
                f'color:{V(sig["tone"])};">{headline}</div>'
                f'<div style="font-size:13px;color:{V("muted")};font-weight:600;">{sub}</div>'
                f'</div>'
                f'<div style="font-size:14px;color:{V("text")};line-height:1.6;">'
                f'{sig["text"]}</div>'
                f'<div style="font-size:12px;color:{V("muted")};margin-top:6px;">'
                f'{sim["n_sims"]:,} simulations. Each player gets one draw for how good '
                f'he really is (from how far the three models disagree) plus fresh '
                f'week-to-week variance, and both are SHARED between drafts · so the '
                f'players these squads have in common cancel out and only the picks '
                f'that differ move the answer.</div></div>'), unsafe_allow_html=True)

            # ── Range bars · the overlap IS the answer ───────────────────────────
            _sec("Where each draft lands", icon="insights",
                 sub="The bar is the middle 80% of outcomes, the tick is the average. "
                 "Bars that overlap heavily are not meaningfully different, however "
                 "far apart their averages look.")
            _boost_by = {e["name"]: e.get("bench_boost_gw") for e in entries
                         if e.get("bench_boost_gw")
                         and window[0] <= e["bench_boost_gw"] <= window[1]}
            st.markdown(_range_bands(ranked, colour, window, _boost_by),
                        unsafe_allow_html=True)

            # ── Ranked table ─────────────────────────────────────────────────────
            rows = []
            for i, d in enumerate(ranked):
                rows.append({
                    "rank": i + 1, "name": d["name"],
                    "mean": d["total_mean"],
                    # Floor, median, ceiling · the 5th, 50th and 95th percentile
                    # of the simulated total. The decision cut: what a bad run
                    # really posts, the honest middle, and the dream scenario.
                    "band": (f"{d['total_p5']:.0f} · {d['total_p50']:.0f} · "
                             f"{d['total_p95']:.0f}"
                             if "total_p5" in d else
                             f"{d['total_lo']:.0f} to {d['total_hi']:.0f}"),
                    "vs_top": d["total_mean"] - top["total_mean"],
                    "p_best": d["p_best"] * 100,
                    "beats_top": (d["beats"].get(top["name"], 0.5) * 100) if i else 100.0,
                })
            T.render(rows, [
                T.col_num("rank", "#", fmt="%.0f"),
                T.col_player("name", "Draft"),
                T.col_bar("mean", f"GW{window[0]}-{window[1]}",
                          max_value=max(d["total_mean"] for d in ranked) * 1.05),
                T.col_text("band", "Floor · median · ceiling", align=T.ALIGN_NUM),
                T.col_num("vs_top", "vs best", fmt="%+.1f",
                          color_fn=lambda v: theme.fill("muted2") if v == 0 else theme.fill("red")),
                T.col_bar("p_best", "Chance it's best", max_value=100, color="gold",
                          fmt="%.0f%%"),
                T.col_bar("beats_top", "Beats the best", max_value=100, color="cyan",
                          fmt="%.0f%%"),
            ], key="ab_rank", row_key="rank", max_height=380)
            st.caption("**Chance it's best** is how often that draft finished top of "
                       "this group across every simulation. When several drafts share "
                       "it fairly evenly, the choice between them is not a points "
                       "decision · it is a football one.")

            # ── Cumulative run ───────────────────────────────────────────────────
            gws = sim["gws"]
            g1, g2 = st.columns([3, 2])
            with g1:
                _sec("Points as the weeks pass", icon="show_chart")
                series = [(f'{d["ident"]["letter"]} · {d["short"]}', [(g, v) for g, v in zip(gws, d["cum_mean"])],
                           colour[d["name"]]) for d in ranked]
                opt = charts.multi_line_option(series, x_name="Gameweek",
                                               y_name="Cumulative points")
                marks = []
                for e in entries:
                    if e.get("bench_boost_gw") and window[0] <= e["bench_boost_gw"] <= window[1]:
                        marks.append((e["bench_boost_gw"], "BB"))
                if marks:
                    opt = charts.with_vertical_marks(opt, sorted(set(marks)))
                charts.render(opt, height="330px", key="ab_cum")
            with g2:
                _sec("Chance of finishing top", icon="emoji_events")
                charts.render(charts.bar_option(
                    x=[d["ident"]["letter"] for d in ranked],
                    y=[round(d["p_best"] * 100, 1) for d in ranked],
                    colors=[colour[d["name"]] for d in ranked], horizontal=True),
                    height="330px", key="ab_pbest")

            # ── Floor to ceiling, week by week · the two-draft decision view ─────
            # Only for a final pair. With two drafts the question stops being
            # "which is best on average" and becomes "which do I regret less":
            # the floor (P5) is the week that ruins a Bench Boost, the ceiling
            # (P95) is the week that wins a mini-league. More than two drafts
            # turns this into eighteen bars and the ranked table reads better.
            if len(ranked) == 2 and all("weekly_p5" in d for d in ranked):
                _sec("Floor to ceiling, week by week", icon="candlestick_chart",
                     sub="For each gameweek: the 5th percentile week (floor), the "
                     "median, and the 95th (ceiling). A higher floor is worth more "
                     "than a higher ceiling in a Bench Boost week · the chip "
                     "multiplies whatever actually happens.")

                def _fade(col: str, alpha: float) -> str:
                    c = str(col).lstrip("#")
                    if len(c) != 6:          # not a hex colour · leave it alone
                        return str(col)
                    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
                    return f"rgba({r},{g},{b},{alpha})"

                _fc_series = []
                for d in ranked:
                    base = colour[d["name"]]
                    letter = d["ident"]["letter"]
                    _fc_series += [
                        (f"{letter} floor", d["weekly_p5"], _fade(base, 0.35)),
                        (f"{letter} median", d["weekly_p50"], _fade(base, 0.7)),
                        (f"{letter} ceiling", d["weekly_p95"], base),
                    ]
                charts.render(charts.grouped_bars_option(
                    [f"GW{g}" for g in sim["gws"]], _fc_series),
                    height="300px", key="ab_floorceil")

            # ── Head to head ─────────────────────────────────────────────────────
            # A grid of every pair is only readable up to about six drafts. Past
            # that the cells are too small to compare and the ranked table above
            # already carries the same information.
            if len(ranked) <= 6:
                _sec("Head to head", icon="grid_view",
                     sub="How often the row's draft beat the column's. Near 50 means "
                     "there is nothing to choose between them.")
                names = [d["name"] for d in ranked]
                shorts = [d["ident"]["letter"] for d in ranked]
                matrix = [[50.0 if d["name"] == n
                           else round(d["beats"].get(n, 0.5) * 100, 1) for n in names]
                          for d in ranked]
                charts.render(charts.heatmap_option(x=shorts, y=shorts, matrix=matrix,
                                                    vmin=0, vmax=100),
                              height=f"{max(260, 46 * len(names))}px", key="ab_matrix")

            # ── The reasons, for the top pair ────────────────────────────────────
            from analytics.head_to_head import compare_drafts, score_draft
            idx = {e["name"]: e for e in entries}
            sa = score_draft(idx[top["name"]]["phases"][0][1], PROJ, window[0], window[1],
                             bench_boost_gw=idx[top["name"]].get("bench_boost_gw"))
            sb = score_draft(idx[second["name"]]["phases"][0][1], PROJ, window[0], window[1],
                             bench_boost_gw=idx[second["name"]].get("bench_boost_gw"))
            res_ab = compare_drafts(sa, sb, top["name"][:28], second["name"][:28])
            if res_ab["reasons"]:
                _sec("Why the top two differ", icon="help")
                for r in res_ab["reasons"]:
                    tok = {"chip": "cyan", "captain": "gold", "week": "mint",
                           "budget": "muted", "warning": "red"}.get(r["kind"], "muted")
                    st.markdown(_one_line(
                        f'<div style="{CARD}border-left:3px solid {V(tok)};'
                        f'margin-bottom:8px;padding:10px 14px;">'
                        f'<div style="font-size:13px;color:{V("text")};line-height:1.5;">'
                        f'{r["text"]}</div></div>'), unsafe_allow_html=True)
                st.caption(f"They share {res_ab['shared']} of 15 players, so "
                           f"{res_ab['differs']} picks are doing all the work.")

            # ── The squads themselves, side by side ──────────────────────────
            # Every number above is an aggregate. At some point you want to look
            # at the actual teams, and the only rows that matter are the ones
            # that differ · so shared players are dimmed and the rest are marked.
            _sec("The squads, side by side", icon="groups",
                 sub="Pick two to line up. Players only that draft has are marked "
                     "with a dot; everyone else is in both.")
            _pair = st.multiselect(
                "Line up", options=[d["name"] for d in ranked],
                default=[top["name"], second["name"]], max_selections=2,
                key="ab_pair", label_visibility="collapsed")
            # Stepping through the weeks is the point of this view: the squads
            # barely change, but the FIXTURES do, and that is what moves the
            # numbers. A stepper beats a slider because you want to nudge one
            # week at a time and watch what happens.
            st.session_state.setdefault("ab_squad_gw", window[0])
            st.session_state["ab_squad_gw"] = int(
                min(max(st.session_state["ab_squad_gw"], window[0]), window[1]))
            _sq_gw = st.session_state["ab_squad_gw"]

            _v0, _v1, _v2, _v3 = st.columns([1, 1, 3, 3])
            with _v0:
                if st.button("◀", key="ab_gw_prev", use_container_width=True,
                             disabled=_sq_gw <= window[0], help="Previous gameweek"):
                    st.session_state["ab_squad_gw"] = _sq_gw - 1
                    st.rerun()
            with _v1:
                if st.button("▶", key="ab_gw_next", use_container_width=True,
                             disabled=_sq_gw >= window[1], help="Next gameweek"):
                    st.session_state["ab_squad_gw"] = _sq_gw + 1
                    st.rerun()
            with _v2:
                # What each draft is worth THIS week, so stepping has a readout.
                _wk = []
                for _n in _pair:
                    _e = idx.get(_n)
                    if not _e:
                        continue
                    _s = _e["phases"][0][1]
                    for _st, _cd in sorted(_e["phases"], key=lambda t: t[0]):
                        if _sq_gw >= _st:
                            _s = _cd
                    from analytics.gw_projection import best_xi as _bxi
                    _x = _bxi(_s, PROJ, _sq_gw)
                    # What this draft ACTUALLY scores this week under its own
                    # chip plan. A Boost week is fifteen players, not eleven,
                    # and that is the whole reason two drafts differ · a row
                    # that always showed the XI hid the thing being compared.
                    _bbw = _SAVED_BY_NAME.get(_n, {}).get("bench_boost_gw")
                    _on = _bbw is not None and int(_bbw) == int(_sq_gw)
                    _who = ([int(c) for c in _s["code"]] if _on else list(_x))
                    _v = sum(PROJ.points(int(c), _sq_gw) for c in _who)
                    if _x:
                        _v += max(PROJ.points(int(c), _sq_gw) for c in _x)
                    _wk.append((_n, _v, _on))
                _bits = "".join(
                    f'<span style="display:inline-flex;align-items:center;gap:6px;'
                    f'margin-right:14px;">{_badge(_ids[_n], 18)}'
                    f'<span class="ff-display" style="font-size:16px;font-weight:800;'
                    f'color:{_ids[_n]["colour"]};">{_v:.1f}</span>'
                    + (f'<span style="font-size:9px;font-weight:900;color:{V("cyan")};'
                       f'letter-spacing:0.08em;">BOOST</span>' if _on else "")
                    + '</span>'
                    for _n, _v, _on in _wk if _n in _ids)
                st.markdown(_one_line(
                    f'<div style="display:flex;align-items:center;gap:12px;'
                    f'height:38px;"><span class="ff-display" style="font-size:19px;'
                    f'font-weight:900;color:{V("text")};">GW{_sq_gw}</span>{_bits}'
                    f'<span style="font-size:11px;color:{V("muted")};">'
                    f'points that week, captain doubled</span></div>'),
                    unsafe_allow_html=True)
            with _v3:
                _sq_view = st.segmented_control(
                    "View", ["Pitch", "List"], default="Pitch", key="ab_squad_view",
                    label_visibility="collapsed")
            if len(_pair) == 2:
                _codes = {}
                for nm in _pair:
                    e = idx.get(nm)
                    if not e:
                        continue
                    sq = e["phases"][0][1]
                    for start, cand in sorted(e["phases"], key=lambda t: t[0]):
                        if _sq_gw >= start:
                            sq = cand
                    _codes[nm] = sq
                if len(_codes) == 2:
                    _a, _b2 = _pair[0], _pair[1]
                    _sa = set(_codes[_a]["code"].astype(int))
                    _sb = set(_codes[_b2]["code"].astype(int))
                    _cols = st.columns(2)
                    for _col, _nm, _only in ((_cols[0], _a, _sa - _sb),
                                             (_cols[1], _b2, _sb - _sa)):
                        with _col:
                            _sqd = _codes[_nm]
                            # The REAL score for this week, per draft: the best
                            # eleven, the captain doubled, and the whole fifteen
                            # if this draft plays its Bench Boost here. It used
                            # to sum all fifteen every week and call the result
                            # "XI points", which overstated a normal week by a
                            # whole bench and ignored the chip that is the only
                            # reason two drafts differ.
                            from analytics.gw_projection import best_xi as _bxi
                            _xi_h = _bxi(_sqd, PROJ, _sq_gw)
                            _bb_h = (_SAVED_BY_NAME.get(_nm, {})
                                     .get("bench_boost_gw"))
                            _boost_h = _bb_h is not None and int(_bb_h) == int(_sq_gw)
                            _pool_h = ([int(c) for c in _sqd["code"]] if _boost_h
                                       else list(_xi_h))
                            _tot = sum(PROJ.points(int(c), _sq_gw) for c in _pool_h)
                            if _xi_h:
                                _tot += max(PROJ.points(int(c), _sq_gw)
                                            for c in _xi_h)      # captain
                            _tot_lab = ("all 15 + captain, Boost on" if _boost_h
                                        else "XI + captain")
                            _id = _ids.get(_nm, {"letter": "?", "colour": colour[_nm]})
                            st.markdown(_one_line(
                                f'<div style="display:flex;align-items:center;gap:9px;'
                                f'margin:4px 0 8px;">{_badge(_id, 24)}'
                                f'<div style="min-width:0;">'
                                f'<div class="ff-display" style="font-size:14px;'
                                f'font-weight:800;color:{_id["colour"]};white-space:nowrap;'
                                f'overflow:hidden;text-overflow:ellipsis;">{_nm}</div>'
                                f'<div style="font-size:11px;color:{V("muted")};">'
                                f'{len(_only)} unique · <b style="color:'
                                f'{V("mint") if _boost_h else V("text")};">'
                                f'{_tot:.1f}</b> in GW{_sq_gw} · {_tot_lab}'
                                f'</div></div></div>'), unsafe_allow_html=True)

                            if _sq_view == "Pitch":
                                # The same pitch the planner uses, so a squad you
                                # compare looks like a squad you built · players
                                # only this draft has get the mint ring.
                                from analytics.gw_projection import best_xi
                                _xi2 = best_xi(_sqd, PROJ, _sq_gw)
                                _plist = []
                                for _, _r in board[board["code"].isin(
                                        _sqd["code"])].iterrows():
                                    _c = int(_r["code"])
                                    _plist.append({
                                        "web_name": _r["web_name"],
                                        "position": _r["position"],
                                        "team_code": int(_r.get("team_code", 1) or 1),
                                        "team_short": _r.get("team_short"),
                                        "on_bench": _c not in _xi2,
                                        "price": float(_r["actual_price"]),
                                        "fixtures": _fixtures_for(
                                            int(_r.get("team_id", 0) or 0), _sq_gw, 3),
                                        "fpl_id": _c, "stat_dp": 1,
                                        "stat": round(PROJ.points(_c, _sq_gw), 1),
                                        "exp_mins": PROJ.expected_minutes(_c, _sq_gw),
                                        "penalties_order": _r.get("pens_order"),
                                        "swap_ok": _c in _only,
                                    })
                                # Two pitches share the width one normally gets,
                                # so they are scaled down together · shrinking
                                # the card alone would clip the fixture chips.
                                render_squad_pitch(
                                    _plist, stat_label=f"GW{_sq_gw}",
                                    title_right=f"{_id['letter']} · GW{_sq_gw}",
                                    compact=True, scale=COMPARE_SCALE,
                                    key=f"ab_pitch_{_id['letter']}")
                            else:
                                _rows = _pool_rows(
                                    board[board["code"].isin(_sqd["code"])], _sq_gw)
                                for _r in _rows:
                                    _r["mark"] = "●" if _r["code"] in _only else ""
                                _rows.sort(key=lambda r: (-len(r["mark"]), -r["gw_pts"]))
                                T.render(_rows, [
                                    T.col_text("mark", ""),
                                    T.col_face("code", url_fn=player_photo_url),
                                    T.col_player("web_name", "Player", sub="team_short",
                                                 action="inspect"),
                                    T.col_chip("position", "Pos", color_fn=theme.pos_color),
                                    T.col_num("actual_price", "£m", fmt="%.1f"),
                                    T.col_run("run", "Next 3"),
                                    T.col_num("gw_pts", f"GW{_sq_gw}", fmt="%.1f"),
                                    T.col_bar("season", "Season",
                                              max_value=_bar_max(_rows, "season", "season")),
                                ], key=f"ab_side_{_nm}", max_height=430)

                # ── The same two, week by week ───────────────────────────
                # Two squads listed side by side tell you WHO differs. These
                # tell you WHEN, which is the part that decides a chip.
                _two = [d for d in ranked if d["name"] in set(_pair)]
                if len(_two) == 2:
                    _sec("Where the gap actually opens", icon="insights",
                         sub="Weekly points, then the running gap. A line that "
                             "climbs in one place and flattens elsewhere is a "
                             "fixture swing, not a better squad.")
                    _w1, _w2 = st.columns(2)
                    with _w1:
                        charts.render(charts.multi_line_option(
                            [(f'{d["ident"]["letter"]} · {d["short"]}',
                              [(g, v) for g, v in zip(sim["gws"], d["weekly_mean"])],
                              colour[d["name"]]) for d in _two],
                            x_name="Gameweek", y_name="Points that week"),
                            height="290px", key="ab_pair_weekly")
                    with _w2:
                        _ha, _hb = _two
                        _gap = [(g, round(x - y, 1)) for g, x, y
                                in zip(sim["gws"], _ha["cum_mean"], _hb["cum_mean"])]
                        charts.render(charts.multi_line_option(
                            [(f'{_ha["ident"]["letter"]} minus '
                              f'{_hb["ident"]["letter"]}', _gap,
                              theme.fill("mint" if _gap[-1][1] >= 0 else "red"))],
                            x_name="Gameweek", y_name="Running gap"),
                            height="290px", key="ab_pair_gap")
                    st.caption(
                        f"Above zero means **{_ha['short']}** is ahead. "
                        f"It ends {abs(_gap[-1][1]):.0f} point"
                        f"{'' if abs(_gap[-1][1]) == 1 else 's'} "
                        f"{'ahead' if _gap[-1][1] >= 0 else 'behind'}.")
    else:
        st.caption("Press **Run comparison** to solve each squad and simulate the window.")


# ── Verdict cards ─────────────────────────────────────────────────────────────
def _scout_questions(row: pd.Series) -> list:
    """1-2 human reads a projection cannot make · depth chart, fitness, role."""
    qs = []
    nail = row.get("ffh_nailedness")
    sr = row.get("starts_ratio")
    price = float(row.get("actual_price") or 0)
    surp = float(row.get("pricing_surprise") or 0)
    if pd.notna(nail) and float(nail) < 0.6:
        qs.append(f"Match model sees only {float(nail) * 90:.0f} mins a game early · "
                  f"is he fit, or behind someone?")
    elif pd.notna(sr) and sr < 0.8:
        qs.append(f"Started {int(row.get('starts_total') or 0)}/"
                  f"{int(row.get('games_played') or 0)} in 25/26 · nailed now, or rotated?")
    if surp <= -1.0:
        qs.append(f"FPL priced £{-surp:.1f}m over the model · reputation tax, or a bigger role?")
    # Only ask about set pieces where the answer is not already on the card.
    if price >= 9.0 and not any(_num_safe(row.get(k)) == 1
                                for k in ("pens_order", "fk_order", "corners_order")):
        qs.append("Premium anchor with no set-piece duty · what justifies the price?")
    elif price <= 4.5:
        qs.append("Cheap starter? Confirm he starts GW1 before locking him in.")

    # The minutes question was printed on every card, which trained the eye to
    # skip the whole block. Ask it only where it is live.
    if bool(row.get("changed_club")):
        qs.append("New club · is he first choice in this system, or a squad signing?")
    elif str(row.get("position", "")) == "DEF" and pd.notna(row.get("role")) \
            and str(row.get("role")) == "FB":
        qs.append("Full-back · attacking returns or a clean-sheet floor?")
    elif not qs:
        qs.append("Any new signing or backup who could eat his minutes?")
    return qs[:2]


def _verdict_card(row: pd.Series) -> str:
    verdict = str(row.get("verdict", VERDICTS.FAIR))
    tok, _ = VERDICT_META.get(verdict, VERDICT_META[VERDICTS.FAIR])
    pos = str(row.get("position", ""))
    price = float(row.get("actual_price") or 0)
    pts = float(row.get(PTS_COL) or 0)
    own = float(row.get("ownership") or 0)
    surp = float(row.get("pricing_surprise") or 0)
    conf = str(row.get("consensus_confidence", row.get("confidence", "")) or "")
    lo, hi = float(row.get("consensus_lo") or 0), float(row.get("consensus_hi") or 0)
    share = max(0.0, min(1.0, float(row.get("mins_share") or 0)))
    is_scout = verdict == VERDICTS.SCOUT
    nail = row.get("ffh_nailedness")

    flag = {"i": "injured", "d": "doubt", "s": "susp.", "u": "out",
            "n": "out"}.get(str(row.get("status", "a") or "a"), "")
    flag_html = (f'<span style="background:{V("chip-bg")};color:{V("red")};'
                 f'border-radius:4px;padding:1px 6px;font-size:9px;font-weight:900;'
                 f'flex-shrink:0;">{flag}</span>' if flag else "")
    mins_html = (f'<span style="background:{V("chip-bg")};color:{V("red")};'
                 f'border-radius:4px;padding:1px 6px;font-size:9px;font-weight:900;'
                 f'flex-shrink:0;">{float(nail) * 90:.0f}\'</span>'
                 if pd.notna(nail) and float(nail) < 0.6 else "")
    # A player showing a club he did not play for last season is correct data
    # that looks exactly like a bug. Naming it turns a trust-breaker into a
    # signal, and the same is true of a hand-entered late start.
    club_html = (f'<span title="Moved club since last season · unproven in this '
                 f'system" style="background:{V("chip-bg")};color:{V("cyan")};'
                 f'border-radius:4px;padding:1px 6px;font-size:9px;font-weight:900;'
                 f'flex-shrink:0;">NEW CLUB</span>'
                 if bool(row.get("changed_club")) else "")
    late_html = (f'<span title="Not expected to play the opening gameweeks" '
                 f'style="background:{V("chip-bg")};color:{V("orange")};'
                 f'border-radius:4px;padding:1px 6px;font-size:9px;font-weight:900;'
                 f'flex-shrink:0;">LATE START</span>'
                 if int(row.get("code", 0) or 0) in MISS_EARLY else "")

    ctok = CONF_TOKEN.get(conf, "muted2")
    conf_html = (f'<span style="display:inline-flex;align-items:center;gap:4px;">'
                 f'<span style="width:7px;height:7px;border-radius:50%;'
                 f'background:{V(ctok)};"></span>'
                 f'<span style="font-size:9px;font-weight:800;color:{V(ctok)};'
                 f'text-transform:uppercase;">{conf}</span></span>' if conf else "")
    range_html = (f'<div style="font-size:10px;color:{V("muted2")};margin-bottom:8px;">'
                  f'Models span {lo:.0f}-{hi:.0f} pts</div>'
                  if (conf and not is_scout and hi) else "")

    pens = _num_safe(row.get("pens_order"))
    fk, corn = _num_safe(row.get("fk_order")), _num_safe(row.get("corners_order"))
    if pens == 1:
        sp = (f'<span style="background:{V("gold-v")};color:#000;border-radius:4px;'
              f'padding:1px 6px;font-size:9px;font-weight:900;">PENS</span>')
    elif (fk in (1, 2)) or (corn in (1, 2)) or (pens in (2, 3)):
        sp = (f'<span style="background:{V("cyan-v")};color:#000;border-radius:4px;'
              f'padding:1px 6px;font-size:9px;font-weight:900;">SET-PC</span>')
    else:
        sp = ""

    note = str(row.get("override_note", "") or "")
    note_html = (f'<div style="font-size:10px;color:{V("cyan")};margin-bottom:6px;">'
                 f'✎ {note}</div>' if note else "")
    stok = "mint" if surp > 0 else "red" if surp < 0 else "muted2"
    surp_txt = (f"+£{surp:.1f}m under model" if surp > 0
                else f"£{-surp:.1f}m over model" if surp < 0 else "at model price")

    def stat(v, l, t="text"):
        return (f'<div style="text-align:center;"><div class="ff-display" '
                f'style="font-size:15px;font-weight:900;color:{V(t)};">{v}</div>'
                f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                f'color:{V("muted2")};">{l}</div></div>')

    if is_scout:
        mid = f'{stat(f"£{price:.1f}", "Price")}{stat(f"{own:.1f}%", "Owned", "cyan")}'
        bar = ""
    else:
        mid = (f'{stat(f"£{price:.1f}", "Price")}{stat(f"{pts:.0f}", "Season", "mint")}'
               f'{stat(f"{pts / price:.1f}" if price else "-", "Per £m", "gold")}'
               f'{stat(f"{own:.1f}%", "Owned", "cyan")}')
        bar = (f'<div style="height:5px;border-radius:3px;background:{V("chip-bg")};'
               f'overflow:hidden;margin-bottom:8px;"><div style="height:100%;'
               f'width:{share * 100:.0f}%;background:{V(tok)};"></div></div>'
               f'<div style="font-size:10px;color:{V(stok)};font-weight:700;'
               f'margin-bottom:8px;">{surp_txt}</div>')

    q_html = "".join(f'<li style="margin-bottom:3px;line-height:1.3;">{q}</li>'
                     for q in _scout_questions(row))
    return _one_line(f"""
<div class="ff-card-3d" style="background:{V('card')};border:1px solid {V('line')};
     border-top:3px solid {V(tok)};border-radius:14px;padding:14px 16px;">
  <div style="display:flex;align-items:center;gap:11px;margin-bottom:10px;">
    {face_html(row.get("code"), int(row.get("team_code", 1) or 1), pos == "GKP", 46)}
    <div style="min-width:0;flex:1;">
      <div style="font-size:15px;font-weight:800;color:{V('text')};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{row.get("web_name", "?")}</div>
      <div style="display:flex;align-items:center;gap:6px;margin-top:2px;">
        {team_dot(row.get("team_short"), size=9)}
        <span style="font-size:11px;color:{V('muted2')};">{row.get("team_name", "")}</span>
      </div>
    </div>
    {flag_html}
    <span style="background:{theme.pos_color(pos)};color:#000;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:900;flex-shrink:0;">{pos}</span>
  </div>
  <div style="display:flex;justify-content:flex-end;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px;">{club_html}{late_html}{mins_html}{sp}{conf_html}</div>
  <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:8px;">{mid}</div>
  {range_html}
  {bar}
  {note_html}
  <div style="font-size:11px;color:{V('muted')};margin-bottom:8px;line-height:1.35;">{row.get("verdict_reason", "") or ""}</div>
  <ul style="margin:0;padding-left:16px;font-size:11px;color:{V('muted2')};">{q_html}</ul>
</div>""")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _lane_html(_df: pd.DataFrame, codes: tuple, stamp: str, light: bool) -> str:
    """Roughly 150 KB of markup that only changes when the data or theme does.

    Keyed on the codes in the lane rather than the frame, plus the content
    stamp and the theme, because those are the only three things that can
    change what a card says.
    """
    return ('<div class="fplh-stagger" style="display:grid;'
            'grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">'
            + "".join(_verdict_card(r) for _, r in _df.iterrows()) + "</div>")


def _lane(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No players in this bucket right now.")
        return
    st.markdown(
        _lane_html(df, tuple(int(c) for c in df["code"]), BOARD_STAMP,
                   theme.is_light()),
        unsafe_allow_html=True)


with tab_verdict:
    counts = board["verdict"].value_counts().to_dict()
    st.caption("Each card carries a confidence dot · how much to trust its number. "
               "Green means the models agree, red means they scatter or only one of "
               "them has an opinion.")
    vt = st.tabs([f":material/star: Necessity ({counts.get(VERDICTS.NECESSITY, 0)})",
                  f":material/trending_up: Value ({counts.get(VERDICTS.VALUE, 0)})",
                  f":material/trending_down: Overpriced ({counts.get(VERDICTS.OVERPRICED, 0)})",
                  f":material/search: Scout · new ({len(scout)})"])
    with vt[0]:
        _lane(board[board["verdict"] == VERDICTS.NECESSITY]
              .sort_values(PTS_COL, ascending=False).head(18))
    with vt[1]:
        _lane(board[board["verdict"] == VERDICTS.VALUE]
              .sort_values("value_score", ascending=False).head(18))
    with vt[2]:
        _lane(board[board["verdict"] == VERDICTS.OVERPRICED]
              .sort_values("actual_price", ascending=False).head(18))
    with vt[3]:
        _lane(scout.head(18))


# ── Model agreement ───────────────────────────────────────────────────────────
with tab_models:
    if not HAS_CONSENSUS:
        st.caption("Only one model is loaded, so there is nothing to compare.")
    else:
        st.caption("Three models, rescaled onto one scale so the comparison is real "
                   "rather than an artefact of each one's units. **Agreement is the "
                   "evidence.** Where they scatter, the blended number is a guess "
                   "wearing a decimal point.")
        cov = board["n_models"].value_counts().to_dict()
        _tiles([
            ("All three", str(cov.get(3, 0)), "models rate the player", "mint"),
            ("Two", str(cov.get(2, 0)), "one has no row", "orange"),
            ("Ours only", str(cov.get(1, 0)), "no external check", "red"),
            ("Early-minutes flags",
             str(int(board.get("ffh_no_early_minutes", pd.Series(dtype=bool)).sum())),
             "under 45 mins a game", "mag"),
        ])

        from analytics.consensus import biggest_disagreements
        dis = biggest_disagreements(board, 25)
        if dis.empty:
            st.info("No material disagreements.")
        else:
            rows = []
            for _, d in dis.iterrows():
                rows.append({
                    "code": int(board[board["web_name"] == d["web_name"]].iloc[0]["code"])
                    if (board["web_name"] == d["web_name"]).any() else 0,
                    "web_name": d["web_name"], "team_short": d.get("team_name", ""),
                    "position": d.get("position", ""),
                    "price": float(d.get("actual_price") or 0),
                    "ours": d.get("src_ours"), "scout": d.get("src_scout"),
                    "hub": d.get("src_ffh"), "blend": d.get("consensus_points"),
                    "gap": d.get("gap"), "nailed": d.get("ffh_nailedness"),
                })
            _dis_click = _click(T.render(rows, [
                T.col_face("code", url_fn=player_photo_url),
                T.col_player("web_name", "Player", sub="team_short", action="inspect"),
                T.col_chip("position", "Pos", color_fn=theme.pos_color),
                T.col_num("price", "£m", fmt="%.1f"),
                T.col_num("ours", "Ours", fmt="%.0f"),
                T.col_num("scout", "Scout", fmt="%.0f"),
                T.col_num("hub", "Hub", fmt="%.0f"),
                T.col_num("blend", "Blend", fmt="%.0f"),
                T.col_bar("gap", "Gap", max_value=_bar_max(rows, "gap", "gap"),
                          color="red"),
                T.col_num("nailed", "Nailed", fmt="%.2f"),
            ], key="dis_tbl", max_height=430), "_dis_nonce")
            if _dis_click and _dis_click.get("action") == "inspect":
                _player_dialog(int(_dis_click["id"]))
            st.caption("A big gap is not a bug. It is usually one model seeing a role "
                       "change (a new club, a new manager, a tournament return) that "
                       "the others are still pricing off last season.")

        _sec("Minutes are the master variable", icon="timer",
             sub="Expected minutes early against the blended season projection. The "
             "bottom-right corner is the trap: a big season number on a player who "
             "is not currently starting.")
        if "ffh_nailedness" in board.columns:
            d = board[board["ffh_nailedness"].notna() & (board[PTS_COL] > 20)]
            groups = []
            for pos in POS_ORDER:
                sub = d[d["position"] == pos]
                pts = [{"x": round(float(r["ffh_nailedness"]) * 90, 0),
                        "y": round(float(r[PTS_COL]), 1), "name": str(r["web_name"]),
                        "size": 7,
                        "tip": (f"{r['web_name']} · {r['team_name']}<br/>"
                                f"£{r['actual_price']:.1f}m · "
                                f"{float(r['ffh_nailedness']) * 90:.0f} mins/game "
                                f"→ {r[PTS_COL]:.0f} pts")}
                       for _, r in sub.iterrows()]
                if pts:
                    groups.append((pos, theme.pos_color(pos), pts))
            xn = ("Expected minutes a game, GW%s-%s" % (MATCH_WINDOW[0], MATCH_WINDOW[-1])
                  if MATCH_WINDOW else "Expected minutes a game")
            charts.render(charts.multi_scatter_option(
                groups, x_name=xn, y_name="Blended season projection"),
                height="400px", key="board_min_pts")


# ── Wildcard ──────────────────────────────────────────────────────────────────
with tab_wc:
    st.caption("A Wildcard is unlimited free transfers, so the squad is rebuilt from "
               "scratch on the fixtures that FOLLOW it. This shows who leaves, who "
               "arrives, and what the reset is worth over the next six gameweeks.")
    w1, w2 = st.columns([2, 3])
    with w1:
        wc_gw = st.slider("Play the Wildcard at GW", 2, MAX_GW, 4, 1, key="wc_gw")
    with w2:
        wc_on = st.checkbox("Show me the Wildcard squad", value=False, key="wc_on")
    if wc_on:
        wc_hi = min(38, wc_gw + 5)
        wc = solve_draft(SOLVE_BOARD, "⚖️ Optimal value", budget, risk, tuple(excluded),
                         1.0, force_names=tuple(locked),
                         opening_map=_window_map(wc_gw, wc_hi),
                         max_attackers_per_club=None if two_att else 1)
        if wc is None:
            st.error("No feasible Wildcard squad · widen the budget or drop a lock.")
        else:
            new, now = wc["squad"], _current_squad()
            new_codes = set(new["code"].astype(int))
            now_codes = set(now["code"].astype(int))
            out_p = now[~now["code"].astype(int).isin(new_codes)]
            in_p = board[board["code"].isin(new_codes - now_codes)]

            def _win_pts(codes, xi_codes):
                return sum(PROJ.points(c, g) for g in range(wc_gw, wc_hi + 1)
                           for c in codes if c in xi_codes)

            gain = (_win_pts(new_codes, set(new[new["in_xi"]]["code"].astype(int)))
                    - _win_pts(now_codes, _xi_for(now, wc_gw)))
            _tiles([
                ("Changes", str(len(in_p)), "players in, free on a Wildcard", "mint"),
                (f"GW{wc_gw}-{wc_hi}", f"{gain:+.0f}", "extra expected XI points", "gold"),
                ("Spend", f"£{wc['squad_cost']:.1f}m", "of your budget", "cyan"),
            ])
            if gain < 6:
                st.info(f"A reset here gains only **{gain:+.0f}** points over six weeks, "
                        f"inside the noise of the projection. The Wildcard is probably "
                        f"better saved, unless you need it to repair injuries the model "
                        f"cannot see, or to move early on price risers.")
            oc, ic = st.columns(2)
            for col, frame, lbl, tok in ((oc, out_p, "Out", "red"), (ic, in_p, "In", "mint")):
                with col:
                    st.markdown(_one_line(
                        f'<div style="font-size:11px;font-weight:800;letter-spacing:0.18em;'
                        f'color:{V(tok)};text-transform:uppercase;margin-bottom:6px;">'
                        f'{lbl} ({len(frame)})</div>'), unsafe_allow_html=True)
                    _wc_rows = _pool_rows(frame, wc_gw)
                    T.render(_wc_rows, [
                        T.col_face("code", url_fn=player_photo_url),
                        T.col_player("web_name", "Player", sub="team_short"),
                        T.col_num("actual_price", "£m", fmt="%.1f"),
                        T.col_bar("season", "Season",
                                  max_value=_bar_max(_wc_rows, "season", "season")),
                    ], key=f"wc_{lbl}", max_height=300, empty="Nobody.")


# ── Chip route ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=6 * 3600, show_spinner="Scoring chip routes over GW1-19…")
def _routes(_board: pd.DataFrame, budget: float, risk: float, excl: tuple,
            stamp: str):
    from analytics.season_opener import bb_dilution, compare_routes, opening_ease
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    fx = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())

    def _solve(b, all_must_play=False, bench_price_cap=None, opening_window=None):
        strategy = "🔋 Bench Boost GW1" if all_must_play else "⚖️ Optimal value"
        omap = ()
        if opening_window:
            oe = opening_ease(fx, opening_window[0], opening_window[1])
            omap = tuple(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))
        return solve_draft(b, strategy, budget, risk, excl, 0.0, opening_map=omap,
                           bench_budget=(bench_price_cap * 4) if bench_price_cap else None)

    return compare_routes(_board, fx, _solve), bb_dilution(_board, _solve)


with tab_route:
    # ── How the SELECTED draft's route plays out ─────────────────────────────
    # A route name says what you do; this says what happens. Built on the draft
    # chosen in Controls, so it answers "how does BB1 into WC4 actually work"
    # rather than describing routes in the abstract.
    _bb_gw, _wc_gw2 = _spec.get("bench_boost_gw"), _spec.get("wildcard_gw")
    if _bb_gw or _wc_gw2:
        _route_name = " then ".join(filter(None, [
            f"Bench Boost GW{_bb_gw}" if _bb_gw else "",
            f"Wildcard GW{_wc_gw2}" if _wc_gw2 else ""]))
        _sec(f"Your route · {_route_name}", icon="route",
             sub=f"What {_spec['name']} actually does, week by week.")
        try:
            from analytics.head_to_head import build_phases, walk_route

            def _rsolve(strategy, ow, omap):
                return solve_draft(SOLVE_BOARD, strategy or "⚖️ Optimal value",
                                   budget, risk, tuple(excluded), ow,
                                   force_names=tuple(locked), opening_map=omap,
                                   max_attackers_per_club=None if two_att else 1,
                                   max_defenders_per_club=_new_draft_defaults().get(
                                       "max_defenders_per_club", 1))

            _ph = build_phases(_spec, _rsolve, _window_map, 1, 10, board=board)
            _ph = [(g, s.merge(board[["code", "actual_price"]], on="code", how="left"))
                   for g, s in _ph]
            _walk = walk_route(_spec, _ph, PROJ, board, 1, 10)

            _tiles([
                ("Boost returns",
                 f"{_walk['boost_return']:.1f}" if _walk["boost_return"] is not None else "-",
                 f"bench points in GW{_bb_gw}" if _bb_gw else "no Boost planned",
                 "mint" if _walk["boost_return"] else "muted2"),
                ("Bench, normal week", f"{_walk['idle_bench']:.1f}",
                 "points sitting on the bench", "cyan"),
                ("Wildcard changes",
                 str(_walk["wildcard"]["changes"]) if _walk["wildcard"] else "-",
                 f"players at GW{_wc_gw2}" if _wc_gw2 else "no reset planned",
                 "gold" if _walk["wildcard"] else "muted2"),
                ("Reset is worth",
                 f"{_walk['wildcard']['gain']:+.1f}" if _walk["wildcard"] else "-",
                 (f"over GW{_walk['wildcard']['window'][0]}-"
                  f"{_walk['wildcard']['window'][1]}") if _walk["wildcard"] else "",
                 "mint" if (_walk["wildcard"] and _walk["wildcard"]["gain"] > 6) else "orange"),
                ("Transfers banked", str(_walk["ft_at_wildcard"]),
                 "by the reset" if _wc_gw2 else "by GW10", "mag"),
            ])

            if _walk.get("timing"):
                _t = _walk["timing"]
                _tok = "mint" if _t["delta"] > 1.5 else "orange" if _t["delta"] < -1.5 else "muted"
                st.markdown(_one_line(
                    f'<div style="{CARD}border-left:3px solid {V(_tok)};margin-bottom:12px;">'
                    f'<div style="font-size:14px;color:{V("text")};line-height:1.6;">'
                    f'The Boost week bench is <b>{_t["delta"]:+.1f}</b> against an '
                    f'average week, so {_t["verdict"]}.</div></div>'),
                    unsafe_allow_html=True)

            _wkrows = []
            for w in _walk["weeks"]:
                chips = []
                if w["boost"]:
                    chips.append("BENCH BOOST")
                if w["wildcard"]:
                    chips.append("WILDCARD")
                _wkrows.append({
                    "gw": w["gw"], "label": f"GW{w['gw']}",
                    "chip": " + ".join(chips) or "",
                    "xi": w["xi"], "bench": w["bench"], "total": w["total"],
                    "warn": ", ".join(w["dead_bench"]),
                })
            T.render(_wkrows, [
                T.col_text("label", "Week"),
                T.col_chip("chip", "Chip",
                           color_fn=lambda v: theme.fill("gold-v") if "BOOST" in str(v)
                           else theme.fill("cyan-v")),
                T.col_bar("xi", "XI", max_value=max(w["xi"] for w in _walk["weeks"]) * 1.1),
                T.col_num("bench", "Bench", fmt="%.1f"),
                T.col_bar("total", "Counts", color="gold",
                          max_value=max(w["total"] for w in _walk["weeks"]) * 1.1),
                T.col_text("warn", "Not expected to play"),
            ], key="route_weeks", row_key="gw", max_height=340)

            if _walk["wildcard"]:
                _o, _i = _walk["wildcard"]["out"], _walk["wildcard"]["in"]
                st.markdown(_one_line(
                    f'<div style="{CARD}margin-top:10px;">'
                    f'<div style="font-size:13px;color:{V("text")};line-height:1.7;">'
                    f'<b>The reset at GW{_wc_gw2}</b> takes out '
                    f'<span style="color:{V("red")};">{", ".join(_o) or "nobody"}</span> '
                    f'and brings in '
                    f'<span style="color:{V("mint")};">{", ".join(_i) or "nobody"}</span>. '
                    f'It is rebuilt on the fixtures that FOLLOW it, which is the only '
                    f'thing a Wildcard is for.</div></div>'), unsafe_allow_html=True)
        except Exception:
            # A Python repr in the middle of the page tells the reader nothing
            # they can act on. The detail belongs in the log.
            logger.exception("route walkthrough failed")
            st.markdown(_one_line(
                f'<div style="{CARD}margin-top:10px;padding:12px 14px;">'
                f'<div style="font-size:13px;color:{V("text")};">'
                f'The week-by-week walkthrough could not be built for this route. '
                f'The route comparison below is unaffected.</div></div>'),
                unsafe_allow_html=True)

    _sec("The routes, priced against each other", icon="alt_route")
    st.caption("A Bench Boost needs 15 playing assets, which costs XI strength every "
               "week you carry it. The Wildcard is what repairs that.")
    try:
        routes_df, dil = _routes(SOLVE_BOARD, budget, risk, tuple(excluded),
                                 _freshness.board_stamp(SOLVE_BOARD, PTS_COL))
    except Exception:
        routes_df, dil = pd.DataFrame(), None
        logger.exception("route comparison failed")
        st.caption("The route comparison could not be built. Try a different "
                   "budget or clear a veto.")

    if dil and dil.get("break_even_lo") is not None:
        st.markdown(_one_line(f"""
        <div style="{CARD}border-left:3px solid {V('gold')};margin-bottom:12px;">
        <div style="font-size:10px;font-weight:800;letter-spacing:0.18em;color:{V('gold')};
        text-transform:uppercase;margin-bottom:4px;">Bench Boost clock</div>
        <div style="font-size:14px;color:{V('text')};line-height:1.6;">
        An all-playing fifteen costs <b>{dil['arms'][0]['dilution_per_gw']:.1f} pts a
        gameweek</b> to carry and the chip returns <b>{dil['arms'][0]['bb_gain']:.0f}
        pts</b> once. Break-even is <b>{dil['break_even_lo']:.1f} to
        {dil['break_even_hi']:.1f} gameweeks</b> · play the Boost early and the reset
        has to follow inside that window.</div></div>"""), unsafe_allow_html=True)

    if not routes_df.empty:
        best = routes_df.iloc[0]
        st.markdown(_one_line(f"""
        <div style="{CARD}border-left:3px solid {V('mint')};margin-bottom:12px;">
        <div style="font-size:10px;font-weight:800;letter-spacing:0.18em;color:{V('mint')};
        text-transform:uppercase;margin-bottom:4px;">Best route on this squad</div>
        <div style="font-size:14px;color:{V('text')};line-height:1.6;">
        <b>{best['label']}</b> · {best['points']:.0f} pts over GW1-19,
        <b>{best['vs_baseline']:+.0f}</b> against holding both chips.</div></div>"""),
            unsafe_allow_html=True)
        rt = routes_df.copy()
        rt.columns = ["route", "bb", "wc", "pts", "vs"]
        T.render(rt.to_dict("records"), [
            T.col_text("route", "Route"),
            T.col_num("bb", "BB GW", fmt="%.0f"),
            T.col_num("wc", "WC GW", fmt="%.0f"),
            T.col_bar("pts", "GW1-19 pts", max_value=float(rt["pts"].max() or 1)),
            T.col_num("vs", "vs holding", fmt="%+.0f",
                      color_fn=lambda v: theme.fill("mint") if v > 0 else theme.fill("red")),
        ], key="routes_tbl", row_key="bb", max_height=280)
        st.caption("Fixture-ease model only. It prices the Bench Boost honestly but "
                   "UNDERSTATES a lone Wildcard: most of a wildcard's value is "
                   "repairing injuries the model cannot see, and moving early on "
                   "price risers to build team value.")

    st.markdown("**The goalkeeper trap.** For the season you want one playing keeper "
                "and a £4.0m dead slot. A Bench Boost needs BOTH keepers at £4.5m+ so "
                "both can score, and carrying that second keeper all year is waste. "
                "That is the case for boosting early and resetting out of it.")


# ── Full table ────────────────────────────────────────────────────────────────
with tab_all:
    f1, f2 = st.columns([2, 3])
    with f1:
        pos_f = st.multiselect("Position", POS_ORDER, default=[], key="tbl_pos",
                               label_visibility="collapsed", placeholder="All positions")
    with f2:
        sort_by = st.radio("Sort", ["Season", "Per £m", "Price", "Owned"],
                           horizontal=True, key="tbl_sort", label_visibility="collapsed")
    t = board[board["position"].isin(pos_f)] if pos_f else board
    price = pd.to_numeric(t["actual_price"], errors="coerce")
    season = pd.to_numeric(t[PTS_COL], errors="coerce")
    t = t.assign(_per_m=(season / price.clip(lower=0.1)))
    key = {"Season": PTS_COL, "Per £m": "_per_m", "Price": "actual_price",
           "Owned": "ownership"}[sort_by]
    t = t.nlargest(60, key)
    rows = []
    for _, a in t.iterrows():
        code = int(a["code"])
        p = float(a["actual_price"])
        s = float(a.get(PTS_COL) or 0)
        rows.append({
            "code": code, "web_name": a["web_name"], "team_short": a.get("team_name", ""),
            "position": a["position"], "actual_price": p,
            "verdict": str(a.get("verdict", "")),
            "season": s, "per_m": s / p if p else 0,
            "surprise": float(a.get("pricing_surprise") or 0),
            "nailed": a.get("ffh_nailedness"),
            "own": float(a.get("ownership") or 0),
            "confidence": a.get("consensus_confidence", a.get("confidence", "")),
        })
    pick = _click(T.render(rows, [
        T.col_face("code", url_fn=player_photo_url),
        T.col_player("web_name", "Player", sub="team_short", action="inspect"),
        T.col_chip("position", "Pos", color_fn=theme.pos_color),
        T.col_chip("verdict", "Verdict",
                   color_fn=lambda v: theme.fill(VERDICT_META.get(v, ("muted2", ""))[0] + "-v")
                   if VERDICT_META.get(v, ("muted2", ""))[0] != "muted"
                   else theme.fill("chip-bg")),
        T.col_num("actual_price", "£m", fmt="%.1f"),
        T.col_num("surprise", "vs model", fmt="%+.1f",
                  color_fn=lambda v: theme.fill("mint") if v > 0 else theme.fill("red")),
        T.col_bar("season", "Season", max_value=_bar_max(rows, "season", "season")),
        T.col_bar("per_m", "Per £m", max_value=_bar_max(rows, "per_m", "per_m"),
                  color="gold"),
        T.col_num("nailed", "Nailed", fmt="%.2f"),
        T.col_num("own", "Owned %", fmt="%.1f"),
        T.col_chip("confidence", "Conf.", color_fn=_conf_color),
    ], key="all_tbl", max_height=520), "_all_nonce")
    if pick and pick.get("action") == "inspect":
        _player_dialog(int(pick["id"]))


st.markdown(_one_line(
    f'<div style="font-size:11px;color:{V("muted2")};margin-top:18px;">'
    f'Projections blend our carryover model (9 season-pairs, Spearman ~0.4, '
    f'+/-38 pt average error) with Fantasy Football Scout and Fantasy Football Hub. '
    f'Snapshots are manual and local. Re-check minutes and set-piece roles once '
    f'{NEXT_SEASON} line-ups firm up.</div>'), unsafe_allow_html=True)
