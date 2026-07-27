"""
2026-27 Value Board · actual launch prices vs projected points.

FPL has published the real 2026-27 prices, so this page is no longer a
projection of prices · it is the value read on the ones that shipped. Each
player's projected points (fitted on the 2025-26 archive) is set against their
actual price and bucketed by `analytics/value_verdicts.py`:

  Necessity · Value (under-priced) · Overpriced · Fair · Scout (no history)

The optimal GW1 squad is solved on the ACTUAL prices, so it is a squad you can
literally build. Promoted-club and new-signing players have no history and are
shown as Scout cards, not given fake numbers.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.animations import inject_global_animations
from components.pitch_view import render_squad_pitch
from components.team_identity import face_html, player_photo_url, team_dot
from config import LAST_COMPLETE_SEASON, NEXT_SEASON
from analytics.value_verdicts import VERDICTS
from ui import charts

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

def _num_safe(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def cap_badge(is_captain: bool) -> str:
    """Gold C armband · matches the captain treatment on the pitch."""
    if not is_captain:
        return ""
    return ('<span style="display:inline-block;background:#FFD700;color:#000;'
            'border-radius:3px;padding:0 3px;font-size:8px;font-weight:900;'
            'margin-right:3px;vertical-align:middle;">C</span>')


POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
POS_ORDER = ["GKP", "DEF", "MID", "FWD"]
MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:14px 18px;")

# verdict → (accent colour, emoji, one-line meaning)
VERDICT_META = {
    VERDICTS.NECESSITY: ("#FFD700", "🥇", "Elite projection, template-owned. Build around them."),
    VERDICTS.VALUE:     ("#00FF87", "🟢", "FPL priced them below their projected return. Load up."),
    VERDICTS.OVERPRICED: ("#FF4B4B", "🔴", "Big tag, pedigree, but the projection doesn't earn it."),
    VERDICTS.FAIR:      ("rgba(255,255,255,0.5)", "⚪", "Priced about right."),
    VERDICTS.SCOUT:     ("#04f5ff", "🔍", "No 25/26 history. Scout the depth chart before committing."),
}


# ── Scout layer: tailored questions per player ─────────────────────────────────

def _scout_questions(row: pd.Series) -> list:
    """1-2 human reads a projection can't make · depth chart, fitness, role."""
    qs = []
    sr    = row.get("starts_ratio")
    price = float(row.get("actual_price") or 0)
    share = float(row.get("mins_share") or 0)
    surp  = float(row.get("pricing_surprise") or 0)

    if pd.notna(sr) and sr < 0.8:
        starts = int(row.get("starts_total") or 0)
        games  = int(row.get("games_played") or 0)
        qs.append(f"Started {starts}/{games} in 25/26 · nailed now, or still rotated?")
    elif share < 0.6:
        qs.append("Projection sees patchy minutes · will he lock down a starting spot?")

    if surp <= -1.0:
        qs.append(f"FPL priced £{-surp:.1f}m over the model · reputation tax, or a bigger role?")
    if price >= 9.0:
        qs.append("Premium anchor · does he own the pens / set-pieces to justify it?")
    elif price <= 4.5:
        qs.append("Cheap starter? Confirm he starts GW1 before locking him in.")

    qs.append("Any new signing or backup who could eat his minutes?")
    return qs[:2]


def _verdict_card(row: pd.Series) -> str:
    verdict = str(row.get("verdict", VERDICTS.FAIR))
    accent, emoji, _ = VERDICT_META.get(verdict, VERDICT_META[VERDICTS.FAIR])
    pos   = str(row.get("position", ""))
    pc    = POS_COLORS.get(pos, "#888")
    name  = str(row.get("web_name", "?"))
    team  = str(row.get("team_name", "") or "")
    price = float(row.get("actual_price") or 0)
    pts   = float(row.get("projected_points") or 0)
    vscr  = float(row.get("value_score") or 0)
    own   = float(row.get("ownership") or 0)
    surp  = float(row.get("pricing_surprise") or 0)
    reason = str(row.get("verdict_reason", "") or "")
    onote = str(row.get("override_note", "") or "")
    status = str(row.get("status", "a") or "a")
    conf = str(row.get("confidence", "") or "")
    plo = float(row.get("proj_lo") or 0)
    phi = float(row.get("proj_hi") or 0)
    share = max(0.0, min(1.0, float(row.get("mins_share") or 0)))
    is_scout = verdict == VERDICTS.SCOUT

    flag_map = {"i": "injured", "d": "doubt", "s": "susp.", "u": "out", "n": "out"}
    flag = flag_map.get(status, "")
    flag_html = (f'<span style="background:rgba(255,75,75,0.15);color:#FF4B4B;'
                 f'border-radius:4px;padding:1px 6px;font-size:9px;font-weight:900;'
                 f'flex-shrink:0;">⚕ {flag}</span>' if flag else "")
    note_html = (f'<div style="font-size:10px;color:#04f5ff;margin-bottom:6px;">'
                 f'✎ {onote}</div>' if onote else "")
    conf_col = {"High": "#00FF87", "Medium": "#FFA500", "Low": "#FF6B6B"}.get(conf, MUTED)
    conf_html = (f'<span style="display:inline-flex;align-items:center;gap:4px;flex-shrink:0;" '
                 f'title="Projection confidence: {conf}">'
                 f'<span style="width:7px;height:7px;border-radius:50%;background:{conf_col};"></span>'
                 f'<span style="font-size:9px;font-weight:800;color:{conf_col};text-transform:uppercase;">{conf}</span>'
                 f'</span>' if conf else "")
    range_html = (f'<div style="font-size:10px;color:rgba(255,255,255,0.5);margin-bottom:8px;">'
                  f'Likely range {plo:.0f}–{phi:.0f} pts</div>' if (conf and not is_scout) else "")

    # Set-piece / penalty flag from the official FPL order.
    pens = row.get("pens_order")
    fk = row.get("fk_order")
    corn = row.get("corners_order")
    def _num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    pens, fk, corn = _num(pens), _num(fk), _num(corn)
    if pens == 1:
        sp_html = ('<span style="background:rgba(255,215,0,0.15);color:#FFD700;border-radius:4px;'
                   'padding:1px 6px;font-size:9px;font-weight:900;flex-shrink:0;">⚽ PENS</span>')
    elif (fk in (1, 2)) or (corn in (1, 2)) or (pens in (2, 3)):
        sp_html = ('<span style="background:rgba(4,245,255,0.12);color:#04f5ff;border-radius:4px;'
                   'padding:1px 6px;font-size:9px;font-weight:900;flex-shrink:0;">◎ SET-PC</span>')
    else:
        sp_html = ""
    cnote = str(row.get("confidence_note", "") or "")
    cnote_html = (f'<div style="font-size:10px;color:rgba(255,255,255,0.4);margin-bottom:6px;">◇ {cnote}</div>'
                  if cnote else "")

    surp_col = "#00FF87" if surp > 0 else "#FF4B4B" if surp < 0 else MUTED
    surp_txt = (f"+£{surp:.1f}m under model" if surp > 0
                else f"£{-surp:.1f}m over model" if surp < 0 else "at model price")

    # The face is the fastest way to recognise a player · a name in 11px is not.
    # Falls back to the club kit automatically for new signings with no photo.
    face = face_html(row.get("code"), int(row.get("team_code", 1) or 1),
                     is_gkp=(pos == "GKP"), width=46)

    q_html = "".join(
        f'<li style="margin-bottom:3px;line-height:1.3;">{q}</li>' for q in _scout_questions(row)
    )
    stat = lambda v, l, c="#fff": (
        f'<div style="text-align:center;"><div style="font-size:15px;font-weight:900;color:{c};">{v}</div>'
        f'<div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,0.4);">{l}</div></div>'
    )
    # Scout cards have no projection · show price + ownership only.
    if is_scout:
        mid = f'{stat(f"£{price:.1f}", "Price")}{stat(f"{own:.1f}%", "Owned", "#04f5ff")}'
        bar = ""
    else:
        mid = (f'{stat(f"£{price:.1f}", "Price")}{stat(f"{pts:.0f}", "Proj pts", "#00FF87")}'
               f'{stat(f"{vscr:.1f}", "Pts/£m", "#FFD700")}{stat(f"{own:.1f}%", "Owned", "#04f5ff")}')
        bar = (f'<div style="height:5px;border-radius:3px;background:rgba(255,255,255,0.08);'
               f'overflow:hidden;margin-bottom:8px;"><div style="height:100%;width:{share*100:.0f}%;'
               f'background:{accent};"></div></div>'
               f'<div style="font-size:10px;color:{surp_col};font-weight:700;margin-bottom:8px;">{surp_txt}</div>')

    _html = f"""
<div class="fplh-card-hover" style="background:rgba(22,26,34,0.85);
     border:1px solid rgba(255,255,255,0.08);border-top:3px solid {accent};
     border-radius:12px;padding:14px 16px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:11px;margin-bottom:10px;">
    {face}
    <div style="min-width:0;flex:1;">
      <div style="font-size:15px;font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</div>
      <div style="display:flex;align-items:center;gap:6px;margin-top:2px;">
        {team_dot(row.get("team_short"), size=9)}
        <span style="font-size:11px;color:rgba(255,255,255,0.45);">{team}</span>
      </div>
    </div>
    {flag_html}
    <span style="background:{pc};color:#000;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:900;flex-shrink:0;">{pos}</span>
  </div>
  <div style="display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-bottom:6px;">{sp_html}{conf_html}</div>
  <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:8px;">{mid}</div>
  {range_html}
  {bar}
  {cnote_html}
  {note_html}
  <div style="font-size:11px;color:rgba(255,255,255,0.7);margin-bottom:8px;line-height:1.35;">{reason}</div>
  <ul style="margin:0;padding-left:16px;font-size:11px;color:rgba(255,255,255,0.55);">{q_html}</ul>
</div>
"""
    # Collapse to a single line · empty interpolations on their own line create
    # whitespace-only lines that make Streamlit's markdown stop passing raw HTML
    # through and escape the rest of the card.
    return "".join(seg.strip() for seg in _html.splitlines())


