"""
Captain Picker · GW recommendation for who to captain.

Shows:
  • Hero card for the #1 captain pick (with armband graphic)
  • Top 5 captain options from your squad with score breakdown
  • Top 5 differential captain options (low-ownership players with high ceiling)
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from typing import Optional, List, Dict, Any

from components.badges import render_badges
from components.team_identity import shirt_html, team_color

# set_page_config is owned by the app.py router (st.navigation)

SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def load_universe():
    from data.fetchers.fpl_api import fetch_bootstrap
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    players = build_player_universe(bootstrap=bs, understat_df=understat_df)
    return players, bs


@st.cache_data(ttl=1800, show_spinner=False)
def load_squad(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad_df


def get_next_gw(bootstrap: dict) -> int:
    for e in bootstrap["events"]:
        if e.get("is_next"):
            return e["id"]
    # fallback: current + 1
    for e in bootstrap["events"]:
        if e.get("is_current"):
            return e["id"] + 1
    return 1


def get_next_gw_fdr(bootstrap: dict, fixtures_raw: list, captain_gw: int) -> Dict[int, float]:
    """Return {team_id: fdr} for the captain GW specifically."""
    from data.fetchers.fpl_api import get_fixtures_df
    fixtures_df = get_fixtures_df(fixtures_raw, bootstrap)
    gw_fix = fixtures_df[fixtures_df["gameweek"] == captain_gw]
    fdr_map = {}
    for _, row in gw_fix.iterrows():
        fdr_map[int(row["home_team_id"])] = float(row["home_fdr"])
        fdr_map[int(row["away_team_id"])] = float(row["away_fdr"])
    return fdr_map


def score_captains(players_df: pd.DataFrame, fdr_map: Dict[int, float]) -> pd.DataFrame:
    """Compute a captain_score for each player."""
    df = players_df.copy()

    df["next_gw_fdr"] = df["team_id"].map(fdr_map).fillna(3.0)
    df["has_fixture"] = df["team_id"].map(lambda t: t in fdr_map)

    # Zero out players with no fixture (BGW)
    df.loc[~df["has_fixture"], "next_gw_fdr"] = 5.0

    # Components (all 0-1)
    def norm(s):
        mn, mx = s.min(), s.max()
        if mx == mn:
            return pd.Series(0.5, index=s.index)
        return (s - mn) / (mx - mn)

    df["c_form"]    = norm(df["form"].fillna(0).astype(float))
    df["c_fixture"] = norm(5.0 - df["next_gw_fdr"])          # low FDR = good
    df["c_xg"]      = norm(df["fpl_xgi_per90"].fillna(0).astype(float))

    # ── Minutes multiplier (not just a component · scales the whole score) ────
    # Use avg_minutes from DEFCON stats when available, else estimate from totals.
    if "avg_minutes" in df.columns and df["avg_minutes"].notna().any():
        avg_mins = df["avg_minutes"].fillna(45.0).clip(0, 90)
    else:
        gws_est = max(1, int(df["minutes"].max() / 90))
        avg_mins = (df["minutes"].fillna(0) / gws_est).clip(0, 90)

    df["c_minutes"]       = (avg_mins / 90.0).round(3)          # kept for display
    df["mins_multiplier"] = ((avg_mins / 90.0) ** 0.5).clip(lower=0.45, upper=1.0)

    # ── Set piece bonus (before multiplier · penalty taker gets captain boost) ─
    import numpy as np
    _nan = pd.Series(float("nan"), index=df.index)
    pen_order = pd.to_numeric(
        df["penalties_order"] if "penalties_order" in df.columns else _nan, errors="coerce"
    )
    df["c_setpiece"] = (
        pen_order.eq(1).fillna(False).astype(float) * 0.10 +
        pen_order.eq(2).fillna(False).astype(float) * 0.04
    )

    # DGW bonus
    dgw_mult = (
        df.get("has_dgw", pd.Series(False, index=df.index))
          .map({True: 1.20, False: 1.0})
          .fillna(1.0)
    )

    # Fixture-weighted captain score: fixture is the strongest influence,
    # followed by form, then xGI. Set-piece bonus stacks on top.
    base_score = (
        df["c_fixture"]  * 0.50 +
        df["c_form"]     * 0.30 +
        df["c_xg"]       * 0.20 +
        df["c_setpiece"]
    )
    df["captain_score"] = (base_score * df["mins_multiplier"] * dgw_mult).round(4)

    # Players with no fixture cannot be captained (blank GW)
    df.loc[~df["has_fixture"], "captain_score"] = 0.0

    return df


# ── HTML components ────────────────────────────────────────────────────────────

def _shirt_url(team_code: int, is_gkp: bool) -> str:
    suffix = "_1" if is_gkp else ""
    return f"{SHIRT_BASE}/shirt_{team_code}{suffix}-66.png"


def _hero_card(player: pd.Series, rank: int = 1) -> str:
    """Render the big captain armband hero card as HTML."""
    code    = int(player.get("team_code", 1) or 1)
    is_gkp  = str(player.get("position", "")) == "GKP"
    shirt   = _shirt_url(code, is_gkp)
    fallback = f"{SHIRT_BASE}/shirt_1-66.png"
    name    = str(player.get("web_name", "?"))
    team    = str(player.get("team", ""))
    pos     = str(player.get("position", ""))
    price   = float(player.get("price", 0) or 0)
    form    = float(player.get("form", 0) or 0)
    ppg     = float(player.get("points_per_game", 0) or 0)
    own     = float(player.get("ownership", 0) or 0)
    xgi     = float(player.get("fpl_xgi_per90", 0) or 0)
    fdr     = float(player.get("next_gw_fdr", 3.0) or 3.0)
    pos_col = POS_COLORS.get(pos, "#00FF87")

    has_dgw = bool(player.get("has_dgw", False))
    dgw_badge = (
        '<span style="background:#f5c518;color:#000;border-radius:4px;'
        'padding:2px 6px;font-size:11px;font-weight:900;margin-left:8px;">2x DGW</span>'
        if has_dgw else ""
    )

    badges_html = render_badges(player, size="sm")
    avg_mins    = float(player.get("avg_minutes", 0) or 0)
    mins_str    = f"{avg_mins:.0f}" if avg_mins > 0 else "-"

    fdr_color = {1: "#00FF87", 2: "#00FF87", 3: "#FFA500", 4: "#FF6B6B", 5: "#FF4B4B"}.get(int(fdr), "#FFA500")

    return f"""
    <div style="
        position:relative;
        background:linear-gradient(135deg, rgba(0,255,135,0.08) 0%, rgba(0,0,0,0.5) 100%);
        border:2px solid #FFD700;
        border-radius:16px;
        padding:28px 32px;
        display:flex;
        align-items:center;
        gap:32px;
        max-width:580px;
        box-shadow:0 0 40px rgba(255,215,0,0.15);
        font-family:sans-serif;
    ">
      <!-- Armband stripe -->
      <div style="
          position:absolute; left:-2px; top:50%; transform:translateY(-50%);
          width:22px; height:70px;
          background:linear-gradient(180deg,#FFD700,#FFA500);
          border-radius:6px 0 0 6px;
          display:flex; align-items:center; justify-content:center;
      ">
        <span style="
            color:#000; font-weight:900; font-size:12px;
            writing-mode:vertical-rl; transform:rotate(180deg); letter-spacing:1px;
        ">C</span>
      </div>

      <!-- Shirt -->
      <div style="text-align:center; flex-shrink:0; padding-left:12px;">
        {shirt_html(code, is_gkp, width=80)}
      </div>

      <!-- Info -->
      <div>
        <div style="font-size:26px; font-weight:900; color:#fff; margin-bottom:4px;">
          {name}{dgw_badge}
        </div>
        <div style="margin-bottom:8px;">{badges_html}</div>
        <div style="color:rgba(255,255,255,0.55); font-size:13px; margin-bottom:14px;">
          <span style="
              background:{pos_col}; color:#000; border-radius:3px;
              padding:1px 7px; font-weight:700; font-size:11px; margin-right:6px;
          ">{pos}</span>
          {team} &nbsp;·&nbsp; £{price:.1f}m &nbsp;·&nbsp; {own:.1f}% owned
        </div>
        <div style="display:flex; gap:24px;">
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:#00FF87;">{form:.1f}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.45);">Form</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:#00FF87;">{ppg:.1f}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.45);">PPG</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:{fdr_color};">{fdr:.0f}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.45);">Next FDR</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:#04f5ff;">{xgi:.2f}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.45);">xGI/90</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:rgba(255,255,255,0.7);">{mins_str}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.45);">Avg Mins</div>
          </div>
        </div>
      </div>
    </div>
    """


def _mini_card(player: pd.Series, rank: int) -> str:
    code    = int(player.get("team_code", 1) or 1)
    is_gkp  = str(player.get("position", "")) == "GKP"
    shirt   = _shirt_url(code, is_gkp)
    fallback = f"{SHIRT_BASE}/shirt_1-66.png"
    name    = str(player.get("web_name", "?"))
    team    = str(player.get("team", ""))
    form    = float(player.get("form", 0) or 0)
    ppg     = float(player.get("points_per_game", 0) or 0)
    fdr     = float(player.get("next_gw_fdr", 3.0) or 3.0)
    score   = float(player.get("captain_score", 0) or 0)
    own     = float(player.get("ownership", 0) or 0)
    pos     = str(player.get("position", ""))
    pos_col = POS_COLORS.get(pos, "#888")
    tcol    = team_color(player.get("team_short"))
    fdr_color = {1: "#00FF87", 2: "#00FF87", 3: "#FFA500", 4: "#FF6B6B", 5: "#FF4B4B"}.get(int(fdr), "#FFA500")
    border_col = "#FFD700" if rank == 1 else "#silver" if rank == 2 else "rgba(255,255,255,0.15)"
    rank_labels = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4th", 5: "5th"}

    has_dgw = bool(player.get("has_dgw", False))
    dgw_tag = '<span style="background:#f5c518;color:#000;border-radius:3px;padding:1px 5px;font-size:10px;font-weight:900;margin-left:4px;">DGW</span>' if has_dgw else ""
    badges_html = render_badges(player, size="sm")

    return f"""
    <div style="
        background:rgba(255,255,255,0.04);
        border:1px solid {border_col};
        border-left:3px solid {tcol};
        border-radius:12px;
        padding:14px 16px;
        display:flex;
        align-items:center;
        gap:14px;
        font-family:sans-serif;
        margin-bottom:8px;
    ">
      <div style="font-size:18px; width:28px; text-align:center; flex-shrink:0;">{rank_labels.get(rank, str(rank))}</div>
      {shirt_html(code, is_gkp, width=42)}
      <div style="flex:1; min-width:0;">
        <div style="font-size:15px; font-weight:800; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          {name}{dgw_tag}
        </div>
        <div style="font-size:11px; color:rgba(255,255,255,0.45); margin-bottom:3px;">
          <span style="background:{pos_col};color:#000;border-radius:2px;padding:0 4px;font-weight:700;font-size:10px;margin-right:4px;">{pos}</span>
          {team} · {own:.1f}% owned
        </div>
        <div>{badges_html}</div>
      </div>
      <div style="display:flex; gap:16px; flex-shrink:0; text-align:center;">
        <div>
          <div style="font-size:16px; font-weight:800; color:#00FF87;">{form:.1f}</div>
          <div style="font-size:10px; color:rgba(255,255,255,0.4);">Form</div>
        </div>
        <div>
          <div style="font-size:16px; font-weight:800; color:#00FF87;">{ppg:.1f}</div>
          <div style="font-size:10px; color:rgba(255,255,255,0.4);">PPG</div>
        </div>
        <div>
          <div style="font-size:16px; font-weight:800; color:{fdr_color};">{fdr:.0f}</div>
          <div style="font-size:10px; color:rgba(255,255,255,0.4);">FDR</div>
        </div>
      </div>
      <div style="text-align:right; flex-shrink:0;">
        <div style="font-size:14px; font-weight:800; color:#FFD700;">{score:.3f}</div>
        <div style="font-size:10px; color:rgba(255,255,255,0.4);">Score</div>
      </div>
    </div>
    """


def score_breakdown_chart(top5: pd.DataFrame, title: str) -> go.Figure:
    """Horizontal stacked bar showing captain score components for top 5."""
    components = ["c_form", "c_fixture", "c_xg", "c_setpiece"]
    labels     = ["Form", "Fixture", "xGI", "Set Pieces"]
    colors     = ["#00FF87", "#04f5ff", "#e90052", "#FFD700"]

    names = top5["web_name"].tolist()

    fig = go.Figure()
    for comp, label, color in zip(components, labels, colors):
        vals = top5[comp].fillna(0).tolist()
        fig.add_trace(go.Bar(
            name=label,
            y=names,
            x=vals,
            orientation="h",
            marker_color=color,
            hovertemplate=f"{label}: %{{x:.3f}}<extra></extra>",
        ))

    fig.update_layout(
        barmode="stack",
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=240,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=-0.15, x=0),
        xaxis=dict(showgrid=False, showticklabels=False),
        yaxis=dict(autorange="reversed"),
        font=dict(color="rgba(255,255,255,0.8)"),
    )
    return fig


# ── Main layout ────────────────────────────────────────────────────────────────

st.title("🏆 Captain Picker")

with st.spinner("Loading player data..."):
    players_df, bootstrap = load_universe()

from data.fetchers.fpl_api import get_current_gameweek, fetch_fixtures
current_gw  = get_current_gameweek(bootstrap)
captain_gw  = get_next_gw(bootstrap)
fixtures_raw = fetch_fixtures()
fdr_map     = get_next_gw_fdr(bootstrap, fixtures_raw, captain_gw)

st.caption(f"Captain picks for **Gameweek {captain_gw}**")

# ── Sidebar: team ID ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Your Squad")
    from config import FPL_TEAM_ID
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=default_id,
        step=1,
        help="Enter your team ID to see captain picks from your own squad.",
    )
    st.caption("Leave blank / enter any ID to see all options.")
    diff_threshold = st.slider(
        "Differential threshold (max ownership %)",
        min_value=5, max_value=30, value=15, step=5,
        help="Differential captains: players owned by fewer than this % of managers.",
    )

# Score all players for captaincy
scored = score_captains(players_df, fdr_map)
scored = scored[scored["status"] == "a"].copy()  # available only
scored = scored.sort_values("captain_score", ascending=False)

# ── Load squad if team_id provided ────────────────────────────────────────────
squad_df = None
if team_id and team_id > 0:
    try:
        with st.spinner(f"Loading squad {team_id}..."):
            squad_df = load_squad(team_id, current_gw)
    except Exception:
        st.sidebar.warning("Could not load squad. Showing global picks only.")

# ── Section 1: Your Squad Captain Pick ────────────────────────────────────────
if squad_df is not None:
    owned_ids = set(squad_df["fpl_id"].tolist())
    squad_scored = scored[scored["fpl_id"].isin(owned_ids)].head(5)

    # Merge team_code onto squad_scored for shirts
    if "team_code" not in squad_scored.columns:
        tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
        squad_scored = squad_scored.merge(tc, on="fpl_id", how="left")

    st.markdown(f"### Your Captain · GW{captain_gw}")

    if not squad_scored.empty:
        top = squad_scored.iloc[0]
        col_hero, col_chart = st.columns([1, 1])

        with col_hero:
            st.markdown(_hero_card(top, rank=1), unsafe_allow_html=True)

            # Reasoning
            fdr_v = float(top.get("next_gw_fdr", 3.0))
            reasons = []
            if float(top.get("form", 0)) >= 7:
                reasons.append(f"exceptional form ({float(top['form']):.1f} pts/game)")
            elif float(top.get("form", 0)) >= 5:
                reasons.append(f"strong form ({float(top['form']):.1f} pts/game)")
            if fdr_v <= 2:
                reasons.append(f"dream fixture (FDR {fdr_v:.0f}/5)")
            elif fdr_v <= 3:
                reasons.append(f"good fixture (FDR {fdr_v:.0f}/5)")
            if bool(top.get("has_dgw", False)):
                reasons.append("Double Gameweek · 2 chances to score")
            xgi = float(top.get("fpl_xgi_per90", 0) or 0)
            if xgi >= 0.6:
                reasons.append(f"elite xGI ({xgi:.2f}/90 · haul threat)")
            if not reasons:
                reasons.append("best composite score across form, fixture & xG")

            st.markdown(
                f"<div style='margin-top:14px;padding:12px;background:rgba(0,255,135,0.07);"
                f"border-left:3px solid #00FF87;border-radius:6px;font-size:13px;color:rgba(255,255,255,0.85);'>"
                f"{'<br>• '.join([''] + reasons)}</div>",
                unsafe_allow_html=True,
            )

        with col_chart:
            if len(squad_scored) > 1:
                fig = score_breakdown_chart(squad_scored, "Captain Score Breakdown · Your Squad")
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Top 5 Captain Options (Your Squad)")
        cards_html = "".join(
            _mini_card(squad_scored.iloc[i], i + 1)
            for i in range(len(squad_scored))
        )
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")

# ── Section 2: Differential Captains ─────────────────────────────────────────
st.markdown(f"### Differential Captains · GW{captain_gw}")
st.caption(f"High-ceiling players owned by fewer than {diff_threshold}% · go against the template.")

diffs = scored[scored["ownership"] <= diff_threshold].copy()

# Exclude owned players from differential section
if squad_df is not None:
    owned_names = set(squad_df["web_name"].tolist())
    diffs = diffs[~diffs["web_name"].isin(owned_names)]

diffs = diffs.head(5)

if not diffs.empty:
    # Merge team_code
    if "team_code" not in diffs.columns:
        tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
        diffs = diffs.merge(tc, on="fpl_id", how="left")

    col_d1, col_d2 = st.columns([1, 1])
    with col_d1:
        top_diff = diffs.iloc[0]
        st.markdown(_hero_card(top_diff, rank=1), unsafe_allow_html=True)
        st.markdown(
            f"<div style='margin-top:10px;padding:10px 14px;"
            f"background:rgba(255,105,0,0.07);border-left:3px solid #ff6900;"
            f"border-radius:6px;font-size:13px;color:rgba(255,255,255,0.8);'>"
            f"Only <b>{float(top_diff.get('ownership',0)):.1f}%</b> own this player. "
            f"Captaining a {float(top_diff.get('ownership',0)):.1f}% player gives "
            f"you massive rank upside if they deliver.</div>",
            unsafe_allow_html=True,
        )

    with col_d2:
        if len(diffs) > 1:
            fig2 = score_breakdown_chart(diffs, "Differential Captain Score Breakdown")
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown("#### Top 5 Differential Options")
    diff_cards = "".join(
        _mini_card(diffs.iloc[i], i + 1)
        for i in range(len(diffs))
    )
    st.markdown(diff_cards, unsafe_allow_html=True)
else:
    st.info(f"No differential captains found under {diff_threshold}% ownership with fixtures this GW.")

# ── Section 3: If no squad loaded, show global top 5 ─────────────────────────
if squad_df is None:
    st.markdown(f"### Top 5 Captain Picks (All Players) · GW{captain_gw}")
    st.caption("Enter your team ID in the sidebar to see picks from your squad only.")
    global_top5 = scored.head(5)
    if "team_code" not in global_top5.columns:
        tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
        global_top5 = global_top5.merge(tc, on="fpl_id", how="left")

    if not global_top5.empty:
        col_g1, col_g2 = st.columns([1, 1])
        with col_g1:
            st.markdown(_hero_card(global_top5.iloc[0]), unsafe_allow_html=True)
        with col_g2:
            fig3 = score_breakdown_chart(global_top5, "Captain Score Breakdown")
            st.plotly_chart(fig3, use_container_width=True)
        cards_g = "".join(_mini_card(global_top5.iloc[i], i+1) for i in range(len(global_top5)))
        st.markdown(cards_g, unsafe_allow_html=True)
