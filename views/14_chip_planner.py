"""
Chip Planner · first half (GW1-19).

2026/27 gives two of every chip and the first set (Wildcard, Free Hit, Bench
Boost, Triple Captain) must be spent by GW19, so this only plans the first half.

The page is a CALENDAR, because that is what the decision is. You are not
choosing whether to play a chip, you are choosing which of nineteen Saturdays to
spend it on, and the old layout hid that behind two bar charts in separate tabs.
One nineteen-week strip carries every chip at once, so a clash (two chips
wanting the same week) is visible rather than something you work out yourself.

Per-gameweek points come from `analytics/gw_projection` via the projector this
page passes into `chip_windows`. It used to spread a season projection over 38
and scale it by fixture difficulty, which is a fixture shape rather than a
forecast · and it meant this page and the Draft page could disagree about the
same squad.
"""
import streamlit as st

from analytics import freshness as _freshness
from analytics.chip_timing import chip_windows, level_by_source
from components.animations import inject_global_animations
from config import CHIP_TIMING
from ui import charts, theme
from ui.theme import var as V
from ui.value_board import DRAFT_STRATEGIES, build_board, solve_draft

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

# Every chip gets ONE colour and keeps it in the strip, the cards and the chart,
# so the eye can follow a chip across the page without re-reading a legend.
# Tokens, never hex · a literal here is what breaks light mode.
CHIP_TONE = {"bench_boost": "cyan", "triple_captain": "gold", "free_hit": "mint"}


def _one_line(html: str) -> str:
    """st.markdown stops passing raw HTML through when a line is whitespace-only
    and renders the rest as literal text. Collapse every card to one line."""
    return "".join(seg.strip() for seg in html.splitlines())


def _timeline(rows, marks, gw_lo, gw_hi, match_hi: int = 0) -> str:
    """Nineteen gameweeks as one strip, with each chip marked on its best week.

    The signature of this page. Bar height is that week's squad projection, so
    the shape of the season is visible at a glance, and the chip markers sit on
    the weeks they want. Two markers on one column is a clash you can see.
    """
    if not rows:
        return ""
    # Scaled to the RANGE, not to zero. Once the two model regions are levelled
    # the weeks sit in a narrow band, and bars measured from zero all come out
    # the same height · a strip that looks like data and carries none. The
    # question here is only "which weeks are the quiet ones", so show the spread.
    vals = [r["squad_pts"] for r in rows]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    cells = []
    for r in rows:
        gw = r["gw"]
        h = 10 + round(46.0 * (r["squad_pts"] - lo) / span)
        here = [(k, v) for k, v in marks.items() if v == gw]
        tone = CHIP_TONE[here[0][0]] if here else None
        col = V(tone) if tone else V("line")
        pins = "".join(
            f'<div style="width:7px;height:7px;border-radius:2px;'
            f'background:{V(CHIP_TONE[k])};margin:0 auto 2px;"></div>'
            for k, _ in here)
        # A hairline where the forecast stops and the shape begins · the reader
        # should know which half of the strip is a real match model.
        edge = ("border-right:1px dashed %s;padding-right:3px;" % V("line")
                if match_hi and gw == match_hi else "")
        cells.append(
            f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
            f'align-items:center;gap:2px;{edge}">'
            f'<div style="height:18px;display:flex;flex-direction:column;'
            f'justify-content:flex-end;">{pins}</div>'
            f'<div title="GW{gw} · {r["squad_pts"]:.0f} pts" style="width:100%;'
            f'height:{h}px;background:{col};opacity:{1.0 if here else 0.30};'
            f'border-radius:3px 3px 0 0;"></div>'
            f'<div style="font-size:8.5px;color:{V("muted")};'
            f'font-variant-numeric:tabular-nums;">{gw}</div>'
            f'</div>')
    legend = " ".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;">'
        f'<span style="width:7px;height:7px;border-radius:2px;'
        f'background:{V(t)};"></span>'
        f'<span style="color:{V("muted")};font-size:10.5px;">{lbl}</span></span>'
        for lbl, t in (("Bench Boost", "cyan"), ("Triple Captain", "gold"),
                       ("Free Hit", "mint")))
    return _one_line(
        f'<div style="background:{V("card")};border:1px solid {V("line")};'
        f'border-radius:12px;padding:16px 18px 12px;">'
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:baseline;margin-bottom:10px;">'
        f'<div style="font-size:9.5px;font-weight:800;letter-spacing:0.16em;'
        f'text-transform:uppercase;color:{V("muted")};">'
        f'GW{gw_lo}-{gw_hi} · squad projection, best to worst week</div>'
        f'<div style="display:flex;gap:12px;">{legend}</div></div>'
        f'<div style="display:flex;align-items:flex-end;gap:3px;">'
        + "".join(cells) + '</div></div>')


