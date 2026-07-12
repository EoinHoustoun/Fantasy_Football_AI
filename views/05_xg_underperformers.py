"""
xG Underperformers Tracker · redesigned.

Finds players who have accumulated significant xG but scored fewer goals.
Statistically, these players are "due" · finishing luck regresses to the mean
and they tend to haul soon after.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components.animations import inject_global_animations
from components.team_identity import shirt_html, team_color

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

# ── Design tokens (kept local for now · will move to shared module later) ─────
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
FDR_COLORS = {1: "#00FF87", 2: "#00FF87", 3: "#FFD60A", 4: "#FF8C42", 5: "#FF4B4B"}
SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"


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


# ── Page header ────────────────────────────────────────────────────────────────
st.markdown(
    """
<div style="padding:18px 0 8px;font-family:'Inter',sans-serif;">
  <div style="font-size:30px;font-weight:900;color:#fff;letter-spacing:-0.5px;">
    📈 xG Underperformers
  </div>
  <div style="font-size:14px;color:rgba(255,255,255,0.55);margin-top:4px;line-height:1.5;">
    Players creating chances faster than they're finishing · statistically due a goal.
    <span style="color:rgba(255,255,255,0.4);">xG gap = xG accumulated − actual goals.</span>
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

# Attach team short codes to upcoming_fixtures for cleaner labels
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


has_xg = "xg" in players_df.columns and players_df["xg"].notna().any()
if not has_xg:
    st.error(
        "Understat xG data is not available. The app tried to fetch the current EPL "
        "season but got no data back · check your internet or try the Refresh button."
    )
    st.stop()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filters")
    positions = st.multiselect(
        "Positions", ["DEF", "MID", "FWD"], default=["MID", "FWD"],
        help="GKP excluded · they don't accumulate meaningful xG.",
    )
    min_xg = st.slider("Min season xG", 0.5, 10.0, 2.0, step=0.5,
                       help="Filters out players with negligible chances.")
    min_gap = st.slider("Min xG gap (goals owed)", 0.25, 5.0, 1.5, step=0.25,
                        help="How many goals below xG a player has scored.")
    max_price = st.slider("Max price (£m)", 4.0, 15.0, 13.0, step=0.5)
    show_overperformers = st.checkbox(
        "Also show overperformers (potential sells)", value=False,
        help="Players scoring faster than their xG suggests · may regress.",
    )


# ── Get underperformers ───────────────────────────────────────────────────────
from analytics.xg_divergence import get_xg_underperformers, get_xg_overperformers

underperformers = get_xg_underperformers(
    players_df, min_xg=min_xg, min_gap=min_gap, positions=positions,
)
if not underperformers.empty and "price" in underperformers.columns:
    underperformers = underperformers[underperformers["price"] <= max_price].reset_index(drop=True)

# Merge back the columns we need for cards (team_code, fixtures)
enrich_cols = [c for c in ("fpl_id", "team_code", "upcoming_fixtures", "avg_fdr_next_6") if c in players_df.columns]
if enrich_cols and not underperformers.empty:
    left = underperformers.merge(
        players_df[["web_name"] + [c for c in enrich_cols if c != "fpl_id"]],
        on="web_name", how="left", suffixes=("", "_x"),
    )
    underperformers = left