def _lane(df: pd.DataFrame, accent: str) -> None:
    if df.empty:
        st.info("No players in this bucket right now.")
        return
    cards = "".join(_verdict_card(r) for _, r in df.iterrows())
    st.markdown(
        f'<div class="fplh-stagger" style="display:grid;'
        f'grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">{cards}</div>',
        unsafe_allow_html=True,
    )




from ui.value_board import build_board
board, scout, price_bt, validation = build_board()
if board is None:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
    <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">
      📋 {NEXT_SEASON} Value Board</div>
    <span style="background:rgba(0,255,135,0.12);border:1px solid rgba(0,255,135,0.4);
      color:#00FF87;font-size:10px;font-weight:800;letter-spacing:0.12em;padding:4px 10px;
      border-radius:20px;text-transform:uppercase;">● Live · actual prices in</span>
  </div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    Real launch prices vs projected points · who came in under price, who's a necessity, who's too dear
  </div>
</div>""",
    unsafe_allow_html=True,
)

# verdict counts + model tiles
counts = board["verdict"].value_counts().to_dict()
worst_pair = min(validation.values(), key=lambda v: v["spearman"])
best_pair = max(validation.values(), key=lambda v: v["spearman"])
tiles = [
    ("Necessity", str(counts.get(VERDICTS.NECESSITY, 0)), "template must-haves", "#FFD700"),
    ("Value", str(counts.get(VERDICTS.VALUE, 0)), "priced under projection", "#00FF87"),
    ("Overpriced", str(counts.get(VERDICTS.OVERPRICED, 0)), "pay up, get less", "#FF4B4B"),
    ("Scout", str(len(scout)), "new · no 25/26 history", "#04f5ff"),
    ("Points signal", f"ρ {best_pair['spearman']:.2f}",
     f"{worst_pair['spearman']:.2f} in a rule-change year", "#04f5ff"),
]
st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;">'
    + "".join(
        (f'<div style="{CARD}flex:1;min-width:128px;">'
         f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};text-transform:uppercase;">{lab}</div>'
         f'<div style="font-size:24px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
         f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>')
        for lab, val, sub, acc in tiles)
    + "</div>",
    unsafe_allow_html=True,
)

# ── Three drafts · pick the strategy ───────────────────────────────────────────
from ui.value_board import DRAFT_STRATEGIES, solve_draft

BLURBS = {
    "⚖️ Optimal value": "The model's best 15 on projected points per pound · no premium forced.",
    "🛡️ Safe · Haaland + Fernandes": "Both template premiums locked in · rank insurance, value built around them.",
    "🎲 Punt · Fernandes, no Haaland": "Skip the £15.5m Haaland tax, reinvest across the squad · higher upside, more variance.",
    "🔋 Bench Boost GW1": "All 15 count equally, so the bench actually plays · set up to Bench Boost GW1 with no transfer prep.",
    "🚀 Bench Boost GW2 → Wildcard GW4": "The aggressive route. All 15 play, and the squad is built on **GW1-3 fixtures only** · the Wildcard at GW4 replaces it, so nothing after GW3 counts.",
}

mode = st.radio("Draft strategy", DRAFT_STRATEGIES, horizontal=True, label_visibility="collapsed")
st.caption(BLURBS[mode])

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    budget = st.slider("Budget (£m)", 95.0, 105.0, 100.0, 0.5)
with c2:
    risk = st.slider("Risk · Upside ↔ Safety", 0.0, 1.0, 0.3, 0.05,
                     help="0 maximises the mean projection (chase upside). 1 maximises the "
                          "confidence floor (safety-first) · low-confidence punts and fullbacks "
                          "get discounted as you slide right.")
with c3:
    opening = st.slider("Opening fixtures GW1-6", 0.0, 1.0, 0.35, 0.05,
                        help="Slide right to favour players with soft opening fixtures. "
                             "Playbook Q15 measured this signal as WEAK (r = -0.38 and "
                             "weakening), while team quality persists at r = +0.53 · "
                             "treat it as a tie-breaker between similar players, not a "
                             "reason to pick one.")
st.caption("Opening fixtures are a tie-breaker, not a strategy · see Playbook Q15.")
_two_att = st.checkbox(
    "Allow 2 attackers from the same club",
    value=False,
    help="The standing rule is one attack-correlated player per club, so a bad week "
         "for that club does not sink two of your picks. Tick this to allow pairs "
         "like Szoboszlai and Isak when the projections justify the correlation.")

_lock_col, _veto_col = st.columns(2)
with _lock_col:
    locked = st.multiselect(
        "🔒 Lock in · players I definitely want",
        options=sorted(board["web_name"].tolist()),
        help="These go into the fifteen no matter what · the optimiser builds the "
             "best squad it can around them. A lock beats a veto.")
with _veto_col:
    excluded = st.multiselect(
        "🚫 Don't trust · exclude these players",
        options=sorted(board["web_name"].tolist()),
        help="Veto anyone you're not convinced by · the optimiser rebuilds around them.")

from ui.value_board import SPRINT_STRATEGY, SPRINT_WINDOW


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _window_map(lo: int, hi: int) -> tuple:
    """Fixture-ease per club over a GW window, as a cache-safe tuple."""
    from analytics.season_opener import opening_ease
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    fx = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())
    oe = opening_ease(fx, lo, hi)
    return tuple(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))


# The sprint route is scored on GW1-3 alone, at full weight · a Wildcard in GW4
# throws this squad away, so fixtures after GW3 are irrelevant to it.
_omap, _oweight = (), opening
if mode == SPRINT_STRATEGY:
    _omap, _oweight = _window_map(*SPRINT_WINDOW), 1.0
    st.caption(f"Built on **GW{SPRINT_WINDOW[0]}-{SPRINT_WINDOW[1]} fixtures only**, "
               f"at full weight. Every one of the fifteen has to start, because the "
               f"Bench Boost in GW2 counts all of them.")

res = solve_draft(board, mode, budget, risk, tuple(excluded), _oweight,
                  force_names=tuple(locked), opening_map=_omap,
                  max_attackers_per_club=2 if _two_att else 1)

if locked and res is not None:
    # What the conviction actually costs · the same solve without the locks. This
    # is the honest price of a hunch, and it is usually far smaller than it feels.
    _free = solve_draft(board, mode, budget, risk, tuple(excluded), _oweight,
                        opening_map=_omap,
                        max_attackers_per_club=2 if _two_att else 1)
    _lk = board[board["web_name"].isin(locked)]
    _spend = float(_lk["actual_price"].sum())
    _cost = (res["xi_points"] - _free["xi_points"]) if _free else None
    _msg = (f"🔒 {len(locked)} locked · £{_spend:.1f}m committed, "
            f"£{budget - _spend:.1f}m left for the other {15 - len(locked)}.")
    if _cost is not None:
        _msg += (f" Costs **{_cost:+.0f}** projected XI pts against the free optimum"
                 + (" · essentially free, back the hunch." if _cost > -12 else
                    " · a real price, make sure you mean it."))
    st.caption(_msg)
if res is None:
    # Name the likely culprit rather than making the user bisect their own locks.
    _why = ""
    if locked:
        _lk = board[board["web_name"].isin(locked)]
        _spend = float(_lk["actual_price"].sum())
        _by_pos = _lk["position"].value_counts().to_dict()
        _over = {p: n for p, n in _by_pos.items()
                 if n > {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}.get(p, 15)}
        if _over:
            _why = (" You locked more players in a position than a squad allows: "
                    + ", ".join(f"{n}× {p}" for p, n in _over.items()) + ".")
        elif _spend > budget - (15 - len(locked)) * 4.0:
            _why = (f" Your locks cost £{_spend:.1f}m, leaving under £4.0m a head for "
                    f"the remaining {15 - len(locked)} · that cannot be filled.")
        else:
            _why = (" It is likely a club limit: at most 3 per club, and this draft "
                    "allows only 1 attacker and 1 defender per club.")
    st.error("Solver found no feasible squad." + _why
             + " Widen the budget, lower risk, or drop a lock.")
    st.stop()

squad = res["squad"]

_sec = lambda t: st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:26px 0 10px;">'
    f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;'
    f'color:{MUTED};white-space:nowrap;">{t}</div>'
    f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>',
    unsafe_allow_html=True)

_bb = " · bench counts (BB-ready)" if "Bench Boost" in mode else ""
_xi = squad[squad["in_xi"]]
_xi_mean = float(_xi["pts"].sum())
_xi_floor = float(_xi["proj_lo"].sum()) if "proj_lo" in _xi.columns else _xi_mean
_open_txt = ""
if opening > 0 and "opening_factor" in squad.columns:
    _oe = float(squad["opening_factor"].mean())
    _lbl = "kind" if _oe >= 1.03 else "tough" if _oe <= 0.97 else "average"
    _open_txt = f" · opening 6 fixtures {_lbl}"
_sec(f"{mode.split(' ', 1)[1] if ' ' in mode else mode} · £{res['squad_cost']:.1f}m real spend · "
     f"XI {_xi_mean:.0f} pts mean / {_xi_floor:.0f} floor{_bb}{_open_txt}")

# ── Live readout · what this squad is, and what your tinkering did to it ───────
# The point of a control panel is seeing the effect. Every number here moves the
# moment a slider does, so a change is legible instead of guessed at.
_bank = float(budget) - float(res["squad_cost"])
_prem = int((squad["price"] >= 9.0).sum())
_lowc = int((squad["confidence"] == "Low").sum()) if "confidence" in squad.columns else 0
_summary = [
    ("Spend", f"£{res['squad_cost']:.1f}m", f"£{_bank:.1f}m in the bank", "#00FF87"),
    ("XI mean", f"{_xi_mean:.0f}", "projected points", "#FFD700"),
    ("XI floor", f"{_xi_floor:.0f}", "if the range breaks against you", "#04f5ff"),
    ("Premiums", str(_prem), "at £9.0m or more", "#e90052"),
    ("Low conf.", str(_lowc), "of 15 · small sample or override",
     "#FF4B4B" if _lowc >= 6 else MUTED),
]
st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 12px;">'
    + "".join(
        f'<div style="{CARD}flex:1;min-width:118px;">'
        f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};'
        f'text-transform:uppercase;">{lab}</div>'
        f'<div style="font-size:22px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>'
        for lab, val, sub, acc in _summary)
    + "</div>", unsafe_allow_html=True)

# ── Shared player evidence · used by both the shirt popup and the inspector ────
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _last_season_stats():
    from data.processors.archive import load_season_summary
    s = load_season_summary()
    s = s[s["season"] == LAST_COMPLETE_SEASON]
    keep = ["goals", "assists", "xg", "xa", "xgi", "defcon_points", "minutes",
            "total_points", "ppg", "clean_sheets", "bonus", "cbit_total",
            "starts_total", "games_played"]
    return s.set_index("code")[[c for c in keep if c in s.columns]]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _defcon_per90():
    """Defensive contributions per 90 last season, plus how often the threshold hit.

    The mean alone flatters a player who spikes once · the DEFCON points are a
    THRESHOLD (10 CBIT for a defender, 12 for a midfielder), so the hit rate is
    what actually converts to points week to week.
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
                              starts=("starts", "sum"),
                              mins=("minutes", "sum"))
    g["dc_per90"] = (g["dc_per_start"] * 90.0
                     / (g["mins"] / g["starts"]).clip(lower=1)).round(2)
    return g.round(2)