def _chip_card(name: str, gw: int, headline: str, why: str, tone: str,
               note: str = "") -> str:
    col = V(tone)
    return _one_line(
        f'<div style="background:{V("card")};border:1px solid {V("line")};'
        f'border-top:3px solid {col};border-radius:12px;padding:16px 18px;'
        f'height:100%;">'
        f'<div style="font-size:9.5px;font-weight:800;letter-spacing:0.14em;'
        f'text-transform:uppercase;color:{V("muted")};">{name}</div>'
        f'<div class="ff-display" style="font-size:38px;font-weight:900;'
        f'color:{col};line-height:1.05;margin-top:2px;'
        f'font-variant-numeric:tabular-nums;">GW{gw}</div>'
        f'<div style="font-size:14px;font-weight:700;color:{V("text")};'
        f'margin-top:2px;">{headline}</div>'
        f'<div style="font-size:12px;color:{V("muted")};margin-top:6px;'
        f'line-height:1.5;">{why}</div>'
        + (f'<div style="font-size:11px;color:{col};margin-top:8px;">{note}</div>'
           if note else "")
        + '</div>')


# ── Header ───────────────────────────────────────────────────────────────────
st.markdown(_one_line(
    f'<div style="padding:16px 0 2px;">'
    f'<div class="ff-display" style="font-size:34px;font-weight:900;'
    f'color:{V("text")};letter-spacing:-0.6px;">Chip Planner</div>'
    f'<div style="font-size:13.5px;color:{V("muted")};margin-top:2px;">'
    f'Which week to spend each first-half chip.</div></div>'),
    unsafe_allow_html=True)

board, scout, _, _ = build_board(_freshness.inputs_stamp())
if board is None:
    st.error("The archive has not been built. Run `python scripts/build_archive.py`, "
             "then reload this page.")
    st.stop()

# ── Squad ────────────────────────────────────────────────────────────────────
# A saved draft first · chip timing depends on WHICH fifteen you own, and the
# page used to solve its own squad, so it answered for a team you had not built.
from analytics import drafts as DR

_saved = [d for d in DR.load_drafts() if DR.has_squad(d)]
_opts = ["Solve a fresh squad"] + [d["name"] for d in _saved]
c1, c2 = st.columns([3, 1])
with c1:
    pick = st.selectbox("Squad", _opts, label_visibility="collapsed")
with c2:
    budget = st.slider("Budget (£m)", 95.0, 105.0, 100.0, 0.5, key="chip_budget",
                       label_visibility="collapsed")

squad = None
if pick != "Solve a fresh squad":
    d = next(x for x in _saved if x["name"] == pick)
    codes = [int(c) for c in d["squad"]]
    squad = board[board["code"].isin(codes)].copy()
    squad["pts"] = squad.get("consensus_points", squad.get("projected_points"))
    # The XI is re-picked per gameweek below · this only seeds a starting split.
    squad["in_xi"] = squad["code"].isin(
        squad.nlargest(11, "pts")["code"]) if len(squad) == 15 else True
    src = "saved draft"
else:
    strategy = st.radio("Strategy", DRAFT_STRATEGIES, horizontal=True,
                        label_visibility="collapsed")
    res = solve_draft(board, strategy, budget)
    if res is None:
        st.error("No legal squad fits that budget. Raise it, or pick a saved draft.")
        st.stop()
    squad = res["squad"]
    src = strategy

if squad is None or squad.empty:
    st.error("That draft's players are not on the current board. Re-save it on the "
             "Draft page and come back.")
    st.stop()

# ── Per-gameweek projector · the same one every other surface reads ──────────
import pandas as pd

fixtures_df = st.session_state.get("fixtures_df")
if fixtures_df is None:
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    fixtures_df = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())


@st.cache_resource(show_spinner=False)
def _projector(stamp: str, _board):
    from analytics import gw_projection
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    bs = fetch_bootstrap()
    short = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    fx = get_fixtures_df(fetch_fixtures(), bs)
    fmap = {}
    for _, r in fx.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        g, h, a = int(r["gameweek"]), int(r["home_team_id"]), int(r["away_team_id"])
        fmap.setdefault((h, g), []).append((short.get(a, "?"), True, float(r["home_fdr"])))
        fmap.setdefault((a, g), []).append((short.get(h, "?"), False, float(r["away_fdr"])))
    return gw_projection.build(_board, fmap)


PROJ = _projector(_freshness.inputs_stamp(), board)

GW_HI = CHIP_TIMING["first_batch_gw_hi"]
w = chip_windows(squad, fixtures_df, 1, GW_HI, proj=PROJ)

# GW1-6 are per-fixture forecasts and GW7+ is fixture shape, and on the real
# board the two sit about 23% apart. Untouched, that step decides every chip:
# anything wanting a quiet week lands in GW1-6 and anything wanting a big week
# lands after it, whatever the fixtures say. Level them before they compete.
bb = level_by_source(w["bench_boost"], key="bench_pts")
tc = level_by_source(w["triple_captain"], key="extra_pts")
fh = level_by_source(w["free_hit"], key="squad_pts")
bb = sorted(bb, key=lambda r: -r["bench_pts"])
tc = sorted(tc, key=lambda r: -r["extra_pts"])
fh = sorted(fh, key=lambda r: (r["squad_pts"], -r["blanks"]))
_MATCH_HI = max([r["gw"] for r in fh if r.get("source") == "match"] or [0])
bb_best, tc_best, fh_best = bb[0], tc[0], fh[0]
bb_gw1 = next((x for x in bb if x["gw"] == 1), {"gw": 1, "bench_pts": 0.0})
bench_names = " · ".join(squad[~squad.get("in_xi", True)]["web_name"].tolist()[:4])