# ── Summary strip ─────────────────────────────────────────────────────────────
if not underperformers.empty:
    top = underperformers.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div style="background:rgba(0,255,135,0.08);
            border:1px solid rgba(0,255,135,0.3);border-radius:12px;padding:14px 18px;">
            <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">FLAGGED</div>
            <div style="font-size:28px;font-weight:900;color:#00FF87;">{len(underperformers)}</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.45);">players due a goal</div>
            </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div style="background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 18px;">
            <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">TOP CANDIDATE</div>
            <div style="font-size:18px;font-weight:800;color:#fff;">{top['web_name']}</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.55);">+{_safe(top.get('xg_gap')):.2f} xG owed</div>
            </div>""", unsafe_allow_html=True)
    with c3:
        total_gap = float(underperformers["xg_gap"].sum()) if "xg_gap" in underperformers.columns else 0
        st.markdown(f"""<div style="background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 18px;">
            <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">TOTAL OWED</div>
            <div style="font-size:28px;font-weight:900;color:#FFD700;">{total_gap:.1f}</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.45);">goals across list</div>
            </div>""", unsafe_allow_html=True)
    with c4:
        avg_own = float(underperformers["ownership"].mean()) if "ownership" in underperformers.columns else 0
        st.markdown(f"""<div style="background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 18px;">
            <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">AVG OWNERSHIP</div>
            <div style="font-size:28px;font-weight:900;color:#04f5ff;">{avg_own:.1f}%</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.45);">differential potential</div>
            </div>""", unsafe_allow_html=True)
else:
    st.info("No players match your filters. Try lowering the xG gap threshold or widening positions.")


# ── Card grid ─────────────────────────────────────────────────────────────────
if not underperformers.empty:
    st.markdown(
        '<div style="margin:24px 0 12px;font-size:20px;font-weight:800;color:#fff;">'
        '🎯 Players Due a Goal</div>',
        unsafe_allow_html=True,
    )

    cards = []
    for _, p in underperformers.iterrows():
        pos = str(p.get("position", ""))
        code = int(p.get("team_code", 1) or 1)
        tcol = team_color(p.get("team_short"))
        name = str(p.get("web_name", "?"))
        team = str(p.get("team", ""))
        price = _safe(p.get("price"))
        own = _safe(p.get("ownership"))
        form = _safe(p.get("form"))
        xg = _safe(p.get("xg"))
        goals = _safe(p.get("goals_scored"))
        gap = _safe(p.get("xg_gap"))
        haul = _safe(p.get("haul_potential"))
        fdr6 = _safe(p.get("avg_fdr_next_6"), 3.0)
        fix = _fixture_pills(p.get("upcoming_fixtures"), n=5)

        # Gap bar · how "due" the player is (scaled to 4 goals owed as max)
        bar_pct = max(0.0, min(1.0, gap / 4.0)) * 100

        cards.append(f"""
<div class="fplh-card-hover" style="
    background:rgba(22,26,34,0.85);
    border:1px solid rgba(255,255,255,0.08);
    border-left:3px solid {tcol};
    border-radius:12px;padding:16px;
    font-family:'Inter',sans-serif;
">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
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

  <div style="display:flex;gap:12px;margin-bottom:10px;">
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#fff;">{xg:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">SEASON xG</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#fff;">{goals:.0f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">GOALS</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#00FF87;">+{gap:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">OWED</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:{_fdr_color(fdr6)};">{fdr6:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">FDR6</div></div>
  </div>

  <div style="background:rgba(255,255,255,0.05);border-radius:4px;height:4px;overflow:hidden;margin-bottom:10px;">
    <div style="background:linear-gradient(90deg,#FFD700,#00FF87);height:100%;width:{bar_pct:.0f}%;"></div>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;">
    <div>{fix}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.4);">
      Form <span style="color:#fff;font-weight:700;">{form:.1f}</span>
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

# ── Scatter chart ─────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="margin:28px 0 10px;font-size:18px;font-weight:800;color:#fff;">'
        '📊 xG vs Actual Goals</div>'
        '<div style="font-size:12px;color:rgba(255,255,255,0.5);margin-bottom:14px;">'
        'Players above the line are underperforming (haul candidates). Below the line = overperforming.'
        '</div>',
        unsafe_allow_html=True,
    )

    chart_df = players_df[
        (players_df["position"].isin(positions)) &
        (players_df["xg"].notna()) &
        (players_df["xg"] >= 0.5)
    ].copy()

    if not chart_df.empty:
        underperformer_names = set(underperformers["web_name"].tolist())
        chart_df["category"] = chart_df["web_name"].apply(
            lambda x: "Underperforming (buy?)" if x in underperformer_names else "On track"
        )
        fig = px.scatter(
            chart_df, x="goals_scored", y="xg",
            color="category",
            hover_name="web_name",
            hover_data=["team", "price", "ownership", "form"],
            labels={"goals_scored": "Actual Goals", "xg": "Expected Goals (xG)"},
            color_discrete_map={
                "Underperforming (buy?)": "#00FF87",
                "On track": "#555a66",
            },
            size="xg", size_max=22,
        )
        max_val = max(chart_df["xg"].max(), chart_df["goals_scored"].max(), 1)
        fig.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.4)", dash="dash", width=1.5),
            name="xG = Goals", showlegend=True,
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e2e2",
            height=500,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)


# ── Finishing luck: both tails, and does it even out? ─────────────────────────
st.markdown(
    '<div style="margin:30px 0 10px;font-size:20px;font-weight:800;color:#fff;">'
    '🎲 Finishing Luck · Both Tails</div>'
    '<div style="font-size:12px;color:rgba(255,255,255,0.5);margin-bottom:14px;">'
    'Every player who took the pitch this season. Green = scoring more than their '
    'chances deserve, red = less. The histogram answers "does it even out": most '
    'players cluster near zero · the tails are luck plus elite/poor finishing.</div>',
    unsafe_allow_html=True,
)

