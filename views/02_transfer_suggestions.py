"""
Transfer Suggestions page · redesigned.

Design goals
------------
  • Clear visual hierarchy: one hero recommendation + podium when close
  • Replace dense tables with a scannable card grid for Top Targets
  • Consistent typography scale, accent palette, and spacing
  • Tight, deliberate use of charts (Season Outlook / Haul / Breakdown tabs)
"""

from __future__ import annotations

import streamlit as st

from components.loading import LINES_MODEL, fpl_loader
from ui import charts
import pandas as pd
from typing import Optional, List, Dict, Any

from config import HAUL_THRESHOLD, TWENTY_PLUS_THRESHOLD, ACCENT_COLOR, FIXTURE_LOOKAHEAD
from components.badges import render_badges
from components.animations import inject_global_animations
from components.team_identity import shirt_html, team_color

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()


# ── Design tokens ──────────────────────────────────────────────────────────────
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
FDR_COLORS = {1: "#00FF87", 2: "#00FF87", 3: "#FFD60A", 4: "#FF8C42", 5: "#FF4B4B"}
SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"


def _shirt(team_code: int, is_gkp: bool) -> str:
    suffix = "_1" if is_gkp else ""
    return f"{SHIRT_BASE}/shirt_{team_code}{suffix}-66.png"


def _fdr_color(fdr: float) -> str:
    return FDR_COLORS.get(int(round(fdr)), "#FFD60A")


