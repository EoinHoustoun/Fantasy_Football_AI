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


def _chip_card(name: str, gw, headline: str, why: str, tone: str,
               note: str = "") -> str:
    """`gw` is a week number or a label ("GW7", "Hold")."""
    big = ("GW%d" % gw) if isinstance(gw, int) else str(gw)
    col = V(tone)
    return _one_line(
        f'<div style="background:{V("card")};border:1px solid {V("line")};'
        f'border-top:3px solid {col};border-radius:12px;padding:16px 18px;'
        f'height:100%;">'
        f'<div style="font-size:9.5px;font-weight:800;letter-spacing:0.14em;'
        f'text-transform:uppercase;color:{V("muted")};">{name}</div>'
        f'<div class="ff-display" style="font-size:38px;font-weight:900;'
        f'color:{col};line-height:1.05;margin-top:2px;'
        f'font-variant-numeric:tabular-nums;">{big}</div>'
        f'<div style="font-size:14px;font-weight:700;color:{V("text")};'
        f'margin-top:2px;">{headline}</div>'
        f'<div style="font-size:12px;color:{V("muted")};margin-top:6px;'
        f'line-height:1.5;">{why}</div>'
        + (f'<div style="font-size:11px;color:{col};margin-top:8px;">{note}</div>'
           if note else "")
        + '</div>')


# ── Header ───────────────────────────────────────────────────────────────────
from ui.page import header as _header
_header("Chips", "Which week to spend each chip you still hold, priced on the engine.", kicker="Plan", icon="casino")


# ── Squad ────────────────────────────────────────────────────────────────────
# A saved draft first · chip timing depends on WHICH fifteen you own, and the
# page used to solve its own squad, so it answered for a team you had not built.
from analytics import drafts as DR

# ── Chip state · which chips are still in hand this half ─────────────────────
from analytics.chip_state import LABEL as CHIP_LABEL, chip_state
from data.fetchers.fpl_api import fetch_entry_history, fetch_team_picks

_bs = st.session_state.get("bootstrap") or {}
_next_gw = next((int(e["id"]) for e in _bs.get("events", []) if e.get("is_next")), 1)
_team_id = st.session_state.get("squad_team_id")


@st.cache_data(ttl=900, show_spinner=False)
def _chips_played(team_id: int):
    try:
        return fetch_entry_history(int(team_id)).get("chips", [])
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def _my_codes(team_id: int, gw: int):
    try:
        from data.fetchers.fpl_api import fetch_bootstrap
        by_id = {int(p["id"]): int(p["code"]) for p in fetch_bootstrap()["elements"]}
        picks = fetch_team_picks(int(team_id), int(gw)).get("picks", [])
        return [by_id[int(p["element"])] for p in picks if int(p["element"]) in by_id]
    except Exception:
        return []


_played = _chips_played(_team_id) if _team_id else None
CS = chip_state(_played or [], _next_gw)
if _played is not None:
    _pills = "".join(
        f'<span style="display:inline-flex;gap:6px;align-items:center;padding:4px 10px;'
        f'border-radius:999px;border:1px solid {V("line")};margin-right:6px;'
        f'font-size:12px;color:{V("muted")};">{CHIP_LABEL[c]} '
        f'<b style="color:{V("text")};">played GW{g}</b></span>'
        for c, g in sorted(CS["used"].items(), key=lambda kv: kv[1]))
    st.markdown(_one_line(
        f'<div style="margin:4px 0 12px;">{_pills}'
        f'<span style="font-size:12px;color:{V("muted")};">Planning GW{CS["gw_lo"]}-{CS["gw_hi"]} '
        f'· {"first" if CS["half"] == 1 else "second"} set of chips</span></div>'),
        unsafe_allow_html=True)

def _played_card(name: str, key: str) -> str:
    return _one_line(
        f'<div style="background:{V("card")};border:1px dashed {V("line")};'
        f'border-radius:12px;padding:16px 18px;height:100%;opacity:0.75;">'
        f'<div style="font-size:9.5px;font-weight:800;letter-spacing:0.14em;'
        f'text-transform:uppercase;color:{V("muted")};">{name}</div>'
        f'<div class="ff-display" style="font-size:30px;font-weight:900;'
        f'color:{V("muted")};margin-top:2px;">Played</div>'
        f'<div style="font-size:12.5px;color:{V("muted")};margin-top:4px;">'
        f'GW{CS["used"].get(key, "?")} · back for the second half from GW20</div></div>')