# ── The calendar · the whole decision in one strip ───────────────────────────
by_gw = sorted(fh, key=lambda x: x["gw"])
st.markdown(_timeline(by_gw, {"bench_boost": bb_best["gw"],
                              "triple_captain": tc_best["gw"],
                              "free_hit": fh_best["gw"]}, 1, GW_HI,
                        match_hi=_MATCH_HI),
            unsafe_allow_html=True)

# A clash is the one thing a planner must not let you miss.
_weeks = [bb_best["gw"], tc_best["gw"], fh_best["gw"]]
if len(set(_weeks)) < 3:
    st.warning("Two chips want the same week. You can only play one, so take the "
               "bigger gain and move the other to its next-best week below.")

# ── The three calls ──────────────────────────────────────────────────────────
h1, h2, h3 = st.columns(3)
with h1:
    note = ("GW1 needs no transfers or wildcard to set up"
            if bb_best["gw"] == 1 else
            "GW1 is worth %.0f and needs no prep" % bb_gw1["bench_pts"])
    st.markdown(_chip_card(
        "Bench Boost", bb_best["gw"], "%.0f bench points" % bb_best["bench_pts"],
        "Your four bench players all score. %s" % (bench_names or "Bench: n/a"),
        CHIP_TONE["bench_boost"], note), unsafe_allow_html=True)
with h2:
    st.markdown(_chip_card(
        "Triple Captain", tc_best["gw"], "+%.0f points" % tc_best["extra_pts"],
        "%s in his best week of the first half." % (tc_best["captain"] or "n/a"),
        CHIP_TONE["triple_captain"]), unsafe_allow_html=True)
with h3:
    blanks = fh_best.get("blanks", 0)
    why = ("%d of your fifteen have no fixture." % blanks if blanks
           else "Your squad's worst week for fixtures.")
    st.markdown(_chip_card(
        "Free Hit", fh_best["gw"], "%.0f squad points" % fh_best["squad_pts"],
        why, CHIP_TONE["free_hit"]), unsafe_allow_html=True)

st.markdown(_one_line(
    f'<div style="font-size:11.5px;color:{V("muted")};margin:10px 0 2px;">'
    f'Squad: <b style="color:{V("text")};">{src}</b>. A Bench Boost wants a full, '
    f'well-fixtured bench; a Triple Captain wants your best player\'s softest '
    f'week; a Free Hit rescues your worst.</div>'), unsafe_allow_html=True)

# ── One chart at a time ──────────────────────────────────────────────────────
# `st.tabs` renders every tab body on every run, which mounts each chart in a
# hidden container. A chart that mounts hidden measures itself at ~90px and
# never re-measures, which is how a previous version arrived with its labels
# printed on top of each other. A segmented control renders one.
VIEWS = ["Bench Boost", "Triple Captain", "Free Hit"]
view = st.segmented_control("Week by week", VIEWS, default=VIEWS[0],
                            label_visibility="collapsed") or VIEWS[0]

if view == "Bench Boost":
    rows = sorted(bb, key=lambda x: x["gw"])
    ys, best, tone = [r["bench_pts"] for r in rows], bb_best["gw"], "cyan"
    cap = "What your bench scores each week. Higher is a better Bench Boost."
elif view == "Triple Captain":
    rows = sorted(tc, key=lambda x: x["gw"])
    ys, best, tone = [r["extra_pts"] for r in rows], tc_best["gw"], "gold"
    cap = "The extra points from tripling your captain, week by week."
else:
    rows = sorted(fh, key=lambda x: x["gw"])
    ys, best, tone = [r["squad_pts"] for r in rows], fh_best["gw"], "mint"
    cap = "What your squad scores each week. A Free Hit is worth most at the low point."

st.caption(cap)
opt = charts.bar_option(
    x=[r["gw"] for r in rows], y=ys,
    colors=[theme.fill(tone) if r["gw"] == best else theme.fill("muted2")
            for r in rows])
opt["tooltip"]["formatter"] = "GW{b}: {c}"
charts.render(opt, height="280px", key="chip_%s" % view.replace(" ", "_"))

st.caption(
    "GW1-%d are per-fixture forecasts. Later weeks are the season projection "
    "shaped by fixture difficulty, and the two sit about 23%% apart on this "
    "board, so they are levelled onto one scale before any chip is chosen · "
    "otherwise the model boundary picks your chips rather than the fixtures. "
    "Differences inside each stretch are untouched. Doubles and blanks firm up "
    "during the season. Wildcard timing has its own page." % (_MATCH_HI or 6))