def _safe(val, default=0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return float(default)
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def _position_chip(pos: str) -> str:
    color = POS_COLORS.get(pos, "#888")
    return (
        f'<span style="background:{color};color:#000;border-radius:4px;'
        f'padding:2px 8px;font-weight:800;font-size:11px;letter-spacing:0.05em;">'
        f'{pos}</span>'
    )


def _fixture_pills(fixtures, n: int = 5) -> str:
    if not isinstance(fixtures, list) or not fixtures:
        return '<span style="color:rgba(255,255,255,0.35);font-size:11px;">No fixtures</span>'
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


def _attach_short_names(players_df: pd.DataFrame, bootstrap: dict) -> pd.DataFrame:
    """Add opp_short to each upcoming_fixtures entry using bootstrap team names."""
    if "upcoming_fixtures" not in players_df.columns:
        return players_df
    short_map = {t["name"]: t["short_name"] for t in bootstrap["teams"]}
    df = players_df.copy()

    def _attach(fixtures):
        if not isinstance(fixtures, list):
            return fixtures
        out = []
        for f in fixtures:
            g = dict(f)
            g["opp_short"] = short_map.get(g.get("opponent", ""), str(g.get("opponent", ""))[:3].upper())
            out.append(g)
        return out

    df["upcoming_fixtures"] = df["upcoming_fixtures"].apply(_attach)
    return df


# ── Render helpers ─────────────────────────────────────────────────────────────
def render_hero(player: pd.Series, reasoning: str) -> None:
    pos = str(player.get("position", ""))
    code = int(player.get("team_code", 1) or 1)
    shirt_url = _shirt(code, pos == "GKP")
    name = str(player.get("web_name", "?"))
    team = str(player.get("team", ""))
    price = _safe(player.get("price"))
    form = _safe(player.get("form"))
    ep_next = _safe(player.get("ep_next"))
    own = _safe(player.get("ownership"))
    fdr6 = _safe(player.get("avg_fdr_next_6"), 3.0)
    season_fdr = _safe(player.get("season_avg_fdr"), 3.0)
    score = _safe(player.get("transfer_score"))
    ceiling = _safe(player.get("ceiling_pts"))
    proj = _safe(player.get("projected_season_pts"))
    fix_html = _fixture_pills(player.get("upcoming_fixtures"), n=6)

    pos_chip = _position_chip(pos)

    html = f"""
<div class="fplh-animate-in" style="
    background:linear-gradient(135deg,rgba(0,255,135,0.08) 0%,rgba(14,17,22,0.85) 55%);
    border:1px solid rgba(0,255,135,0.35);
    border-radius:18px;
    padding:28px 32px;
    display:grid;
    grid-template-columns:120px 1fr auto;
    gap:28px;
    align-items:center;
    box-shadow:0 12px 40px rgba(0,0,0,0.35),0 0 80px rgba(0,255,135,0.06);
    font-family:'Inter','SF Pro Display',sans-serif;
    margin-bottom:18px;
">
  <div style="text-align:center;filter:drop-shadow(0 6px 10px rgba(0,0,0,0.45));">
    {shirt_html(code, pos == "GKP", width=110)}
  </div>

  <div>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
      <span style="background:#FFD700;color:#000;padding:2px 10px;border-radius:4px;
             font-size:11px;font-weight:900;letter-spacing:0.1em;">#1 PICK</span>
      {pos_chip}
      <span style="color:rgba(255,255,255,0.5);font-size:13px;">{team}</span>
    </div>
    <div style="font-size:34px;font-weight:900;color:#fff;line-height:1.05;letter-spacing:-0.5px;">
      {name}
    </div>
    <div style="margin-top:4px;color:rgba(255,255,255,0.55);font-size:13px;">
      £{price:.2f}m &nbsp;·&nbsp; {own:.1f}% owned &nbsp;·&nbsp; Next 6 FDR {fdr6:.2f}
    </div>
    <div style="margin-top:14px;">{fix_html}</div>
  </div>

  <div style="text-align:right;border-left:1px solid rgba(255,255,255,0.08);padding-left:28px;">
    <div style="font-size:42px;font-weight:900;color:#00FF87;line-height:1;letter-spacing:-1px;">
      {score:.2f}
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.4);letter-spacing:0.15em;margin-top:4px;">
      TRANSFER SCORE
    </div>
    <div style="margin-top:18px;display:flex;gap:20px;justify-content:flex-end;">
      <div><div style="font-size:18px;font-weight:800;color:#fff;">{form:.2f}</div>
           <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">FORM</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#04f5ff;">{ep_next:.2f}</div>
           <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">xP NEXT</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#FFD700;">{ceiling:.1f}</div>
           <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">CEILING</div></div>
    </div>
  </div>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)

    # Reasoning panel under the hero
    st.markdown(
        f"""
<div style="
    background:rgba(0,255,135,0.04);
    border-left:3px solid #00FF87;
    border-radius:0 10px 10px 0;
    padding:16px 22px;
    margin-bottom:22px;
    font-size:14px;color:rgba(255,255,255,0.88);line-height:1.6;
    font-family:'Inter',sans-serif;
">{reasoning}</div>
""",
        unsafe_allow_html=True,
    )


def render_podium(close_list: List[Dict[str, Any]]) -> None:
    labels = ["#1", "#2", "#3"]
    accents = ["#FFD700", "#C0C0C0", "#CD7F32"]

    cards = []
    for i, item in enumerate(close_list[:3]):
        p = item["player"]
        pos = str(p.get("position", ""))
        code = int(p.get("team_code", 1) or 1)
        shirt_url = _shirt(code, pos == "GKP")
        name = str(p.get("web_name", "?"))
        team = str(p.get("team", ""))
        price = _safe(p.get("price"))
        form = _safe(p.get("form"))
        ep = _safe(p.get("ep_next"))
        score = _safe(p.get("transfer_score"))
        fdr6 = _safe(p.get("avg_fdr_next_6"), 3.0)

        cards.append(f"""
<div class="fplh-card-hover" style="
    background:rgba(255,255,255,0.03);
    border:1px solid {accents[i]};
    border-radius:14px;padding:20px;font-family:'Inter',sans-serif;
    box-shadow:0 6px 20px rgba(0,0,0,0.25);
">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
    <span style="background:{accents[i]};color:#000;padding:2px 10px;border-radius:4px;
           font-size:11px;font-weight:900;letter-spacing:0.1em;">{labels[i]}</span>
    {_position_chip(pos)}
  </div>
  <div style="display:flex;align-items:center;gap:14px;">
    <div style="filter:drop-shadow(0 3px 5px rgba(0,0,0,0.4));flex-shrink:0;">{shirt_html(code, pos == "GKP", width=62)}</div>
    <div style="flex:1;min-width:0;">
      <div style="font-size:20px;font-weight:900;color:#fff;white-space:nowrap;
                  overflow:hidden;text-overflow:ellipsis;">{name}</div>
      <div style="font-size:12px;color:rgba(255,255,255,0.5);">{team} · £{price:.2f}m</div>
    </div>
  </div>
  <div style="display:flex;gap:14px;margin-top:16px;padding-top:14px;
              border-top:1px solid rgba(255,255,255,0.06);">
    <div style="flex:1;"><div style="font-size:17px;font-weight:800;color:#00FF87;">{score:.2f}</div>
         <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">SCORE</div></div>
    <div style="flex:1;"><div style="font-size:17px;font-weight:800;color:#fff;">{form:.2f}</div>
         <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">FORM</div></div>
    <div style="flex:1;"><div style="font-size:17px;font-weight:800;color:#04f5ff;">{ep:.2f}</div>
         <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">xP</div></div>
    <div style="flex:1;"><div style="font-size:17px;font-weight:800;color:{_fdr_color(fdr6)};">{fdr6:.1f}</div>
         <div style="font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">FDR6</div></div>
  </div>
  <div style="margin-top:12px;font-size:12px;color:rgba(255,255,255,0.75);line-height:1.5;">
    {item['reasoning']}
  </div>
</div>
""")

    st.markdown(
        '<div class="fplh-stagger" style="display:grid;'
        'grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:22px;">'
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def render_target_grid(df: pd.DataFrame, n: int = 12) -> None:
    """Card grid replacement for the all-rankings dense dataframe."""
    cards = []
    for _, p in df.head(n).iterrows():
        pos = str(p.get("position", ""))
        code = int(p.get("team_code", 1) or 1)
        tcol = team_color(p.get("team_short"))
        name = str(p.get("web_name", "?"))
        team = str(p.get("team", ""))
        price = _safe(p.get("price"))
        form = _safe(p.get("form"))
        ep = _safe(p.get("ep_next"))
        own = _safe(p.get("ownership"))
        score = _safe(p.get("transfer_score"))
        fdr6 = _safe(p.get("avg_fdr_next_6"), 3.0)
        fix = _fixture_pills(p.get("upcoming_fixtures"), n=5)

        # Score bar (0..1 assumed; clamp)
        bar_pct = max(0.0, min(1.0, score)) * 100

        cards.append(f"""
<div class="fplh-card-hover" style="
    background:rgba(22,26,34,0.85);
    border:1px solid rgba(255,255,255,0.08);
    border-left:3px solid {tcol};
    border-radius:12px;padding:16px;
    font-family:'Inter',sans-serif;
">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
    <div style="filter:drop-shadow(0 3px 5px rgba(0,0,0,0.4));flex-shrink:0;">{shirt_html(code, pos == "GKP", width=50)}</div>
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
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#fff;">{form:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">FORM</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#04f5ff;">{ep:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">xP</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:{_fdr_color(fdr6)};">{fdr6:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">FDR6</div></div>
    <div style="flex:1;"><div style="font-size:14px;font-weight:800;color:#00FF87;">{score:.2f}</div>
         <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.08em;">SCORE</div></div>
  </div>

  <div style="background:rgba(255,255,255,0.05);border-radius:4px;height:4px;overflow:hidden;margin-bottom:10px;">
    <div style="background:linear-gradient(90deg,#00FF87,#04f5ff);height:100%;width:{bar_pct:.0f}%;"></div>
  </div>

  <div style="font-size:11px;">{fix}</div>
</div>
""")

    st.markdown(
        '<div class="fplh-stagger" style="display:grid;'
        'grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;">'
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


# ── Page header ────────────────────────────────────────────────────────────────
st.markdown(
    """
<div style="padding:18px 0 8px;font-family:'Inter',sans-serif;">
  <div style="font-size:30px;font-weight:900;color:#fff;letter-spacing:-0.5px;">
    🔄 Transfer Suggestions
  </div>
  <div style="font-size:14px;color:rgba(255,255,255,0.45);margin-top:4px;">
    Your #1 transfer · with reasoning, a top-targets grid, and deeper breakdowns.
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ── Data ───────────────────────────────────────────────────────────────────────
def get_players():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


players_df = get_players()

from data.fetchers.fpl_api import (
    fetch_bootstrap, get_current_gameweek, get_fixtures_df, get_team_squad,
)
_bs = fetch_bootstrap()
_current_gw = get_current_gameweek(_bs)
players_df = _attach_short_names(players_df, _bs)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Your Team")
    from config import FPL_TEAM_ID
    _default_id = st.session_state.get("squad_team_id") or (int(FPL_TEAM_ID) if FPL_TEAM_ID else 0)
    squad_team_id = st.number_input(
        "FPL Team ID",
        min_value=0,
        value=_default_id,
        step=1,
        help="Enter your team ID to exclude players you already own from recommendations.",
    )
    st.caption("Recommendations will exclude players you already own.")

    st.markdown("### Position & Budget")
    position = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    pos_filter = None if position == "All" else position
    price_range = st.slider("Price range (£m)", 3.5, 15.0, (4.0, 12.0), step=0.5)

    st.markdown("---")
    st.markdown("### 🃏 Free Hit Chip")
    playing_fh = st.toggle("I'm playing Free Hit this GW", value=False)
    free_hit_gw = None
    if playing_fh:
        free_hit_gw = st.number_input(
            "Free Hit gameweek",
            min_value=_current_gw, max_value=38, value=_current_gw, step=1,
        )

    st.markdown("---")
    with st.expander("⚙️ Score Weights (advanced)", expanded=False):
        st.caption("Tune what matters most to you this GW.")
        w_form    = st.slider("Form",            0.0, 1.0, 0.25, step=0.05)
        w_fixture = st.slider("Fixture Ease",    0.0, 1.0, 0.25, step=0.05)
        w_xg      = st.slider("xG Potential",    0.0, 1.0, 0.20, step=0.05)
        w_value   = st.slider("Value (PPM)",     0.0, 1.0, 0.15, step=0.05)
        w_trend   = st.slider("Transfer Trend",  0.0, 1.0, 0.10, step=0.05)
        w_minutes = st.slider("Minutes Security", 0.0, 1.0, 0.05, step=0.05)

    top_n = st.slider("Show top N targets", 6, 30, 12)

custom_weights = {
    "form": w_form, "fixture_ease": w_fixture, "xg_potential": w_xg,
    "value": w_value, "ownership_trend": w_trend, "minutes_security": w_minutes,
}


# ── Owned players ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _load_owned(team_id: int, gw: int) -> list:
    from data.fetchers.fpl_api import fetch_bootstrap as _fb
    bs = _fb()
    squad, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad["web_name"].tolist()


owned_names = []
if squad_team_id and int(squad_team_id) > 0:
    try:
        owned_names = _load_owned(int(squad_team_id), _current_gw)
        st.session_state.owned_names = owned_names
        st.session_state.squad_team_id = int(squad_team_id)
    except Exception:
        owned_names = st.session_state.get("owned_names", [])
else:
    owned_names = st.session_state.get("owned_names", [])


# ── Recommendation engine ──────────────────────────────────────────────────────
from analytics.transfer_engine import (
    get_top_recommendation, get_transfer_targets, score_players,
    estimate_season_points, estimate_ceiling,
    apply_free_hit_adjustment, get_free_hit_targets,
)

_fixtures_df = st.session_state.get("fixtures_df")
if _fixtures_df is None:
    _fixtures_df = get_fixtures_df(bootstrap=_bs)

with fpl_loader("Scoring the transfer market", LINES_MODEL):
    base_df = players_df
    if free_hit_gw:
        base_df = apply_free_hit_adjustment(players_df, _fixtures_df, _current_gw, free_hit_gw)

    reco = get_top_recommendation(
        base_df,
        owned_names=owned_names if not free_hit_gw else None,
        budget=price_range[1],
        position=pos_filter,
        weights=custom_weights,
        free_hit_gw=free_hit_gw,
    )

    full_df = score_players(base_df, weights=custom_weights)
    full_df = estimate_season_points(full_df)
    full_df = estimate_ceiling(full_df)
    full_df = full_df[full_df["status"] == "a"].copy()
    if owned_names and not free_hit_gw:
        full_df = full_df[~full_df["web_name"].isin(owned_names)]
    if pos_filter:
        full_df = full_df[full_df["position"] == pos_filter]
    # Apply price-range filter from the sidebar
    full_df = full_df[(full_df["price"] >= price_range[0]) & (full_df["price"] <= price_range[1])]
    full_df = full_df.sort_values("transfer_score", ascending=False).reset_index(drop=True)


if free_hit_gw:
    st.info(
        f"**Free Hit active · GW{free_hit_gw}.** "
        f"GW{free_hit_gw} is excluded from season projections and fixture averages "
        f"for your regular squad. See the **Season Outlook** tab for Free Hit targets."
    )

if reco["top"] is None:
    st.warning("No players match your filters. Try widening the price range or removing the position filter.")
    st.stop()


# ── Hero / podium ──────────────────────────────────────────────────────────────
top = reco["top"]
is_close = reco["is_close"]
top_reasoning = reco["close"][0]["reasoning"] if reco["close"] else ""

if is_close:
    st.markdown(
        '<div style="font-size:20px;font-weight:800;color:#fff;margin-bottom:6px;">'
        '🏆 It\'s close at the top</div>'
        '<div style="font-size:13px;color:rgba(255,255,255,0.55);margin-bottom:16px;">'
        'Scores are tight · read the reasoning and pick what fits your squad.</div>',
        unsafe_allow_html=True,
    )
    render_podium(reco["close"])
else:
    render_hero(top, top_reasoning)

# Contextual alerts (price rise / BGW / DGW)
_bal = int(top.get("transfer_balance", 0) or 0)
_price_ch = _safe(top.get("price_change"))
_bgw = top.get("bgw_gameweeks") or []
_dgw = top.get("dgw_gameweeks") or []
alert_cols = st.columns(3)
with alert_cols[0]:
    if _bal > 150_000:
        st.warning(f"💹 Price rise likely · {_bal / 1000:.0f}k net in. Buy before deadline.")
    elif _bal > 60_000:
        st.info(f"📈 Rising popularity · {_bal / 1000:.0f}k net in.")
    elif _price_ch > 0:
        st.info(f"↑ Already rose £{_price_ch:.1f}m this GW.")
with alert_cols[1]:
    if isinstance(_bgw, list) and _bgw:
        st.warning(f"⚠️ Blank GW: no fixture in GW{', GW'.join(str(g) for g in _bgw)}")
    elif isinstance(_dgw, list) and _dgw:
        st.success(f"⭐ Double GW: plays twice in GW{', GW'.join(str(g) for g in _dgw)}")
with alert_cols[2]:
    if top.get("twenty_plus"):
        st.success("🎯 20+ point haul potential")
    elif top.get("haul_candidate"):
        st.info("🎯 Haul candidate (15+ ceiling)")


# ── Top Targets grid ───────────────────────────────────────────────────────────
st.markdown(
    f'<div style="margin:26px 0 14px;display:flex;align-items:baseline;justify-content:space-between;">'
    f'  <div style="font-size:20px;font-weight:800;color:#fff;">🎯 Top Targets</div>'
    f'  <div style="font-size:12px;color:rgba(255,255,255,0.45);">'
    f'    Top {min(top_n, len(full_df))} ranked by transfer score'
    f'  </div>'
    f'</div>',
    unsafe_allow_html=True,
)
render_target_grid(full_df, n=top_n)


# ── Tabs ───────────────────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
tab_season, tab_ceiling, tab_breakdown, tab_fixtures = st.tabs([
    "📅 Season Outlook",
    "🎯 Haul Potential",
    "📊 Score Breakdown",
    "🗓️ Fixture Ticker",
])


with tab_season:
    st.caption(
        "Projected points from now until GW38, based on PPG × remaining fixtures × fixture ease. "
        "Colour = season FDR (green easier)."
    )
    season_chart = full_df[[
        "web_name", "team", "position", "price", "projected_season_pts",
        "season_avg_fdr", "remaining_fixtures", "points_per_game",
    ]].head(top_n).copy()
    season_chart = season_chart.dropna(subset=["projected_season_pts"])
    season_chart = season_chart.sort_values("projected_season_pts", ascending=False)

    if not season_chart.empty:
        fdr_colors = charts.diverging_colors(
            [min(max(float(v), 1.5), 4.0) for v in season_chart["season_avg_fdr"].fillna(2.75)],
            "#00FF87", "#FFD60A", "#FF4B4B", midpoint=2.75)
        opt = charts.bar_option(
            x=list(season_chart["web_name"]),
            y=[round(float(v), 1) for v in season_chart["projected_season_pts"]],
            colors=fdr_colors, horizontal=True)
        for item, (_, r) in zip(opt["series"][0]["data"], season_chart.iterrows()):
            item["tooltip"] = {"formatter": (
                f"<b>{r['web_name']}</b> · {r['team']} {r['position']}<br/>"
                f"{r['projected_season_pts']:.0f} projected pts · £{r['price']:.1f}m<br/>"
                f"{int(r['remaining_fixtures'])} fixtures · FDR {r['season_avg_fdr']:.2f} "
                f"· {r['points_per_game']:.1f} ppg")}
        charts.render(opt, height=f"{max(380, 28 * len(season_chart))}px",
                      key="ts_season_proj")

    if free_hit_gw:
        st.markdown("---")
        st.markdown(f"**Free Hit Targets · GW{free_hit_gw}**")
        fh_targets = get_free_hit_targets(players_df, _fixtures_df, free_hit_gw, top_n=top_n)
        if not fh_targets.empty:
            fh_display = fh_targets.rename(columns={
                "web_name": "Player", "team": "Team", "position": "Pos",
                "price": "Price", "form": "Form", "total_points": "Season Pts",
                "fh_fdr": f"GW{free_hit_gw} FDR", "ownership": "Own%",
            })
            for c in ("Form", "Season Pts", f"GW{free_hit_gw} FDR", "Own%"):
                if c in fh_display.columns:
                    fh_display[c] = pd.to_numeric(fh_display[c], errors="coerce").round(2)
            fh_display["Price"] = fh_display["Price"].apply(lambda x: f"£{x:.2f}m")
            st.dataframe(fh_display, use_container_width=True, hide_index=True)
        else:
            st.info(f"No fixture data available for GW{free_hit_gw} yet.")


with tab_ceiling:
    st.caption(
        "Ceiling = max single-game haul model (xG/xA × goal pts + CS × fixture ease). "
        "Green = 20+ haul threshold, orange = 15+."
    )
    ceiling_chart = full_df[[
        "web_name", "team", "position", "price", "ceiling_pts",
        "haul_candidate", "twenty_plus", "avg_fdr_next_6",
    ]].head(top_n * 2).copy()
    ceiling_chart = ceiling_chart.sort_values("ceiling_pts", ascending=False).head(top_n)

    if not ceiling_chart.empty:
        def _tier(row):
            if row["twenty_plus"]: return "20+ Haul"
            if row["haul_candidate"]: return "15+ Haul"
            return "Standard"
        ceiling_chart["Tier"] = ceiling_chart.apply(_tier, axis=1)

        tier_color = {"20+ Haul": ACCENT_COLOR, "15+ Haul": "#FFA500", "Standard": "#8888aa"}
        opt = charts.bar_option(
            x=list(ceiling_chart["web_name"]),
            y=[round(float(v), 1) for v in ceiling_chart["ceiling_pts"]],
            colors=[tier_color[t] for t in ceiling_chart["Tier"]], horizontal=True)
        for item, (_, r) in zip(opt["series"][0]["data"], ceiling_chart.iterrows()):
            item["tooltip"] = {"formatter": (
                f"<b>{r['web_name']}</b> · {r['team']} {r['position']}<br/>"
                f"Ceiling {r['ceiling_pts']:.1f} pts ({r['Tier']})<br/>"
                f"£{r['price']:.1f}m · FDR next 6: {r['avg_fdr_next_6']:.2f}")}
        charts.with_vertical_marks(opt, [
            (float(TWENTY_PLUS_THRESHOLD), "20 pts", ACCENT_COLOR),
            (float(HAUL_THRESHOLD), "15 pts", "#FFA500"),
        ])
        charts.render(opt, height=f"{max(380, 28 * len(ceiling_chart))}px",
                      key="ts_ceiling")


with tab_breakdown:
    st.caption("How each component contributes to the transfer score.")
    score_cols = [c for c in ["score_form", "score_fixture", "score_xg", "score_value"] if c in full_df.columns]

    if score_cols:
        top15 = full_df[["web_name"] + score_cols].head(15)
        comp_colors = ["#00FF87", "#04f5ff", "#e90052", "#FFD700"]
        series = [
            (col.replace("score_", "").title(),
             [round(float(v), 3) for v in top15[col].fillna(0)],
             comp_colors[i % len(comp_colors)])
            for i, col in enumerate(score_cols)
        ]
        opt = charts.stacked_bars_option(list(top15["web_name"]), series,
                                         horizontal=True)
        charts.render(opt, height="480px", key="ts_breakdown")

    fdr_col = next((c for c in full_df.columns if c.startswith("avg_fdr_next_")), None)
    if fdr_col and "form" in full_df.columns and "price" in full_df.columns:
        top50 = full_df.head(50)
        fdr_cols = charts.diverging_colors(
            [float(v) for v in top50[fdr_col].fillna(3.0)],
            "#00FF87", "#FFD60A", "#FF4B4B", midpoint=3.0)
        sizes = charts.scale_sizes(list(top50["transfer_score"].fillna(0)),
                                   lo=7.0, hi=24.0)
        pts = [{
            "x": round(float(r["price"]), 1), "y": round(float(r["form"]), 2),
            "name": str(r["web_name"]), "color": fdr_cols[i], "size": sizes[i],
            "tip": (f"<b>{r['web_name']}</b><br/>£{r['price']:.1f}m · form {r['form']}"
                    f"<br/>FDR {r[fdr_col]:.2f} · score {r['transfer_score']:.2f}"),
        } for i, (_, r) in enumerate(top50.iterrows())]
        opt = charts.scatter_option(pts, x_name="Price (£m)", y_name="Form")
        opt["title"] = {"text": "Form vs Price (bubble = score, colour = FDR)",
                        "textStyle": {"color": "#eef1f5", "fontSize": 12,
                                      "fontWeight": "bold"}}
        charts.render(opt, height="400px", key="ts_form_price")


with tab_fixtures:
    if "upcoming_fixtures" in players_df.columns:
        fixture_data = players_df[["web_name", "upcoming_fixtures"]].copy()
        top_players = full_df.head(top_n)
        suggestions_with_fixtures = top_players.merge(fixture_data, on="web_name", how="left", suffixes=("", "_drop"))
        if "upcoming_fixtures_drop" in suggestions_with_fixtures.columns:
            suggestions_with_fixtures = suggestions_with_fixtures.drop(columns=["upcoming_fixtures_drop"])
        from components.fixture_ticker import render_fixture_ticker
        render_fixture_ticker(suggestions_with_fixtures, top_n=min(top_n, len(suggestions_with_fixtures)))
    else:
        st.info("Fixture data not available.")
