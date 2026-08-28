"""The player evidence card · why a player is worth what the board says.

Extracted from `views/18_draft_2026_27.py` so a second page (My Team) can open
the exact same "why this player" dialog the Draft opens, instead of a smaller
copy re-derived from scratch. `CardCtx` carries every piece of page state the
card reads (the board, the three-model projector, the DEFCON table, the
snapshot stamp) plus the footer actions as callables, because those differ by
caller: the Draft wires them to its axe/compare queues, My Team will wire them
to its own transfer plan and add a captain button.

Every colour here is a `--ff-*` variable via `ui.theme`, never a literal, so
the card follows the light/dark switch without knowing which theme is on.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from analytics.squad_rules import POS_ORDER
from components.team_identity import face_html
from config import DRAFT_UI, LAST_COMPLETE_SEASON
from ui import charts
from ui import theme
from ui.theme import var as V

logger = logging.getLogger(__name__)

# ── Constants the card grades against ───────────────────────────────────────
CARD = (f"background:{V('card')};border:1px solid {V('line')};"
        f"border-radius:14px;padding:14px 16px;")

CONF_TOKEN = {"High": "mint", "Medium": "orange", "Low": "red"}

# "108 projected points" means nothing on its own. Every number in the player
# card is graded against the players you would actually consider instead, and
# the grade is the colour · so the card can be read at a glance rather than
# parsed.
#
# Two kinds of grade, because two kinds of number:
#   RANK      compare against every player in his position (points, per £m, per
#             90). Top 10% is good, top third is fair, the rest is not.
#   THRESHOLD compare against a fixed bar the rules define (DEFCON). Clearing it
#             is what pays, being close is worth something, below is nothing.
GRADE_TOKENS = {"good": "mint", "ok": "gold", "poor": "red", "none": "muted2"}

# FPL's defensive-contribution bar: 10 CBIT for a defender, 12 for a midfielder,
# confirmed by Eoin and matching what `defcon_per90` scores against. Clearing it
# pays a flat 2 points, which is why the HIT RATE matters more than the average:
# a player who averages 11 by spiking to 20 once and sitting at 8 otherwise earns
# the bonus far less often than the mean suggests. Forwards and keepers have no
# route to it.
DEFCON_THRESHOLD = {"DEF": 10.0, "MID": 12.0}
DEFCON_CLOSE = 0.8          # within 20% of the bar counts as close

# A forecast and a fact should never look alike on screen.
PROJ_MARK = " ~"      # projected · a model's opinion
STAT_MARK = " ●"      # measured · what actually happened last season

POOL_FLOOR = float(DRAFT_UI["pool_floor_points"])
GRADE_GOOD = float(DRAFT_UI["grade_good"])
GRADE_FAIR = float(DRAFT_UI["grade_fair"])
SEASON_MINUTES = float(DRAFT_UI["season_minutes"])


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
    # The Replace button is only meaningful for a player already in a squad.
    # The Draft's squad is session-state the card has no business owning, so
    # the caller hands over a live membership check instead of a snapshot ·
    # None means "always enabled" (a caller with no squad concept).
    in_squad: Optional[Callable[[int], bool]] = None
    # The gameweek the card should show a "this week" figure for. A plain int
    # rather than a session lookup so the card carries no page-specific keying
    # · the caller refreshes it (it is mutable) immediately before each open,
    # which keeps it live even when the caller itself runs inside a fragment.
    current_gw: int = 1


# ── Small helpers (page-local by design · every page that renders card-style
# HTML keeps its own copy rather than sharing one, see views/*.py) ──────────
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
        if out and (out[-1].isalnum() or out[-1] in ",.;:!?") \
                and (seg[0].isalnum() or seg[0] == "<"):
            out += " "
        out += seg
    return out


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


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


# ── Data loaders ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def defcon_per90(stamp: str) -> pd.DataFrame:
    """Defensive contributions per 90 last season, plus how often the threshold hit.

    The mean flatters a player who spikes once · DEFCON points are a THRESHOLD
    (10 CBIT for a defender, 12 for a midfielder), so the hit rate is what
    converts to points week to week.

    `stamp` does not change the computation · this reads only the historical
    archive, which cannot change inside a session. It is here purely so the
    cache key tracks the board the caller built it for, per CLAUDE.md's
    no-arguments-means-a-constant-key gotcha.
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
    # Whitelisting output columns is how this repo has silently lost data
    # before · `pts_per_million` and `position` were absent, so the card showed
    # a dash for value and could not rank anything by position.
    keep = ["goals", "assists", "xg", "xa", "xgi", "defcon_points", "minutes",
            "total_points", "ppg", "clean_sheets", "bonus", "starts_total",
            "games_played", "pts_per_million", "pp90", "position",
            "goals_per90", "assists_per90"]
    return s.set_index("code")[[c for c in keep if c in s.columns]]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _dc_ratings():
    from data.fetchers.dixon_coles import fetch_dixon_coles_ratings
    try:
        return fetch_dixon_coles_ratings()
    except Exception:            # noqa: BLE001 · a missing fit must not break the card
        logger.warning("Dixon-Coles ratings unavailable")
        return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _short_to_name() -> Dict:
    from data.fetchers.fpl_api import fetch_bootstrap
    return {t["short_name"]: t["name"] for t in fetch_bootstrap()["teams"]}


