"""
Injury & Availability Tracker.

Shows:
  • Your squad · any players flagged as injured, doubtful, or suspended
  • Full league: all players with availability concerns, grouped by status
  • Suggested replacements for your injured starters
"""

import streamlit as st

from components.loading import LINES_GENERIC, LINES_SQUAD, fpl_loader
import pandas as pd
from typing import Optional, List

from ui import charts

# set_page_config is owned by the app.py router (st.navigation)

STATUS_CONFIG = {
    "i": {"label": "Injured",    "color": "#FF4B4B", "emoji": "🚑", "bg": "rgba(255,75,75,0.08)",   "border": "rgba(255,75,75,0.4)"},
    "s": {"label": "Suspended",  "color": "#FF4B4B", "emoji": "🚫", "bg": "rgba(255,75,75,0.08)",   "border": "rgba(255,75,75,0.4)"},
    "d": {"label": "Doubtful",   "color": "#FFA500", "emoji": "⚠️", "bg": "rgba(255,165,0,0.08)",   "border": "rgba(255,165,0,0.4)"},
    "u": {"label": "Unavailable","color": "#aaa",    "emoji": "❓", "bg": "rgba(180,180,180,0.06)", "border": "rgba(180,180,180,0.3)"},
}

SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)   # 15 min cache · news changes fast
def load_universe():
    from data.fetchers.fpl_api import fetch_bootstrap
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    players = build_player_universe(bootstrap=bs, understat_df=understat_df)
    return players, bs


@st.cache_data(ttl=900, show_spinner=False)
def load_squad(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad_df


def _shirt_url(team_code: int, is_gkp: bool) -> str:
    # GK kit is the ONLY one with a suffix (_1); outfield has no suffix.
    suffix = "_1" if is_gkp else ""
    return f"{SHIRT_BASE}/shirt_{team_code}{suffix}-66.png"


def _player_alert_card(player: pd.Series, show_shirt: bool = True) -> str:
    status = str(player.get("status", "a"))
    cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["u"])
    code = int(player.get("team_code", 1) or 1)
    is_gkp = str(player.get("position", "")) == "GKP"
    shirt = _shirt_url(code, is_gkp)
    fallback = f"{SHIRT_BASE}/shirt_1_1-66.png"

    name  = str(player.get("web_name", "?"))
    team  = str(player.get("team", ""))
    pos   = str(player.get("position", ""))
    price = float(player.get("price", 0) or 0)
    own   = float(player.get("ownership", 0) or 0)
    news  = str(player.get("news", "") or "")
    cop   = player.get("chance_of_playing_next_round")
    ppg   = float(player.get("points_per_game", 0) or 0)
    form  = float(player.get("form", 0) or 0)

    cop_html = ""
    if cop is not None:
        cop_color = "#00FF87" if cop >= 75 else "#FFA500" if cop >= 25 else "#FF4B4B"
        cop_html = (
            f'<div style="background:{cop_color};color:#000;border-radius:20px;'
            f'padding:2px 10px;font-size:12px;font-weight:800;display:inline-block;margin-bottom:8px;">'
            f'{int(cop)}% chance of playing</div>'
        )

    pos_col = POS_COLORS.get(pos, "#888")
    img_html = (
        f'<img src="{shirt}" width="48" onerror="this.src=\'{fallback}\'" style="flex-shrink:0;"/>'
        if show_shirt else ""
    )

    return f"""
    <div style="
        background:{cfg['bg']};
        border:1px solid {cfg['border']};
        border-radius:12px;
        padding:14px 18px;
        display:flex;
        align-items:flex-start;
        gap:14px;
        font-family:sans-serif;
        margin-bottom:10px;
    ">
      {img_html}
      <div style="flex:1; min-width:0;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;flex-wrap:wrap;">
          <span style="font-size:16px;font-weight:800;color:#fff;">{name}</span>
          <span style="background:{cfg['color']};color:#fff;border-radius:4px;padding:1px 8px;font-size:11px;font-weight:700;">{cfg['emoji']} {cfg['label']}</span>
          <span style="background:{pos_col};color:#000;border-radius:3px;padding:0 6px;font-size:11px;font-weight:700;">{pos}</span>
        </div>
        <div style="font-size:12px;color:rgba(255,255,255,0.45);margin-bottom:6px;">
          {team} &nbsp;·&nbsp; £{price:.1f}m &nbsp;·&nbsp; {own:.1f}% owned
          &nbsp;·&nbsp; {ppg:.1f} PPG &nbsp;·&nbsp; {form:.1f} form
        </div>
        {cop_html}
        <div style="font-size:12px;color:rgba(255,255,255,0.65);font-style:italic;line-height:1.4;">
          {news if news else "No further news available."}
        </div>
      </div>
    </div>
    """


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("🚑 Injury & Availability Tracker")
st.caption("Live status from the FPL API. Updated every 15 minutes.")

with fpl_loader("Checking the treatment room", LINES_GENERIC):
    players_df, bootstrap = load_universe()

from data.fetchers.fpl_api import get_current_gameweek
current_gw = get_current_gameweek(bootstrap)

# Merge team_code if missing
if "team_code" not in players_df.columns:
    teams_lookup = {t["id"]: t["code"] for t in bootstrap["teams"]}
    players_df["team_code"] = players_df["team_id"].map(teams_lookup).fillna(1).astype(int)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Your Squad")
    from config import FPL_TEAM_ID
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input("FPL Team ID", min_value=1, value=default_id, step=1)
    st.markdown("---")
    show_pos = st.multiselect(
        "Filter by position",
        ["GKP", "DEF", "MID", "FWD"],
        default=["GKP", "DEF", "MID", "FWD"],
    )
    show_status = st.multiselect(
        "Filter by status",
        ["Injured", "Doubtful", "Suspended", "Unavailable"],
        default=["Injured", "Doubtful", "Suspended"],
    )

