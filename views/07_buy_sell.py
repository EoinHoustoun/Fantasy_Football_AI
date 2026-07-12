"""
Buy / Sell Pairing · for each player in your squad, find their best replacement.

Shows: Sell X → Buy Y cards with projected pts/GW gain, fixture comparison,
and key stats side-by-side. Simple, opinionated, action-ready.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from typing import Optional, List

from components.badges import render_badges
from components.team_identity import shirt_url, shirt_fallback_url, badge_url, team_color

# set_page_config is owned by the app.py router (st.navigation)

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
    from data.fetchers.fpl_api import get_team_squad, fetch_bootstrap, fetch_team_info
    bs = fetch_bootstrap()
    squad_df, entry_history = get_team_squad(team_id, gw, bootstrap=bs)
    team_info = fetch_team_info(team_id)
    return squad_df, entry_history, team_info


def find_best_replacement(
    player: pd.Series,
    players_df: pd.DataFrame,
    budget: float,
    owned_ids: set,
    owned_team_counts: dict,
) -> Optional[pd.Series]:
    """Find best available replacement at same position within budget."""
    from analytics.transfer_engine import score_players
    pos = str(player.get("position", ""))
    scored = score_players(players_df)
    candidates = scored[
        (scored["position"] == pos) &
        (scored["price"] <= budget) &
        (scored["status"] == "a") &
        (~scored["fpl_id"].isin(owned_ids))
    ].copy()

    # Max 3 players per team (FPL rule)
    candidates = candidates[
        candidates["team_id"].map(lambda t: owned_team_counts.get(t, 0)) < 3
    ]

    if candidates.empty:
        return None
    return candidates.sort_values("transfer_score", ascending=False).iloc[0]


def _shirt_with_crest(code: int, is_gkp: bool) -> str:
    """52px kit image. (Crest omitted · PL crest CDN unreliable; the kit carries
    club identity.)"""
    return (
        f'<img src="{shirt_url(code, is_gkp)}" width="52" '
        f'onerror="this.src=\'{shirt_fallback_url(is_gkp)}\'"/>'
    )


def _pair_card(sell: pd.Series, buy: pd.Series, bank: float, fdr_col: str) -> str:
    """Render a sell→buy pairing card as HTML."""
    sell_code = int(sell.get("team_code", 1) or 1)
    buy_code  = int(buy.get("team_code", 1) or 1)
    sell_gkp  = str(sell.get("position", "")) == "GKP"
    buy_gkp   = str(buy.get("position", "")) == "GKP"

    sell_fdr  = float(sell.get(fdr_col, 3.0) or 3.0)
    buy_fdr   = float(buy.get(fdr_col, 3.0) or 3.0)
    fdr_delta = sell_fdr - buy_fdr  # positive = buy has easier fixtures

    sell_ppg  = float(sell.get("points_per_game", 0) or 0)
    buy_ppg   = float(buy.get("points_per_game", 0) or 0)
    ppg_gain  = buy_ppg - sell_ppg

    sell_form = float(sell.get("form", 0) or 0)
    buy_form  = float(buy.get("form", 0) or 0)

    sell_price = float(sell.get("price", 0) or 0)
    buy_price  = float(buy.get("price", 0) or 0)
    cost_diff  = buy_price - sell_price  # positive = costs more

    new_bank = bank - cost_diff
    cost_str = (f"costs £{cost_diff:.1f}m more" if cost_diff > 0 else
                f"saves £{abs(cost_diff):.1f}m" if cost_diff < 0 else "same price")
    bank_str = f"£{new_bank:.1f}m bank remaining"

    gain_color = "#00FF87" if ppg_gain > 0 else "#FF4B4B" if ppg_gain < 0 else "#aaa"
    fdr_color  = "#00FF87" if fdr_delta > 0.3 else "#aaa" if abs(fdr_delta) <= 0.3 else "#FF4B4B"

    pos    = str(sell.get("position", ""))
    pc     = POS_COLORS.get(pos, "#888")

    sell_status = str(sell.get("status", "a"))
    status_note = ""
    if sell_status == "i":
        status_note = '<span style="background:#FF4B4B;color:#fff;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:700;margin-left:8px;">INJURED</span>'
    elif sell_status == "d":
        status_note = '<span style="background:#FFA500;color:#000;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:700;margin-left:8px;">DOUBT</span>'

    buy_own = float(buy.get("ownership", 0) or 0)
    buy_dgw = bool(buy.get("has_dgw", False))
    dgw_tag = '<span style="background:#f5c518;color:#000;border-radius:3px;padding:0 5px;font-size:11px;font-weight:900;margin-left:6px;">DGW</span>' if buy_dgw else ""
    buy_badges = render_badges(buy, size="sm")

    return f"""
    <div style="
        background:rgba(255,255,255,0.03);
        border:1px solid rgba(255,255,255,0.1);
        border-radius:14px;
        padding:20px 24px;
        font-family:sans-serif;
        margin-bottom:14px;
    ">
      <!-- Position badge -->
      <div style="margin-bottom:12px;">
        <span style="background:{pc};color:#000;border-radius:4px;padding:2px 10px;font-size:11px;font-weight:900;">{pos}</span>
        <span style="color:rgba(255,255,255,0.35);font-size:11px;margin-left:10px;">{cost_str} · {bank_str}</span>
      </div>

      <!-- Sell / Buy row -->
      <div style="display:flex;align-items:center;gap:20px;">

        <!-- SELL side -->
        <div style="flex:1;background:rgba(255,75,75,0.08);border:1px solid rgba(255,75,75,0.25);border-radius:10px;padding:14px;text-align:center;">
          <div style="font-size:11px;color:#FF4B4B;font-weight:700;letter-spacing:2px;margin-bottom:8px;">SELL</div>
          {_shirt_with_crest(sell_code, sell_gkp)}
          <div style="font-size:16px;font-weight:800;color:#fff;margin-top:6px;">{sell.get("web_name","?")}{status_note}</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.45);margin-bottom:10px;">{sell.get("team","")} · £{sell_price:.1f}m</div>
          <div style="display:flex;justify-content:center;gap:18px;">
            <div><div style="font-size:15px;font-weight:700;color:#ff6b6b;">{sell_form:.1f}</div><div style="font-size:10px;color:rgba(255,255,255,0.4);">Form</div></div>
            <div><div style="font-size:15px;font-weight:700;color:#ff6b6b;">{sell_ppg:.1f}</div><div style="font-size:10px;color:rgba(255,255,255,0.4);">PPG</div></div>
            <div><div style="font-size:15px;font-weight:700;color:#ff6b6b;">{sell_fdr:.1f}</div><div style="font-size:10px;color:rgba(255,255,255,0.4);">FDR</div></div>
          </div>
        </div>

        <!-- Arrow -->
        <div style="font-size:28px;color:#FFD700;flex-shrink:0;">→</div>

        <!-- BUY side -->
        <div style="flex:1;background:rgba(0,255,135,0.08);border:1px solid rgba(0,255,135,0.3);border-radius:10px;padding:14px;text-align:center;">
          <div style="font-size:11px;color:#00FF87;font-weight:700;letter-spacing:2px;margin-bottom:8px;">BUY</div>
          {_shirt_with_crest(buy_code, buy_gkp)}
          <div style="font-size:16px;font-weight:800;color:#fff;margin-top:6px;">{buy.get("web_name","?")}{dgw_tag}</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.45);margin-bottom:6px;">{buy.get("team","")} · £{buy_price:.1f}m · {buy_own:.1f}% owned</div>
          <div style="margin-bottom:8px;">{buy_badges}</div>
          <div style="display:flex;justify-content:center;gap:18px;">
            <div><div style="font-size:15px;font-weight:700;color:#00FF87;">{buy_form:.1f}</div><div style="font-size:10px;color:rgba(255,255,255,0.4);">Form</div></div>
            <div><div style="font-size:15px;font-weight:700;color:#00FF87;">{buy_ppg:.1f}</div><div style="font-size:10px;color:rgba(255,255,255,0.4);">PPG</div></div>
            <div><div style="font-size:15px;font-weight:700;color:#00FF87;">{buy_fdr:.1f}</div><div style="font-size:10px;color:rgba(255,255,255,0.4);">FDR</div></div>
          </div>
        </div>
      </div>

      <!-- Summary bar -->
      <div style="display:flex;gap:24px;margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.07);">
        <div>
          <span style="color:rgba(255,255,255,0.4);font-size:12px;">PPG gain: </span>
          <span style="color:{gain_color};font-weight:800;font-size:14px;">{'+' if ppg_gain>=0 else ''}{ppg_gain:.1f} pts/GW</span>
        </div>
        <div>
          <span style="color:rgba(255,255,255,0.4);font-size:12px;">Fixture swing: </span>
          <span style="color:{fdr_color};font-weight:800;font-size:14px;">{'+' if fdr_delta>=0 else ''}{fdr_delta:.1f} FDR easier</span>
        </div>
      </div>
    </div>
    """


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("💰 Buy / Sell")
st.caption("For every player in your squad · find your best upgrade and see the net gain instantly.")

with st.spinner("Loading..."):
    players_df, bootstrap = load_universe()

from data.fetchers.fpl_api import get_current_gameweek
current_gw = get_current_gameweek(bootstrap)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Your Squad")
    from config import FPL_TEAM_ID, FIXTURE_LOOKAHEAD
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input("FPL Team ID", min_value=1, value=default_id, step=1)
    pos_filter = st.selectbox("Show position", ["All", "GKP", "DEF", "MID", "FWD"])
    sort_by = st.selectbox("Sort by", ["PPG gain", "FDR improvement", "Transfer score"])
    st.markdown("---")
    st.markdown("**How it works**")
    st.caption(
        "For each player you own, we find the best affordable replacement "
        "at the same position. Budget = bank + sell price. "
        "FPL 3-per-team limit is respected."
    )

# Load squad
try:
    with st.spinner(f"Loading team {team_id}..."):
        squad_df, entry_history, team_info = load_squad(team_id, current_gw)
except Exception as e:
    st.error(f"Could not load team {team_id}. Check your team ID.")
    st.stop()

bank_m = entry_history.get("bank", 0) / 10
team_name = team_info.get("name", f"Team {team_id}")

st.markdown(f"### {team_name} · Transfer Pairings")

# Merge team_code onto squad
if "team_code" not in squad_df.columns:
    tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
    squad_df = squad_df.merge(tc, on="fpl_id", how="left")

# Merge enriched player stats onto squad
enrich_cols = ["fpl_id", f"avg_fdr_next_{FIXTURE_LOOKAHEAD}", "has_dgw", "has_bgw",
               "transfer_score", "score_form", "score_fixture"]
enrich_cols = [c for c in enrich_cols if c in players_df.columns]
squad_enriched = squad_df.merge(players_df[enrich_cols], on="fpl_id", how="left")

# Only starting XI
xi = squad_enriched[~squad_enriched["on_bench"]].copy()

# Apply position filter
if pos_filter != "All":
    xi = xi[xi["position"] == pos_filter]

# Owned set for replacement exclusion
owned_ids = set(squad_df["fpl_id"].tolist())
from collections import Counter
team_counts = Counter(squad_df["team"].tolist())

# Merge team_code into players_df for buy cards
if "team_code" not in players_df.columns:
    players_df["team_code"] = 1

fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"

# Count per team_id
team_id_counts = Counter(squad_df["team_id"].tolist())

# Build pairings
pairings = []
with st.spinner("Finding best replacements..."):
    for _, player in xi.iterrows():
        sell_price = float(player.get("price", 0) or 0)
        budget = bank_m + sell_price
        replacement = find_best_replacement(player, players_df, budget, owned_ids, team_id_counts)
        if replacement is not None:
            ppg_gain   = float(replacement.get("points_per_game", 0) or 0) - float(player.get("form", 0) or 0)
            sell_fdr   = float(player.get(fdr_col, 3.0) or 3.0)
            buy_fdr    = float(replacement.get(fdr_col, 3.0) or 3.0)
            fdr_delta  = sell_fdr - buy_fdr
            pairings.append({
                "sell": player,
                "buy":  replacement,
                "ppg_gain":   float(replacement.get("points_per_game", 0) or 0) - float(player.get("points_per_game", 0) or 0),
                "fdr_delta":  fdr_delta,
                "score_gain": float(replacement.get("transfer_score", 0) or 0) - float(player.get("transfer_score", 0) or 0.5),
            })

if not pairings:
    st.warning("No replacements found. Try adjusting the position filter.")
    st.stop()

# Sort
sort_key = {"PPG gain": "ppg_gain", "FDR improvement": "fdr_delta", "Transfer score": "score_gain"}[sort_by]
pairings.sort(key=lambda x: x[sort_key], reverse=True)

# ── Summary metrics ────────────────────────────────────────────────────────────
best_ppg   = max(pairings, key=lambda x: x["ppg_gain"])
best_fix   = max(pairings, key=lambda x: x["fdr_delta"])
n_upgrades = sum(1 for p in pairings if p["ppg_gain"] > 0)

m1, m2, m3 = st.columns(3)
m1.metric("Upgrades available",     f"{n_upgrades} of {len(pairings)}")
m2.metric("Best PPG gain",          f"+{best_ppg['ppg_gain']:.1f} pts/GW",
          f"{best_ppg['sell'].get('web_name','?')} → {best_ppg['buy'].get('web_name','?')}")
m3.metric("Best fixture improvement", f"{best_fix['fdr_delta']:+.1f} FDR",
          f"{best_fix['sell'].get('web_name','?')} → {best_fix['buy'].get('web_name','?')}")

st.markdown("---")

# ── Upgrade-impact chart · projected PPG gain of every swap at a glance ─────────
st.markdown("##### Upgrade impact")
st.caption("Projected points-per-gameweek gain for each swap. Green = upgrade, red = downgrade.")
_labels = [f"{p['sell'].get('web_name','?')} → {p['buy'].get('web_name','?')}" for p in pairings]
_gains  = [p["ppg_gain"] for p in pairings]
_colors = ["#00FF87" if g > 0 else "#FF4B4B" for g in _gains]
_impact = go.Figure(go.Bar(
    x=_gains, y=_labels, orientation="h",
    marker=dict(color=_colors),
    text=[f"{g:+.1f}" for g in _gains], textposition="outside",
    hovertemplate="%{y}<br>%{x:+.1f} PPG/GW<extra></extra>",
))
_impact.update_layout(
    height=max(200, 34 * len(pairings) + 50), margin=dict(l=10, r=24, t=6, b=10),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="rgba(255,255,255,0.7)", size=11),
    xaxis=dict(title="PPG gain per GW", gridcolor="rgba(255,255,255,0.06)",
               zeroline=True, zerolinecolor="rgba(255,255,255,0.25)"),
    yaxis=dict(autorange="reversed"),
)
st.plotly_chart(_impact, use_container_width=True)

st.markdown("---")

# ── Pairing cards ──────────────────────────────────────────────────────────────
for p in pairings:
    st.markdown(
        _pair_card(p["sell"], p["buy"], bank_m, fdr_col),
        unsafe_allow_html=True,
    )