def _set_piece_line(row) -> str:
    """Penalties and set pieces from the OFFICIAL FPL order · fact, not a guess."""
    p_ord = _num_safe(row.get("pens_order"))
    f_ord = _num_safe(row.get("fk_order"))
    c_ord = _num_safe(row.get("corners_order"))
    bits = []
    if p_ord == 1:
        bits.append('<span style="background:#FFD700;color:#000;border-radius:4px;'
                    'padding:1px 7px;font-size:10px;font-weight:900;">⚽ ON PENALTIES</span>')
    elif p_ord in (2, 3):
        bits.append(f'<span style="color:#FFD700;font-size:11px;font-weight:800;">'
                    f'Penalties #{p_ord} in the queue</span>')
    if f_ord in (1, 2):
        bits.append(f'<span style="color:#04f5ff;font-size:11px;font-weight:800;">'
                    f'Free kicks #{f_ord}</span>')
    if c_ord in (1, 2):
        bits.append(f'<span style="color:#04f5ff;font-size:11px;font-weight:800;">'
                    f'Corners #{c_ord}</span>')
    if not bits:
        return ('<div style="font-size:11px;color:rgba(255,255,255,0.35);margin:6px 0;">'
                'Not on penalties or first-choice set pieces.</div>')
    return ('<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;'
            'margin:6px 0;">' + "".join(bits) + '</div>')


