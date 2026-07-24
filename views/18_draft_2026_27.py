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
from components.team_identity import team_dot
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
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
    {team_dot(row.get("team_short"), size=14)}
    <div style="min-width:0;flex:1;">
      <div style="font-size:15px;font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</div>
      <div style="font-size:11px;color:rgba(255,255,255,0.45);">{team}</div>
    </div>
    {flag_html}
    <span style="background:{pc};color:#000;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:900;flex-shrink:0;">{pos}</span>
    <span style="font-size:14px;flex-shrink:0;" title="{verdict}">{emoji}</span>
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
        (f'<div style="{CARD}flex:1;min-width:150px;">'
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
    opening = st.slider("Opening fixtures GW1-6", 0.0, 1.0, 0.0, 0.05,
                        help="Slide right to favour players with soft opening fixtures, so the "
                             "squad holds up longer before you spend transfers (first wildcard "
                             "usually goes by ~GW10).")
excluded = st.multiselect(
    "Don't trust · exclude these players", options=sorted(board["web_name"].tolist()),
    help="Veto anyone you're not convinced by · the optimiser rebuilds around them.")

res = solve_draft(board, mode, budget, risk, tuple(excluded), opening)
if res is None:
    st.error("Solver found no feasible squad · widen the budget, lower risk, or un-exclude a player.")
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
if opening > 0:
    st.caption("Opening-fixtures weight is a tie-breaker · it favours soft GW1-6 runs among "
               "similar players so the squad lasts longer, without overriding your best picks.")

from components.pitch_view import render_squad_pitch

render_squad_pitch(
    [{
        "web_name": r["web_name"],
        "position": r["position"],
        "team_code": int(r.get("team_code", 1) or 1),
        "on_bench": not r["in_xi"],
        "is_captain": bool(r["is_captain"]),
        "stat": float(r["pts"]),
        "price": float(r["price"]),
    } for _, r in squad.iterrows()],
    stat_label="proj", title_right=NEXT_SEASON)

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
_groups = []
for verdict, acc, _e, _m in [(k,) + v for k, v in VERDICT_META.items() if k != VERDICTS.SCOUT]:
    d = board[board["verdict"] == verdict]
    if d.empty:
        continue
    _groups.append((verdict, acc, [
        {"x": int(r["projected_minutes"]), "y": round(float(r["projected_points"]), 1),
         "name": str(r["web_name"]), "size": 7,
         "tip": (f"{r['web_name']} · {r['team_name']}<br/>£{r['actual_price']:.1f}m · "
                 f"{int(r['projected_minutes']):,} mins → {r['projected_points']:.0f} pts")}
        for _, r in d.iterrows()
    ]))
charts.render(
    charts.multi_scatter_option(_groups, x_name="Projected minutes 26/27", y_name="Projected points"),
    height="340px", key="board_min_pts",
)

# ── Full table ─────────────────────────────────────────────────────────────────
# ── Inspect any player ─────────────────────────────────────────────────────────
_sec("🔍 Inspect any player")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _last_season_stats():
    from data.processors.archive import load_season_summary
    s = load_season_summary()
    s = s[s["season"] == LAST_COMPLETE_SEASON]
    keep = ["goals", "assists", "xg", "xa", "xgi", "defcon_points", "minutes",
            "total_points", "ppg", "clean_sheets", "bonus"]
    return s.set_index("code")[[c for c in keep if c in s.columns]]


_pick = st.selectbox("Pick a player to see the numbers behind the projection",
                     options=sorted(board["web_name"].tolist()), key="draft_inspect")
_r = board[board["web_name"] == _pick].iloc[0]
_ls = _last_season_stats()
_code = int(_r["code"])
_s = _ls.loc[_code] if _code in _ls.index else None


def _tile(label, value, color="#fff"):
    return (f'<div style="text-align:center;flex:1;min-width:66px;">'
            f'<div style="font-size:18px;font-weight:900;color:{color};">{value}</div>'
            f'<div style="font-size:9px;letter-spacing:0.08em;text-transform:uppercase;'
            f'color:rgba(255,255,255,0.4);">{label}</div></div>')


_v = str(_r.get("verdict", ""))
_acc, _emoji, _ = VERDICT_META.get(_v, VERDICT_META[VERDICTS.FAIR])
_cc = {"High": "#00FF87", "Medium": "#FFA500", "Low": "#FF6B6B"}.get(str(_r.get("confidence")), MUTED)
_of = float(_r.get("opening_factor") or 1.0)
_of_lbl, _of_col = (("Kind", "#00FF87") if _of >= 1.03
                    else ("Tough", "#FF6B6B") if _of <= 0.97 else ("Average", MUTED))
_hdr = "".join(s.strip() for s in f"""
<div style="{CARD}border-top:3px solid {_acc};margin-bottom:10px;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
    {team_dot(_r.get('team_short'), size=16)}
    <div style="font-size:20px;font-weight:900;color:#fff;">{_pick}</div>
    <div style="font-size:12px;color:{MUTED};">{_r.get('team_name','')} · {_r.get('position','')} · £{float(_r.get('actual_price') or 0):.1f}m</div>
    <div style="flex:1;"></div>
    <span style="font-size:16px;" title="{_v}">{_emoji}</span>
    <span style="font-size:11px;font-weight:800;color:{_cc};text-transform:uppercase;">{_r.get('confidence','')}</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;">
    {_tile('Proj 26/27', f"{float(_r.get('projected_points') or 0):.0f}", '#00FF87')}
    {_tile('Range', f"{float(_r.get('proj_lo') or 0):.0f}–{float(_r.get('proj_hi') or 0):.0f}", _cc)}
    {_tile('Pts/£m', f"{float(_r.get('value_score') or 0):.1f}", '#FFD700')}
    {_tile('Owned', f"{float(_r.get('ownership') or 0):.0f}%", '#04f5ff')}
    {_tile('vs model', f"{float(_r.get('pricing_surprise') or 0):+.1f}", '#fff')}
    {_tile('Open 1-6', _of_lbl, _of_col)}
  </div>
</div>""".splitlines())
st.markdown(_hdr, unsafe_allow_html=True)

if _s is not None:
    _ev = "".join(s.strip() for s in f"""
<div style="{CARD}margin-bottom:6px;">
  <div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};text-transform:uppercase;margin-bottom:8px;">25/26 evidence · the basis for the projection</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;">
    {_tile('Points', f"{float(_s.get('total_points') or 0):.0f}")}
    {_tile('Goals', f"{float(_s.get('goals') or 0):.0f}", '#FF7B00')}
    {_tile('Assists', f"{float(_s.get('assists') or 0):.0f}", '#e90052')}
    {_tile('xGI', f"{float(_s.get('xgi') or 0):.1f}", '#04f5ff')}
    {_tile('DEFCON', f"{float(_s.get('defcon_points') or 0):.0f}", '#00FF87')}
    {_tile('Clean sh.', f"{float(_s.get('clean_sheets') or 0):.0f}", '#04f5ff')}
    {_tile('Minutes', f"{float(_s.get('minutes') or 0):,.0f}")}
    {_tile('PPG', f"{float(_s.get('ppg') or 0):.1f}", '#FFD700')}
  </div>
</div>""".splitlines())
    st.markdown(_ev, unsafe_allow_html=True)
    _cn = str(_r.get("confidence_note", "") or "")
    _pens = _r.get("pens_order")
    _sp = " · ⚽ on penalties" if (_num_safe(_pens) == 1) else ""
    _on = str(_r.get("override_note", "") or "")
    _note = " · ".join(x for x in [_cn, _on] if x)
    st.caption(f"Projected **{float(_r.get('projected_points') or 0):.0f}** pts (range "
               f"{float(_r.get('proj_lo') or 0):.0f}–{float(_r.get('proj_hi') or 0):.0f}), "
               f"confidence **{_r.get('confidence','')}**{_sp}."
               + (f" {_note}." if _note else ""))
else:
    st.caption("No 2025/26 record · this is a promoted-club or new-signing player (Scout). "
               "Judge on the eye test and the opening fixtures until data lands.")

# where they rank in their position, by projection
_pos_df = board[board["position"] == _r["position"]].nlargest(12, "projected_points")
if _pick not in set(_pos_df["web_name"]):
    _pos_df = pd.concat([_pos_df, board[board["web_name"] == _pick]])
_pos_df = _pos_df.sort_values("projected_points")
_bar_colors = ["#FFD700" if n == _pick else "#04f5ff" for n in _pos_df["web_name"]]
_opt = charts.bar_option(x=list(_pos_df["web_name"]),
                         y=[round(float(v), 0) for v in _pos_df["projected_points"]],
                         colors=_bar_colors, horizontal=True)
_opt["tooltip"]["formatter"] = "{b}: {c} proj pts"
charts.render(_opt, height="300px", key="inspect_rank")
st.caption(f"Where **{_pick}** is projected to finish among {_r['position']}s (gold), by projected 26/27 points.")

# ── Full table ─────────────────────────────────────────────────────────────────
_sec("Every price · every verdict")
tab_all, tab_surprise = st.tabs(["All players", "Biggest bargains & taxes"])

table = board[["web_name", "position", "team_name", "verdict", "confidence",
               "actual_price", "pricing_surprise", "projected_points", "proj_lo", "proj_hi",
               "value_score", "ownership", "last_season_points"]].copy()
table.columns = ["Player", "Pos", "Team", "Verdict", "Conf.", "Price 26/27 (£m)",
                 "vs model (£m)", "Proj pts", "Low", "High", "Pts/£m", "Owned %", "25/26 pts"]
table = table.round(2)

with tab_all:
    st.dataframe(table.sort_values("Proj pts", ascending=False),
                 use_container_width=True, height=420, hide_index=True)
with tab_surprise:
    st.caption("Positive vs model = FPL priced them below the model (bargain). Negative = tax.")
    st.dataframe(table.reindex(table["vs model (£m)"].abs().sort_values(ascending=False).index).head(40),
                 use_container_width=True, height=420, hide_index=True)

st.markdown(
    f'<div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:18px;">'
    f'Projections fitted on 9 historical season-pairs; points signal is honest, not heroic. '
    f'Promoted-club and new-signing players have no FPL history · they are in the Scout tab, '
    f'not force-ranked. Re-check minutes and set-piece roles once {NEXT_SEASON} line-ups firm up.</div>',
    unsafe_allow_html=True)
