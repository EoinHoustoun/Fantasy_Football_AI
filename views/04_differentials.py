"""
Differentials Spotter · redesigned.

Uses the tagged, multi-signal differentials engine:
  diff_score = ceiling × momentum × minutes × rank_upside

Each player is labelled with qualitative tags (Template Breaker, Hot Run,
Nailed-On Starter, Set-Piece Threat, Underlying Burst, Dream Fixtures, Rising)
so you can see *why* a player is a good differential, not just the number.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from components.animations import inject_global_animations
from components.team_identity import shirt_html, team_color

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
FDR_COLORS = {1: "#00FF87", 2: "#00FF87", 3: "#FFD60A", 4: "#FF8C42", 5: "#FF4B4B"}
SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"

TAG_COLOR = {
    "Template Breaker":   "#FFD700",
    "Hot Run":            "#FF4B4B",
    "Nailed-On Starter":  "#00FF87",
    "Set-Piece Threat":   "#f5c518",
    "Underlying Burst":   "#04f5ff",
    "Dream Fixtures":     "#a3e635",
    "Rising":             "#f472b6",
}


def _shirt(team_code: int, is_gkp: bool) -> str:
    suffix = "_1" if is_gkp else ""
    return f"{SHIRT_BASE}/shirt_{team_code}{suffix}-66.png"


def _safe(val, default=0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return float(default)
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def _fdr_color(fdr: float) -> str:
    return FDR_COLORS.get(int(round(fdr)), "#FFD60A")


def _position_chip(pos: str) -> str:
    color = POS_COLORS.get(pos, "#888")
    return (
        f'<span style="background:{color};color:#000;border-radius:4px;'
        f'padding:2px 8px;font-weight:800;font-size:11px;letter-spacing:0.05em;">'
        f'{pos}</span>'
    )


def _tag_pills(tags) -> str:
    if not isinstance(tags, list) or not tags:
        return ''
    pills = []
    for t in tags:
        color = TAG_COLOR.get(t, "#888")
        pills.append(
            f'<span style="background:{color}22;border:1px solid {color}66;'
            f'color:{color};border-radius:4px;padding:2px 7px;font-size:10px;'
            f'font-weight:700;margin-right:4px;display:inline-block;">{t}</span>'
        )
    return "".join(pills)


def _fixture_pills(fixtures, n: int = 5) -> str:
    if not isinstance(fixtures, list) or not fixtures:
        return '<span style="color:rgba(255,255,255,0.35);font-size:11px;">-</span>'
    pills = []
    for f in fixtures[:n]:
        opp = str(f.get("opp_short") or f.get("opponent", "?"))[:3].upper()
        home = bool(f.get("home", False))
        fdr = _safe(f.get("fdr"), 3.0)
        color = _fdr_color(fdr)
        pills.append(
            f'<span style="background:{color};color:#000;border-radius:4px;'
            f'padding:2px 6px;font-size:10px;font-weight:800;'
            f'margin-right:4px;display:inline-block;">'
            f'{opp}{"·H" if home else "·A"}</span>'
        )
    return "".join(pills)


# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(
    """
<div style="padding:18px 0 8px;font-family:'Inter',sans-serif;">
  <div style="font-size:30px;font-weight:900;color:#fff;letter-spacing:-0.5px;">
    🎯 Differentials Spotter
  </div>
  <div style="font-size:14px;color:rgba(255,255,255,0.55);margin-top:4px;line-height:1.5;">
    Low-owned picks with real upside · scored on ceiling × momentum × minutes × rank upside.
    <span style="color:rgba(255,255,255,0.4);">Tags explain <em>why</em> each pick is interesting.</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ── Data ──────────────────────────────────────────────────────────────────────
def get_players():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


players_df = get_players()

# Attach team short codes to fixtures for pill labels
from data.fetchers.fpl_api import fetch_bootstrap
_bs = fetch_bootstrap()
_short_map = {t["name"]: t["short_name"] for t in _bs["teams"]}
if "upcoming_fixtures" in players_df.columns:
    def _attach_short(fixtures):
        if not isinstance(fixtures, list):
            return fixtures
        return [
            {**f, "opp_short": _short_map.get(f.get("opponent", ""), str(f.get("opponent", ""))[:3].upper())}
            for f in fixtures
        ]
    players_df = players_df.copy()
    players_df["upcoming_fixtures"] = players_df["upcoming_fixtures"].apply(_attach_short)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filters")
    max_own = st.slider("Max ownership (%)", 1.0, 20.0, 10.0, step=0.5)
    position = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    max_price = st.slider("Max price (£m)", 4.0, 15.0, 12.0, step=0.5)
    min_mins = st.slider(
        "Minimum minutes played", 90, 2000, 300, step=90,
        help="Filters out cameos · only players who actually feature for their team.",
    )
    top_n = st.slider("Show top N", 6, 30, 18)


# ── Run engine ────────────────────────────────────────────────────────────────
from analytics.differentials import get_differentials

pos_filter = None if position == "All" else position
with st.spinner("Finding differentials..."):
    diffs = get_differentials(
        players_df,
        max_ownership=max_own,
        position=pos_filter,
        max_price=max_price,
        min_minutes=min_mins,
        top_n=top_n,
    )

if diffs.empty:
    st.warning("No differentials found with these filters. Try relaxing the ownership threshold.")
    st.stop()