# ── The squad · click a shirt for the player's numbers ────────────────────────
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _club_fixtures():
    """(team_id, gw) -> list of (opponent short, is_home, fdr) for 26/27."""
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    bs = fetch_bootstrap()
    short = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    fx = get_fixtures_df(fetch_fixtures(), bs)
    out = {}
    for _, r in fx.iterrows():
        if pd.isna(r.get("gameweek")):
            continue
        gw = int(r["gameweek"])
        h, a = int(r["home_team_id"]), int(r["away_team_id"])
        out.setdefault((h, gw), []).append((short.get(a, "?"), True, float(r["home_fdr"])))
        out.setdefault((a, gw), []).append((short.get(h, "?"), False, float(r["away_fdr"])))
    return out


_FIX = _club_fixtures()
_TICKER_GWS = 12          # how far the popup's fixture strip runs


def _gw_points(season_pts: float, team_id: int, gw: int) -> float:
    """This gameweek's projection · the season total spread over 38 and scaled by
    fixture ease. Identical model to the Chip Planner, so the two cannot drift.
    A blank scores nothing; a double stacks both fixtures."""
    from config import CHIP_TIMING as _CT
    base = float(season_pts) / 38.0
    return sum(base * max(_CT["factor_floor"],
                          1.0 + (3.0 - f) * _CT["fdr_slope"])
               for _, _, f in _FIX.get((int(team_id), int(gw)), []))


_vc, _gc = st.columns([2, 3])
with _vc:
    _view = st.radio("Show on each shirt", ["Projected points", "Fixture"],
                     horizontal=True, key="pitch_view_mode")
with _gc:
    _gw = st.slider("Gameweek", 1, 19, 1, 1, key="pitch_gw",
                    help="Step through the opening gameweeks to see each club's "
                         "fixture and this week's projection.")

# ── Bench the four worst for THIS gameweek ────────────────────────────────────
# The MILP picks an XI to maximise the SEASON, but in any single week the worst
# four differ: a blank or a hard away trip should drop a player who is otherwise
# a starter. Re-pick the XI on this gameweek's projection, respecting formation
# (exactly 1 GKP, at least 3 DEF, 2 MID, 1 FWD).
def _xi_for_gw(sq: pd.DataFrame, gw: int) -> set:
    scored = {}
    for _, r in sq.iterrows():
        scored[int(r["code"])] = _gw_points(r["pts"], int(r.get("team_id", 0) or 0), gw)
    by_pos = {}
    for _, r in sq.iterrows():
        by_pos.setdefault(r["position"], []).append(int(r["code"]))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda c: -scored.get(c, 0.0))

    xi = set()
    xi.update(by_pos.get("GKP", [])[:1])                 # exactly one keeper
    for pos, lo in (("DEF", 3), ("MID", 2), ("FWD", 1)):  # positional minimums
        xi.update(by_pos.get(pos, [])[:lo])
    # fill the remaining outfield slots with the best of who is left
    rest = [c for c in scored
            if c not in xi and sq.set_index("code").loc[c, "position"] != "GKP"]
    rest.sort(key=lambda c: -scored.get(c, 0.0))
    for c in rest[:11 - len(xi)]:
        xi.add(c)
    return xi


_gw_xi = _xi_for_gw(squad, _gw)

_players = []
for _, r in squad.iterrows():
    _tid = int(r.get("team_id", 0) or 0)
    _fx = _FIX.get((_tid, _gw), [])
    if _fx:
        _lbl = " + ".join(f"{o}({'H' if h else 'A'})" for o, h, _f in _fx)
    else:
        _lbl = "BLANK"
    _players.append({
        "web_name": r["web_name"],
        "position": r["position"],
        "team_code": int(r.get("team_code", 1) or 1),
        "team_short": r.get("team_short"),
        "on_bench": int(r["code"]) not in _gw_xi,
        "is_captain": bool(r["is_captain"]),
        "price": float(r["price"]),
        "fixture_label": _lbl,
        "fpl_id": int(r["code"]),          # click id · the stable player code
        "stat": (round(_gw_points(r["pts"], _tid, _gw), 1)
                 if _view == "Projected points" else None),
    })

_click = render_squad_pitch(
    _players, stat_label=f"GW{_gw}", title_right=f"{NEXT_SEASON} · GW{_gw}",
    interactive=True, key="draft_pitch")

# ── Free transfers at this gameweek ───────────────────────────────────────────
# GW1 is the draft itself, so it costs nothing. From GW2 you get one a week,
# banking what you do not spend, capped at 5 (the 2025-26 rule, still current).
from analytics.squad_planner import FT_CAP
_ft = 0 if _gw <= 1 else min(FT_CAP, _gw - 1)
_ft_txt = ("This is the draft itself · no transfers needed."
           if _gw <= 1 else
           f"**{_ft}** free transfer{'s' if _ft != 1 else ''} banked by GW{_gw} "
           f"(1 a week from GW2, capped at {FT_CAP}). A Wildcard makes them "
           f"unlimited and free.")
st.caption(_ft_txt)

st.caption(f"👆 Tap any shirt for that player's numbers. Showing **GW{_gw}** fixtures"
           + (" and this week's projection." if _view == "Projected points" else "."))


