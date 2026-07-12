"""
The Playbook · how to actually play FPL, answered from 10 seasons of data.

Every section is a question Eoin asked, answered empirically from the
archive (analytics/playbook.py), distilled into a rule for 2026-27.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components.animations import inject_global_animations
from config import CACHE_DIR, LAST_COMPLETE_SEASON

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:16px 20px;")

PLOT_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                   font_color="#e2e2e2",
                   xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                   yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                   margin=dict(l=10, r=10, t=20, b=10))


@st.cache_data(ttl=24 * 3600, show_spinner="Crunching 10 seasons of data…")
def _answers():
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
    fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h",
                           marker_color="#00FF87", opacity=0.85))
    fig.update_layout(height=300, title=dict(text="Weeks each formation was the best XI",
                                             font=dict(size=12)), **PLOT_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
with c2:
    if "perfect_season_formations" in f:
        pcounts = pd.Series(f["perfect_season_formations"]).sort_values(ascending=True)
        fig = go.Figure(go.Bar(x=pcounts.values, y=pcounts.index, orientation="h",
                               marker_color="#FFD700", opacity=0.85))
        fig.update_layout(height=300, title=dict(text="Formations the Perfect Season actually fielded",
                                                 font=dict(size=12)), **PLOT_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

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
fig = px.bar(share, x="season", y="pct_of_points", color="position", barmode="group",
             color_discrete_map=POS_COLORS,
             labels={"pct_of_points": "% of all points", "season": ""})
fig.update_layout(height=320, legend=dict(orientation="h", yanchor="bottom", y=1.02),
                  **PLOT_LAYOUT)
st.plotly_chart(fig, use_container_width=True)

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
    fig = px.bar(p, x="position", y="med_pts", color="pen_taker", barmode="group",
                 color_discrete_map={"Taker": "#FFD700", "Not taker": "#555a66"},
                 labels={"med_pts": "Median season pts", "position": "", "pen_taker": ""})
    fig.update_layout(height=300, legend=dict(orientation="h", yanchor="bottom", y=1.02),
                      **PLOT_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

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
fig = go.Figure(go.Bar(x=sig["signal"], y=sig["next_gw"],
                       marker_color=["#00FF87", "#04f5ff", "#FF8C42"]))
fig.update_layout(height=300, yaxis_title="Spearman ρ vs next-GW points", **PLOT_LAYOUT)
st.plotly_chart(fig, use_container_width=True)

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
fig = go.Figure(go.Scatter(x=hz["horizon"], y=hz["spearman"], mode="lines+markers",
                           line=dict(color="#04f5ff", width=3)))
fig.update_layout(height=280, xaxis_title="Fixture horizon (GWs ahead)",
                  yaxis_title="Ease → points correlation", **PLOT_LAYOUT)
st.plotly_chart(fig, use_container_width=True)

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
fig = go.Figure(go.Scatter(x=traj["gw"], y=traj["growth"], mode="lines",
                           fill="tozeroy", line=dict(color="#FF8C42", width=2)))
fig.update_layout(height=280, xaxis_title="Gameweek",
                  yaxis_title="GW1 template value change (£m)", **PLOT_LAYOUT)
st.plotly_chart(fig, use_container_width=True)
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
fig = go.Figure()
fig.add_trace(go.Bar(x=ov["band"].astype(str), y=ov["pts_per_match"],
                     name="Points per match", marker_color="#00FF87", opacity=0.9))
fig.add_trace(go.Scatter(x=ov["band"].astype(str), y=ov["pts_per_90"],
                         name="Points per 90 (efficiency)", mode="lines+markers",
                         line=dict(color="#FF8C42", width=3, dash="dot")))
fig.update_layout(height=320,
                  yaxis=dict(title="Points", gridcolor="rgba(255,255,255,0.06)"),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02),
                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                  font_color="#e2e2e2",
                  xaxis=dict(title="Average minutes per appearance (regulars, 20+ games)",
                             gridcolor="rgba(255,255,255,0.06)"),
                  margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(fig, use_container_width=True)

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