# ── In season: every chip priced on the engine, one source for the whole page ──
# The calendar, the three cards and the week-by-week chart used to come from the
# preseason Value Board (season projection shaped by fixtures, GW1-19) while the
# Free Hit section read the engine, and the two disagreed about the same week.
# In season they all read `service.chip_calendar` / `service.chip_squad` now.
from analytics import service as _svc

_long = _svc.projections(allow_compute=False)
if _team_id and _long is not None:
    from ui.page import section as _section

    @st.cache_data(ttl=1800, show_spinner=False)
    def _fh_by_week(team_id: int, stamp: str):
        out = []
        for g in sorted(int(x) for x in _svc.projections(allow_compute=False)["gw"].unique()):
            if g > CS["gw_hi"]:
                break
            r = _svc.chip_squad("fh", g, team_id=team_id)
            if r.get("ok"):
                out.append(r)
        return out

    _stamp = "%s-%s-%s" % (_next_gw, len(_played or []), id(_long))
    HAVE = {"bench_boost": "bboost" in CS["remaining"],
            "triple_captain": "3xc" in CS["remaining"],
            "free_hit": "freehit" in CS["remaining"]}
    cal = [w for w in _svc.chip_calendar(int(_team_id))["weeks"] if w["gw"] <= CS["gw_hi"]]
    _fh = []
    if HAVE["free_hit"]:
        with st.spinner("Solving a Free Hit squad for each week"):
            _fh = _fh_by_week(int(_team_id), _stamp)
    fh_gain = {r["gws"][0]: r["gain"] for r in _fh}
    for w_ in cal:
        w_["fh_gain"] = fh_gain.get(w_["gw"])

    def _pick(key, flat_gap):
        rows = [w_ for w_ in cal if w_.get(key) is not None]
        if not rows:
            return None, True, 0.0
        vals = sorted(w_[key] for w_ in rows)
        best = max(rows, key=lambda w_: w_[key])
        med = vals[len(vals) // 2]
        return best, (best[key] - med) < flat_gap, med

    bb_best, bb_flat, bb_med = _pick("bench_pts", 2.0)
    tc_best, tc_flat, tc_med = _pick("captain_xp", 1.5)
    fh_best, fh_flat, fh_med = _pick("fh_gain", 3.0)
    lo_gw, hi_gw = cal[0]["gw"], cal[-1]["gw"]

    _marks = {k: b["gw"] for k, b, have, flat in (
        ("bench_boost", bb_best, HAVE["bench_boost"], bb_flat),
        ("triple_captain", tc_best, HAVE["triple_captain"], tc_flat),
        ("free_hit", fh_best, HAVE["free_hit"], fh_flat)) if have and b and not flat}
    st.markdown(_timeline(cal, _marks, lo_gw, hi_gw), unsafe_allow_html=True)
    if len(set(_marks.values())) < len(_marks):
        st.warning("Two chips want the same week. You can only play one, so take the "
                   "bigger gain and move the other to its next-best week below.")

    def _hold_card(name: str, tone: str, best_txt: str, why: str) -> str:
        return _chip_card(name, "Hold", best_txt, why, tone,
                          "No standout week in GW%d-%d. Doubles and blanks are where chips pay."
                          % (lo_gw, hi_gw))

    h1, h2, h3 = st.columns(3)
    with h1:
        if not HAVE["bench_boost"]:
            st.markdown(_played_card("Bench Boost", "bboost"), unsafe_allow_html=True)
        elif bb_flat:
            st.markdown(_hold_card("Bench Boost", CHIP_TONE["bench_boost"],
                                   "Best GW%d: %.1f bench pts" % (bb_best["gw"], bb_best["bench_pts"]),
                                   "A typical week is worth %.1f." % bb_med), unsafe_allow_html=True)
        else:
            st.markdown(_chip_card(
                "Bench Boost", "GW%d" % bb_best["gw"], "%.1f bench points" % bb_best["bench_pts"],
                "Bench that week: %s. A typical week is worth %.1f."
                % (" · ".join(bb_best["bench"]), bb_med), CHIP_TONE["bench_boost"]),
                unsafe_allow_html=True)
    with h2:
        if not HAVE["triple_captain"]:
            st.markdown(_played_card("Triple Captain", "3xc"), unsafe_allow_html=True)
        elif tc_flat:
            st.markdown(_hold_card("Triple Captain", CHIP_TONE["triple_captain"],
                                   "Best GW%d: %s +%.1f" % (tc_best["gw"], tc_best["captain"],
                                                            tc_best["captain_xp"]),
                                   "A typical week adds %.1f." % tc_med), unsafe_allow_html=True)
        else:
            st.markdown(_chip_card(
                "Triple Captain", "GW%d" % tc_best["gw"], "+%.1f points" % tc_best["captain_xp"],
                "%s in his best week of the horizon. A typical week adds %.1f."
                % (tc_best["captain"], tc_med), CHIP_TONE["triple_captain"]), unsafe_allow_html=True)
    with h3:
        if not HAVE["free_hit"]:
            st.markdown(_played_card("Free Hit", "freehit"), unsafe_allow_html=True)
        elif fh_best is None:
            st.markdown(_hold_card("Free Hit", CHIP_TONE["free_hit"], "No solve available", ""),
                        unsafe_allow_html=True)
        elif fh_flat:
            st.markdown(_hold_card("Free Hit", CHIP_TONE["free_hit"],
                                   "Best GW%d: +%.1f" % (fh_best["gw"], fh_best["fh_gain"]),
                                   "A typical week gains %.1f over your XI." % fh_med),
                        unsafe_allow_html=True)
        else:
            st.markdown(_chip_card(
                "Free Hit", "GW%d" % fh_best["gw"], "+%.1f over your XI" % fh_best["fh_gain"],
                "A typical week gains %.1f." % fh_med, CHIP_TONE["free_hit"]), unsafe_allow_html=True)

    VIEWS = [lbl for lbl, k in (("Bench Boost", "bench_boost"), ("Triple Captain", "triple_captain"),
                                 ("Free Hit", "free_hit")) if HAVE[k]]
    if not VIEWS:
        st.info("Every chip in this set is played. The second set arrives in GW20.")
        st.stop()
    _section("Week by week", "What each chip you hold would add in each week of the engine's "
             "horizon, on your current fifteen.", "bar_chart")
    view = st.segmented_control("Week by week", VIEWS, default=VIEWS[0],
                                label_visibility="collapsed") or VIEWS[0]
    key, best, tone = {"Bench Boost": ("bench_pts", bb_best, "cyan"),
                       "Triple Captain": ("captain_xp", tc_best, "gold"),
                       "Free Hit": ("fh_gain", fh_best, "mint")}[view]
    rows = [w_ for w_ in cal if w_.get(key) is not None]
    opt = charts.bar_option(
        x=["GW%d" % w_["gw"] for w_ in rows], y=[round(w_[key], 1) for w_ in rows],
        colors=[theme.fill(tone) if best and w_["gw"] == best["gw"] else theme.fill("muted2")
                for w_ in rows])
    opt["tooltip"]["formatter"] = "{b}: +{c} pts"
    charts.render(opt, height="260px", key="chipcal_%s" % view.replace(" ", "_"))

    if view == "Free Hit" and _fh:
        _pick_gw = st.selectbox("Show the Free Hit squad for", ["GW%d" % r["gws"][0] for r in _fh],
                                index=[r["gws"][0] for r in _fh].index(fh_best["gw"]), key="fh_pick")
        _r = next(r for r in _fh if "GW%d" % r["gws"][0] == _pick_gw)
        st.markdown(_one_line(
            f'<div style="background:{V("card")};border:1px solid {V("line")};'
            f'border-top:3px solid {V("mint")};border-radius:14px;padding:14px 16px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
            f'<div class="ff-display ff-num" style="font-size:30px;font-weight:900;color:{V("mint")};">'
            f'+{_r["gain"]:.1f}</div><div style="font-size:12.5px;color:{V("muted")};">'
            f'{_r["points"]:.1f} vs your {_r["current_points"]:.1f} · £{_r["cost"]:.1f}m of '
            f'£{_r["budget"]:.1f}m</div></div>'
            + "".join(
                f'<div style="display:flex;align-items:center;gap:8px;padding:4px 0;'
                f'border-bottom:1px solid {V("line")};font-size:13px;'
                f'{"opacity:0.6;" if not p["in_xi"] else ""}">'
                f'<span style="width:34px;color:{V("muted")};">{p["position"]}</span>'
                f'<span style="flex:1;color:{V("text")};font-weight:{700 if p["captain"] else 500};">'
                f'{p["name"]}{" (C)" if p["captain"] else ""}{" · yours" if p["owned"] else ""}</span>'
                f'<span class="ff-num" style="color:{V("cyan")};">{p["xp"]:.2f}</span></div>'
                for p in sorted(_r["squad"], key=lambda p: (not p["in_xi"],
                                ["GKP", "DEF", "MID", "FWD"].index(p["position"]))))
            + '</div>'), unsafe_allow_html=True)

    st.caption("All on the engine and your current fifteen, GW%d-%d (its horizon). This set must "
               "be spent by GW%d; later weeks join as the horizon rolls forward. Blanks and doubles "
               "are announced during the season and are where chips pay, so re-read this when one "
               "is." % (lo_gw, hi_gw, CS["gw_hi"]))
    st.stop()

# ── Preseason fallback: the Value Board path, for a draft before a ball is kicked ──
board, scout, _, _ = build_board(_freshness.inputs_stamp())
if board is None:
    st.error("The archive has not been built. Run `python scripts/build_archive.py`, "
             "then reload this page.")
    st.stop()
_saved = [d for d in DR.load_drafts() if DR.has_squad(d)]
_mine = _my_codes(_team_id, _next_gw) if _team_id else []
_opts = (["My squad"] if len(_mine) == 15 else []) + ["Solve a fresh squad"] + [d["name"] for d in _saved]
c1, c2 = st.columns([3, 1])
with c1:
    pick = st.selectbox("Squad", _opts, label_visibility="collapsed")
with c2:
    budget = st.slider("Budget (£m)", 95.0, 105.0, 100.0, 0.5, key="chip_budget",
                       label_visibility="collapsed")

squad = None
if pick == "My squad":
    squad = board[board["code"].isin(_mine)].copy()
    squad["pts"] = squad.get("consensus_points", squad.get("projected_points"))
    squad["in_xi"] = squad["code"].isin(squad.nlargest(11, "pts")["code"])
    src = "your current squad"
elif pick != "Solve a fresh squad":
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

GW_LO, GW_HI = CS["gw_lo"], CS["gw_hi"]
w = chip_windows(squad, fixtures_df, GW_LO, GW_HI, proj=PROJ)

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
bb_gw1 = next((x for x in bb if x["gw"] == GW_LO), {"gw": GW_LO, "bench_pts": 0.0})
bench_names = " · ".join(squad[~squad.get("in_xi", True)]["web_name"].tolist()[:4])

# ── The calendar · the whole decision in one strip ───────────────────────────
by_gw = sorted(fh, key=lambda x: x["gw"])
HAVE = {"bench_boost": "bboost" in CS["remaining"],
        "triple_captain": "3xc" in CS["remaining"],
        "free_hit": "freehit" in CS["remaining"]}
_marks = {k: v for k, v in {"bench_boost": bb_best["gw"],
                            "triple_captain": tc_best["gw"],
                            "free_hit": fh_best["gw"]}.items() if HAVE[k]}
st.markdown(_timeline(by_gw, _marks, GW_LO, GW_HI, match_hi=_MATCH_HI),
            unsafe_allow_html=True)

# A clash is the one thing a planner must not let you miss.
_weeks = list(_marks.values())
if len(set(_weeks)) < len(_weeks):
    st.warning("Two chips want the same week. You can only play one, so take the "
               "bigger gain and move the other to its next-best week below.")

# ── The three calls ──────────────────────────────────────────────────────────
h1, h2, h3 = st.columns(3)
with h1:
    if not HAVE["bench_boost"]:
        st.markdown(_played_card("Bench Boost", "bboost"), unsafe_allow_html=True)
    else:
        note = ("Needs no transfers or wildcard to set up"
                if bb_best["gw"] == GW_LO else
                "GW%d is worth %.0f and needs no prep" % (GW_LO, bb_gw1["bench_pts"]))
        st.markdown(_chip_card(
            "Bench Boost", bb_best["gw"], "%.0f bench points" % bb_best["bench_pts"],
            "Your four bench players all score. %s" % (bench_names or "Bench: n/a"),
            CHIP_TONE["bench_boost"], note), unsafe_allow_html=True)
with h2:
    if not HAVE["triple_captain"]:
        st.markdown(_played_card("Triple Captain", "3xc"), unsafe_allow_html=True)
    else:
        st.markdown(_chip_card(
            "Triple Captain", tc_best["gw"], "+%.0f points" % tc_best["extra_pts"],
            "%s in his best week of this window." % (tc_best["captain"] or "n/a"),
            CHIP_TONE["triple_captain"]), unsafe_allow_html=True)
with h3:
    if not HAVE["free_hit"]:
        st.markdown(_played_card("Free Hit", "freehit"), unsafe_allow_html=True)
    else:
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
VIEWS = [lbl for lbl, k in (("Bench Boost", "bench_boost"), ("Triple Captain", "triple_captain"),
                             ("Free Hit", "free_hit")) if HAVE[k]]
if not VIEWS:
    st.info("Every chip in this set is played. The second set arrives in GW20.")
    st.stop()
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