@st.dialog("Player", width="large")
def _player_dialog(code: int) -> None:
    """Face, headline numbers, DEFCON, set pieces and the opening run · one popup.

    Built from data already in memory, so it opens instantly rather than
    refitting anything.
    """
    m = board[board["code"] == code]
    if m.empty:
        st.info("Player not on the board.")
        return
    r = m.iloc[0]
    pos = str(r.get("position", ""))
    dc = _defcon_per90()
    d = dc.loc[code] if (not dc.empty and code in dc.index) else None
    ls = _last_season_stats()
    lsr = ls.loc[code] if code in ls.index else None

    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(face_html(code, int(r.get("team_code", 1) or 1),
                              pos == "GKP", 96), unsafe_allow_html=True)
    with c2:
        st.markdown(
            " ".join(x.strip() for x in (
                f'<div style="font-size:26px;font-weight:900;color:#fff;'
                f'letter-spacing:-0.5px;">{r["web_name"]}</div>'
                f'<div style="font-size:13px;color:{MUTED};margin-top:2px;">'
                f'{r.get("team_name","")} · {pos} · £{float(r.get("actual_price") or 0):.1f}m'
                f'</div>').splitlines()),
            unsafe_allow_html=True)
        st.markdown(_set_piece_line(r), unsafe_allow_html=True)

    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric("Projected 26/27", f"{float(r.get('projected_points') or 0):.0f}",
               help="Season projection. Range: "
                    f"{float(r.get('proj_lo') or 0):.0f}-{float(r.get('proj_hi') or 0):.0f}")
    _m2.metric("Projected minutes", f"{float(r.get('projected_minutes') or 0):,.0f}")
    _m3.metric("DEFCON / 90", f"{float(d['dc_per90']):.1f}" if d is not None else "n/a",
               help="Defensive actions per 90 last season.")
    _m4.metric("DEFCON hit rate",
               f"{float(d['dc_hit_rate'])*100:.0f}%" if d is not None else "n/a",
               help="Share of starts clearing the threshold (10 for a defender, 12 "
                    "for a midfielder). This is what converts to points.")

    if lsr is not None:
        _l1, _l2, _l3, _l4 = st.columns(4)
        _l1.metric("Goals 25/26", f"{float(lsr.get('goals') or 0):.0f}")
        _l2.metric("Assists 25/26", f"{float(lsr.get('assists') or 0):.0f}")
        _l3.metric("Minutes 25/26", f"{float(lsr.get('minutes') or 0):,.0f}")
        _l4.metric("Points 25/26", f"{float(lsr.get('total_points') or 0):.0f}")
    else:
        st.caption("No 2025/26 Premier League record · this projection comes from an "
                   "external model or a manual override.")

    _note = str(r.get("override_note", "") or "")
    if _note:
        st.info(f"✎ {_note}")

    # ✕ Replace him · who you could actually afford instead, best first.
    _in_squad = int(code) in set(squad["code"].astype(int))
    if _in_squad:
        _bank = float(budget) - float(res["squad_cost"])
        _ceiling = float(r.get("actual_price") or 0) + _bank
        _clubs = squad[squad["code"] != code]["team_id"].value_counts().to_dict()
        _alt = board[(board["position"] == pos)
                     & (board["actual_price"] <= _ceiling)
                     & (~board["code"].isin(squad["code"]))].copy()
        # a swap that breaks the 3-per-club limit is not actually available
        _alt = _alt[_alt["team_id"].map(lambda t: _clubs.get(t, 0)) < 3]
        _alt = _alt.nlargest(5, "projected_points")
        st.markdown(
            " ".join(x.strip() for x in (
                f'<div style="font-size:10px;font-weight:800;letter-spacing:0.18em;'
                f'color:{MUTED};text-transform:uppercase;margin:16px 0 6px;">'
                f'Replace him · top 5 you can afford</div>').splitlines()),
            unsafe_allow_html=True)
        if _alt.empty:
            st.caption("Nothing affordable in this position without freeing money first.")
        else:
            _rows = []
            for _, a in _alt.iterrows():
                _atid = int(a.get("team_id", 0) or 0)
                _nf = _FIX.get((_atid, _gw), [])
                _nfl = " + ".join(f"{o}({'H' if h else 'A'})" for o, h, _f in _nf) or "BLANK"
                _rows.append({
                    "Face": player_photo_url(a["code"]),
                    "Player": a["web_name"],
                    "Team": a.get("team_short", ""),
                    "£m": round(float(a["actual_price"]), 1),
                    "Δ£m": round(float(a["actual_price"]) - float(r.get("actual_price") or 0), 1),
                    f"GW{_gw}": _nfl,
                    "Proj": round(float(a["projected_points"]), 0),
                    "Δ Proj": round(float(a["projected_points"])
                                    - float(r.get("projected_points") or 0), 0),
                    "Conf.": str(a.get("confidence", "")),
                })
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                         column_config={
                             "Face": st.column_config.ImageColumn("", width="small"),
                             "Δ£m": st.column_config.NumberColumn("Δ£m", format="%+.1f"),
                             "Δ Proj": st.column_config.NumberColumn("Δ Proj", format="%+.0f"),
                         })
            st.caption(f"Affordable means his price plus your £{_bank:.1f}m bank, and "
                       f"the swap must keep you inside 3 players per club. "
                       f"Fixture shown is GW{_gw}.")

    # Every upcoming fixture, colour-coded · the run is usually the reason you
    # are looking at a player at all, so it sits above the projection chart.
    from components.fixture_ticker import (load_scout_ticker, player_fixture_strip,
                                           run_summary)
    _tid = int(r.get("team_id", 0) or 0)
    # Scout's ratings vary by venue and opponent form; FPL's are fixed per club.
    # Use Scout where a snapshot exists, and say which is on screen.
    _sc = load_scout_ticker()
    _fix_src = _FIX
    _src_note = ("official FPL difficulty, which is set per club and does not "
                 "vary by home or away")
    if _sc:
        _ts = str(r.get("team_short") or "")
        _fix_src = {k: [(o, h, _sc.get((_ts, k[1]), f)) for o, h, f in v]
                    for k, v in _FIX.items() if k[0] == _tid}
        _src_note = ("Fantasy Football Scout's model ratings, which vary by venue "
                     "and opponent form")
    _sum6 = run_summary(_fix_src, _tid, 1, 6)
    _sum12 = run_summary(_fix_src, _tid, 1, 12)
    st.markdown(
        " ".join(x.strip() for x in (
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.18em;'
            f'color:{MUTED};text-transform:uppercase;margin:14px 0 6px;">'
            f'Fixtures · GW1 to GW{_TICKER_GWS}</div>').splitlines()),
        unsafe_allow_html=True)
    st.markdown(player_fixture_strip(_fix_src, _tid, 1, _TICKER_GWS),
                unsafe_allow_html=True)
    _fdr6 = _sum6.get("mean_fdr")
    _read = ("kind" if (_fdr6 or 3) <= 2.85 else
             "tough" if (_fdr6 or 3) >= 3.2 else "average")
    st.caption(
        f"Opening six average **{_fdr6 if _fdr6 is not None else 'n/a'}** difficulty "
        f"({_read}), {_sum6['home']} at home. First twelve average "
        f"**{_sum12.get('mean_fdr')}**. Green is easy, red is hard · {_src_note}.")

    # The opening run · this is the graph that actually drives a draft decision.
    _gws = list(range(1, 11))
    _pts = [round(_gw_points(r.get("projected_points") or 0, _tid, g), 1) for g in _gws]
    _labels = []
    for g in _gws:
        f = _FIX.get((_tid, g), [])
        _labels.append(" + ".join(o for o, _h, _f in f) if f else "blank")
    _opt = charts.bar_option(
        x=[f"GW{g}" for g in _gws], y=_pts,
        colors=["#00FF87" if v >= (sum(_pts) / max(len(_pts), 1)) else "rgba(4,245,255,0.5)"
                for v in _pts])
    _opt["title"] = {"text": "Projected points by gameweek · opening run",
                     "textStyle": {"color": "#eef1f5", "fontSize": 12, "fontWeight": "bold"}}
    _opt["grid"]["top"] = 40
    for _item, _lab in zip(_opt["series"][0]["data"], _labels):
        _item["tooltip"] = {"formatter": f"vs {_lab}"}
    charts.render(_opt, height="240px", key=f"dlg_run_{code}")
    st.caption("Season projection spread over 38 gameweeks and scaled by fixture "
               "difficulty · the same model the Chip Planner uses. It is a fixture "
               "shape, not a match forecast.")