def _team_name_for_short(short: str) -> str:
    return _short_to_name().get(str(short), str(short))


def miss_early_codes() -> set:
    """Players a human has said will miss part of the opening window.

    The overrides file already knows this · surfacing it stops a deliberate
    zero looking like a data gap.
    """
    try:
        from analytics.projection_overrides import load_overrides
        return {int(c) for c, adj in load_overrides().items()
                if adj.get("miss_gws")}
    except Exception:
        logger.warning("could not read miss_gws overrides", exc_info=True)
        return set()


# ── Player evidence ───────────────────────────────────────────────────────────
def profile(ctx: CardCtx, code: int) -> Dict:
    from analytics.head_to_head import player_profile
    row = ctx.board[ctx.board["code"] == int(code)]
    if row.empty:
        return {}
    return player_profile(row.iloc[0], ctx.pts_col, ctx.defcon, ctx.proj)


def set_piece_line(row) -> str:
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


def setpiece_glyphs(row) -> str:
    """Penalties and set pieces as tiny glyphs. These are official ORDERS, not
    forecasts, so they belong next to the player rather than behind a card."""
    out = []
    if _num_safe(row.get("pens_order")) == 1:
        out.append(f'<span title="First-choice penalties" style="background:'
                   f'{theme.fill("gold-v")};color:#000;border-radius:4px;'
                   f'padding:1px 4px;font-size:9px;font-weight:900;">P</span>')
    for key, label, tip in (("corners_order", "C", "Takes corners"),
                            ("fk_order", "F", "Takes free kicks")):
        if _num_safe(row.get(key)) == 1:
            out.append(f'<span title="{tip}" style="background:{V("chip-bg")};'
                       f'color:{V("cyan")};border-radius:4px;padding:1px 4px;'
                       f'font-size:9px;font-weight:800;">{label}</span>')
    return ('<span style="display:inline-flex;gap:3px;">' + "".join(out) + "</span>"
            if out else "")


def conf_color(v):
    return theme.fill(CONF_TOKEN.get(str(v), "muted2") + "-v"
                      if CONF_TOKEN.get(str(v)) else "chip-bg")


def dc_hit(ctx: CardCtx, code: int, pos: str) -> Optional[float]:
    """Share of last season's starts clearing the DEFCON threshold."""
    if pos not in ("DEF", "MID") or ctx.defcon.empty or code not in ctx.defcon.index:
        return None
    v = ctx.defcon.loc[code].get("dc_hit_rate")
    return round(float(v) * 100, 0) if pd.notna(v) else None


def _keep_verdict(ctx: CardCtx, p: Dict, row: pd.Series) -> str:
    """Should he be in the squad · the question the card exists to answer.

    Deliberately built from the things that decide it rather than from the
    headline projection: minutes first, then value for money, then whether the
    models actually agree on the number.
    """
    pos = p.get("position", "")
    peers = ctx.board[(ctx.board["position"] == pos)
                  & (ctx.board["actual_price"].between(p["price"] - 0.6, p["price"] + 0.6))]
    per_m = pd.to_numeric(peers[ctx.pts_col], errors="coerce") / \
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


def _grade_rank(pct: float) -> str:
    """Percentile within position, where 1.0 is the best player."""
    if pct >= GRADE_GOOD:
        return "good"
    if pct >= GRADE_FAIR:
        return "ok"
    return "poor"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _position_ranks(_board: pd.DataFrame, pts_col: str, stamp: str) -> Dict:
    """Per-position ordered lists for points, points per £m and points per 90.

    Restricted to players the models actually rate, so a rank means "of the
    players worth considering" rather than "of everyone in the game".
    """
    out = {}
    for pos in POS_ORDER:
        d = _board[(_board["position"] == pos)
                  & (pd.to_numeric(_board[pts_col], errors="coerce") >= POOL_FLOOR)].copy()
        if d.empty:
            continue
        price = pd.to_numeric(d["actual_price"], errors="coerce").clip(lower=0.1)
        season = pd.to_numeric(d[pts_col], errors="coerce")
        nail = pd.to_numeric(d.get("ffh_nailedness"), errors="coerce")
        mins = (nail.fillna(pd.to_numeric(d["projected_minutes"], errors="coerce")
                            / SEASON_MINUTES) * SEASON_MINUTES).clip(lower=90)
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


