"""
The Playbook · how to actually play FPL, answered from 10 seasons of data.

Every section is a question Eoin asked, answered empirically from the
archive (analytics/playbook.py), distilled into a rule for 2026-27.
"""

from __future__ import annotations

import json

import pandas as pd
from ui import charts
import streamlit as st

from components.animations import inject_global_animations
from config import CACHE_DIR, LAST_COMPLETE_SEASON

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:16px 20px;")

CHART_TITLE = {"color": "#eef1f5", "fontSize": 12, "fontWeight": "bold"}


@st.cache_data(ttl=24 * 3600, show_spinner="Crunching 10 seasons of data…")
def _answers(_v: int = 3):   # bump _v to bust the cache when analyses change
    from data.processors.archive import (build_optimizer_input, load_gw_archive,
                                         load_season_summary)
    from analytics import playbook as pb

    arch = load_gw_archive()
    summary = load_season_summary()
    opt = build_optimizer_input(LAST_COMPLETE_SEASON)
    pj_path = CACHE_DIR / "perfect_season_2025_26.json"
    pj = json.load(open(pj_path)) if pj_path.exists() else None

    return {
        "formation": pb.formation_summary(opt, pj),
        "share": pb.position_share_by_season(arch),
        "defenders": pb.defender_archetypes(summary, arch),
        "pens": pb.pen_taker_uplift(summary),
        "predict": pb.predictiveness(arch),
        "horizon": pb.fixture_horizon(arch),
        "value": pb.team_value_growth(arch),
        "minutes": pb.minutes_importance(summary),
        "intensity": pb.minutes_intensity(summary),
        "captaincy": pb.premium_captaincy(arch, summary),
        "icon_field": pb.icon_vs_field(summary),
        "bench": pb.bench_doctrine(summary),
        "defcon_mix": pb.defcon_mix(summary),
    }


A = _answers()


def _question(num: int, q: str, rule: str, accent: str = "#00FF87") -> None:
    st.markdown(
        f'<div class="fplh-animate-in" style="margin:34px 0 12px;">'
        f'<div style="display:flex;align-items:center;gap:12px;">'
        f'<div style="background:{accent};color:#000;border-radius:8px;width:30px;'
        f'height:30px;display:inline-flex;align-items:center;justify-content:center;'
        f'font-weight:900;font-size:15px;flex-shrink:0;">{num}</div>'
        f'<div style="font-size:19px;font-weight:900;color:#fff;">{q}</div></div>'
        f'<div style="margin-top:10px;{CARD}border-left:3px solid {accent};">'
        f'<div style="font-size:10px;font-weight:800;letter-spacing:0.18em;color:{accent};'
        f'text-transform:uppercase;margin-bottom:4px;">The rule</div>'
        f'<div style="font-size:14px;color:#eef1f5;line-height:1.6;">{rule}</div>'
        f'</div></div>',
        unsafe_allow_html=True)


# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">📖 The Playbook</div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    Your strategy questions, answered by 253,000 player-gameweeks · not vibes
  </div>