# The component replays its LAST value on every rerun, so without deduping on the
# nonce the popup reopens whenever any other control moves (the gameweek slider,
# a radio, the budget). Dedupe, exactly as the My Team pitch does.
if _click and isinstance(_click, dict) and _click.get("action") == "detail":
    if _click.get("nonce") != st.session_state.get("_draft_pitch_nonce"):
        st.session_state["_draft_pitch_nonce"] = _click.get("nonce")
        _player_dialog(int(_click["id"]))

if opening > 0:
    st.caption("Opening-fixtures weight is a tie-breaker · it favours soft GW1-6 runs among "
               "similar players so the squad lasts longer, without overriding your best picks.")

# ── Wildcard planner · what a reset at GW N actually buys ────────────────────
_sec("🃏 Wildcard planner · what a reset would look like")
st.caption("A Wildcard is unlimited free transfers, so the squad is rebuilt from "
           "scratch on the fixtures that FOLLOW it. This shows who leaves, who "
           "arrives, and what the reset is worth over the next six gameweeks.")

_w1, _w2 = st.columns([2, 3])
with _w1:
    _wc_gw = st.slider("Play the Wildcard at GW", 2, 19, 4, 1, key="wc_gw")
with _w2:
    _wc_on = st.checkbox("Show me the Wildcard squad", value=False, key="wc_on")

if _wc_on:
    _wc_hi = min(38, _wc_gw + 5)
    _wc_squad = solve_draft(
        board, "⚖️ Optimal value", budget, risk, tuple(excluded), 1.0,
        force_names=tuple(locked), opening_map=_window_map(_wc_gw, _wc_hi),
        max_attackers_per_club=2 if _two_att else 1)

    if _wc_squad is None:
        st.error("No feasible Wildcard squad · widen the budget or drop a lock.")
    else:
        _new = _wc_squad["squad"]
        _now_codes = set(squad["code"].astype(int))
        _new_codes = set(_new["code"].astype(int))
        _out = squad[~squad["code"].astype(int).isin(_new_codes)]
        _in = _new[~_new["code"].astype(int).isin(_now_codes)]

        # Value the reset over the SAME window for both squads · that is the only
        # fair comparison, and it is what the wildcard is actually worth.
        def _window_pts(sq):
            return sum(_gw_points(r["pts"], int(r.get("team_id", 0) or 0), g)
                       for _, r in sq.iterrows() if r["in_xi"]
                       for g in range(_wc_gw, _wc_hi + 1))

        _gain = _window_pts(_new) - _window_pts(squad)
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("Changes", f"{len(_in)}", help="Players in. A Wildcard makes them free.")
        _c2.metric(f"GW{_wc_gw}-{_wc_hi} gain", f"{_gain:+.0f}",
                   help="Extra projected XI points over the six weeks after the reset.")
        _c3.metric("Spend", f"£{_wc_squad['squad_cost']:.1f}m")

        if _gain < 6:
            st.info(f"A reset here gains only **{_gain:+.0f}** points over six weeks. "
                    f"That is inside the noise of the projection · the Wildcard is "
                    f"probably better saved, unless you need it to repair injuries "
                    f"the model cannot see.")

        _oc, _ic = st.columns(2)
        with _oc:
            st.markdown(f'<div style="font-size:11px;font-weight:800;letter-spacing:0.18em;'
                        f'color:#FF4B4B;text-transform:uppercase;margin-bottom:6px;">'
                        f'Out ({len(_out)})</div>', unsafe_allow_html=True)
            if _out.empty:
                st.caption("Nobody · the squad already suits these fixtures.")
            else:
                st.dataframe(pd.DataFrame({
                    "Face": [player_photo_url(c) for c in _out["code"]],
                    "Player": _out["web_name"].values,
                    "Pos": _out["position"].values,
                    "£m": _out["price"].astype(float).round(1).values,
                    "Proj": _out["pts"].astype(float).round(0).values,
                }), hide_index=True, use_container_width=True,
                    column_config={"Face": st.column_config.ImageColumn("", width="small")})
        with _ic:
            st.markdown(f'<div style="font-size:11px;font-weight:800;letter-spacing:0.18em;'
                        f'color:#00FF87;text-transform:uppercase;margin-bottom:6px;">'
                        f'In ({len(_in)})</div>', unsafe_allow_html=True)
            if _in.empty:
                st.caption("Nobody.")
            else:
                st.dataframe(pd.DataFrame({
                    "Face": [player_photo_url(c) for c in _in["code"]],
                    "Player": _in["web_name"].values,
                    "Pos": _in["position"].values,
                    "£m": _in["price"].astype(float).round(1).values,
                    "Proj": _in["pts"].astype(float).round(0).values,
                }), hide_index=True, use_container_width=True,
                    column_config={"Face": st.column_config.ImageColumn("", width="small")})

        st.caption(f"Built on GW{_wc_gw}-{_wc_hi} fixtures at full weight. Locks and "
                   f"vetoes still apply, so you can force a player through the reset.")

# ── Verdict lanes ──────────────────────────────────────────────────────────────
_sec("🎯 The verdict · who to want, who to swerve")
st.markdown(
    f'<div style="font-size:13px;color:{MUTED};margin:-2px 0 12px;">'
    f'Each card carries a confidence dot · how much to trust its number. '
    f'Green = big minutes sample, red = small sample or a manual assumption.</div>',
    unsafe_allow_html=True,
)
with st.expander("ℹ️ What is 'projected', and how much should I trust it?"):
    st.markdown(
        "**Projected points** = a player's per-90 scoring rate × his projected minutes, "
        "both regressed from last season and 9 historical season-pairs. It is a *map, not a promise*: "
        "predicting a season from the year before validates at **Spearman ≈ 0.4** with a "
        "**±38-point average error**, so treat every number as the middle of a wide range.\n\n"
        "**Confidence dot** on each card:\n"
        "- 🟢 **High** · 2500+ minutes last season, no assumptions (Haaland, Fernandes)\n"
        "- 🟠 **Medium** · a partial season (1500–2500 min)\n"
        "- 🔴 **Low** · a small sample **or** a manual override\n\n"
        "**Manual overrides** (the ✎ notes) are calls the model can't make · fitness, a new role, "
        "regression · and they live in `assets/player_overrides_2026_27.json`, editable by hand. "
        "**Isak is the honest example**: his 5.24 per-90 came from just **694 minutes** last year, and "
        "his minutes are *assumed*, so he's flagged Low with a wide range. The number is a scenario, "
        "not a forecast · trust the dot, not the decimal.")

n_nec = board[board["verdict"] == VERDICTS.NECESSITY].sort_values("projected_points", ascending=False)
n_val = board[board["verdict"] == VERDICTS.VALUE].sort_values("value_score", ascending=False).head(18)
n_over = board[board["verdict"] == VERDICTS.OVERPRICED].sort_values("actual_price", ascending=False)
n_scout = scout.head(18)

t_nec, t_val, t_over, t_scout = st.tabs([
    f"🥇 Necessity ({len(n_nec)})",
    f"🟢 Value ({len(board[board['verdict'] == VERDICTS.VALUE])})",
    f"🔴 Overpriced ({len(n_over)})",
    f"🔍 Scout · new ({len(scout)})",
])
with t_nec:
    st.caption(VERDICT_META[VERDICTS.NECESSITY][2])
    _lane(n_nec.head(18), "#FFD700")