def _graded_tiles(ctx: CardCtx, code: int, row: pd.Series, p: Dict) -> List:
    """The five headline numbers, each graded and each carrying its rank.

    Every label is marked: `~` for a projection, `●` for a measured stat.
    """
    pos = str(row.get("position", ""))
    ranks = _position_ranks(ctx.board, ctx.pts_col, ctx.board_stamp).get(pos, {})
    gw = int(ctx.current_gw or 1)

    # A projection and a measured stat are different kinds of number and should
    # never look alike. DEFCON per 90 is what a player DID; 109 season points is
    # what a model GUESSES he will do. Reading the second with the confidence of
    # the first is how you end up trusting a punt.
    def rank_tile(icon, label, value, key, fmt="%.0f", kind="proj"):
        r, n, pct = _rank_of(value, ranks.get(key, []))
        mark = PROJ_MARK if kind == "proj" else STAT_MARK
        if not n:
            return (icon, label + mark, fmt % (value or 0), "no comparison set", "muted2")
        return (icon, label + mark, fmt % value,
                f"{_ordinal(r)} of {n} {pos}", GRADE_TOKENS[_grade_rank(pct)])

    tiles = [
        rank_tile("military_tech", "Season", float(row.get(ctx.pts_col) or 0), "season"),
        rank_tile("savings", "Per £m", p.get("per_m"), "per_m", "%.1f"),
        rank_tile("speed", "Per 90", p.get("per_90"), "per_90", "%.2f"),
    ]

    # This gameweek, against what a starting player is worth in a week.
    gw_pts = ctx.proj.points(code, gw)
    gw_tok = "good" if gw_pts >= 5 else "ok" if gw_pts >= 3.2 else "poor"
    gw_sub = ("not expected to play" if ctx.proj.misses(code, gw)
              else "expected this week")
    tiles.append(("sports_soccer", f"GW{gw}" + PROJ_MARK, f"{gw_pts:.1f}", gw_sub,
                  GRADE_TOKENS["none" if ctx.proj.misses(code, gw) else gw_tok]))

    # DEFCON against the bar the rules set, not against other players.
    thr = DEFCON_THRESHOLD.get(pos)
    dc = ctx.defcon.loc[code] if (not ctx.defcon.empty and code in ctx.defcon.index) else None
    if thr is None:
        tiles.append(("shield", "DEFCON" + STAT_MARK, "n/a", f"no route to it as a {pos}",
                      GRADE_TOKENS["none"]))
    elif dc is None:
        tiles.append(("shield", "DEFCON / 90" + STAT_MARK, "n/a", "no 25/26 record",
                      GRADE_TOKENS["none"]))
    else:
        per90 = float(dc.get("dc_per90") or 0)
        tok = ("good" if per90 >= thr else
               "ok" if per90 >= thr * DEFCON_CLOSE else "poor")
        hit = float(dc.get("dc_hit_rate") or 0) * 100
        tiles.append(("shield", "DEFCON / 90" + STAT_MARK, f"{per90:.1f}",
                      f"25/26 · bar {thr:.0f} for 2 pts · cleared it {hit:.0f}% of starts",
                      GRADE_TOKENS[tok]))
    return tiles