luck_df = players_df[
    players_df["xg"].notna() & (players_df["minutes"] > 0)
].copy()
if not luck_df.empty:
    luck_df["xg_diff"] = luck_df["goals_scored"].fillna(0) - luck_df["xg"]

    fig_luck = px.scatter(
        luck_df, x="xg", y="goals_scored",
        color="xg_diff", color_continuous_scale=["#FF4B4B", "#555a66", "#00FF87"],
        color_continuous_midpoint=0,
        hover_name="web_name",
        hover_data={"team": True, "price": ":.2f", "xg": ":.2f",
                    "goals_scored": ":.0f", "xg_diff": ":+.2f"},
        labels={"xg": "Expected goals (xG)", "goals_scored": "Actual goals",
                "xg_diff": "Goals − xG"},
        size=luck_df["xg_diff"].abs() + 0.6, size_max=20, opacity=0.85,
    )
    max_ax = float(max(luck_df["xg"].max(), luck_df["goals_scored"].max(), 1)) + 1
    fig_luck.add_trace(go.Scatter(
        x=[0, max_ax], y=[0, max_ax], mode="lines",
        line=dict(color="rgba(255,255,255,0.4)", dash="dash", width=1.5),
        name="Goals = xG", showlegend=False, hoverinfo="skip"))
    # label the extremes in both directions
    for _, r in pd.concat([luck_df.nlargest(5, "xg_diff"),
                           luck_df.nsmallest(5, "xg_diff")]).iterrows():
        fig_luck.add_annotation(
            x=r["xg"], y=r["goals_scored"], text=str(r["web_name"]),
            showarrow=False, yshift=12,
            font=dict(size=10, color="#00FF87" if r["xg_diff"] > 0 else "#FF4B4B"))
    fig_luck.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e2e2", height=520,
        coloraxis_colorbar=dict(title="G − xG"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig_luck, use_container_width=True)

    col_h, col_s = st.columns([2, 1])
    with col_h:
        fig_hist = px.histogram(luck_df, x="xg_diff", nbins=40,
                                labels={"xg_diff": "Goals − xG"},
                                color_discrete_sequence=["#04f5ff"])
        fig_hist.add_vline(x=0, line=dict(color="rgba(255,255,255,0.5)", dash="dash"))
        mean_gap = float(luck_df["xg_diff"].mean())
        fig_hist.add_vline(x=mean_gap, line=dict(color="#FFD700", width=2))
        fig_hist.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e2e2", height=300, showlegend=False,
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(title="Players", gridcolor="rgba(255,255,255,0.06)"),
            margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig_hist, use_container_width=True)
    with col_s:
        within_1 = float((luck_df["xg_diff"].abs() <= 1.0).mean())
        st.markdown(
            f'<div style="background:rgba(22,26,34,0.85);border:1px solid '
            f'rgba(255,255,255,0.08);border-radius:12px;padding:16px 18px;margin-top:8px;">'
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;'
            f'color:rgba(255,255,255,0.5);text-transform:uppercase;">Does it even out?</div>'
            f'<div style="font-size:26px;font-weight:900;color:#00FF87;margin:4px 0;">'
            f'{within_1:.0%}</div>'
            f'<div style="font-size:12px;color:rgba(255,255,255,0.55);line-height:1.5;">'
            f'of players finish within ±1 goal of their xG. Mean gap '
            f'<span style="color:#FFD700;font-weight:800;">{mean_gap:+.2f}</span> · '
            f'mostly, yes. Bet on the chances, not the streak.</div></div>',
            unsafe_allow_html=True)

# ── Overperformers section ────────────────────────────────────────────────────
if show_overperformers:
    st.markdown(
        '<div style="margin:28px 0 10px;font-size:20px;font-weight:800;color:#fff;">'
        '⚠️ Overperformers · Regression Risk</div>'
        '<div style="font-size:12px;color:rgba(255,255,255,0.5);margin-bottom:14px;">'
        'Scoring well above their xG · finishing luck may run out.'
        '</div>',
        unsafe_allow_html=True,
    )
    overperformers = get_xg_overperformers(players_df, positions=positions)
    if overperformers.empty:
        st.info("No significant overperformers found.")
    else:
        from components.player_table import render_player_table
        render_player_table(overperformers, height=300)