# ── Summary strip ─────────────────────────────────────────────────────────────
top = diffs.iloc[0]
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div style="background:rgba(255,215,0,0.06);
        border:1px solid rgba(255,215,0,0.35);border-radius:12px;padding:14px 18px;">
        <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">TOP DIFFERENTIAL</div>
        <div style="font-size:18px;font-weight:800;color:#fff;">{top['web_name']}</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.55);">{_safe(top['ownership']):.1f}% owned</div>
        </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div style="background:rgba(255,255,255,0.03);
        border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 18px;">
        <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">TOP SCORE</div>
        <div style="font-size:28px;font-weight:900;color:#00FF87;">{_safe(top['differential_score']):.2f}</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.45);">out of 10</div>
        </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div style="background:rgba(255,255,255,0.03);
        border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 18px;">
        <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">PLAYERS FOUND</div>
        <div style="font-size:28px;font-weight:900;color:#fff;">{len(diffs)}</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.45);">matching filters</div>
        </div>""", unsafe_allow_html=True)
with c4:
    avg_own = float(diffs["ownership"].mean()) if "ownership" in diffs.columns else 0
    st.markdown(f"""<div style="background:rgba(255,255,255,0.03);
        border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 18px;">
        <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">AVG OWNERSHIP</div>
        <div style="font-size:28px;font-weight:900;color:#04f5ff;">{avg_own:.1f}%</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.45);">template gap</div>
        </div>""", unsafe_allow_html=True)


# ── Card grid ─────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin:24px 0 12px;font-size:20px;font-weight:800;color:#fff;">'
    'Ranked Differentials</div>',
    unsafe_allow_html=True,
)

cards = []
for _, p in diffs.iterrows():
    pos = str(p.get("position", ""))
    code = int(p.get("team_code", 1) or 1)
    tcol = team_color(p.get("team_short"))
    name = str(p.get("web_name", "?"))
    team = str(p.get("team", ""))
    price = _safe(p.get("price"))
    own = _safe(p.get("ownership"))
    form = _safe(p.get("form"))
    total = _safe(p.get("total_points"))
    score = _safe(p.get("differential_score"))
    ceiling = _safe(p.get("haul_ceiling"))
    momentum = _safe(p.get("momentum"))
    mins_f = _safe(p.get("minutes_factor"))
    fdr6 = _safe(p.get("avg_fdr_next_6"), 3.0)
    fix = _fixture_pills(p.get("upcoming_fixtures"), n=5)
    tags = _tag_pills(p.get("tags"))

    bar_pct = max(0.0, min(1.0, score / 10.0)) * 100

    cards.append(f"""
<div class="fplh-card-hover" style="
    background:rgba(22,26,34,0.85);
    border:1px solid rgba(255,255,255,0.08);
    border-left:3px solid {tcol};
    border-radius:12px;padding:16px;
    font-family:'Inter',sans-serif;
">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
    <div style="flex-shrink:0;filter:drop-shadow(0 3px 5px rgba(0,0,0,0.4));">{shirt_html(code, pos == "GKP", width=50)}</div>
    <div style="flex:1;min-width:0;">
      <div style="font-size:15px;font-weight:800;color:#fff;white-space:nowrap;
                  overflow:hidden;text-overflow:ellipsis;">{name}</div>
      <div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:2px;">
        {_position_chip(pos)} <span style="margin-left:6px;">{team}</span>
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:16px;font-weight:800;color:#fff;">£{price:.2f}m</div>
      <div style="font-size:10px;color:rgba(255,255,255,0.4);">{own:.1f}% own</div>
    </div>
  </div>

  <div style="margin-bottom:10px;min-height:22px;">{tags}</div>

  <div style="display:flex;gap:12px;margin-bottom:10px;">
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#00FF87;">{score:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">DIFF SCORE</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#fff;">{form:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">FORM</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#fff;">{total:.0f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">SEASON</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:{_fdr_color(fdr6)};">{fdr6:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">FDR6</div></div>
  </div>

  <div style="background:rgba(255,255,255,0.05);border-radius:4px;height:4px;overflow:hidden;margin-bottom:10px;">
    <div style="background:linear-gradient(90deg,#FFD700,#00FF87);height:100%;width:{bar_pct:.0f}%;"></div>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
    <div>{fix}</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.35);white-space:nowrap;">
      mins <span style="color:#fff;font-weight:700;">{int(mins_f*90)}'</span> ·
      ceil <span style="color:#fff;font-weight:700;">{ceiling:.2f}</span>
    </div>
  </div>
</div>
""")

st.markdown(
    '<div class="fplh-stagger" style="display:grid;'
    'grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;">'
    + "".join(cards) + "</div>",
    unsafe_allow_html=True,
)


# ── Ownership vs Form scatter ─────────────────────────────────────────────────
st.markdown(
    '<div style="margin:28px 0 10px;font-size:18px;font-weight:800;color:#fff;">'
    'Ownership vs Form</div>'
    '<div style="font-size:12px;color:rgba(255,255,255,0.5);margin-bottom:14px;">'
    'Bottom-left + large bubble = ideal differential. '
    '</div>',
    unsafe_allow_html=True,
)

if "ownership" in diffs.columns and "form" in diffs.columns:
    fig = px.scatter(
        diffs,
        x="ownership", y="form",
        size="differential_score",
        color="position" if "position" in diffs.columns else None,
        hover_name="web_name",
        hover_data=["price", "total_points"],
        labels={"ownership": "Ownership (%)", "form": "Form"},
        color_discrete_map=POS_COLORS,
    )
    top_row = diffs.iloc[0]
    fig.add_annotation(
        x=top_row["ownership"], y=top_row["form"],
        text=f"  {top_row['web_name']}",
        showarrow=False,
        font=dict(color="#FFD700", size=12),
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e2e2",
        height=480,
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)