def _model_chart(ctx: CardCtx, row: pd.Series, code: int) -> None:
    """Where the three models land, on one axis.

    Three separate bars make you compare heights. One axis with three points
    makes the SPREAD the thing you see, which is the question actually being
    asked: do they agree, and by how much.
    """
    # A model can have a NUMBER and still not have a VOTE. `consensus` drops a
    # source from the season blend in two cases · a player whose "our" figure is
    # really the Scout backfill (one opinion arriving twice, so ours and the Hub
    # both stand down), and a player the Hub expects almost no early minutes
    # from, whose window total is an availability report rather than a scoring
    # rate. The blend was already right; the CHART was not, because it plotted
    # every number it could find and then measured a spread across models that
    # had abstained. A dot the blend ignores now says so.
    _echo = bool(row.get("consensus_echoed_scout", False))
    _no_mins = bool(row.get("ffh_no_early_minutes", False))
    VOTED = {"src_ours": not _echo,
             "src_scout": True,
             "src_ffh": not (_echo or _no_mins)}
    WHY_SILENT = {
        "src_ours": " · no PL record, so this IS the Scout number (not a "
                    "second opinion)",
        "src_scout": "",
        "src_ffh": (" · no PL record, so its season extrapolation does not vote"
                    if _echo else
                    " · expects too few early minutes to imply a season rate"),
    }

    labels, values, cols, notes = [], [], [], []
    for col, lab, tok in (("src_ours", "Ours", "mint"),
                          ("src_scout", "Scout", "gold"),
                          ("src_ffh", "Hub", "cyan")):
        v = row.get(col)
        if pd.notna(v):
            voted = VOTED[col]
            labels.append(lab if voted else "%s (no vote)" % lab)
            values.append(round(float(v), 0))
            cols.append(theme.fill(tok) if voted else theme.fill("muted2"))
            notes.append("" if voted else WHY_SILENT[col])
    # Every model's number, stated. The chart shows the SPREAD, but the reader
    # also wants to know who said what · a blend of 109 means something very
    # different when it is 118 against 102 than when all three sit on 109.
    _rows = []
    for col, lab, tok, what in (
            ("src_ours", "Ours", "mint", "carryover from last season"),
            ("src_scout", "Scout", "gold", "their season projection"),
            ("src_ffh", "Hub", "cyan", "four-gameweek forecast, scaled to a season")):
        v = row.get(col)
        _voted = VOTED[col] and pd.notna(v)
        _tok = tok if _voted else "muted2"
        _rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:4px 0;">'
            f'<span style="width:9px;height:9px;border-radius:50%;flex-shrink:0;'
            f'background:{V(_tok)};"></span>'
            f'<span style="font-size:12px;font-weight:700;color:{V("text")};'
            f'width:44px;">{lab}</span>'
            f'<span class="ff-display" style="font-size:15px;font-weight:800;'
            f'color:{V(_tok)};width:46px;'
            f'text-align:right;">'
            f'{("%.0f" % float(v)) if pd.notna(v) else "no view"}</span>'
            f'<span style="font-size:11px;color:{V("muted")};">{what}'
            + ('' if _voted or pd.isna(v)
               else f'<b style="color:{V("muted2")};"> · does not vote</b>')
            + '</span></div>')
    _blend = float(row.get(ctx.pts_col) or 0)
    _rows.append(
        f'<div style="display:flex;align-items:center;gap:10px;padding:7px 0 0;'
        f'margin-top:4px;border-top:1px solid {V("line")};">'
        f'<span style="width:9px;flex-shrink:0;"></span>'
        f'<span style="font-size:12px;font-weight:800;color:{V("text")};'
        f'width:44px;">Blend</span>'
        f'<span class="ff-display" style="font-size:15px;font-weight:900;'
        f'color:{V("text")};width:46px;text-align:right;">{_blend:.0f}</span>'
        f'<span style="font-size:11px;color:{V("muted")};">'
        f'what the page ranks him on</span></div>')
    st.markdown(_one_line(f'<div style="{CARD}padding:10px 14px;margin-bottom:8px;">'
                          + "".join(_rows) + '</div>'), unsafe_allow_html=True)

    if bool(row.get("consensus_echoed_scout")):
        st.caption("He has no Premier League record, so our number IS the Scout "
                   "backfill · one opinion, not two. The Hub is shown but does "
                   "not vote on his season: it runs about 40% hot on players it "
                   "cannot see.")

    if len(labels) < 2:
        st.info("Only one model rates this player, so there is nothing to "
                "cross-check. Treat the number as a single opinion.")
        return
    blend = float(row.get(ctx.pts_col) or 0)
    charts.render(charts.model_spread_option(labels, values, blend, cols,
                                             notes=notes),
                  height="180px", key=f"dlg_models_{code}")

    # Measure the spread across the models that actually VOTED. Including an
    # abstaining model made the headline gap disagree with the confidence tier
    # sitting beside it · "73 points between the models" under a Low badge that
    # was computed from one opinion.
    _voting = [v for v, nt in zip(values, notes) if not nt]
    conf = str(row.get("consensus_confidence", "") or "")
    tok = CONF_TOKEN.get(conf, "muted")
    if len(_voting) < 2:
        st.markdown(_one_line(
            f'<div style="{CARD}border-left:3px solid {V(tok)};padding:10px 14px;">'
            f'<div style="font-size:13px;color:{V("text")};line-height:1.55;">'
            f'Only <b>one model votes</b> on his season · the greyed dots have a '
            f'number but no say. Treat this as a single opinion, not a '
            f'consensus.</div></div>'), unsafe_allow_html=True)
        return
    gap = max(_voting) - min(_voting)
    verdict = ("They agree, so the number is worth trusting."
               if conf == "High" else
               "They disagree enough that the middle is a guess. Decide this one "
               "on football, not on the decimal." if conf == "Low" else
               "Partial agreement · treat the range, not the midpoint, as the forecast.")
    st.markdown(_one_line(
        f'<div style="{CARD}border-left:3px solid {V(tok)};padding:10px 14px;">'
        f'<div style="font-size:13px;color:{V("text")};line-height:1.55;">'
        f'<b>{gap:.0f} points</b> between the most and least optimistic '
        f'<b>voting</b> model. {verdict}</div></div>'), unsafe_allow_html=True)