with t_val:
    st.caption(VERDICT_META[VERDICTS.VALUE][2])
    _lane(n_val, "#00FF87")
with t_over:
    st.caption(VERDICT_META[VERDICTS.OVERPRICED][2])
    _lane(n_over, "#FF4B4B")
with t_scout:
    st.caption(VERDICT_META[VERDICTS.SCOUT][2])
    _lane(n_scout, "#04f5ff")

# ── Minutes → points thesis, coloured by verdict ───────────────────────────────
_sec("Minutes drive points · the whole thesis in one view")
# Faces only for the very top · the high-minutes, high-points corner is crowded by
# definition, so 28 faces there became a pile-up that hid the trend it was meant to
# show. Ten anchors the premium cluster without burying it.
_faceable = set(board.nlargest(10, "projected_points")["code"])
_groups = []
for verdict, acc, _e, _m in [(k,) + v for k, v in VERDICT_META.items() if k != VERDICTS.SCOUT]:
    d = board[board["verdict"] == verdict]
    if d.empty:
        continue
    pts = []
    for _, r in d.iterrows():
        p = {"x": int(r["projected_minutes"]), "y": round(float(r["projected_points"]), 1),
             "name": str(r["web_name"]), "size": 7,
             "tip": (f"{r['web_name']} · {r['team_name']}<br/>£{r['actual_price']:.1f}m · "
                     f"{int(r['projected_minutes']):,} mins → {r['projected_points']:.0f} pts")}
        if r["code"] in _faceable:
            p["image"] = player_photo_url(r["code"])
            p["size"] = 26
        pts.append(p)
    _groups.append((verdict, acc, pts))
charts.render(
    charts.multi_scatter_option(_groups, x_name="Projected minutes 26/27", y_name="Projected points"),
    height="380px", key="board_min_pts",
)
st.caption("The top 10 by projection carry their face. Everything trends up and to the "
           "right because **minutes are the master variable** · a player who does not "
           "start cannot score, whatever his per-90 says.")

# ── Inspect any player ────────────────────────────────────────────────────────
# One player view, not two. The shirt popup already shows everything, so this is
# just a way to reach it for someone who is NOT in the current squad.
_sec("🔍 Inspect any player")
_pick = st.selectbox(
    "Search any player in the game", options=sorted(board["web_name"].tolist()),
    key="draft_inspect",
    help="Squad players open the same card by tapping their shirt on the pitch.")
if st.button(f"📊 Open {_pick}'s card", use_container_width=False):
    _row = board[board["web_name"] == _pick]
    if not _row.empty:
        _player_dialog(int(_row.iloc[0]["code"]))

# ── Second opinion · Scout's snapshot joined to the board ─────────────────────
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _scout_rows():
    """(matched Scout rows, our scale vs theirs). None when no snapshot is saved."""
    from analytics.scout_projections import load_snapshot, match_to_board, model_scale
    snap = load_snapshot()
    if snap is None:
        return None, 1.0
    res = match_to_board(snap, board)
    return res["matched"], model_scale(res["matched"])


_scout_df, _scale = _scout_rows()

# ── Full table ─────────────────────────────────────────────────────────────────
_sec("Every price · every verdict")
tab_all, tab_surprise, tab_scout = st.tabs(
    ["All players", "Biggest bargains & taxes", "Second opinion · Scout"])

_CONF_DOT = {"High": "🟢", "Medium": "🟠", "Low": "🔴"}
_VERDICT_DOT = {VERDICTS.NECESSITY: "🥇", VERDICTS.VALUE: "🟢",
                VERDICTS.OVERPRICED: "🔴", VERDICTS.FAIR: "⚪", VERDICTS.SCOUT: "🔍"}


def _readable(df: pd.DataFrame) -> pd.DataFrame:
    """Board rows as a scannable table · face, then identity, then numbers.

    Bars beat bare decimals for ranking at a glance, and a dot beats a word for
    verdict and confidence, so the eye lands on the number that matters.
    """
    t = pd.DataFrame({
        "Face": [player_photo_url(c) for c in df["code"]],
        "Player": df["web_name"].values,
        "Pos": df["position"].values,
        "Team": df["team_name"].values,
        "Verdict": [f"{_VERDICT_DOT.get(v, '⚪')} {v}" for v in df["verdict"]],
        "Conf.": [f"{_CONF_DOT.get(c, '·')} {c}" for c in df["confidence"].fillna("")],
        "£m": df["actual_price"].astype(float).round(1).values,
        "vs model": df["pricing_surprise"].astype(float).round(1).values,
        "Proj pts": df["projected_points"].astype(float).round(0).values,
        "Range": [f"{lo:.0f}–{hi:.0f}" for lo, hi in
                  zip(df["proj_lo"].fillna(0), df["proj_hi"].fillna(0))],
        "Pts/£m": df["value_score"].astype(float).round(1).values,
        "Owned %": df["ownership"].astype(float).round(1).values,
        "25/26": df["last_season_points"].astype(float).round(0).values,
    })
    return t


_COLCFG = {
    "Face": st.column_config.ImageColumn("", width="small", pinned=True),
    "Player": st.column_config.TextColumn("Player", width="medium", pinned=True),
    "£m": st.column_config.NumberColumn("£m", format="%.1f", width="small"),
    "vs model": st.column_config.NumberColumn(
        "vs model", format="%+.1f", width="small",
        help="Positive = FPL priced them BELOW our model (a bargain). Negative = a tax."),
    "Proj pts": st.column_config.ProgressColumn(
        "Proj pts", format="%.0f", min_value=0.0, max_value=260.0, width="medium"),
    "Pts/£m": st.column_config.ProgressColumn(
        "Pts/£m", format="%.1f", min_value=0.0, max_value=32.0, width="small"),
    "Owned %": st.column_config.NumberColumn("Owned %", format="%.1f%%", width="small"),
    "25/26": st.column_config.NumberColumn("25/26 pts", format="%.0f", width="small"),
}

table = _readable(board)

with tab_all:
    _pos_f = st.multiselect("Filter by position", ["GKP", "DEF", "MID", "FWD"],
                            default=[], key="tbl_pos", label_visibility="collapsed",
                            placeholder="Filter by position · all shown")
    _t = table[table["Pos"].isin(_pos_f)] if _pos_f else table
    st.dataframe(_t.sort_values("Proj pts", ascending=False),
                 use_container_width=True, height=460, hide_index=True,
                 column_config=_COLCFG)
with tab_surprise:
    st.caption("Positive **vs model** = FPL priced them below our projection, a bargain. "
               "Negative = a reputation tax. Sorted by the size of the gap either way.")
    st.dataframe(
        table.reindex(table["vs model"].abs().sort_values(ascending=False).index).head(40),
        use_container_width=True, height=460, hide_index=True, column_config=_COLCFG)