status_map = {"Injured": "i", "Doubtful": "d", "Suspended": "s", "Unavailable": "u"}
selected_statuses = [status_map[s] for s in show_status]

# ── Section 1: YOUR SQUAD alerts ──────────────────────────────────────────────
squad_df = None
if team_id and team_id > 0:
    try:
        with fpl_loader(f"Fetching squad {team_id}", LINES_SQUAD):
            squad_df = load_squad(team_id, current_gw)
    except Exception:
        st.sidebar.warning("Could not load squad.")

if squad_df is not None:
    st.markdown("### 🔴 Your Squad Alerts")

    if "team_code" not in squad_df.columns:
        tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
        squad_df = squad_df.merge(tc, on="fpl_id", how="left")

    # Also merge chance_of_playing
    cop_merge = players_df[["fpl_id", "chance_of_playing_next_round", "news",
                             "points_per_game", "form"]].drop_duplicates("fpl_id")
    squad_df = squad_df.merge(cop_merge, on="fpl_id", how="left", suffixes=("", "_pu"))
    for col in ["news", "chance_of_playing_next_round", "points_per_game", "form"]:
        if col + "_pu" in squad_df.columns:
            squad_df[col] = squad_df[col].fillna(squad_df[col + "_pu"])

    squad_flagged = squad_df[squad_df["status"].isin(["i", "d", "s", "u"])].copy()

    if squad_flagged.empty:
        st.success("✅ All your players are fully fit and available!")
    else:
        n_starters = squad_flagged[~squad_flagged["on_bench"]].shape[0]
        n_bench    = squad_flagged[squad_flagged["on_bench"]].shape[0]
        if n_starters > 0:
            st.warning(f"⚠️ **{n_starters} starting XI player(s)** with concerns · check before GW{current_gw + 1}!")

        starters_flagged = squad_flagged[~squad_flagged["on_bench"]].sort_values("status")
        bench_flagged    = squad_flagged[squad_flagged["on_bench"]].sort_values("status")

        if not starters_flagged.empty:
            st.markdown("**Starting XI concerns**")
            for _, p in starters_flagged.iterrows():
                st.markdown(_player_alert_card(p), unsafe_allow_html=True)

        if not bench_flagged.empty:
            with st.expander(f"Bench concerns ({n_bench} player{'s' if n_bench>1 else ''})"):
                for _, p in bench_flagged.iterrows():
                    st.markdown(_player_alert_card(p), unsafe_allow_html=True)

    st.markdown("---")

# ── Section 2: Full league injury board ───────────────────────────────────────
st.markdown("### 📋 Full Injury Board")

all_flagged = players_df[
    (players_df["status"].isin(selected_statuses)) &
    (players_df["position"].isin(show_pos))
].copy()

if all_flagged.empty:
    st.info("No players match the current filters.")
else:
    # Summary chart: injured/doubtful count by team
    team_counts = all_flagged.groupby("team")["fpl_id"].count().reset_index()
    team_counts.columns = ["team", "flagged"]
    team_counts = team_counts.sort_values("flagged", ascending=False)

    counts = [int(v) for v in team_counts["flagged"]]
    opt = charts.bar_option(
        x=list(team_counts["team"]), y=counts, horizontal=True,
        colors=charts.color_ramp(counts, "#FFA500", "#FF4B4B"),
    )
    opt["title"] = {"text": "Players with Availability Concerns · by Team",
                    "textStyle": {"color": "#eef1f5", "fontSize": 13,
                                  "fontWeight": "bold"}}
    opt["grid"]["top"] = 40
    opt["tooltip"]["formatter"] = "{b}: {c} flagged"
    charts.render(opt, height=f"{max(250, len(team_counts) * 24)}px",
                  key="inj_by_team")

    st.markdown(f"**{len(all_flagged)} players flagged**")

    # Group by status for display
    for status_code in ["i", "s", "d", "u"]:
        if status_code not in selected_statuses:
            continue
        cfg   = STATUS_CONFIG[status_code]
        group = all_flagged[all_flagged["status"] == status_code].sort_values("ownership", ascending=False)
        if group.empty:
            continue

        with st.expander(f"{cfg['emoji']} {cfg['label']} · {len(group)} players", expanded=(status_code in ["i", "s"])):
            # High-ownership ones first
            high_own = group[group["ownership"] >= 5.0]
            low_own  = group[group["ownership"] < 5.0]

            if not high_own.empty:
                st.markdown("*Highly owned (5%+) · transfer decisions needed:*")
                for _, p in high_own.iterrows():
                    st.markdown(_player_alert_card(p), unsafe_allow_html=True)

            if not low_own.empty:
                # Streamlit forbids nested expanders (we're already inside the
                # status-group one) · a native <details> collapses the same way.
                _cards = "".join(_player_alert_card(p, show_shirt=False)
                                 for _, p in low_own.iterrows())
                st.markdown(
                    f"<details><summary style='cursor:pointer;font-size:13px;"
                    f"color:rgba(255,255,255,0.6);padding:4px 0;'>Lower ownership "
                    f"({len(low_own)} more)</summary>{_cards}</details>",
                    unsafe_allow_html=True)