def _run_chart(ctx: CardCtx, code: int, row: pd.Series, team_id: int, key: str) -> None:
    """The opening run · expected points a week, coloured by fixture difficulty.

    Colour carries the WHY: green bars are kind fixtures, red are not, so the
    shape of the run is readable without a legend or a tooltip. The dashed line
    is expected minutes, because a tall bar on thin minutes is exactly the trap
    this chart exists to expose.
    """
    gws = list(range(1, 11))
    pts, opps, fdrs, mins = [], [], [], []
    for g in gws:
        pts.append(round(ctx.proj.points(code, g), 1))
        fx = ctx.fix.get((int(team_id), g), [])
        if fx:
            opps.append(" + ".join(o for o, _h, _f in fx))
            fdrs.append(sum(f for _o, _h, f in fx) / len(fx))
        else:
            opps.append("blank")
            fdrs.append(3)
        mins.append(ctx.proj.expected_minutes(code, g))

    charts.render(
        charts.fixture_run_option(gws, pts, opps, fdrs,
                                  minutes=mins if any(m is not None for m in mins) else None,
                                  fdr_colors=theme.FDR_COLORS),
        height="290px", key=key)

    nail, vol = row.get("ffh_nailedness"), row.get("ffh_mins_volatility")
    bits = []
    _match_window = ctx.proj.window
    if _match_window:
        bits.append(f"GW{_match_window[0]}-{_match_window[-1]} are per-fixture "
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


def _band_chart(ctx: CardCtx, code: int, row: pd.Series, p: Dict, key: str) -> None:
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
    band = ctx.board[(ctx.board["position"] == pos)
                 & (ctx.board["actual_price"].between(price - 0.5, price + 0.5))
                 & (pd.to_numeric(ctx.board[ctx.pts_col], errors="coerce") >= POOL_FLOOR)]
    if len(band) < 4:
        band = ctx.board[(ctx.board["position"] == pos)
                     & (ctx.board["actual_price"].between(price - 1.0, price + 1.0))
                     & (pd.to_numeric(ctx.board[ctx.pts_col], errors="coerce") >= 25)]
    if len(band) < 4:
        st.info("Too few comparable players in his price band.")
        return

    def _med(col, default=0.0):
        v = pd.to_numeric(band.get(col), errors="coerce")
        return float(v.median()) if v is not None and v.notna().any() else default

    dc_band = ctx.defcon.reindex(band["code"].astype(int)).dropna(how="all") \
        if not ctx.defcon.empty else pd.DataFrame()
    dc_med = float(dc_band["dc_hit_rate"].median()) if not dc_band.empty else 0.0
    dc_his = 0.0
    if not ctx.defcon.empty and code in ctx.defcon.index:
        dc_his = float(ctx.defcon.loc[code].get("dc_hit_rate", 0) or 0)

    axes = [
        ("Season pts", float(row.get(ctx.pts_col) or 0), _med(ctx.pts_col, 1)),
        ("Per £m", (p.get("per_m") if pd.notna(p.get("per_m")) else 0),
         _med(ctx.pts_col, 1) / max(price, 0.1)),
        ("Minutes", float(row.get("ffh_nailedness") or 0) * 90,
         _med("ffh_nailedness", 0.7) * 90),
        ("DEFCON", dc_his * 100, dc_med * 100),
        ("Fixtures", float(row.get("opening_factor") or 1.0) * 100, 100.0),
        ("Agreement", (1 - float(row.get("model_spread") or 0.3)) * 100, 75.0),
    ]
    # A thin price band (Fernandes at £12.0m has very few peers within ±0.6m)
    # makes the median NaN, and NaN is not valid JSON · it reached the browser
    # as a parse error and killed the whole card. Coerce before the arithmetic,
    # not after: max(x, nan) is already poisoned.
    def _safe(v, default=0.0):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return default
        return f if math.isfinite(f) else default

    inds, his, theirs = [], [], []
    for name, mine, med in axes:
        mine, med = _safe(mine), _safe(med)
        top = max(mine, med) * 1.25
        inds.append({"name": name, "max": round(top, 1) if top > 0 else 1.0})
        his.append(round(mine, 1))
        theirs.append(round(med, 1))
    charts.render(charts.radar_compare_option(inds, [
        (f"Typical £{price:.1f}m {pos}", theirs, theme.fill("muted2"), 0.10),
        (str(row["web_name"]), his, theme.pos_color(pos), 0.26),
    ]), height="330px", key=key)
    st.markdown(_one_line(
        f'<div style="font-size:12.5px;color:{V("muted")};line-height:1.55;">'
        f'Against the median {pos} you could buy instead at this price '
        f'({len(band)} players the models actually rate). Outside the grey shape '
        f'is where he wins.</div>'), unsafe_allow_html=True)


def _defcon_frame(ctx: CardCtx, season: pd.DataFrame) -> pd.DataFrame:
    """DEFCON rates joined onto the season frame, so a rank can be positional."""
    d = ctx.defcon.copy()
    if d.empty:
        return d
    return d.join(season[[c for c in ("position", "minutes") if c in season.columns]],
                  how="left")


def _last_season_badges(ctx: CardCtx, code: int, r) -> str:
    """What he actually DID last season, each number next to how good it is.

    Percentiles are against his own position and against players with real
    minutes · a per-90 rate off two substitute appearances is noise, and leaving
    it in flatters everyone above it.
    """
    from analytics import player_card as PC
    from components.stat_badge import badges_row

    ls = _last_season_stats()
    if code not in ls.index:
        return ""
    row = ls.loc[code]
    pos = str(r.get("position", ""))
    full = _last_season_stats()

    def _num(v):
        try:
            f = float(v)
            return f if math.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    mins = _num(row.get("minutes")) or 0.0
    starts = _num(row.get("starts_total")) or 0.0
    pts = _num(row.get("total_points"))
    xgi = _num(row.get("xgi"))
    xgi90 = (xgi / mins * 90.0) if (xgi is not None and mins >= 90) else None
    ppstart = (pts / starts) if (pts is not None and starts >= 1) else None
    ppm = _num(row.get("pts_per_million"))

    dc = ctx.defcon.loc[code] if code in ctx.defcon.index else None
    dc90 = _num(dc.get("dc_per90")) if dc is not None else None
    dchit = _num(dc.get("dc_hit_rate")) if dc is not None else None

    def _rank(col, val, frame=None):
        pop = PC.rank_population(frame if frame is not None else full, col, pos)
        return PC.percentile(pop, val)

    # Derived columns the archive does not carry, computed across the same
    # population so the rank means what it says.
    _f = full.copy()
    _f["_xgi90"] = pd.to_numeric(_f.get("xgi"), errors="coerce") / \
        pd.to_numeric(_f.get("minutes"), errors="coerce").replace(0, float("nan")) * 90.0
    _f["_ppstart"] = pd.to_numeric(_f.get("total_points"), errors="coerce") / \
        pd.to_numeric(_f.get("starts_total"), errors="coerce").replace(0, float("nan"))

    items = [
        dict(label="Points", value=("%.0f" % pts) if pts is not None else None,
             sub="2025/26", percentile=_rank("total_points", pts)),
        dict(label="Points / start",
             value=("%.1f" % ppstart) if ppstart is not None else None,
             sub="per start", percentile=_rank("_ppstart", ppstart, _f)),
        dict(label="Points / £m", value=("%.1f" % ppm) if ppm is not None else None,
             sub="value last year", percentile=_rank("pts_per_million", ppm)),
        dict(label="xGI / 90", value=("%.2f" % xgi90) if xgi90 is not None else None,
             sub="goal involvement", percentile=_rank("_xgi90", xgi90, _f)),
    ]
    if dc90 is not None:
        thr = 10 if pos == "DEF" else 12
        items.append(dict(
            label="DEFCON / 90", value="%.1f" % dc90,
            sub="bar is %d" % thr,
            note=("hit it %.0f%% of starts" % (100 * dchit)) if dchit is not None else "",
            percentile=PC.percentile(
                PC.rank_population(_defcon_frame(ctx, full), "dc_per90", pos), dc90)))
    return badges_row(items)


def _this_week_panel(ctx: CardCtx, code: int, r, team_id: int) -> None:
    """What the models expect from this player, and from his team, in GW1.

    Clean-sheet and goal chances come from our own Dixon-Coles fit rather than a
    paid ticker · see `analytics/player_card.match_shape`.
    """
    from analytics import player_card as PC
    from components.stat_badge import badges_row

    gw = int(ctx.current_gw or 1)
    fx = ctx.fix.get((int(team_id), gw), [])
    pts = ctx.proj.points(int(code), gw)
    mins = ctx.proj.expected_minutes(int(code), gw)
    src = ctx.proj.source(int(code), gw)

    items = [
        dict(label="Projected GW%d" % gw, value="%.1f" % pts, sub="expected points",
             tone="cyan",
             note="match forecast" if src == "match" else "fixture shape"),
        dict(label="Expected minutes",
             value=("%.0f" % mins) if mins is not None else None,
             sub="this gameweek", tone="mint" if (mins or 0) >= 60 else "orange",
             note="" if mins is not None else "no stated view"),
    ]

    shape = None
    if fx:
        opp_short, is_home, _fdr = fx[0]
        ratings = _dc_ratings()
        keys = list((ratings or {}).get("attacks") or {})
        me = PC.resolve_team(str(r.get("team_name", "")), keys)
        # The fixture list gives the opponent's SHORT code, so it has to go back
        # through the bootstrap to get a name the fit will recognise.
        opp_name = _team_name_for_short(opp_short)
        them = PC.resolve_team(opp_name, keys)
        if me and them:
            shape = PC.match_shape(ratings, me, them, is_home)
    if shape:
        cs = 100 * shape["p_clean_sheet"]
        # `bar`, not `percentile` · this is the chance of the thing happening,
        # not a position in a distribution. Captioning 39% as "Top 61%" was
        # nonsense and is exactly what the two arguments now keep apart.
        items.append(dict(label="Clean sheet", value="%.0f%%" % cs,
                          sub="his team, this fixture", bar=int(round(cs)),
                          tone="mint" if cs >= 40 else "gold" if cs >= 25 else "red",
                          note="%.2f goals against" % shape["exp_goals_against"]))
        items.append(dict(label="Team goals",
                          value="%.2f" % shape["exp_goals_for"],
                          sub="expected, this fixture", tone="gold",
                          note="%.0f%% chance of 2+" % (100 * shape["p_score_2_plus"])))
    st.markdown(badges_row(items), unsafe_allow_html=True)
    if not shape:
        st.caption("Clean-sheet and team-goal odds need a Dixon-Coles fit for both "
                   "clubs. A promoted side has no Premier League history to fit, so "
                   "they are left blank rather than guessed.")


@st.dialog("Player", width="large")
def open_player_card(ctx: CardCtx, code: int) -> None:
    m = ctx.board[ctx.board["code"] == code]
    if m.empty:
        st.info("Player not on the board.")
        return
    r = m.iloc[0]
    p = profile(ctx, code)
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
            f'· {float(r.get("ownership") or 0):.1f}% owned</div>'
            + (f'<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">'
               + (f'<span style="background:{V("chip-bg")};color:{V("cyan")};'
                  f'border-radius:4px;padding:2px 7px;font-size:9.5px;'
                  f'font-weight:900;">NEW CLUB</span>'
                  if bool(r.get("changed_club")) else "")
               + (f'<span style="background:{V("chip-bg")};color:{V("orange")};'
                  f'border-radius:4px;padding:2px 7px;font-size:9.5px;'
                  f'font-weight:900;">LATE START</span>'
                  if int(r.get("code", 0) or 0) in miss_early_codes() else "")
               + '</div>')),
            unsafe_allow_html=True)
        st.markdown(set_piece_line(r), unsafe_allow_html=True)

    st.markdown(_keep_verdict(ctx, p, r), unsafe_allow_html=True)

    if bool(r.get("ffh_no_early_minutes", False)):
        _match_window = ctx.proj.window
        st.warning(f"The match model expects **{float(r.get('ffh_exp_mins_mean') or 0):.0f} "
                   f"minutes a game** from him over "
                   f"GW{_match_window[0]}-{_match_window[-1]}. The season numbers below "
                   f"assume he plays: they are a scenario for later in the season, "
                   f"not a read on the opening weeks.")

    st.markdown(_strip(_graded_tiles(ctx, code, r, p)), unsafe_allow_html=True)
    # Say which numbers are forecasts and which are facts. Reading a projection
    # with the confidence of a measured stat is how a punt starts to look safe.
    st.markdown(_one_line(
        f'<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:10.5px;'
        f'color:{V("muted")};margin:-6px 0 10px;">'
        f'<span><b style="color:{V("text")};">~</b> projected · a model\'s '
        f'opinion about this season</span>'
        f'<span><b style="color:{V("text")};">●</b> measured · what actually '
        f'happened in 2025-26</span></div>'), unsafe_allow_html=True)
    st.markdown(_one_line(
        f'<div style="font-size:11.5px;color:{V("muted2")};margin:-6px 0 10px;">'
        f'Green beats most players in his position, amber is mid-table, red is '
        f'behind. DEFCON is graded against the rule\'s bar, not against other '
        f'players · clearing it is a flat 2 points.</div>'), unsafe_allow_html=True)
    # ── One panel at a time, and only the one you are looking at ─────────────
    # `st.tabs` renders EVERY tab body on every run, so opening this dialog
    # mounted three ECharts iframes at once. That cost about 1.8 seconds of the
    # 2.5 the popup took to appear, and it also broke the charts: a chart that
    # mounts inside a hidden tab measures its container at ~90px, draws itself
    # at that width, and never re-measures when the tab is shown · which is why
    # the model chart arrived with "ScoutOursHub" printed on top of itself.
    #
    # A segmented control is a dialog-scoped widget, so switching panels reruns
    # the dialog fragment only, and the chart mounts while it is VISIBLE and
    # sizes itself correctly. One iframe instead of three, drawn at the width it
    # actually has.
    # Ordered the way the question is actually asked: what do we expect from him
    # now, what has he actually done, then the two "is the number trustworthy"
    # views. Projections first because that is what a draft decision turns on.
    PANELS = ["This week", "Fixtures", "Last season", "Model agreement",
              "Value for money"]
    _pk = f"dlg_panel_{code}"
    panel = st.segmented_control(
        "View", PANELS, key=_pk,
        default=st.session_state.get(_pk) or PANELS[0],
        label_visibility="collapsed") or PANELS[0]

    if panel == "This week":
        _this_week_panel(ctx, code, r, team_id)
        _run_chart(ctx, code, r, team_id, f"dlg_run_{code}")
    elif panel == "Fixtures":
        _run_chart(ctx, code, r, team_id, f"dlg_runfx_{code}")
        from components.fixture_ticker import player_fixture_strip, run_summary
        st.markdown(player_fixture_strip(ctx.fix, team_id, 1, 12), unsafe_allow_html=True)
        s6 = run_summary(ctx.fix, team_id, 1, 6)
        f6 = s6.get("mean_fdr")
        read = "kind" if (f6 or 3) <= 2.85 else "tough" if (f6 or 3) >= 3.2 else "average"
        st.markdown(_one_line(
            f'<div style="font-size:12.5px;color:{V("muted")};margin-top:4px;">'
            f'Opening six average <b>{f6 if f6 is not None else "n/a"}</b> difficulty '
            f'({read}), {s6["home"]} at home.</div>'), unsafe_allow_html=True)
    elif panel == "Model agreement":
        _model_chart(ctx, r, code)
    elif panel == "Value for money":
        _band_chart(ctx, code, r, p, f"dlg_band_{code}")
    else:
        ls = _last_season_stats()
        if code in ls.index:
            lsr = ls.loc[code]
            _tiles([
                ("Goals", f"{float(lsr.get('goals') or 0):.0f}", "2025/26", "orange"),
                ("Assists", f"{float(lsr.get('assists') or 0):.0f}", "2025/26", "mag"),
                ("Minutes", f"{float(lsr.get('minutes') or 0):,.0f}", "2025/26", "cyan"),
                ("Clean sheets", f"{float(lsr.get('clean_sheets') or 0):.0f}",
                 "2025/26", "mint"),
            ])
            # The rate stats, each against the players he is competing with for a
            # slot. A bare 6.7 DEFCON per 90 says nothing; "top 16% of defenders"
            # is the number a human can act on.
            st.markdown(_last_season_badges(ctx, code, r), unsafe_allow_html=True)
            st.caption("Ranks are against others in his position who played at "
                       "least 450 minutes · a per-90 rate off a couple of "
                       "substitute appearances is noise.")
        else:
            st.info("No 2025/26 Premier League record · this projection comes from "
                    "an external model or a manual override.")
        note = str(r.get("override_note", "") or "")
        if note:
            st.info(f"Manual override: {note}")

    n_btns = sum(x is not None for x in (ctx.on_replace, ctx.on_compare, ctx.on_captain))
    if n_btns:
        btn_cols = st.columns(n_btns)
        _i = 0
        if ctx.on_replace is not None:
            with btn_cols[_i]:
                in_squad = bool(ctx.in_squad(code)) if ctx.in_squad is not None else True
                if st.button(":material/swap_horiz: Replace him", key=f"dlg_axe_{code}",
                             use_container_width=True, disabled=not in_squad,
                             type="primary" if in_squad else "secondary"):
                    ctx.on_replace(code)
            _i += 1
        if ctx.on_compare is not None:
            with btn_cols[_i]:
                if st.button(":material/balance: Compare him", key=f"dlg_cmp_{code}",
                             use_container_width=True):
                    ctx.on_compare(code)
            _i += 1
        if ctx.on_captain is not None:
            with btn_cols[_i]:
                if st.button(f"⭐ Captain for GW{ctx.captain_gw}", key=f"dlg_cap_{code}",
                             use_container_width=True):
                    ctx.on_captain(code)