with tab_scout:
    if _scout_df is None:
        st.caption("No Scout snapshot loaded · save one to "
                   "`data/cache/scout_projections_2026_27.csv` to switch this on.")
    else:
        st.caption(
            f"Scout's projected component breakdown, ours alongside. Our model runs at "
            f"**{_scale:.2f}×** Scout's scale, so **Like-for-like** rescales Scout onto "
            f"our numbers · **Residual** is the genuine disagreement after that. "
            f"Sort by Residual to find where the two models actually differ, and by "
            f"Scout mins to find players ours cannot see.")
        _sd = _scout_df.copy()
        _sd["expected"] = (_sd["scout_pts"] * _scale).round(0)
        _sd["residual"] = (_sd["projected_points"] - _sd["expected"]).round(0)
        _st = pd.DataFrame({
            "Face": [player_photo_url(c) for c in _sd["code"]],
            "Player": _sd["web_name"].values,
            "Pos": _sd["pos"].values,
            "Team": _sd["team_short"].values,
            "£m": _sd["actual_price"].astype(float).round(1).values,
            "Scout mins": _sd["scout_mins"].astype(float).round(0).values,
            "Scout pts": _sd["scout_pts"].astype(float).round(0).values,
            "Like-for-like": _sd["expected"].astype(float).values,
            "Our pts": _sd["projected_points"].astype(float).round(0).values,
            "Residual": _sd["residual"].astype(float).values,
            "Goals": _sd["g"].astype(float).round(1).values,
            "Assists": _sd["a"].astype(float).round(1).values,
            "Clean sh.": _sd["cs"].astype(float).round(1).values,
            "DEFCON": _sd["dc"].astype(float).round(1).values,
            "Conf.": [f"{_CONF_DOT.get(c, '·')} {c}"
                      for c in _sd["confidence"].fillna("")],
        })
        st.dataframe(
            _st.sort_values("Scout pts", ascending=False),
            use_container_width=True, height=460, hide_index=True,
            column_config={
                "Face": st.column_config.ImageColumn("", width="small", pinned=True),
                "Player": st.column_config.TextColumn("Player", width="medium", pinned=True),
                "£m": st.column_config.NumberColumn("£m", format="%.1f", width="small"),
                "Scout mins": st.column_config.ProgressColumn(
                    "Scout mins", format="%.0f", min_value=0.0, max_value=3420.0,
                    width="medium",
                    help="Scout's projected minutes · the signal our model lacks for "
                         "anyone who missed 25/26."),
                "Scout pts": st.column_config.NumberColumn("Scout pts", format="%.0f"),
                "Like-for-like": st.column_config.NumberColumn(
                    "Like-for-like", format="%.0f",
                    help=f"Scout rescaled onto our {_scale:.2f}x scale · compare THIS to Our pts."),
                "Our pts": st.column_config.NumberColumn("Our pts", format="%.0f"),
                "Residual": st.column_config.NumberColumn(
                    "Residual", format="%+.0f",
                    help="Our pts minus Like-for-like. Negative = we are more bearish "
                         "than even our own scale explains. This is the real disagreement."),
                "DEFCON": st.column_config.ProgressColumn(
                    "DEFCON", format="%.1f", min_value=0.0, max_value=42.0, width="small"),
            })

st.markdown(
    f'<div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:18px;">'
    f'Projections fitted on 9 historical season-pairs; points signal is honest, not heroic. '
    f'Promoted-club and new-signing players have no FPL history · they are in the Scout tab, '
    f'not force-ranked. Re-check minutes and set-piece roles once {NEXT_SEASON} line-ups firm up.</div>',
    unsafe_allow_html=True)

# ── Chip route · the early Bench Boost and the Wildcard, priced as one decision ─
_sec("🗺️ Chip route · Bench Boost and Wildcard together")
st.caption("A Bench Boost needs 15 playing assets, which costs XI strength every week "
           "you carry it. The Wildcard is what repairs that. Scored end to end over "
           "GW1-19 against holding both chips.")


@st.cache_data(ttl=6 * 3600, show_spinner="Scoring chip routes over GW1-19…")
def _routes(_board: pd.DataFrame, _budget: float, _risk: float, _excl: tuple):
    """Score every configured route. Cached · each route runs several MILPs."""
    from analytics.season_opener import bb_dilution, compare_routes
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df

    from analytics.season_opener import opening_ease

    fx = get_fixtures_df(fetch_fixtures(), fetch_bootstrap())

    def _solve(b, all_must_play=False, bench_price_cap=None, opening_window=None):
        strategy = "🔋 Bench Boost GW1" if all_must_play else "⚖️ Optimal value"
        # A window builds the squad for the fixtures that actually follow it ·
        # this is what gives a wildcard rebuild its point.
        omap = ()
        if opening_window:
            oe = opening_ease(fx, opening_window[0], opening_window[1])
            omap = tuple(zip(oe["team_id"].astype(int), oe["ease"].astype(float)))
        return solve_draft(b, strategy, _budget, _risk, _excl, 0.0,
                           opening_map=omap,
                           bench_budget=(bench_price_cap * 4) if bench_price_cap else None)

    return compare_routes(_board, fx, _solve), bb_dilution(_board, _solve)


try:
    _routes_df, _dil = _routes(board, budget, risk, tuple(excluded))
except Exception as _e:
    _routes_df, _dil = pd.DataFrame(), None
    st.caption(f"Route comparison unavailable ({_e}).")

if _dil and _dil.get("break_even_lo") is not None:
    st.markdown(
        " ".join(s.strip() for s in f"""
        <div style="{CARD}border-left:3px solid #FFD700;margin-bottom:12px;">
        <div style="font-size:10px;font-weight:800;letter-spacing:0.18em;color:#FFD700;
        text-transform:uppercase;margin-bottom:4px;">Bench Boost clock</div>
        <div style="font-size:14px;color:#eef1f5;line-height:1.6;">
        An all-playing fifteen costs
        <b>{_dil['arms'][0]['dilution_per_gw']:.1f} pts a gameweek</b> to carry and the
        chip returns <b>{_dil['arms'][0]['bb_gain']:.0f} pts</b> once. That is a
        break-even of <b>{_dil['break_even_lo']:.1f} to {_dil['break_even_hi']:.1f}
        gameweeks</b> · play the Boost early and the reset has to follow inside that
        window.</div></div>""".splitlines()),
        unsafe_allow_html=True)

if not _routes_df.empty:
    _best = _routes_df.iloc[0]
    st.markdown(
        " ".join(s.strip() for s in f"""
        <div style="{CARD}border-left:3px solid #00FF87;margin-bottom:12px;">
        <div style="font-size:10px;font-weight:800;letter-spacing:0.18em;color:#00FF87;
        text-transform:uppercase;margin-bottom:4px;">Best route on this squad</div>
        <div style="font-size:14px;color:#eef1f5;line-height:1.6;">
        <b>{_best['label']}</b> · {_best['points']:.0f} pts over GW1-19,
        <b>{_best['vs_baseline']:+.0f}</b> against holding both chips.</div></div>
        """.splitlines()),
        unsafe_allow_html=True)

    _rt = _routes_df.copy()
    _rt.columns = ["Route", "BB GW", "WC GW", "GW1-19 pts", "vs holding chips"]
    st.dataframe(_rt, use_container_width=True, hide_index=True)
    st.caption("Fixture-ease model only · doubles and blanks past GW19 are not known "
               "yet, and the first chip set expires at GW19 regardless. It prices the "
               "Bench Boost honestly but UNDERSTATES a lone Wildcard: most of a "
               "wildcard's real value is repairing injuries and form the model cannot "
               "see, which is why the two no-Boost routes score alike. Read the Boost "
               "routes against each other, not the gap to holding both chips.")
