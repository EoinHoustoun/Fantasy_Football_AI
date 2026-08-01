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
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from components import ff_table as T
from components.animations import inject_global_animations
from components.pitch_view import render_squad_pitch
from components.team_identity import face_html, player_photo_url, team_dot
from config import LAST_COMPLETE_SEASON, NEXT_SEASON
from analytics.value_verdicts import VERDICTS
from ui import charts
from ui import theme
from ui.theme import var as V

inject_global_animations()

POS_ORDER = ["GKP", "DEF", "MID", "FWD"]
CARD = (f"background:{V('card')};border:1px solid {V('line')};"
        f"border-radius:14px;padding:14px 16px;")

SQUAD_LIMITS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MINIMUMS = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
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
    weeks = [w for w in ledger["weeks"] if w["moves"]]
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
        for i, (out, inn) in enumerate(w["moves"].items()):
            free = i < w["free_used"]
            tag = ("FREE" if free else "-4")
            tok = "mint" if free else "red"
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
        meta = ("%d move%s, %d free available%s"
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
# Enough letters to label every saved draft · "compare all" can pass
# thirteen, and a repeated letter is worse than no letter at all.
_ID_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ID_TOKENS = ["mint", "gold", "cyan", "mag", "orange", "red"]
_ID_SHAPES = ["circle", "square", "change_history", "diamond", "hexagon", "star"]


def _draft_identities(names: List[str]) -> Dict[str, Dict]:
    out = {}
    for i, nm in enumerate(names):
        out[nm] = {"letter": _ID_LETTERS[i % len(_ID_LETTERS)],
                   "token": _ID_TOKENS[i % len(_ID_TOKENS)],
                   "shape": _ID_SHAPES[i % len(_ID_SHAPES)],
                   "colour": theme.fill(_ID_TOKENS[i % len(_ID_TOKENS)])}
    return out


def _badge(ident: Dict, size: int = 22) -> str:
    """The lettered chip that stands in for a draft anywhere it is referenced."""
    return (f'<span style="display:inline-grid;place-items:center;'
            f'width:{size}px;height:{size}px;border-radius:7px;flex-shrink:0;'
            f'background:{ident["colour"]};color:#06251A;'
            f'font-family:var(--ff-display);font-size:{int(size * 0.55)}px;'
            f'font-weight:900;line-height:1;'
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


def _range_bands(ranked: List[Dict], colour: Dict, window) -> str:
    """Outcome ranges as HTML bands · overlap is the answer.

    Drawn by hand rather than in ECharts: a floating bar (lo to hi with a tick at
    the mean) is awkward to encode in a charting library and easy to get subtly
    wrong, and here the whole point is that the reader can see at a glance
    whether two ranges overlap. Absolute positioning makes that exact.
    """
    lo_all = min(d["total_lo"] for d in ranked)
    hi_all = max(d["total_hi"] for d in ranked)
    span = (hi_all - lo_all) or 1.0
    pad = span * 0.04
    lo_all, hi_all = lo_all - pad, hi_all + pad
    span = hi_all - lo_all

    def pct(v):
        return (v - lo_all) / span * 100.0

    best = ranked[0]["total_mean"]
    rows = []
    for d in ranked:
        c = colour[d["name"]]
        left, width = pct(d["total_lo"]), pct(d["total_hi"]) - pct(d["total_lo"])
        rows.append(
            f'<div style="display:grid;grid-template-columns:190px 1fr 74px;'
            f'align-items:center;gap:12px;margin-bottom:9px;">'
            f'<div style="font-size:12px;font-weight:600;color:{V("text")};'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" '
            f'title="{d["name"]}">{d["name"]}</div>'
            f'<div style="position:relative;height:22px;border-radius:6px;'
            f'background:{V("chip-bg")};">'
            f'<div style="position:absolute;top:0;bottom:0;left:{left:.2f}%;'
            f'width:{width:.2f}%;background:{c};opacity:0.34;border-radius:6px;'
            f'border:1px solid {c};"></div>'
            f'<div style="position:absolute;top:-2px;bottom:-2px;'
            f'left:{pct(d["total_mean"]):.2f}%;width:3px;background:{c};'
            f'border-radius:2px;"></div></div>'
            f'<div class="ff-display" style="font-size:15px;font-weight:800;'
            f'color:{c};text-align:right;">{d["total_mean"]:.0f}'
            f'<span style="font-size:10px;font-weight:600;color:{V("muted2")};'
            f'display:block;">{d["total_mean"] - best:+.0f}</span></div></div>')
    return _one_line(
        f'<div style="{CARD}">' + "".join(rows)
        + f'<div style="display:flex;justify-content:space-between;'
        f'font-size:10px;color:{V("muted2")};margin-top:2px;">'
        f'<span>{lo_all:.0f}</span>'
        f'<span>points, GW{window[0]} to GW{window[1]}</span>'
        f'<span>{hi_all:.0f}</span></div></div>')


# ── Substitution rules ────────────────────────────────────────────────────────
# A legal XI is exactly one keeper plus at least three defenders, two midfielders
# and one forward. That leaves four free slots, so a 3-4-3, a 3-5-2, a 4-4-2 and
# a 5-2-3 are all legal and a 2-5-3 is not. Every swap on the pitch is checked
# against this rather than assumed, which is what lets the bench highlight only
# the players who can actually come on.
def _formation_of(codes, pos_by_code: Dict) -> Dict[str, int]:
    out = {p: 0 for p in POS_ORDER}
    for c in codes:
        p = pos_by_code.get(int(c))
        if p in out:
            out[p] += 1
    return out


def _is_legal_xi(codes, pos_by_code: Dict) -> bool:
    if len(codes) != 11:
        return False
    f = _formation_of(codes, pos_by_code)
    return (f["GKP"] == 1 and f["DEF"] >= XI_MINIMUMS["DEF"]
            and f["MID"] >= XI_MINIMUMS["MID"] and f["FWD"] >= XI_MINIMUMS["FWD"])


def _legal_swaps(out_code: int, xi: set, squad_codes: List[int],
                 pos_by_code: Dict) -> List[int]:
    """Who could come on for this player without breaking the formation.

    A keeper can only ever be swapped for the other keeper. Outfield swaps are
    legal whenever the resulting eleven still clears the minimums, which is why
    taking off a third defender usually only allows another defender in.
    """
    out_code = int(out_code)
    on_bench = [int(c) for c in squad_codes if int(c) not in xi]
    ok = []
    for cand in on_bench:
        trial = (set(xi) - {out_code}) | {cand}
        if _is_legal_xi(trial, pos_by_code):
            ok.append(cand)
    return ok


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
from ui.value_board import (DRAFT_STRATEGIES, SPRINT_STRATEGY, SPRINT_WINDOW,
                            build_board, solve_draft)

board, scout, price_bt, validation = build_board()
if board is None:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

HAS_CONSENSUS = "consensus_points" in board.columns
PTS_COL = "consensus_points" if HAS_CONSENSUS else "projected_points"
NAMES = sorted(board["web_name"].tolist())


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _club_fixtures() -> Dict:
    """(team_id, gw) -> [(opponent short, is_home, fdr), ...] for 26/27.

    Difficulty comes from Fantasy Football Scout's model ratings where a ticker
    snapshot exists, because theirs vary by venue and opponent form while FPL's
    are fixed per club.
    """
    from components.fixture_ticker import load_scout_ticker
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    bs = fetch_bootstrap()
    short = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    fx = get_fixtures_df(fetch_fixtures(), bs)
    scout_fdr = load_scout_ticker() or {}
    out: Dict = {}
    for _, r in fx.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        gw = int(r["gameweek"])
        h, a = int(r["home_team_id"]), int(r["away_team_id"])
        hs, as_ = short.get(h, "?"), short.get(a, "?")
        out.setdefault((h, gw), []).append(
            (as_, True, float(scout_fdr.get((hs, gw), r["home_fdr"]))))
        out.setdefault((a, gw), []).append(
            (hs, False, float(scout_fdr.get((as_, gw), r["away_fdr"]))))
    return out


_FIX = _club_fixtures()


# Bump when GwProjection gains a method or changes behaviour. `cache_resource`
# holds the LIVE object across code edits, so without a version in the key an
# edited class keeps serving the old instance and you get AttributeError on a
# method that plainly exists in the file.
_PROJ_VERSION = 2


@st.cache_resource(show_spinner=False)
def _projector(_board: pd.DataFrame, _fix: Dict, _stamp: int, _version: int):
    from analytics import gw_projection
    return gw_projection.build(_board, _fix)


PROJ = _projector(board, _FIX, len(board), _PROJ_VERSION)
MATCH_WINDOW = PROJ.window


def _fixtures_for(team_id: int, gw: int, n: int = 3) -> List[Dict]:
    out = []
    for g in range(gw, gw + n):
        fx = _FIX.get((int(team_id), g), [])
        if not fx:
            out.append({"opp": "BLANK", "blank": True, "fdr": 3, "home": True})
            continue
        for opp, home, fdr in fx:
            out.append({"opp": opp, "home": home, "fdr": fdr})
    return out[:n]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _defcon_per90() -> pd.DataFrame:
    """Defensive contributions per 90 last season, plus how often the threshold hit.

    The mean flatters a player who spikes once · DEFCON points are a THRESHOLD
    (10 CBIT for a defender, 12 for a midfielder), so the hit rate is what
    converts to points week to week.
    """
    from data.processors.archive import load_gw_archive
    a = load_gw_archive()
    a = a[(a["season"] == LAST_COMPLETE_SEASON) & (a["starts"] == 1)]
    if a.empty:
        return pd.DataFrame()
    a = a.assign(_thr=a["position"].map({"DEF": 10, "MID": 12}).fillna(999))
    a = a.assign(_hit=(a["defensive_contribution"] >= a["_thr"]).astype(float))
    g = a.groupby("code").agg(dc_per_start=("defensive_contribution", "mean"),
                              dc_hit_rate=("_hit", "mean"),
                              starts=("starts", "sum"), mins=("minutes", "sum"))
    g["dc_per90"] = (g["dc_per_start"] * 90.0
                     / (g["mins"] / g["starts"]).clip(lower=1)).round(2)
    return g.round(2)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _last_season_stats() -> pd.DataFrame:
    from data.processors.archive import load_season_summary
    s = load_season_summary()
    s = s[s["season"] == LAST_COMPLETE_SEASON]
    keep = ["goals", "assists", "xg", "xa", "xgi", "defcon_points", "minutes",
            "total_points", "ppg", "clean_sheets", "bonus", "starts_total",
            "games_played"]
    return s.set_index("code")[[c for c in keep if c in s.columns]]


DEFCON = _defcon_per90()


# ── Hero ──────────────────────────────────────────────────────────────────────
# A single compact line rather than a 40px hero. The sidebar already says which
# page this is, and every pixel above the pitch is a pixel the pitch does not get.
_HERO = _one_line(f"""
<div class="fplh-animate-in" style="display:flex;align-items:center;gap:12px;
     flex-wrap:wrap;padding:0 0 6px;font-family:'Inter',sans-serif;">
  <div class="ff-display" style="font-size:24px;font-weight:900;color:{V('text')};">
    {NEXT_SEASON} Draft</div>
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
    st.warning("No saved drafts. Restore the presets in Compare drafts.")
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
    squad = (head.replace("Optimal + ", "+")
                 .replace("Optimal", "Base")
                 .replace("Fernandes", "Fern").replace("Mosquera", "Mosq")
                 .replace("Haaland", "Haal").replace(" + ", "+"))
    return f"{icon} {squad} {chip}".strip() if chip else f"{icon} {squad}"


# Your own drafts first · a preset is a starting point, the one you built is the
# one you came back for.
_opts = sorted(list(_SAVED_BY_NAME),
               key=lambda n: (bool(_SAVED_BY_NAME[n].get("preset")),
                              not DR.has_squad(_SAVED_BY_NAME[n]), n))
_default = st.session_state.get(
    "planner_draft",
    next((n for n in _opts if "BB1 → WC4" in n), _opts[0]))
if _default not in _opts:
    _default = _opts[0]

_hero, _ctrl = st.columns([4, 1])
with _hero:
    st.markdown(_HERO, unsafe_allow_html=True)
with _ctrl:
    _open_controls = st.popover(":material/tune: Tune", use_container_width=True)

_pick = st.pills("Draft", options=_opts, default=_default, key="planner_draft",
                 format_func=_draft_label, label_visibility="collapsed")
if _pick is None:
    _pick = _default
_spec = _SAVED_BY_NAME[_pick]

# One line under the pills saying what the selection actually IS. A selector
# that only echoes its own label teaches you nothing; this carries the kind of
# draft, the chip plan and the players you insisted on.
_kind = ("Your saved fifteen" if DR.has_squad(_spec)
         else "Route experiment" if _spec["name"].startswith("Route")
         else "Preset")
_facts = []
if _spec.get("locks"):
    _facts.append("locked: " + ", ".join(_spec["locks"]))
if _spec.get("bench_boost_gw"):
    _facts.append(f"Bench Boost GW{_spec['bench_boost_gw']}")
if _spec.get("wildcard_gw"):
    _facts.append(f"Wildcard GW{_spec['wildcard_gw']}")
if not _facts:
    _facts.append("no locks, no chips")
st.markdown(_one_line(
    f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
    f'margin:2px 0 10px;font-size:12.5px;">'
    f'<span style="background:{V("chip-bg")};color:{V("mint")};border-radius:5px;'
    f'padding:2px 8px;font-size:10px;font-weight:700;letter-spacing:0.08em;'
    f'text-transform:uppercase;">{_kind}</span>'
    f'<span style="color:{V("text")};font-weight:600;">{_spec["name"]}</span>'
    f'<span style="color:{V("muted")};">{" · ".join(_facts)}</span></div>'),
    unsafe_allow_html=True)

with _open_controls:
    mode = _spec.get("strategy", "⚖️ Optimal value")

    # The dials start from the chosen draft and are overrides from there. Keying
    # them on the draft id is what makes them re-read when you switch draft
    # rather than carrying the previous one's settings across.
    _k = _spec["id"]
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
        two_att = st.checkbox(
            "Allow 2 attackers from the same club",
            value=bool(_spec.get("two_attackers", False)), key=f"twoatt_{_k}",
            help="The standing rule is one attack-correlated player per club, so a "
                 "bad week for that club does not sink two picks.")
    l1, l2 = st.columns(2)
    with l1:
        locked = st.multiselect(
            "Lock in · players I definitely want", options=NAMES,
            default=[n for n in _spec.get("locks", []) if n in NAMES],
            key=f"lock_{_k}",
            help="These go into the fifteen no matter what. A lock beats a veto. "
                 "This is where a premium call lives: locking Haaland IS the "
                 "Haaland draft.")
    with l2:
        excluded = st.multiselect(
            "Don't trust · exclude these players", options=NAMES,
            default=[n for n in _spec.get("vetoes", []) if n in NAMES],
            key=f"veto_{_k}",
            help="Veto anyone you're not convinced by.")

    _bb, _wc = _spec.get("bench_boost_gw"), _spec.get("wildcard_gw")
    if _bb or _wc:
        st.caption("Chip plan on this draft: "
                   + " then ".join(filter(None, [
                       f"Bench Boost GW{_bb}" if _bb else "",
                       f"Wildcard GW{_wc}" if _wc else ""]))
                   + ". The planner shows the squad; the chips are priced in "
                     "Compare drafts.")

    # ── Save what is on screen as a draft of your own ────────────────────────
    # Saving belongs where the draft is built, not only in the comparison tab.
    # You tune the dials here, so this is where "keep this one" is asked.
    st.markdown(f'<div style="height:1px;background:{V("line")};margin:14px 0 10px;"></div>',
                unsafe_allow_html=True)
    _n1, _n2, _n3 = st.columns([3, 2, 2])
    with _n1:
        _new_name = st.text_input("Save these settings as", key="ctrl_save_name",
                                  placeholder="Name your draft")
    with _n2:
        _new_bb = st.selectbox("Bench Boost", ["None"] + [f"GW{g}" for g in range(1, 13)],
                               index=0 if not _bb else _bb, key="ctrl_save_bb")
    with _n3:
        _new_wc = st.selectbox("Wildcard", ["None"] + [f"GW{g}" for g in range(2, 15)],
                               index=0 if not _wc else max(0, _wc - 1), key="ctrl_save_wc")
    if st.button(":material/bookmark_add: Save as a new draft", key="ctrl_save_go",
                 use_container_width=True, disabled=not _new_name.strip()):
        DR.save_draft(_new_name.strip(), {
            "strategy": mode, "locks": list(locked), "vetoes": list(excluded),
            "budget": float(budget), "risk": float(risk), "opening": float(opening),
            "minutes_gate": float(minutes_gate), "two_attackers": bool(two_att),
            "bench_boost_gw": None if _new_bb == "None" else int(_new_bb[2:]),
            "wildcard_gw": None if _new_wc == "None" else int(_new_wc[2:]),
        })
        st.session_state["planner_draft"] = _new_name.strip()
        st.success(f"Saved **{_new_name.strip()}**. It is now in the picker and in "
                   f"Compare drafts.")
        st.rerun()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _window_map(lo: int, hi: int) -> tuple:
    from analytics.season_opener import opening_ease
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    fx = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())
    oe = opening_ease(fx, lo, hi)
    return tuple(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))


def _tuned_board(gate: float) -> pd.DataFrame:
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


SOLVE_BOARD = _tuned_board(minutes_gate)
_omap, _oweight = (), opening
if mode == SPRINT_STRATEGY:
    _omap, _oweight = _window_map(*SPRINT_WINDOW), 1.0

_SAVED_SQUAD = None
if DR.has_squad(_spec):
    _codes = [int(c) for c in _spec["squad"] if int(c) in set(board["code"].astype(int))]
    if len(_codes) == 15:
        _SAVED_SQUAD = _codes

res = None
if _SAVED_SQUAD is None:
    res = solve_draft(SOLVE_BOARD, mode, budget, risk, tuple(excluded), _oweight,
                      force_names=tuple(locked), opening_map=_omap,
                      max_attackers_per_club=2 if two_att else 1)
if _SAVED_SQUAD is None and res is None:
    why = ""
    if locked:
        lk = board[board["web_name"].isin(locked)]
        spend = float(lk["actual_price"].sum())
        over = {p: n for p, n in lk["position"].value_counts().to_dict().items()
                if n > SQUAD_LIMITS.get(p, 15)}
        if over:
            why = (" You locked more players in a position than a squad allows: "
                   + ", ".join(f"{n}x {p}" for p, n in over.items()) + ".")
        elif spend > budget - (15 - len(locked)) * 4.0:
            why = (f" Your locks cost £{spend:.1f}m, leaving under £4.0m a head for "
                   f"the remaining {15 - len(locked)} · that cannot be filled.")
        else:
            why = (" It is likely a club limit: at most 3 per club, and this draft "
                   "allows only 1 attacker and 1 defender per club.")
    st.error("Solver found no feasible squad." + why
             + " Widen the budget, lower risk, or drop a lock.")
    st.stop()

if _SAVED_SQUAD is not None:
    SOLVED = board[board["code"].isin(_SAVED_SQUAD)].copy()
    SOLVED = SOLVED.set_index("code").reindex(_SAVED_SQUAD).reset_index()
    SOLVED["price"] = SOLVED["actual_price"]
    SOLVED["pts"] = SOLVED[PTS_COL]
    SOLVED["is_captain"] = False
else:
    SOLVED = res["squad"]

if locked and res is not None:
    # What the conviction actually costs · the same solve without the locks. This
    # is the whole Fernandes question: owning him is only wrong if spreading his
    # money returns more.
    free = solve_draft(SOLVE_BOARD, mode, budget, risk, tuple(excluded), _oweight,
                       opening_map=_omap, max_attackers_per_club=2 if two_att else 1)
    lk = board[board["web_name"].isin(locked)]
    spend = float(lk["actual_price"].sum())
    cost = (res["xi_points"] - free["xi_points"]) if free else None
    _tok = "mint" if (cost is None or cost > -12) else "orange" if cost > -35 else "red"
    _verdict = ("" if cost is None else
                " · essentially free" if cost > -12 else
                " · a real price" if cost > -35 else " · an expensive conviction")
    st.markdown(_one_line(
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;'
        f'font-size:12.5px;margin:-4px 0 8px;">'
        f'{theme.icon("lock", 15, V(_tok))}'
        f'<span style="color:{V("muted")};">£{spend:.1f}m committed, '
        f'£{budget - spend:.1f}m for the other {15 - len(locked)}</span>'
        + (f'<span style="color:{V(_tok)};font-weight:700;">'
           f'{cost:+.0f} XI pts vs the free optimum{_verdict}</span>'
           if cost is not None else "")
        + '</div>'), unsafe_allow_html=True)

st.session_state.setdefault("draft_swaps", {})
st.session_state.setdefault("draft_axe", None)
st.session_state.setdefault("draft_bench", set())
st.session_state.setdefault("sub_from", None)     # player tapped to be subbed
st.session_state.setdefault("xi_override", {})    # {gw: set(codes)} manual XI
st.session_state.setdefault("draft_gw", 1)


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
        gw = int(st.session_state.get("draft_gw", 1))
    codes = [int(c) for c in SOLVED["code"]]
    for g in sorted(int(k) for k in st.session_state["draft_swaps"]):
        if g > int(gw):
            break
        for out, inn in st.session_state["draft_swaps"][g].items():
            if int(out) in codes:
                codes[codes.index(int(out))] = int(inn)
    return _squad_from_codes(codes)


def _transfer_ledger(upto_gw: int) -> Dict:
    """Free transfers, hits and what each week's moves cost.

    One free transfer a gameweek from GW2, banked up to FT_CAP, spent oldest
    first. Anything past the free allowance costs 4 points. GW1 is the draft
    itself, so it is free by definition and never appears in the ledger.

    Saving transfers early is worth more than it looks: a bank of five in GW6 is
    the flexibility to react once there is real information, which is a large
    part of why an early Bench Boost and Wildcard are attractive.
    """
    from analytics.squad_planner import FT_CAP
    swaps = st.session_state["draft_swaps"]
    weeks, avail, total_hits = [], 0, 0
    for g in range(2, int(upto_gw) + 1):
        avail = min(FT_CAP, avail + 1)
        moves = swaps.get(g, {})
        used = len(moves)
        free_used = min(used, avail)
        hits = used - free_used
        total_hits += hits
        weeks.append({
            "gw": g, "moves": moves, "used": used,
            "free_used": free_used, "hits": hits, "cost": hits * 4,
            "available_before": avail,
        })
        avail = max(0, avail - used)
    return {"weeks": weeks, "available_now": avail, "hits": total_hits,
            "points_cost": total_hits * 4, "cap": FT_CAP}


# ── Player evidence ───────────────────────────────────────────────────────────
def _profile(code: int) -> Dict:
    from analytics.head_to_head import player_profile
    row = board[board["code"] == int(code)]
    if row.empty:
        return {}
    return player_profile(row.iloc[0], PTS_COL, DEFCON, PROJ)


def _set_piece_line(row) -> str:
    """Penalties and set pieces from the OFFICIAL FPL order · fact, not a guess."""
    p_ord, f_ord = _num_safe(row.get("pens_order")), _num_safe(row.get("fk_order"))
    c_ord = _num_safe(row.get("corners_order"))
    bits = []
    if p_ord == 1:
        bits.append(f'<span style="background:{V("gold-v")};color:#000;border-radius:5px;'
                    f'padding:2px 8px;font-size:10px;font-weight:900;">ON PENALTIES</span>')
    elif p_ord in (2, 3):
        bits.append(f'<span style="color:{V("gold")};font-size:11px;font-weight:800;">'
                    f'Penalties #{p_ord} in the queue</span>')
    if f_ord in (1, 2):
        bits.append(f'<span style="color:{V("cyan")};font-size:11px;font-weight:800;">'
                    f'Free kicks #{f_ord}</span>')
    if c_ord in (1, 2):
        bits.append(f'<span style="color:{V("cyan")};font-size:11px;font-weight:800;">'
                    f'Corners #{c_ord}</span>')
    if not bits:
        return (f'<div style="font-size:11px;color:{V("muted2")};margin:6px 0;">'
                f'Not on penalties or first-choice set pieces.</div>')
    return ('<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;'
            'margin:6px 0;">' + "".join(bits) + '</div>')


def _keep_verdict(p: Dict, row: pd.Series) -> str:
    """Should he be in the squad · the question the card exists to answer.

    Deliberately built from the things that decide it rather than from the
    headline projection: minutes first, then value for money, then whether the
    models actually agree on the number.
    """
    pos = p.get("position", "")
    peers = board[(board["position"] == pos)
                  & (board["actual_price"].between(p["price"] - 0.6, p["price"] + 0.6))]
    per_m = pd.to_numeric(peers[PTS_COL], errors="coerce") / \
        pd.to_numeric(peers["actual_price"], errors="coerce").clip(lower=0.1)
    rank = int((per_m > (p.get("per_m") or 0)).sum()) + 1
    n = max(len(peers), 1)

    nailed = p.get("mins")
    conf = p.get("confidence", "")
    good, bad = [], []
    if pd.notna(nailed):
        (good if nailed >= 75 else bad).append(
            f"{nailed:.0f} minutes a game expected early")
    if rank <= max(3, n // 5):
        good.append(f"{rank} of {n} on points per £m in his price band")
    elif rank > n // 2:
        bad.append(f"only {rank} of {n} on points per £m in his price band")
    if conf == "High":
        good.append("all three models agree on the number")
    elif conf == "Low":
        bad.append("the models disagree, so the number is a guess")
    if _num_safe(row.get("pens_order")) == 1:
        good.append("he takes the penalties")

    if len(good) >= 2 and not bad:
        head, tok = "Keep him.", "mint"
    elif bad and not good:
        head, tok = "Hard to justify.", "red"
    elif len(bad) > len(good):
        head, tok = "Leaning against.", "orange"
    else:
        head, tok = "Defensible pick.", "gold"

    body = ""
    if good:
        body += "In favour: " + "; ".join(good) + ". "
    if bad:
        body += "Against: " + "; ".join(bad) + "."
    return _one_line(
        f'<div style="{CARD}border-left:3px solid {V(tok)};margin:10px 0 12px;">'
        f'<div class="ff-display" style="font-size:17px;font-weight:900;'
        f'color:{V(tok)};margin-bottom:3px;">{head}</div>'
        f'<div style="font-size:12.5px;color:{V("muted")};line-height:1.5;">{body}</div>'
        f'</div>')


# ── Grading a stat ────────────────────────────────────────────────────────────
# "108 projected points" means nothing on its own. Every number in the player
# card is graded against the players you would actually consider instead, and the
# grade is the colour · so the card can be read at a glance rather than parsed.
#
# Two kinds of grade, because two kinds of number:
#   RANK      compare against every player in his position (points, per £m, per
#             90). Top 10% is good, top third is fair, the rest is not.
#   THRESHOLD compare against a fixed bar the rules define (DEFCON). Clearing it
#             is what pays, being close is worth something, below is nothing.
GRADE_TOKENS = {"good": "mint", "ok": "gold", "poor": "red", "none": "muted2"}

# FPL's defensive-contribution bar: 10 CBIT for a defender, 12 for a midfielder,
# confirmed by Eoin and matching what `_defcon_per90` scores against. Clearing it
# pays a flat 2 points, which is why the HIT RATE matters more than the average:
# a player who averages 11 by spiking to 20 once and sitting at 8 otherwise earns
# the bonus far less often than the mean suggests. Forwards and keepers have no
# route to it.
DEFCON_THRESHOLD = {"DEF": 10.0, "MID": 12.0}
DEFCON_CLOSE = 0.8          # within 20% of the bar counts as close


def _grade_rank(pct: float) -> str:
    """Percentile within position, where 1.0 is the best player."""
    if pct >= 0.90:
        return "good"
    if pct >= 0.67:
        return "ok"
    return "poor"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _position_ranks(_stamp: int) -> Dict:
    """Per-position ordered lists for points, points per £m and points per 90.

    Restricted to players the models actually rate, so a rank means "of the
    players worth considering" rather than "of everyone in the game".
    """
    out = {}
    for pos in POS_ORDER:
        d = board[(board["position"] == pos)
                  & (pd.to_numeric(board[PTS_COL], errors="coerce") >= 40)].copy()
        if d.empty:
            continue
        price = pd.to_numeric(d["actual_price"], errors="coerce").clip(lower=0.1)
        season = pd.to_numeric(d[PTS_COL], errors="coerce")
        nail = pd.to_numeric(d.get("ffh_nailedness"), errors="coerce")
        mins = (nail.fillna(pd.to_numeric(d["projected_minutes"], errors="coerce")
                            / 3420.0) * 3420.0).clip(lower=90)
        out[pos] = {
            "season": sorted(season.dropna().tolist()),
            "per_m": sorted((season / price).dropna().tolist()),
            "per_90": sorted((season / (mins / 90.0)).dropna().tolist()),
            "n": len(d),
        }
    return out


def _rank_of(value: float, sorted_vals: List[float]) -> Tuple[int, int, float]:
    """(rank from the top, total, percentile) for a value in a sorted list."""
    n = len(sorted_vals)
    if not n or value is None or pd.isna(value):
        return 0, n, 0.0
    below = sum(1 for v in sorted_vals if v < value)
    return n - below, n, below / n


def _graded_tiles(code: int, row: pd.Series, p: Dict) -> List:
    """The five headline numbers, each graded and each carrying its rank."""
    pos = str(row.get("position", ""))
    ranks = _position_ranks(len(board)).get(pos, {})
    gw = int(st.session_state.get("draft_gw", 1))

    def rank_tile(icon, label, value, key, fmt="%.0f"):
        r, n, pct = _rank_of(value, ranks.get(key, []))
        if not n:
            return (icon, label, fmt % (value or 0), "no comparison set", "muted2")
        return (icon, label, fmt % value,
                f"{_ordinal(r)} of {n} {pos}", GRADE_TOKENS[_grade_rank(pct)])

    tiles = [
        rank_tile("military_tech", "Season", float(row.get(PTS_COL) or 0), "season"),
        rank_tile("savings", "Per £m", p.get("per_m"), "per_m", "%.1f"),
        rank_tile("speed", "Per 90", p.get("per_90"), "per_90", "%.2f"),
    ]

    # This gameweek, against what a starting player is worth in a week.
    gw_pts = PROJ.points(code, gw)
    gw_tok = "good" if gw_pts >= 5 else "ok" if gw_pts >= 3.2 else "poor"
    gw_sub = ("not expected to play" if PROJ.misses(code, gw)
              else "expected this week")
    tiles.append(("sports_soccer", f"GW{gw}", f"{gw_pts:.1f}", gw_sub,
                  GRADE_TOKENS["none" if PROJ.misses(code, gw) else gw_tok]))

    # DEFCON against the bar the rules set, not against other players.
    thr = DEFCON_THRESHOLD.get(pos)
    dc = DEFCON.loc[code] if (not DEFCON.empty and code in DEFCON.index) else None
    if thr is None:
        tiles.append(("shield", "DEFCON", "n/a", f"no route to it as a {pos}",
                      GRADE_TOKENS["none"]))
    elif dc is None:
        tiles.append(("shield", "DEFCON / 90", "n/a", "no 25/26 record",
                      GRADE_TOKENS["none"]))
    else:
        per90 = float(dc.get("dc_per90") or 0)
        tok = ("good" if per90 >= thr else
               "ok" if per90 >= thr * DEFCON_CLOSE else "poor")
        hit = float(dc.get("dc_hit_rate") or 0) * 100
        tiles.append(("shield", "DEFCON / 90", f"{per90:.1f}",
                      f"bar {thr:.0f} for 2 pts · clears it {hit:.0f}% of starts",
                      GRADE_TOKENS[tok]))
    return tiles


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def _model_chart(row: pd.Series, code: int) -> None:
    """Where the three models land, on one axis.

    Three separate bars make you compare heights. One axis with three points
    makes the SPREAD the thing you see, which is the question actually being
    asked: do they agree, and by how much.
    """
    labels, values, cols = [], [], []
    for col, lab, tok in (("src_ours", "Ours", "mint"),
                          ("src_scout", "Scout", "gold"),
                          ("src_ffh", "Hub", "cyan")):
        v = row.get(col)
        if pd.notna(v):
            labels.append(lab)
            values.append(round(float(v), 0))
            cols.append(theme.fill(tok))
    if len(labels) < 2:
        st.info("Only one model rates this player, so there is nothing to "
                "cross-check. Treat the number as a single opinion.")
        return
    blend = float(row.get(PTS_COL) or 0)
    charts.render(charts.model_spread_option(labels, values, blend, cols),
                  height="180px", key=f"dlg_models_{code}")

    conf = str(row.get("consensus_confidence", "") or "")
    gap = max(values) - min(values)
    tok = CONF_TOKEN.get(conf, "muted")
    verdict = ("They agree, so the number is worth trusting."
               if conf == "High" else
               "They disagree enough that the middle is a guess. Decide this one "
               "on football, not on the decimal." if conf == "Low" else
               "Partial agreement · treat the range, not the midpoint, as the forecast.")
    st.markdown(_one_line(
        f'<div style="{CARD}border-left:3px solid {V(tok)};padding:10px 14px;">'
        f'<div style="font-size:13px;color:{V("text")};line-height:1.55;">'
        f'<b>{gap:.0f} points</b> between the most and least optimistic model. '
        f'{verdict}</div></div>'), unsafe_allow_html=True)


def _run_chart(code: int, row: pd.Series, team_id: int, key: str) -> None:
    """The opening run · expected points a week, coloured by fixture difficulty.

    Colour carries the WHY: green bars are kind fixtures, red are not, so the
    shape of the run is readable without a legend or a tooltip. The dashed line
    is expected minutes, because a tall bar on thin minutes is exactly the trap
    this chart exists to expose.
    """
    gws = list(range(1, 11))
    pts, opps, fdrs, mins = [], [], [], []
    for g in gws:
        pts.append(round(PROJ.points(code, g), 1))
        fx = _FIX.get((int(team_id), g), [])
        if fx:
            opps.append(" + ".join(o for o, _h, _f in fx))
            fdrs.append(sum(f for _o, _h, f in fx) / len(fx))
        else:
            opps.append("blank")
            fdrs.append(3)
        mins.append(PROJ.expected_minutes(code, g))

    charts.render(
        charts.fixture_run_option(gws, pts, opps, fdrs,
                                  minutes=mins if any(m is not None for m in mins) else None,
                                  fdr_colors=theme.FDR_COLORS),
        height="290px", key=key)

    nail, vol = row.get("ffh_nailedness"), row.get("ffh_mins_volatility")
    bits = []
    if MATCH_WINDOW:
        bits.append(f"GW{MATCH_WINDOW[0]}-{MATCH_WINDOW[-1]} are per-fixture "
                    f"forecasts; later weeks are the season projection shaped by "
                    f"difficulty")
    if pd.notna(nail):
        read = ("nailed on" if nail >= 0.9 else
                "a starter with rotation risk" if nail >= 0.7 else
                "a part-player right now" if nail >= 0.4 else "not expected to feature")
        bits.append(f"averages {float(nail) * 90:.0f} minutes a game · {read}")
    if pd.notna(vol) and float(vol) > 15:
        bits.append(f"minutes swing by {float(vol):.0f}, so the role is not settled")
    if bits:
        st.markdown(_one_line(
            f'<div style="font-size:12.5px;color:{V("muted")};line-height:1.55;'
            f'margin-top:4px;">' + ". ".join(b[0].upper() + b[1:] for b in bits)
            + '.</div>'), unsafe_allow_html=True)


def _band_chart(code: int, row: pd.Series, p: Dict, key: str) -> None:
    """Him against the players who cost the same.

    A season total means nothing without a price. This scales every axis against
    the median of his own position within a pound of his price, so the outer edge
    is "best of the players you could buy instead" rather than best in the game.
    """
    pos, price = str(row.get("position", "")), float(row.get("actual_price") or 0)
    # The comparison set is who you would ACTUALLY buy instead: same position,
    # half a million either way, and rated by the models. Without that last
    # filter the median is dragged down by two hundred squad players who never
    # start, and every pick looks like a bargain against it.
    band = board[(board["position"] == pos)
                 & (board["actual_price"].between(price - 0.5, price + 0.5))
                 & (pd.to_numeric(board[PTS_COL], errors="coerce") >= 40)]
    if len(band) < 4:
        band = board[(board["position"] == pos)
                     & (board["actual_price"].between(price - 1.0, price + 1.0))
                     & (pd.to_numeric(board[PTS_COL], errors="coerce") >= 25)]
    if len(band) < 4:
        st.info("Too few comparable players in his price band.")
        return

    def _med(col, default=0.0):
        v = pd.to_numeric(band.get(col), errors="coerce")
        return float(v.median()) if v is not None and v.notna().any() else default

    dc_band = DEFCON.reindex(band["code"].astype(int)).dropna(how="all") \
        if not DEFCON.empty else pd.DataFrame()
    dc_med = float(dc_band["dc_hit_rate"].median()) if not dc_band.empty else 0.0
    dc_his = 0.0
    if not DEFCON.empty and code in DEFCON.index:
        dc_his = float(DEFCON.loc[code].get("dc_hit_rate", 0) or 0)

    axes = [
        ("Season pts", float(row.get(PTS_COL) or 0), _med(PTS_COL, 1)),
        ("Per £m", (p.get("per_m") if pd.notna(p.get("per_m")) else 0),
         _med(PTS_COL, 1) / max(price, 0.1)),
        ("Minutes", float(row.get("ffh_nailedness") or 0) * 90,
         _med("ffh_nailedness", 0.7) * 90),
        ("DEFCON", dc_his * 100, dc_med * 100),
        ("Fixtures", float(row.get("opening_factor") or 1.0) * 100, 100.0),
        ("Agreement", (1 - float(row.get("model_spread") or 0.3)) * 100, 75.0),
    ]
    inds, his, theirs = [], [], []
    for name, mine, med in axes:
        top = max(mine, med) * 1.25 or 1.0
        inds.append({"name": name, "max": round(top, 1)})
        his.append(round(float(mine), 1))
        theirs.append(round(float(med), 1))
    charts.render(charts.radar_compare_option(inds, [
        (f"Typical £{price:.1f}m {pos}", theirs, theme.fill("muted2"), 0.10),
        (str(row["web_name"]), his, theme.pos_color(pos), 0.26),
    ]), height="330px", key=key)
    st.markdown(_one_line(
        f'<div style="font-size:12.5px;color:{V("muted")};line-height:1.55;">'
        f'Against the median {pos} you could buy instead at this price '
        f'({len(band)} players the models actually rate). Outside the grey shape '
        f'is where he wins.</div>'), unsafe_allow_html=True)


@st.dialog("Player", width="large")
def _player_dialog(code: int) -> None:
    m = board[board["code"] == code]
    if m.empty:
        st.info("Player not on the board.")
        return
    r = m.iloc[0]
    p = _profile(code)
    pos = str(r.get("position", ""))
    team_id = int(r.get("team_id", 0) or 0)

    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(face_html(code, int(r.get("team_code", 1) or 1), pos == "GKP", 92),
                    unsafe_allow_html=True)
    with c2:
        st.markdown(_one_line(
            f'<div class="ff-display" style="font-size:28px;font-weight:900;'
            f'color:{V("text")};">{r["web_name"]}</div>'
            f'<div style="font-size:13px;color:{V("muted")};margin-top:2px;">'
            f'{r.get("team_name", "")} · {pos} · £{float(r.get("actual_price") or 0):.1f}m '
            f'· {float(r.get("ownership") or 0):.1f}% owned</div>'),
            unsafe_allow_html=True)
        st.markdown(_set_piece_line(r), unsafe_allow_html=True)

    st.markdown(_keep_verdict(p, r), unsafe_allow_html=True)

    if bool(r.get("ffh_no_early_minutes", False)):
        st.warning(f"The match model expects **{float(r.get('ffh_exp_mins_mean') or 0):.0f} "
                   f"minutes a game** from him over "
                   f"GW{MATCH_WINDOW[0]}-{MATCH_WINDOW[-1]}. The season numbers below "
                   f"assume he plays: they are a scenario for later in the season, "
                   f"not a read on the opening weeks.")

    st.markdown(_strip(_graded_tiles(code, r, p)), unsafe_allow_html=True)
    st.markdown(_one_line(
        f'<div style="font-size:11.5px;color:{V("muted2")};margin:-6px 0 10px;">'
        f'Green beats most players in his position, amber is mid-table, red is '
        f'behind. DEFCON is graded against the rule\'s bar, not against other '
        f'players · clearing it is a flat 2 points.</div>'), unsafe_allow_html=True)
    t1, t2, t3, t4 = st.tabs([":material/insights: Opening run",
                              ":material/balance: Model agreement",
                              ":material/radar: Value for money",
                              ":material/history: Last season"])
    with t1:
        _run_chart(code, r, team_id, f"dlg_run_{code}")
        from components.fixture_ticker import player_fixture_strip, run_summary
        st.markdown(player_fixture_strip(_FIX, team_id, 1, 12), unsafe_allow_html=True)
        s6 = run_summary(_FIX, team_id, 1, 6)
        f6 = s6.get("mean_fdr")
        read = "kind" if (f6 or 3) <= 2.85 else "tough" if (f6 or 3) >= 3.2 else "average"
        st.markdown(_one_line(
            f'<div style="font-size:12.5px;color:{V("muted")};margin-top:4px;">'
            f'Opening six average <b>{f6 if f6 is not None else "n/a"}</b> difficulty '
            f'({read}), {s6["home"]} at home.</div>'), unsafe_allow_html=True)
    with t2:
        _model_chart(r, code)
    with t3:
        _band_chart(code, r, p, f"dlg_band_{code}")
    with t4:
        ls = _last_season_stats()
        if code in ls.index:
            lsr = ls.loc[code]
            _tiles([
                ("Goals", f"{float(lsr.get('goals') or 0):.0f}", "2025/26", "orange"),
                ("Assists", f"{float(lsr.get('assists') or 0):.0f}", "2025/26", "mag"),
                ("Minutes", f"{float(lsr.get('minutes') or 0):,.0f}", "2025/26", "cyan"),
                ("Points", f"{float(lsr.get('total_points') or 0):.0f}", "2025/26", "mint"),
            ])
        else:
            st.info("No 2025/26 Premier League record · this projection comes from "
                    "an external model or a manual override.")
        note = str(r.get("override_note", "") or "")
        if note:
            st.info(f"Manual override: {note}")


    b1, b2 = st.columns(2)
    in_squad = int(code) in set(_current_squad()["code"].astype(int))
    with b1:
        if st.button(":material/swap_horiz: Replace him", key=f"dlg_axe_{code}",
                     use_container_width=True, disabled=not in_squad,
                     type="primary" if in_squad else "secondary"):
            st.session_state["draft_axe"] = int(code)
            st.rerun()
    with b2:
        if st.button(":material/balance: Compare him", key=f"dlg_cmp_{code}",
                     use_container_width=True):
            cur = list(st.session_state.get("cmp_players", []))
            if r["web_name"] not in cur:
                st.session_state["cmp_players"] = (cur + [r["web_name"]])[-3:]
            st.session_state["cmp_pick"] = st.session_state["cmp_players"]
            st.rerun()


# ── Table columns ─────────────────────────────────────────────────────────────
def _conf_color(v):
    return theme.fill(CONF_TOKEN.get(str(v), "muted2") + "-v"
                      if CONF_TOKEN.get(str(v)) else "chip-bg")


def _pool_cols(gw: int, with_delta: bool = False) -> List[Dict]:
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
        T.col_num("mins", "Mins", fmt="%.0f",
                  color_fn=lambda v: theme.fill("red") if v < 45 else None),
        T.col_bar("season", "Season", max_value=190),
        T.col_num("per_m", "Per £m", fmt="%.1f"),
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
    manual = st.session_state["xi_override"].get(int(gw))
    if manual:
        manual = {int(c) for c in manual if int(c) in pos_by}
        if _is_legal_xi(manual, pos_by):
            return manual
    forced = set(st.session_state["draft_bench"])
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


@st.fragment
def planner() -> None:
    gw = int(st.session_state["draft_gw"])
    sq = _current_squad(gw)
    axed = st.session_state["draft_axe"]
    ledger = _transfer_ledger(gw)

    # ── Gameweek stepper ─────────────────────────────────────────────────────
    nav = st.columns([1, 1, 4, 3, 3])
    with nav[0]:
        if st.button("◀", use_container_width=True, disabled=gw <= 1,
                     help="Previous gameweek"):
            st.session_state["draft_gw"] = max(1, gw - 1)
            st.rerun(scope="fragment")
    with nav[1]:
        if st.button("▶", use_container_width=True, disabled=gw >= MAX_GW,
                     help="Next gameweek"):
            st.session_state["draft_gw"] = min(MAX_GW, gw + 1)
            st.rerun(scope="fragment")
    with nav[2]:
        st.markdown(_one_line(
            f'<div class="ff-display" style="font-size:22px;font-weight:900;'
            f'color:{V("text")};line-height:38px;">Gameweek {gw}'
            f'<span style="font-size:12px;font-weight:600;color:{V("muted2")};'
            f'margin-left:8px;">of {MAX_GW}</span></div>'), unsafe_allow_html=True)
    with nav[3]:
        compact = st.toggle("Compact", value=True, key="pitch_compact",
                            help="Shrinks the shirts so the fifteen and the bench "
                                 "fit a laptop screen without scrolling.")
    with nav[4]:
        if st.session_state["draft_swaps"] or st.session_state["draft_bench"]:
            if st.button("↺ Reset squad", use_container_width=True):
                st.session_state.update(draft_swaps={}, draft_bench=set(),
                                        draft_axe=None, xi_override={},
                                        sub_from=None)
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
    _freed = 0.0
    if axed is not None and int(axed) in set(sq["code"].astype(int)):
        _freed = float(board[board["code"] == axed].iloc[0]["actual_price"])
    _spend = bank + _freed
    _bank_label = ("To spend" if _freed else "In the bank")
    _bank_sub = (f"£{bank:.1f}m banked + £{_freed:.1f}m freed" if _freed
                 else "unspent")
    st.markdown(_strip([
        ("savings", "Squad value", f"£{cost:.1f}m", "of your budget", "text"),
        ("account_balance", _bank_label, f"£{_spend:.1f}m", _bank_sub,
         "mint" if _spend >= 0 else "red"),
        ("swap_horiz", "Free transfers",
         "Draft week" if gw <= 1 else f"{_ft} of {ledger['cap']}",
         "the draft is free" if gw <= 1 else "banked, cap 5",
         "muted" if gw <= 1 else ("mint" if _ft else "orange")),
        ("shopping_cart", "Made this week", str(_made) if gw > 1 else "-",
         "transfers" if gw > 1 else "no transfers in GW1",
         "text" if not _made else "cyan"),
        ("trending_down", "Points spent",
         f"-{ledger['points_cost']}" if ledger["points_cost"] else "0",
         "on hits so far", "red" if ledger["points_cost"] else "muted"),
    ]), unsafe_allow_html=True)
    xi_pts = sum(PROJ.points(c, gw) for c in codes if c in xi)
    bench_pts = sum(PROJ.points(c, gw) for c in codes if c not in xi)
    dead = [r["web_name"] for _, r in sq.iterrows()
            if int(r["code"]) in xi and PROJ.points(int(r["code"]), gw) < 1.5]
    hit, n = PROJ.coverage(codes, gw)

    # Which bench players could legally come on for the armed player. Only these
    # get lit on the pitch, so the formation rule is visible rather than enforced
    # after the fact.
    sub_from = st.session_state["sub_from"]
    pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
    all_codes = [int(c) for c in sq["code"]]
    swap_targets = set()
    if sub_from is not None and sub_from in pos_by:
        if sub_from in xi:
            swap_targets = set(_legal_swaps(sub_from, xi, all_codes, pos_by))
        else:
            # A benched player was tapped: light every starter he could replace.
            swap_targets = {c for c in xi
                            if _is_legal_xi((set(xi) - {c}) | {sub_from}, pos_by)}

    players = []
    for _, r in sq.iterrows():
        code = int(r["code"])
        players.append({
            "web_name": r["web_name"], "position": r["position"],
            "team_code": int(r.get("team_code", 1) or 1),
            "team_short": r.get("team_short"),
            "on_bench": code not in xi,
            "is_captain": bool(r.get("is_captain", False)),
            "price": float(r["actual_price"]),
            "fixtures": _fixtures_for(int(r.get("team_id", 0) or 0), gw, 3),
            "fpl_id": code, "stat": round(PROJ.points(code, gw), 1), "stat_dp": 1,
            "exp_mins": PROJ.expected_minutes(code, gw),
            "penalties_order": r.get("pens_order"),
            "is_axed": axed == code, "allow_axe": True, "allow_bench": True,
            "is_sub_source": sub_from == code,
            "swap_ok": code in swap_targets,
        })

    click = _click(render_squad_pitch(
        players, stat_label=f"GW{gw}", title_right=f"{NEXT_SEASON} · GW{gw}",
        interactive=True, compact=compact, key="draft_pitch"), "_pitch_nonce")
    if click:
        action, cid = click.get("action"), int(click.get("id") or 0)
        if action == "detail":
            _player_dialog(cid)
        elif action in ("axe", "unaxe"):
            st.session_state["draft_axe"] = cid if action == "axe" else None
            st.rerun(scope="fragment")
        elif action == "bench":
            # First tap arms the swap, second tap completes it. Tapping the armed
            # player again cancels, which is the only way out that does not need
            # a separate control.
            if sub_from == cid:
                st.session_state["sub_from"] = None
            elif sub_from is not None and cid in swap_targets:
                new_xi = (set(xi) - {sub_from}) | {cid} if sub_from in xi \
                    else (set(xi) - {cid}) | {sub_from}
                pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
                if _is_legal_xi(new_xi, pos_by):
                    st.session_state["xi_override"][int(gw)] = new_xi
                st.session_state["sub_from"] = None
            else:
                st.session_state["sub_from"] = cid
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
    _is_mine = not _spec.get("preset") and DR.has_squad(_spec)
    _s1, _s2, _s3 = st.columns([3, 2, 2])
    with _s1:
        _save_as = st.text_input(
            "Draft name", value=_spec["name"] if _is_mine else "",
            placeholder="Name this draft to save it", key="planner_save_name",
            label_visibility="collapsed")
    with _s2:
        _same = _save_as.strip() == _spec.get("name")
        _label = (f":material/save: Update" if (_is_mine and _same)
                  else ":material/bookmark_add: Save this team")
        if st.button(_label, use_container_width=True, type="primary",
                     disabled=not _save_as.strip(), key="planner_save_go"):
            DR.save_draft(_save_as.strip(), {
                "strategy": mode, "locks": list(locked), "vetoes": list(excluded),
                "budget": float(budget), "risk": float(risk),
                "opening": float(opening), "minutes_gate": float(minutes_gate),
                "two_attackers": bool(two_att),
                "bench_boost_gw": _spec.get("bench_boost_gw"),
                "wildcard_gw": _spec.get("wildcard_gw"),
                "squad": [int(c) for c in sq["code"]],
            })
            st.session_state["planner_draft"] = _save_as.strip()
            st.session_state.update(draft_swaps={}, draft_axe=None, sub_from=None)
            st.toast(f"Saved {_save_as.strip()}", icon="✅")
            st.rerun()
    with _s3:
        show_changes = st.toggle("Summary of changes", value=False,
                                 key="show_changes")
    if show_changes:
        st.markdown(_changes_summary(ledger), unsafe_allow_html=True)

    _tiles([
        ("Spend", f"£{cost:.1f}m", f"£{bank:.1f}m banked", "mint"),
        (f"XI · GW{gw}", f"{xi_pts:.1f}", "expected points", "gold"),
        (f"Bench · GW{gw}", f"{bench_pts:.1f}", "what a Boost adds", "cyan"),
        ("Non-starters", str(len(dead)),
         ", ".join(dead)[:30] if dead else "everyone plays", "red" if dead else "muted2"),
        ("Forecast", f"{hit}/{n}", "on match forecasts" if hit else "fixture shape",
         "mint" if hit >= n * 0.8 else "orange"),
    ])


    # ── One table: replacements when someone is marked, otherwise the pool ───
    if axed is not None and int(axed) in set(sq["code"].astype(int)):
        out_row = board[board["code"] == axed].iloc[0]
        _sec(f"Replacing {out_row['web_name']}",
             f"£{float(out_row['actual_price']):.1f}m out, "
             f"£{float(out_row['actual_price']) + bank:.1f}m to spend, staying inside "
             f"3 per club. Click + to swap him in.")
        alt = _candidates(sq, int(axed), bank)
        if alt.empty:
            st.info("Nothing affordable in this position without freeing money first.")
        else:
            # The top three, surfaced as cards before the full list. Twenty-two
            # rows is a research tool; three cards is an answer, and an answer is
            # what you want the moment you take someone out.
            _top3 = alt.assign(_k=[PROJ.run_total(int(c), gw, min(gw + 3, 38))
                                   for c in alt["code"]]).nlargest(3, "_k")
            _cards = []
            for _rank, (_, _c) in enumerate(_top3.iterrows(), start=1):
                _cc = int(_c["code"])
                _tok = ["mint", "gold", "cyan"][_rank - 1]
                _d_price = float(_c["actual_price"]) - float(out_row["actual_price"])
                _runs = _fixtures_for(int(_c.get("team_id", 0) or 0), gw, 3)
                _chips = "".join(
                    f'<span style="background:{theme.FDR_COLORS.get(int(round(float(f.get("fdr", 3)))), "#FFD60A")};'
                    f'color:#000;border-radius:4px;padding:1px 5px;font-size:9px;'
                    f'font-weight:900;">{str(f.get("opp", "?"))[:3]}'
                    f'{"" if f.get("home") else "·a"}</span>' for f in _runs)
                _mins = PROJ.expected_minutes(_cc, gw)
                _cards.append(
                    f'<div style="{CARD}flex:1;min-width:210px;border-top:3px solid {V(_tok)};">'
                    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
                    f'<span style="display:inline-grid;place-items:center;width:22px;'
                    f'height:22px;border-radius:7px;background:{V(_tok)};color:#06251A;'
                    f'font-family:var(--ff-display);font-size:12px;font-weight:900;">'
                    f'{_rank}</span>'
                    f'{face_html(_cc, int(_c.get("team_code", 1) or 1), _c["position"] == "GKP", 34)}'
                    f'<div style="min-width:0;flex:1;">'
                    f'<div style="font-size:13.5px;font-weight:700;color:{V("text")};'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'{_c["web_name"]}</div>'
                    f'<div style="font-size:10.5px;color:{V("muted")};">'
                    f'{_c.get("team_short", "")} · £{float(_c["actual_price"]):.1f}m '
                    f'({_d_price:+.1f})</div></div></div>'
                    f'<div style="display:flex;gap:3px;margin-bottom:8px;">{_chips}</div>'
                    f'<div style="display:flex;justify-content:space-between;gap:6px;">'
                    f'<div><div class="ff-display" style="font-size:17px;font-weight:800;'
                    f'color:{V(_tok)};">{float(_c["_k"]):.1f}</div>'
                    f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                    f'color:{V("muted2")};">next 4 GWs</div></div>'
                    f'<div><div class="ff-display" style="font-size:17px;font-weight:800;'
                    f'color:{V("text")};">{PROJ.points(_cc, gw):.1f}</div>'
                    f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                    f'color:{V("muted2")};">GW{gw}</div></div>'
                    f'<div><div class="ff-display" style="font-size:17px;font-weight:800;'
                    f'color:{V("text")};">{("%.0f" % _mins) if _mins is not None else "-"}</div>'
                    f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;'
                    f'color:{V("muted2")};">mins</div></div></div></div>')
            st.markdown(_one_line(
                '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">'
                + "".join(_cards) + "</div>"), unsafe_allow_html=True)
            _r1, _r2, _r3 = st.columns(3)
            for _col, (_, _c) in zip((_r1, _r2, _r3), _top3.iterrows()):
                with _col:
                    if st.button(f"Bring in {_c['web_name']}", use_container_width=True,
                                 key=f"top3_{int(_c['code'])}"):
                        st.session_state["draft_swaps"].setdefault(int(gw), {})[
                            int(axed)] = int(_c["code"])
                        st.session_state["draft_axe"] = None
                        st.rerun(scope="fragment")

            s1, s2 = st.columns([3, 1])
            with s1:
                rank_by = st.radio("Rank by", [f"GW{gw}", "Season", "Per £m"],
                                   horizontal=True, key="cand_sort",
                                   label_visibility="collapsed")
            with s2:
                if st.button("Cancel", key="cand_cancel", use_container_width=True):
                    st.session_state["draft_axe"] = None
                    st.rerun(scope="fragment")
            if rank_by.startswith("GW"):
                alt = alt.assign(_k=[PROJ.points(int(c), gw) for c in alt["code"]])
            elif rank_by == "Season":
                alt = alt.assign(_k=alt[PTS_COL])
            else:
                alt = alt.assign(_k=alt[PTS_COL] / alt["actual_price"].clip(lower=0.1))
            rows = _pool_rows(alt.nlargest(22, "_k"), gw, out_row)
            pick = _click(T.render(rows, _pool_cols(gw, with_delta=True),
                                   key=f"cand_{axed}", max_height=360),
                          "_cand_nonce")
            if pick:
                if pick.get("action") == "swap":
                    st.session_state["draft_swaps"].setdefault(int(gw), {})[
                        int(axed)] = int(pick["id"])
                    st.session_state["draft_axe"] = None
                    st.rerun(scope="fragment")
    else:
        _sec("The pool", "Everyone you could pick, ranked for this gameweek. "
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
                "Points over the next N gameweeks", 1, 8, 4, key="pool_horizon",
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
            pool = pool[pool["web_name"].str.contains(name_q.strip(), case=False,
                                                      na=False, regex=False)]
        _hi_gw = min(38, gw + horizon - 1)
        pool = pool.assign(_k=[PROJ.run_total(int(c), gw, _hi_gw) for c in pool["code"]])
        rows = _pool_rows(pool.nlargest(22, "_k"), gw)
        for _r in rows:
            _r["horizon"] = round(PROJ.run_total(int(_r["code"]), gw, _hi_gw), 1)
        _cols = _pool_cols(gw)
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


planner()


# ── Analysis ──────────────────────────────────────────────────────────────────
_sec("The read", "Analysis that informs the draft without crowding it.")

tab_cmp, tab_ab, tab_verdict, tab_models, tab_wc, tab_route, tab_all = st.tabs(
    ["⚖️ Compare players", "🆚 Compare drafts", "🎯 Verdicts",
     "🤝 Model agreement", "🃏 Wildcard", "🗺️ Chip route", "📋 All players"])


# ── Compare players ───────────────────────────────────────────────────────────
with tab_cmp:
    st.caption("Two or three players on the same axes. Totals flatter whoever is "
               "expensive, so the comparison is also shown **per £m** and **per 90** "
               "· the first respects your budget, the second takes minutes out of it.")
    st.session_state.setdefault("cmp_players", [])
    picks = st.multiselect(
        "Players", options=NAMES, default=st.session_state["cmp_players"],
        max_selections=3, key="cmp_pick",
        help="Pick two or three. The ⚖ button on a player's card adds them here.")
    st.session_state["cmp_players"] = picks

    if len(picks) < 2:
        st.info("Pick two players to compare.")
    else:
        from analytics.head_to_head import compare_players, verdict_line
        profs = [_profile(int(board[board["web_name"] == nm].iloc[0]["code"]))
                 for nm in picks]
        cmp = compare_players(profs)

        st.markdown(_one_line(
            f'<div style="{CARD}border-left:3px solid {V("mint")};margin:6px 0 14px;">'
            f'<div style="font-size:15px;color:{V("text")};line-height:1.6;">'
            f'{verdict_line(cmp, profs)}</div></div>'), unsafe_allow_html=True)

        head = st.columns(len(profs))
        for col, p in zip(head, profs):
            with col:
                st.markdown(_one_line(
                    f'<div style="{CARD}text-align:center;">'
                    f'<div style="display:flex;justify-content:center;margin-bottom:6px;">'
                    f'{face_html(p["code"], p["team_code"], p["position"] == "GKP", 56)}</div>'
                    f'<div class="ff-display" style="font-size:18px;font-weight:900;'
                    f'color:{V("text")};">{p["name"]}</div>'
                    f'<div style="font-size:11px;color:{V("muted")};">'
                    f'{p["team"]} · {p["position"]} · £{p["price"]:.1f}m</div></div>'),
                    unsafe_allow_html=True)

        cc1, cc2 = st.columns([1, 1])
        with cc1:
            # Radar · each axis scaled across the compared players only, because
            # the question is never "is he good" but "is he better than the
            # alternative I can actually afford".
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
            # The near-term run, week by week. Two lines make a fixture swing
            # obvious in a way a season total never will.
            gws = list(range(1, 11))
            series = []
            for i, p in enumerate(profs):
                pts = [(g, round(PROJ.points(p["code"], g), 2)) for g in gws]
                series.append((p["name"], pts, theme.fill(["mint", "gold", "cyan"][i % 3])))
            charts.render(charts.multi_line_option(series, x_name="Gameweek",
                                                   y_name="Expected points"),
                          height="330px", key="cmp_run")

        rows = []
        for a in cmp["axes"]:
            row = {"axis": a["label"], "why": a["why"]}
            for i, p in enumerate(profs):
                v = a["values"][i]
                row["p%d" % i] = "n/a" if v is None or pd.isna(v) else (
                    "%.0f%%" % (v * 100) if a["key"] == "defcon" else
                    "%.0f'" % v if a["key"] == "mins" else
                    "%.2f" % v if a["key"] in ("per_90", "agreement", "fixtures") else
                    "%.1f" % v)
                if i == a["best"]:
                    row["p%d" % i] = "◆ " + row["p%d" % i]
            rows.append(row)
        cols = [T.col_text("axis", "Metric"),
                T.col_text("why", "What it tells you")]
        cols[1:1] = [T.col_text("p%d" % i, p["name"], align=T.ALIGN_NUM)
                     for i, p in enumerate(profs)]
        T.render(rows, cols, key="cmp_table", row_key="axis", max_height=320)
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

    # ── Save the current controls as a named draft ───────────────────────────
    with st.expander("💾 Save this draft, or manage the saved ones", expanded=False):
        s1, s2, s3 = st.columns([3, 2, 2])
        with s1:
            new_name = st.text_input(
                "Name", key="save_name", placeholder="e.g. Optimal, no Haaland",
                help="Saves the CONTROLS, not the fifteen · strategy, locks, dials "
                     "and chip plan. A saved draft stays correct when prices move "
                     "or a projection updates.")
        with s2:
            save_bb = st.selectbox("Bench Boost", ["None"] + [f"GW{g}" for g in range(1, 11)],
                                   key="save_bb")
        with s3:
            save_wc = st.selectbox("Wildcard", ["None"] + [f"GW{g}" for g in range(2, 13)],
                                   key="save_wc")
        if st.button("Save draft", key="save_go", disabled=not new_name.strip()):
            DR.save_draft(new_name.strip(), {
                "strategy": mode, "locks": list(locked), "vetoes": list(excluded),
                "budget": float(budget), "risk": float(risk),
                "opening": float(opening), "minutes_gate": float(minutes_gate),
                "two_attackers": bool(two_att),
                "bench_boost_gw": None if save_bb == "None" else int(save_bb[2:]),
                "wildcard_gw": None if save_wc == "None" else int(save_wc[2:]),
            })
            st.success(f"Saved **{new_name.strip()}**.")
            st.rerun()

        st.markdown(_one_line(
            f'<div style="font-size:11px;font-weight:800;letter-spacing:0.18em;'
            f'color:{V("muted")};text-transform:uppercase;margin:12px 0 6px;">'
            f'Saved drafts ({len(saved)})</div>'), unsafe_allow_html=True)
        drop = st.multiselect("Delete", options=[d["name"] for d in saved],
                              key="drop_drafts", label_visibility="collapsed",
                              placeholder="Pick drafts to delete")
        d1, d2 = st.columns([1, 3])
        with d1:
            if st.button("Delete selected", key="drop_go", disabled=not drop):
                for d in saved:
                    if d["name"] in drop:
                        DR.delete_draft(d["id"])
                st.rerun()
        with d2:
            if st.button("Restore the nine presets", key="reset_presets",
                         help="Wipes the list and lays the preset drafts down again."):
                DR.reset_to_presets()
                st.rerun()

    # ── Pick which to compare ────────────────────────────────────────────────
    default = [d["name"] for d in saved][:4]
    _sec("1 · Choose the drafts", icon="checklist")

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

    _sec("2 · Set the window", icon="tune")
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
        _ab_key = (tuple(picks), window, int(n_sims), len(board))
        _cached = st.session_state.get("_ab_cache")
        _reuse = bool(_cached and _cached.get("key") == _ab_key and not run_ab)
        entries = _cached["entries"] if _reuse else []
        sim = _cached["sim"] if _reuse else None
        if not _reuse:
            with st.spinner("Solving squads and simulating the window…"):
                entries = []
                for spec in specs:
                    def _solve(strategy, ow, omap, _s=spec):
                        return solve_draft(
                            _tuned_board(float(_s.get("minutes_gate", 0.5))),
                            strategy or "⚖️ Optimal value", float(_s.get("budget", 100.0)),
                            float(_s.get("risk", 0.3)), tuple(_s.get("vetoes", [])), ow,
                            force_names=tuple(_s.get("locks", [])), opening_map=omap,
                            max_attackers_per_club=2 if _s.get("two_attackers") else 1)

                    phases = build_phases(spec, _solve, _window_map, window[0], window[1],
                                          board=board)
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
            # and abbreviate the squad. "Optimal + Fernan…" hides the useful half.
            for d in ranked:
                nm = d["name"]
                head, _, chip = nm.partition(" · ")
                squad = (head.replace("Optimal + ", "+ ")
                             .replace("Optimal", "Base")
                             .replace("Fernandes", "Fern").replace("Mosquera", "Mosq")
                             .replace("Haaland", "Haal"))
                d["short"] = (f"{squad} {chip}" if chip else squad)[:26]
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
            st.markdown(_range_bands(ranked, colour, window), unsafe_allow_html=True)

            # ── Ranked table ─────────────────────────────────────────────────────
            rows = []
            for i, d in enumerate(ranked):
                rows.append({
                    "rank": i + 1, "name": d["name"],
                    "mean": d["total_mean"],
                    "band": f"{d['total_lo']:.0f} to {d['total_hi']:.0f}",
                    "vs_top": d["total_mean"] - top["total_mean"],
                    "p_best": d["p_best"] * 100,
                    "beats_top": (d["beats"].get(top["name"], 0.5) * 100) if i else 100.0,
                })
            T.render(rows, [
                T.col_num("rank", "#", fmt="%.0f"),
                T.col_player("name", "Draft"),
                T.col_bar("mean", f"GW{window[0]}-{window[1]}",
                          max_value=max(d["total_mean"] for d in ranked) * 1.05),
                T.col_text("band", "Middle 80%", align=T.ALIGN_NUM),
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
                    _wk.append((_n, sum(PROJ.points(int(c), _sq_gw)
                                        for c in _s["code"] if int(c) in _x)))
                _bits = "".join(
                    f'<span style="display:inline-flex;align-items:center;gap:6px;'
                    f'margin-right:14px;">{_badge(_ids[_n], 18)}'
                    f'<span class="ff-display" style="font-size:16px;font-weight:800;'
                    f'color:{_ids[_n]["colour"]};">{_v:.1f}</span></span>'
                    for _n, _v in _wk if _n in _ids)
                st.markdown(_one_line(
                    f'<div style="display:flex;align-items:center;gap:12px;'
                    f'height:38px;"><span class="ff-display" style="font-size:19px;'
                    f'font-weight:900;color:{V("text")};">GW{_sq_gw}</span>{_bits}'
                    f'<span style="font-size:11px;color:{V("muted")};">XI points'
                    f'</span></div>'), unsafe_allow_html=True)
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
                            _tot = sum(PROJ.points(int(c), _sq_gw)
                                       for c in _sqd["code"])
                            _id = _ids.get(_nm, {"letter": "?", "colour": colour[_nm]})
                            st.markdown(_one_line(
                                f'<div style="display:flex;align-items:center;gap:9px;'
                                f'margin:4px 0 8px;">{_badge(_id, 24)}'
                                f'<div style="min-width:0;">'
                                f'<div class="ff-display" style="font-size:14px;'
                                f'font-weight:800;color:{_id["colour"]};white-space:nowrap;'
                                f'overflow:hidden;text-overflow:ellipsis;">{_nm}</div>'
                                f'<div style="font-size:11px;color:{V("muted")};">'
                                f'{len(_only)} unique · {_tot:.1f} pts in GW{_sq_gw}'
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
                                render_squad_pitch(
                                    _plist, stat_label=f"GW{_sq_gw}",
                                    title_right=f"{_id['letter']} · GW{_sq_gw}",
                                    compact=True, key=f"ab_pitch_{_id['letter']}")
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
                                    T.col_bar("season", "Season", max_value=190),
                                ], key=f"ab_side_{_nm}", max_height=430)
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
    if price >= 9.0:
        qs.append("Premium anchor · does he own the pens or set pieces to justify it?")
    elif price <= 4.5:
        qs.append("Cheap starter? Confirm he starts GW1 before locking him in.")
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
  <div style="display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-bottom:6px;">{mins_html}{sp}{conf_html}</div>
  <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:8px;">{mid}</div>
  {range_html}
  {bar}
  {note_html}
  <div style="font-size:11px;color:{V('muted')};margin-bottom:8px;line-height:1.35;">{row.get("verdict_reason", "") or ""}</div>
  <ul style="margin:0;padding-left:16px;font-size:11px;color:{V('muted2')};">{q_html}</ul>
</div>""")


def _lane(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No players in this bucket right now.")
        return
    st.markdown('<div class="fplh-stagger" style="display:grid;'
                'grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">'
                + "".join(_verdict_card(r) for _, r in df.iterrows()) + "</div>",
                unsafe_allow_html=True)


with tab_verdict:
    counts = board["verdict"].value_counts().to_dict()
    st.caption("Each card carries a confidence dot · how much to trust its number. "
               "Green means the models agree, red means they scatter or only one of "
               "them has an opinion.")
    vt = st.tabs([f"🥇 Necessity ({counts.get(VERDICTS.NECESSITY, 0)})",
                  f"🟢 Value ({counts.get(VERDICTS.VALUE, 0)})",
                  f"🔴 Overpriced ({counts.get(VERDICTS.OVERPRICED, 0)})",
                  f"🔍 Scout · new ({len(scout)})"])
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
                T.col_bar("gap", "Gap", max_value=110, color="red"),
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
                         max_attackers_per_club=2 if two_att else 1)
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
                    T.render(_pool_rows(frame, wc_gw), [
                        T.col_face("code", url_fn=player_photo_url),
                        T.col_player("web_name", "Player", sub="team_short"),
                        T.col_num("actual_price", "£m", fmt="%.1f"),
                        T.col_bar("season", "Season", max_value=190),
                    ], key=f"wc_{lbl}", max_height=300, empty="Nobody.")


# ── Chip route ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=6 * 3600, show_spinner="Scoring chip routes over GW1-19…")
def _routes(_board: pd.DataFrame, _budget: float, _risk: float, _excl: tuple):
    from analytics.season_opener import bb_dilution, compare_routes, opening_ease
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    fx = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())

    def _solve(b, all_must_play=False, bench_price_cap=None, opening_window=None):
        strategy = "🔋 Bench Boost GW1" if all_must_play else "⚖️ Optimal value"
        omap = ()
        if opening_window:
            oe = opening_ease(fx, opening_window[0], opening_window[1])
            omap = tuple(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))
        return solve_draft(b, strategy, _budget, _risk, _excl, 0.0, opening_map=omap,
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
                                   max_attackers_per_club=2 if two_att else 1)

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
        except Exception as _exc:
            st.caption(f"Route walkthrough unavailable ({_exc}).")

    _sec("The routes, priced against each other", icon="alt_route")
    st.caption("A Bench Boost needs 15 playing assets, which costs XI strength every "
               "week you carry it. The Wildcard is what repairs that.")
    try:
        routes_df, dil = _routes(SOLVE_BOARD, budget, risk, tuple(excluded))
    except Exception as exc:
        routes_df, dil = pd.DataFrame(), None
        st.caption(f"Route comparison unavailable ({exc}).")

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
        T.col_bar("season", "Season", max_value=190),
        T.col_bar("per_m", "Per £m", max_value=32, color="gold"),
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