</div>""",
    unsafe_allow_html=True,
)

# ── Season Start Kit ──────────────────────────────────────────────────────────
st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:26px 0 12px;">'
    f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;'
    f'color:#FFD700;white-space:nowrap;">🚀 Season Start Kit · day one of 2026-27</div>'
    f'<div style="flex:1;height:1px;background:rgba(255,215,0,0.25);"></div></div>'
    f'<div style="font-size:12px;color:rgba(255,255,255,0.45);margin-bottom:12px;">'
    f'The whole playbook compressed into what to do at the deadline. '
    f'The named squad lives in the 26/27 Draft page · this is the thinking behind it.</div>',
    unsafe_allow_html=True)

kit = [
    ("💷", "Budget blueprint", "#FFD700",
     "Hindsight's optimal GW1 split: <b>GKP £10.0 · DEF £26.5 · MID £35.5 · FWD £27.5</b>. "
     "Two playing keepers from solid defences, budget CB core, midfield is where the money goes, "
     "one premium forward · no £14m+ luxury unless he's projected top-3 overall."),
    ("⏱️", "Minutes first, always", "#00FF87",
     "Minutes ↔ points: ρ = <b>0.98</b>. Nailed (2700+ min) players average <b>3.6 ppg and "
     "23.9 pts/£m</b> vs 1.5 ppg / 3.0 for rotation players. Every pick must answer "
     "'does he play 90 every week?' before any other question. Pre-season: watch friendlies "
     "for role locks, avoid anyone in a positional battle."),
    ("🛡️", "Defender shopping list", "#04f5ff",
     "3 starting CBs at £4.5–5.5 from top/mid defensive units · prioritise set-piece targets "
     "(DEFCON floor ~14–22 pts + header goals). Full-backs only if elite-team assist machines. "
     "Promoted-team defenders: cheap but check the CBIT profile once data lands."),
    ("⚽", "Midfield & forward criteria", "#e90052",
     "Mids: nailed + xGI per 90 ≥ 0.5 + ideally on pens (tiebreaker, don't pay premium for it). "
     "Mid-priced (£6.5–8.5) is where last season's 200-pt breakouts lived (Semenyo, Gibbs-White). "
     "One forward who starts every week beats two who rotate."),
    ("🚩", "Red flags", "#FF4B4B",
     "New signing 'competition for places' · back from long injury · European-competition rotation "
     "risk at big clubs · great pre-season hype on a bench player · paying for last season's "
     "overperformance (check the Finishing Luck scatter · G−xG > +3 regresses)."),
    ("🗓️", "First 5 GWs", "#FF8C42",
     "Judge opening fixture runs over 5–6 GWs, not 1–2. Bank transfers early while watching "
     "minutes settle. <b>Default to zero hits</b> · a hit is only worth +2.4 pts even with "
     "perfect foresight; save them for forced moves or chip set-up. First wildcard: "
     "hold until the first international break when roles are clear."),
]
st.markdown(
    '<div class="fplh-stagger" style="display:grid;'
    'grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;">'
    + "".join(
        f'<div class="fplh-card-hover" style="{CARD}border-top:3px solid {acc};">'
        f'<div style="font-size:20px;">{emoji}</div>'
        f'<div style="font-size:13px;font-weight:800;color:#fff;margin:4px 0;">{title}</div>'
        f'<div style="font-size:12px;color:rgba(255,255,255,0.62);line-height:1.6;">{body}</div></div>'
        for emoji, title, acc, body in kit)
    + "</div>",
    unsafe_allow_html=True)
try:
    st.page_link("views/18_draft_2026_27.py", label="→ See the named optimal squad in the 26/27 Draft")
except Exception:
    pass

# ── Q1 Formation ──────────────────────────────────────────────────────────────
f = A["formation"]
top_form = max(f["best_xi_formations"], key=f["best_xi_formations"].get)
_question(
    1, "What formation scores most since DEFCON · is 5-4-1 the play?",
    f"No. The weekly best-possible XI was most often <b>3-5-2</b> "
    f"({f['best_xi_formations'].get('3-5-2', 0)}/38 weeks) or <b>4-5-1</b> "
    f"({f['best_xi_formations'].get('4-5-1', 0)}/38), averaging "
    f"{f['avg_def']:.1f}-{f['avg_mid']:.1f}-{f['avg_fwd']:.1f}. DEFCON made defenders "
    f"<i>cheap points</i>, not <i>ceiling points</i> · hauls still come from midfield. "
    f"Build: 3-4 playing defenders for the floor, 5 midfielders for the ceiling, "
    f"one elite forward. 5-4-1 topped the week exactly once all season.",
    "#00FF87")
per_gw = f["per_gw"]
counts = pd.Series(f["best_xi_formations"]).sort_values(ascending=True)
c1, c2 = st.columns([1, 1])
with c1:
    counts = counts.sort_values(ascending=False)
    opt = charts.bar_option(x=list(counts.index), y=[int(v) for v in counts.values],
                            color="#00FF87", horizontal=True)
    opt["title"] = {"text": "Weeks each formation was the best XI",
                    "textStyle": CHART_TITLE}
    opt["grid"]["top"] = 36
    charts.render(opt, height="300px", key="pb_formations_best")
with c2:
    if "perfect_season_formations" in f:
        pcounts = pd.Series(f["perfect_season_formations"]).sort_values(ascending=False)
        opt = charts.bar_option(x=list(pcounts.index), y=[int(v) for v in pcounts.values],
                                color="#FFD700", horizontal=True)
        opt["title"] = {"text": "Formations the Perfect Season actually fielded",
                        "textStyle": CHART_TITLE}
        opt["grid"]["top"] = 36
        charts.render(opt, height="300px", key="pb_formations_ps")

# ── Q2 Spend structure ────────────────────────────────────────────────────────
share = A["share"]
def_25 = float(share[(share["season"] == "2025-26") & (share["position"] == "DEF")]["pct_of_points"].iloc[0])
def_pre = float(share[(share["season"] != "2025-26") & (share["position"] == "DEF")]["pct_of_points"].mean())
_question(
    2, "Big defence + cheap midfield, or the classic premium-mid build?",
    f"Defenders' share of all FPL points jumped from ~{def_pre:.0f}% to "
    f"<b>{def_25:.0f}%</b> with DEFCON · but the jump lives in the <b>£4.0–5.5m bracket</b> "
    f"(Guéhi £4.5→179pts, Senesi £4.5→175, Mukiele £4.0→151). Premium defenders did not "
    f"get better; cheap ones did. Optimal structure: <b>budget defence (3 starters at "
    f"4.5–5.5 from top defensive units), heavy midfield spend</b>. Don't pay £6m+ for a "
    f"defender unless he's an attacking FB on a top team.",
    "#04f5ff")
_seasons = sorted(share["season"].unique())
_series = []
for pos, col in POS_COLORS.items():
    sub = share[share["position"] == pos].set_index("season")
    if sub.empty:
        continue
    _series.append((pos, [round(float(sub["pct_of_points"].get(se, 0) or 0), 1)
                          for se in _seasons], col))
opt = charts.grouped_bars_option(_seasons, _series)
opt["tooltip"]["trigger"] = "item"
opt["tooltip"]["formatter"] = "{a} · {b}: {c}% of all points"
charts.render(opt, height="320px", key="pb_pos_share")

# ── Q3 Which defenders ────────────────────────────────────────────────────────
d = A["defenders"]
_question(
    3, "CBs or full-backs? Good teams or bad teams?",
    "With every defender hand-labelled (curated role map, editable in "
    "<code>assets/defender_roles_2025_26.json</code>): <b>centre-backs from top "
    "defensive teams are the DEFCON-era kings</b> · avg 120 pts at 24.8 pts/£m with "
    "~22 DEFCON pts of pure floor (Senesi, Gabriel, Guéhi, Tarkowski). CBs from "
    "<i>mid</i> teams (99 pts, 20.3 pts/£m) still beat full-backs from anywhere except "
    "the elite. Full-backs barely earn DEFCON (~4–7 pts vs CBs' 14–22) · only top-team "
    "attacking FBs justify themselves (110 pts), and the set-piece-threat CB beats them "
    "anyway. Rule: <b>buy CBs who head set pieces from top/mid defences; treat "
    "full-backs as luxury picks needing assist upside</b>.",
    "#e90052")
grid = d["grid"].rename(columns={
    "archetype": "Archetype", "team_tier": "Team (CS tier)", "n": "N",
    "avg_pts": "Avg pts", "avg_ppm": "Pts/£m", "avg_defcon": "DEFCON pts",
    "avg_price": "Avg £m"})
st.dataframe(grid, use_container_width=True, hide_index=True, height=260)
st.markdown(f'<div style="font-size:12px;color:{MUTED};margin-bottom:8px;">'
            f'Best-value defenders of 2025-26:</div>', unsafe_allow_html=True)
st.dataframe(d["top_value"].rename(columns={
    "web_name": "Player", "team_name": "Team", "archetype": "Type",
    "team_tier": "Tier", "start_price": "GW1 £m", "total_points": "Pts",
    "pts_per_million": "Pts/£m", "defcon_points": "DEFCON", "cbit_per90": "CBIT/90"}),
    use_container_width=True, hide_index=True, height=290)

# ── Q4 Penalty takers ─────────────────────────────────────────────────────────
pens = A["pens"]
_question(
    4, "Are penalty takers worth targeting?",
    "Yes for total points, with a price caveat. First-choice takers (1500+ mins) "
    "out-scored positional peers by <b>~20 points median</b> (MID 125.5 vs 103.0, "
    "FWD 127.0 vs 114.0). But takers are priced for it · MID takers' pts/£m is "
    "actually <i>lower</i> (14.6 vs 17.5). Rule: a pen taker is a <b>tiebreaker "
    "between similar players</b>, not a reason to pay up. The exception: a "
    "cheap player who just inherited pens is a genuine market edge.",
    "#FFD700")
if pens is not None:
    p = pens.copy()
    p["pen_taker"] = p["pen_taker"].map({True: "Taker", False: "Not taker"})
    _pos_order = [x for x in ["GKP", "DEF", "MID", "FWD"] if x in set(p["position"])]
    _series = []
    for grp, col in [("Taker", "#FFD700"), ("Not taker", "#555a66")]:
        sub = p[p["pen_taker"] == grp].set_index("position")
        _series.append((grp, [round(float(sub["med_pts"].get(x, 0) or 0), 1)
                              for x in _pos_order], col))
    opt = charts.grouped_bars_option(_pos_order, _series)
    opt["tooltip"]["trigger"] = "item"
    opt["tooltip"]["formatter"] = "{a} · {b}: {c} median pts"
    charts.render(opt, height="300px", key="pb_pens")

# ── Q5 Form vs fixtures vs xG ─────────────────────────────────────────────────
pr = A["predict"]
_question(
    5, "Form or fixtures · what should I actually chase?",
    f"<b>Form first, fixtures last.</b> Across {pr['n']:,} player-gameweeks "
    f"(4 seasons), last-4 points predicts next-GW points at ρ={pr['next_gw']['form (last-4 pts)']:.2f}, "
    f"last-4 xGI at ρ={pr['next_gw']['underlying (last-4 xGI)']:.2f}, and next-opponent ease at only "
    f"ρ={pr['next_gw']['fixture ease (next opp)']:.2f}. Over the next 4 GWs the gap widens "
    f"(form {pr['next_4_gws']['form (last-4 pts)']:.2f} vs xGI {pr['next_4_gws']['underlying (last-4 xGI)']:.2f}). "
    f"Honest caveat: 'form' partly means 'plays 90 minutes every week' · minutes security "
    f"is the hidden king. So: <b>nailed minutes → recent returns → underlying xGI → "
    f"fixtures</b>, in that order. Never transfer in a bench risk for a nice fixture.",
    "#00FF87")
sig = pd.DataFrame({
    "signal": ["Form (last-4 pts)", "xGI (last-4)", "Fixture ease (next opp)"],
    "next_gw": [pr["next_gw"]["form (last-4 pts)"],
                pr["next_gw"]["underlying (last-4 xGI)"],
                pr["next_gw"]["fixture ease (next opp)"]],
})
opt = charts.bar_option(x=list(sig["signal"]),
                        y=[round(float(v), 2) for v in sig["next_gw"]],
                        colors=["#00FF87", "#04f5ff", "#FF8C42"])
opt["yAxis"]["name"] = "Spearman ρ vs next-GW points"
opt["yAxis"]["nameTextStyle"] = {"color": "rgba(236,241,245,0.55)", "fontSize": 10}
charts.render(opt, height="300px", key="pb_signals")

# ── Q6 Fixture horizon ────────────────────────────────────────────────────────
hz = A["horizon"]
_question(
    6, "How many fixtures ahead should I judge · 4? 5?",
    f"There's no cliff · predictive power <i>rises slowly</i> with horizon "
    f"(ρ {hz['spearman'].iloc[0]:.2f} at 2 GWs → {hz['spearman'].iloc[-1]:.2f} at 8) because longer "
    f"windows smooth one-off blanks. Practical rule: <b>judge runs of 5–6 fixtures</b>, "
    f"and never move for a single good fixture · one game of ease is worth almost "
    f"nothing (ρ≈0.14). The app's 6-GW lookahead default is right.",
    "#04f5ff")
opt = charts.multi_line_option(
    [("Ease → points correlation",
      [(int(h), round(float(r), 3)) for h, r in zip(hz["horizon"], hz["spearman"])],
      "#04f5ff")],
    x_name="Fixture horizon (GWs ahead)", y_name="Ease → points correlation")
opt["series"][0]["symbol"] = "circle"
opt["series"][0]["symbolSize"] = 7
opt["series"][0]["lineStyle"]["width"] = 3
opt["legend"] = {"show": False}
charts.render(opt, height="280px", key="pb_horizon")

# ── Q7 Team value ─────────────────────────────────────────────────────────────
v = A["value"]
_question(
    7, "Does team value really grow ~£0.5m a month?",
    f"<b>Not by holding · 2025-26 punished it.</b> The GW1 template lost "
    f"<b>£{abs(v['total_growth']):.1f}m</b> over the season (Salah, Isak and friends bled value), "
    f"and even re-buying the most-owned 15 every week got cheaper. Value came from "
    f"catching risers early: the top-30 risers gained ~£0.5m each (B.Fernandes +1.4, "
    f"Gabriel +1.3, Thiago +1.2). And remember the sell rule: you bank only "
    f"<b>half</b> the rise (every £0.2 up = £0.1 sell profit). Plan for "
    f"<b>£0–1.5m of realised growth all season</b>, earned by early moves onto "
    f"form risers · never budget +£0.5m/month into your plans.",
    "#FF8C42")
traj = v["trajectory"]
opt = charts.multi_line_option(
    [("GW1 template value change (£m)",
      [(int(g), round(float(v), 2)) for g, v in zip(traj["gw"], traj["growth"])],
      "#FF8C42")],
    x_name="Gameweek", y_name="GW1 template value change (£m)")
opt["series"][0]["areaStyle"] = {"color": "rgba(255,140,66,0.15)"}
opt["series"][0]["lineStyle"]["width"] = 2
opt["legend"] = {"show": False}
charts.render(opt, height="280px", key="pb_value_traj")
st.markdown(f'<div style="font-size:11px;color:rgba(255,255,255,0.35);">{v["note"]}</div>',
            unsafe_allow_html=True)

# ── Q8 Minutes ────────────────────────────────────────────────────────────────
mi = A["minutes"]
it = A["intensity"]
ov = it["overall"]
_question(
    8, "Full-90 players vs subbed-early players · does it really matter per match?",
    f"The clean test (regulars only, 20+ appearances, so 'plays more games' can't "
    f"cheat): a <b>full-90 player scores {ov.iloc[-1]['pts_per_match']:.1f} pts per match "
    f"vs {ov.iloc[0]['pts_per_match']:.1f} for someone subbed before 65'</b> · about "
    f"+1.2 per match, ~45 pts over a season. The twist: per-90 efficiency is actually "
    f"<i>flat-to-falling</i> ({ov.iloc[0]['pts_per_90']:.1f} → {ov.iloc[-1]['pts_per_90']:.1f}) "
    f"- early-subbed attackers aren't worse per minute, they just get fewer minutes for "
    f"returns to land in, miss the 60' appearance threshold, lose CS eligibility and "
    f"DEFCON accumulation. It's an <b>exposure effect, not a quality effect</b>. "
    f"Sharpest in midfield (4.2 vs 2.3 per match) and attack (5.3 vs 2.6). Rule: a "
    f"60–70-minute player needs clearly elite per-90 numbers to justify a slot; "
    f"when in doubt, take the locked-in 90-minute man. (Season-level confound for "
    f"context: minutes ↔ points ρ = {mi['spearman']:.2f}.)",
    "#00FF87")
opt = charts.bar_option(x=[str(b) for b in ov["band"]],
                        y=[round(float(v), 1) for v in ov["pts_per_match"]],
                        color="#00FF87", name="Points per match")
opt["series"].append({
    "name": "Points per 90 (efficiency)", "type": "line",
    "data": [round(float(v), 1) for v in ov["pts_per_90"]],
    "symbol": "circle", "symbolSize": 7,
    "lineStyle": {"color": "#FF8C42", "width": 3, "type": "dotted"},
    "itemStyle": {"color": "#FF8C42"},
})
opt["legend"] = {"top": 0, "right": 0,
                 "textStyle": {"color": "rgba(236,241,245,0.55)", "fontSize": 10},
                 "itemWidth": 12, "itemHeight": 8}
opt["grid"]["top"] = 30
opt["xAxis"]["name"] = "Avg minutes per appearance (regulars, 20+ games)"
opt["xAxis"]["nameLocation"] = "middle"
opt["xAxis"]["nameGap"] = 28
opt["xAxis"]["nameTextStyle"] = {"color": "rgba(236,241,245,0.55)", "fontSize": 10}
charts.render(opt, height="320px", key="pb_minutes_combo")

# ── Q9 Hits ───────────────────────────────────────────────────────────────────
_question(
    9, "When is a -4 hit actually worth it?",
    "Almost never · your instinct is correct, and the scenarios prove it without "
    "hindsight bias. The unlimited engine took <b>141 hits</b> and beat the zero-hit "
    "engine by only 334 points: <b>+2.4 net points per hit WITH PERFECT FORESIGHT</b>. "
    "A real manager forecasts with error, so the expected value of a routine hit is "
    "negative · the 141-hit season is overfitted omniscience, not a strategy. Where "
    "perfect play <i>did</i> concentrate its hits is instructive: <b>47% landed within "
    "one GW of a chip</b> (loading the squad before Bench Boost / Triple Captain, "
    "rebuilding around Wildcard). The legitimate hit triggers, in order: "
    "<b>1)</b> forced · key player injured/suspended with no playable bench cover; "
    "<b>2)</b> chip amplification · a hit that upgrades your BB/TC week pays double; "
    "<b>3)</b> a projected gain over the next 5–6 GWs that clears <b>~8+ points</b> "
    "(double the cost, to survive your forecast error). Everything else: bank the "
    "transfer and wait.",
    "#FF4B4B")

# ── The distilled plan ────────────────────────────────────────────────────────
# ── Q10 Premium captaincy ─────────────────────────────────────────────────────
cap = A["captaincy"]
_saf = cap["saf"]
_haal = next((x for x in _saf if x["name"] == "Haaland"), _saf[0])
_second = next((x for x in _saf if x["name"] != _haal["name"]), _saf[1])
_freed = _haal["price"] - _second["price"]
_curve = cap["budget_curve"]
_up_gain = float(_curve["mean"].iloc[3] - _curve["mean"].iloc[1]) \
    if len(_curve) >= 4 else 0.0
_pair = cap["pairs"][0]
_question(
    10, "Is the premium captain worth it · or captain a cheaper set-and-forget?",
    f"The armband case for Haaland was real but tiny: set-and-forget "
    f"Haaland banked <b>+{_haal['extra']}</b> captain points vs "
    f"<b>+{_second['extra']}</b> for {_second['name']} · just "
    f"{_haal['extra'] - _second['extra']} points for <b>£{_freed:.0f}m more</b>. "
    f"That freed £{_freed:.0f}m upgraded a £5.5–7m attacker into the £8.5–10m "
    f"band, historically worth <b>~+{_up_gain:.0f} season points</b>. Rotation "
    f"reality check: the best pair ({_pair['pair']}) hit +{_pair['perfect']} with "
    f"perfect hindsight but only <b>+{_pair['home_rule']}</b> on an honest "
    f"home-first rule · barely above just captaining one of them forever. Rule: "
    f"<b>a ~£9m set-and-forget captain + the savings spent in the XI beat the "
    f"£14m icon</b> unless the icon is dramatically outscoring everyone. "
    f"Captaincy consistency matters more than captaincy ceiling. "
    f"<i>Honest caveat: a £9m player scoring like Fernandes did is rare · but "
    f"the ten-season base rate below says betting AGAINST the crown price is "
    f"the percentage play, even when you can't name the challenger in advance.</i>",
    "#FFD700")

# Ten-season base rate: the priciest player vs the best cheaper premium
_iv = A["icon_field"]
if not _iv.empty:
    _beat = int((_iv["delta"] > 0).sum())
    st.markdown(
        f'<div style="font-size:12px;color:rgba(255,255,255,0.55);margin:2px 0 8px;">'
        f'Across {len(_iv)} seasons, a premium at least £2m cheaper outscored the '
        f'most expensive player in <b style="color:#00FF87;">{_beat} of {len(_iv)}</b> '
        f'· the icon price bought the best armband only '
        f'{len(_iv) - _beat} times (picked with hindsight · read it as a base '
        f'rate on the crown price, not a guarantee you\'d find the challenger).</div>',
        unsafe_allow_html=True)
    opt = charts.bar_option(
        x=[f"{r.season} · {r.challenger} vs {r.icon}" for r in _iv.itertuples()],
        y=[int(r.delta) for r in _iv.itertuples()],
        colors=["#00FF87" if r.delta > 0 else "#FF4B4B" for r in _iv.itertuples()],
        horizontal=True)
    for item, r in zip(opt["series"][0]["data"], _iv.itertuples()):
        item["tooltip"] = {"formatter": (
            f"<b>{r.season}</b><br/>Icon: {r.icon} £{r.icon_price:.1f}m · {r.icon_pts} pts"
            f"<br/>Challenger: {r.challenger} £{r.ch_price:.1f}m · {r.ch_pts} pts"
            f"<br/>{r.delta:+d} pts while saving £{r.saved:.1f}m")}
    opt["title"] = {"text": "Cheaper premium vs the priciest player · ten seasons",
                    "textStyle": CHART_TITLE}
    opt["grid"]["top"] = 36
    opt["grid"]["left"] = 210
    charts.render(opt, height="330px", key="pb_icon_field")
_c1, _c2 = st.columns(2)
with _c1:
    opt = charts.bar_option(
        x=[x["name"] for x in _saf],
        y=[x["extra"] for x in _saf],
        colors=["#FFD700" if x["name"] == _haal["name"] else "#04f5ff"
                for x in _saf],
        horizontal=True)
    for item, x in zip(opt["series"][0]["data"], _saf):
        item["tooltip"] = {"formatter": (f"<b>{x['name']}</b> · £{x['price']:.0f}m"
                                         f"<br/>+{x['extra']} captain pts if "
                                         f"captained every week")}
    from components.team_identity import player_photo_url as _ppu
    charts.with_image_labels(opt, [_ppu(x.get("code")) for x in _saf])
    opt["title"] = {"text": "Set-and-forget captain · extra points banked",
                    "textStyle": CHART_TITLE}
    opt["grid"]["top"] = 36
    opt["grid"]["left"] = 132
    charts.render(opt, height="320px", key="pb_saf_captain")
with _c2:
    _pp = cap["pairs"]
    opt = charts.grouped_bars_option(
        x=[p["pair"].replace(" + ", "\n+ ") for p in _pp],
        series=[("Perfect rotation (hindsight)", [p["perfect"] for p in _pp], "#8891A5"),
                ("Home-first rule (honest)", [p["home_rule"] for p in _pp], "#00FF87")])
    opt["title"] = {"text": "Rotating pairs · hindsight vs honest rule",
                    "textStyle": CHART_TITLE}
    opt["grid"]["top"] = 46
    opt["legend"]["top"] = 22
    opt["xAxis"]["axisLabel"]["fontSize"] = 8
    charts.render(opt, height="300px", key="pb_pair_captain")

# ── Q11 Bench strength ────────────────────────────────────────────────────────
bn = A["bench"]
_question(
    11, "Strong bench or cheap bench?",
    f"A nailed starter missed only <b>{bn['missed_per_starter']:.1f} gameweeks</b> "
    f"a season, so a full XI generates roughly {bn['autosub_events']:.0f} autosub "
    f"appearances a year. Upgrading all three outfield bench slots from £4.0–4.5 "
    f"to £5.0–5.5 buys ~<b>+{bn['tiers'][2]['autosub_pts'] - bn['tiers'][0]['autosub_pts']} "
    f"autosub points for ~£{bn['tiers'][2]['extra_cost']:.0f}m</b> · the same money "
    f"moved INTO the XI buys 3–8× that (see the price-band curve in Q10). Rule: "
    f"<b>bench money is dead money · one playing £4.5 DEFCON defender as first "
    f"sub, fodder behind him</b>, and spend everything else on the eleven who "
    f"score every week. DEFCON quietly strengthened this: the best cheap "
    f"defenders now carry a real floor, so your first sub is decent by default.",
    "#04f5ff")
opt = charts.grouped_bars_option(
    x=[t["tier"] for t in bn["tiers"]],
    series=[("Autosub points / season", [t["autosub_pts"] for t in bn["tiers"]], "#04f5ff"),
            ("Extra cost (£m ×10)", [t["extra_cost"] * 10 for t in bn["tiers"]], "#FF8C42")])
opt["title"] = {"text": "Bench tiers · what upgrades actually return",
                "textStyle": CHART_TITLE}
opt["grid"]["top"] = 46
opt["legend"]["top"] = 22
opt["tooltip"]["trigger"] = "item"
charts.render(opt, height="280px", key="pb_bench_tiers")

# ── Q12 How many DEFCON defenders? ───────────────────────────────────────────
dm = A["defcon_mix"]
_st = dm["stats"]
_best = max(dm["mixes"], key=lambda m: (m["usable_pts"], -m["k"]))
_question(
    12, "How many DEFCON defenders should the squad carry?",
    f"The cheapest points in the game: a DEFCON monster (20+ DEFCON pts) averaged "
    f"<b>{_st['monster']['pts']} points at £{_st['monster']['price']:.1f}m</b> vs "
    f"{_st['fodder']['pts']} for ordinary cheap defenders at £{_st['fodder']['price']:.1f}m "
    f"· <b>~+{_st['monster']['pts'] - _st['fodder']['pts']} points per slot for "
    f"£0.3m</b>. Sweeping full five-defender mixes under one budget (usable points: "
    f"3 start weekly, the 4th half the time), value climbs with every monster and "
    f"flattens at <b>{_best['k']}</b>. Rule: <b>carry {min(_best['k'], 4)} DEFCON "
    f"defenders</b> · the fifth adds nothing you can field, and one premium "
    f"attacking defender keeps the ceiling. Watch the curated role map "
    f"(<code>assets/defender_roles_2025_26.json</code>) · stat filters mislabel "
    f"set-piece CBs, and roles must be re-checked for 2026-27.",
    "#00FF87")
opt = charts.bar_option(
    x=[m["mix"] for m in dm["mixes"]],
    y=[m["usable_pts"] for m in dm["mixes"]],
    colors=["#00FF87" if m["k"] == _best["k"] else "rgba(4,245,255,0.55)"
            for m in dm["mixes"]],
    horizontal=True)
for item, m in zip(opt["series"][0]["data"], dm["mixes"]):
    item["tooltip"] = {"formatter": f"<b>{m['mix']}</b><br/>{m['usable_pts']} usable "
                                    f"pts · £{m['spend']:.1f}m of the £26m defender budget"}
opt["title"] = {"text": "Five-defender mixes · usable points under one budget",
                "textStyle": CHART_TITLE}
opt["grid"]["top"] = 36
opt["grid"]["left"] = 200
charts.render(opt, height="300px", key="pb_defcon_mix")

st.markdown(
    f'<div style="font-size:12px;color:{MUTED};margin-top:6px;">📌 Coming when the '
    f'2026-27 game launches: bookmaker goal + clean-sheet odds folded into these '
    f'doctrines for the GW1 draft. The 2025-26 archive behind every number here is '
    f'preserved in git · it does not depend on any external source surviving.</div>',
    unsafe_allow_html=True)

st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:38px 0 12px;">'
    f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;'
    f'color:{MUTED};white-space:nowrap;">The 2026-27 plan, distilled</div>'
    f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>',
    unsafe_allow_html=True)
rules = [
    ("🧱", "Structure", "Budget defence (4.5–5.5 starters from top defensive units), "
     "premium midfield, one elite striker. Target 3-5-2 / 4-5-1 most weeks."),
    ("🛡️", "Defenders", "Set-piece CBs from top/mid defences first (DEFCON floor + "
     "CS + goal threat); full-backs only with real assist upside on elite teams."),
    ("⏱️", "Transfers", "Minutes security (ρ=0.98 · the master variable) → form → xGI → "
     "fixtures. Judge fixture runs of 5–6. One good fixture is never a reason."),
    ("💰", "Value", "Move early onto risers, expect ~£1m realised growth, not £0.5m/month. "
     "Half of every rise is yours."),
    ("🃏", "Hits", "Default zero · perfect foresight nets only +2.4 pts per hit, so real "
     "forecasts make them negative-EV. Take one only when forced, to set up a chip "
     "(47% of perfect play's hits were chip-adjacent), or for a projected 5–6 GW gain ≥ 8 pts."),
]
st.markdown(
    '<div class="fplh-stagger" style="display:grid;'
    'grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;">'
    + "".join(
        f'<div class="fplh-card-hover" style="{CARD}border-top:3px solid #00FF87;">'
        f'<div style="font-size:20px;">{emoji}</div>'
        f'<div style="font-size:13px;font-weight:800;color:#fff;margin:4px 0;">{title}</div>'
        f'<div style="font-size:12px;color:rgba(255,255,255,0.6);line-height:1.55;">{body}</div></div>'
        for emoji, title, body in rules)
    + "</div>",
    unsafe_allow_html=True)
