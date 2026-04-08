"""
Wildcard Planner.

For each remaining gameweek, shows how many elite players have easy fixtures —
helping identify the optimal week to play your Wildcard chip.

Logic: score the "top squad available" for each GW based on form × fixture ease for
that specific GW, with DGW double-count and BGW exclusion. The GW with the
highest summed score for a 15-man optimal squad is the best wildcard window.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import List, Dict, Optional

st.set_page_config(page_title="Wildcard Planner — FPL Hub", layout="wide")

SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}

# FPL squad constraints: 2 GKP, 5 DEF, 5 MID, 3 FWD
SQUAD_LIMITS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
SQUAD_TOTAL  = 15
BUDGET_CAP   = 100.0  # £100m wildcard budget


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_data():
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_current_gameweek, get_fixtures_df
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    players = build_player_universe(bootstrap=bs, understat_df=understat_df)
    fixtures_raw = fetch_fixtures()
    fixtures_df = get_fixtures_df(fixtures_raw, bs)
    gw = get_current_gameweek(bs)
    return players, bs, fixtures_df, gw


def _gw_fdr_map(fixtures_df: pd.DataFrame, gw: int) -> Dict[int, List[float]]:
    """Return {team_id: [fdr, fdr, ...]} for a specific GW (handles DGWs)."""
    gw_fix = fixtures_df[fixtures_df["gameweek"] == gw]
    fdr_map: Dict[int, List[float]] = {}
    for _, row in gw_fix.iterrows():
        for side in ("home", "away"):
            tid = int(row["home_team_id"] if side == "home" else row["away_team_id"])
            fdr = float(row["home_fdr"]   if side == "home" else row["away_fdr"])
            fdr_map.setdefault(tid, []).append(fdr)
    return fdr_map


def _projected_pts(player: pd.Series, fdr_list: List[float]) -> float:
    """Estimate pts for player in a GW given their fixture(s)."""
    if not fdr_list:
        return 0.0   # blank GW
    ppg  = float(player.get("points_per_game", 0) or 0)
    # Fixture ease multiplier: FDR 1 = 1.3x, 3 = 1.0x, 5 = 0.7x
    ease = np.mean([1.0 + (3.0 - f) * 0.15 for f in fdr_list])
    # DGW bonus: multiply by number of games
    return ppg * ease * len(fdr_list)


def _pick_optimal_squad(players_df: pd.DataFrame, fdr_map: Dict[int, List[float]]) -> pd.DataFrame:
    """
    Greedily pick the best 15 within FPL squad constraints and budget cap.
    Returns the selected squad DataFrame with projected_gw_pts column.
    """
    df = players_df[players_df["status"] == "a"].copy()
    df["gw_fdr_list"]   = df["team_id"].map(lambda t: fdr_map.get(int(t), []))
    df["projected_gw"]  = df.apply(lambda r: _projected_pts(r, r["gw_fdr_list"]), axis=1)
    df["n_fixtures"]    = df["gw_fdr_list"].apply(len)

    selected = []
    pos_counts: Dict[str, int] = {p: 0 for p in SQUAD_LIMITS}
    total_cost = 0.0
    teams_in: Dict[int, int] = {}

    for _, row in df.sort_values("projected_gw", ascending=False).iterrows():
        pos  = str(row.get("position", ""))
        cost = float(row.get("price", 0) or 0)
        tid  = int(row.get("team_id", 0) or 0)

        if pos not in pos_counts:
            continue
        if pos_counts[pos] >= SQUAD_LIMITS[pos]:
            continue
        if total_cost + cost > BUDGET_CAP:
            continue
        if teams_in.get(tid, 0) >= 3:
            continue
        if len(selected) >= SQUAD_TOTAL:
            break

        selected.append(row)
        pos_counts[pos] += 1
        total_cost += cost
        teams_in[tid] = teams_in.get(tid, 0) + 1

    return pd.DataFrame(selected) if selected else pd.DataFrame()


def compute_wildcard_scores(
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    current_gw: int,
    last_gw: int = 38,
) -> pd.DataFrame:
    """
    For each remaining GW, compute the total projected pts for the optimal 15-man squad.
    Returns DataFrame with columns: gw, total_pts, squad, n_dgw, n_bgw
    """
    results = []
    for gw in range(current_gw + 1, last_gw + 1):
        fdr_map = _gw_fdr_map(fixtures_df, gw)
        squad   = _pick_optimal_squad(players_df, fdr_map)
        if squad.empty:
            total_pts = 0.0
            n_dgw = n_bgw = 0
        else:
            total_pts = float(squad["projected_gw"].sum())
            n_dgw = int((squad["n_fixtures"] >= 2).sum())
            n_bgw = int((squad["n_fixtures"] == 0).sum())
        results.append({
            "gw":       gw,
            "total_pts": round(total_pts, 1),
            "n_dgw":    n_dgw,
            "n_bgw":    n_bgw,
            "squad":    squad,
        })
    return pd.DataFrame(results)


def _shirt_url(team_code: int, is_gkp: bool) -> str:
    t = "2" if is_gkp else "1"
    return f"{SHIRT_BASE}/shirt_{team_code}_{t}-66.png"


def _squad_preview_html(squad: pd.DataFrame, players_df: pd.DataFrame) -> str:
    """Render a compact squad preview grid for the selected GW."""
    if squad.empty:
        return "<p style='color:rgba(255,255,255,0.4);'>No squad data.</p>"

    if "team_code" not in squad.columns:
        tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
        squad = squad.merge(tc, on="fpl_id", how="left")

    fallback = f"{SHIRT_BASE}/shirt_1_1-66.png"
    html_parts = []

    for pos in ["GKP", "DEF", "MID", "FWD"]:
        pos_players = squad[squad["position"] == pos].sort_values("projected_gw", ascending=False)
        if pos_players.empty:
            continue
        pos_col = POS_COLORS.get(pos, "#888")
        cards = []
        for _, p in pos_players.iterrows():
            code  = int(p.get("team_code", 1) or 1)
            is_g  = pos == "GKP"
            shirt = _shirt_url(code, is_g)
            name  = str(p.get("web_name", "?"))[:9]
            pts   = float(p.get("projected_gw", 0) or 0)
            price = float(p.get("price", 0) or 0)
            nfix  = int(p.get("n_fixtures", 1))
            dgw_tag = ('<div style="background:#f5c518;color:#000;border-radius:2px;'
                       'font-size:8px;font-weight:900;padding:0 3px;">DGW</div>') if nfix >= 2 else ""
            cards.append(
                f'<div style="text-align:center;width:70px;">'
                f'<img src="{shirt}" width="36" onerror="this.src=\'{fallback}\'"/>'
                f'{dgw_tag}'
                f'<div style="font-size:10px;color:#fff;font-weight:700;margin-top:2px;">{name}</div>'
                f'<div style="font-size:10px;color:#00FF87;">£{price:.1f}m</div>'
                f'<div style="font-size:10px;color:#04f5ff;">{pts:.1f}pts</div>'
                f'</div>'
            )
        html_parts.append(
            f'<div style="margin-bottom:8px;">'
            f'<div style="font-size:10px;font-weight:700;color:{pos_col};letter-spacing:2px;margin-bottom:4px;">{pos}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:6px;">{"".join(cards)}</div>'
            f'</div>'
        )

    return (
        f'<div style="font-family:sans-serif;background:rgba(255,255,255,0.03);'
        f'border-radius:12px;padding:16px;">'
        + "".join(html_parts) +
        "</div>"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("🃏 Wildcard Planner")
st.caption(
    "Find the best remaining gameweek to play your Wildcard. "
    "We simulate the optimal 15-man squad for each GW and score it by projected points."
)

with st.spinner("Simulating remaining gameweeks..."):
    players_df, bootstrap, fixtures_df, current_gw = load_data()
    wc_scores = compute_wildcard_scores(players_df, fixtures_df, current_gw)

if wc_scores.empty:
    st.warning("No remaining gameweeks to analyse.")
    st.stop()

# ── Best GW highlight ──────────────────────────────────────────────────────────
best_row = wc_scores.loc[wc_scores["total_pts"].idxmax()]
best_gw  = int(best_row["gw"])

m1, m2, m3 = st.columns(3)
m1.metric("Best Wildcard GW", f"GW{best_gw}", f"{best_row['total_pts']:.1f} projected pts")
m2.metric("DGW players in that squad", f"{int(best_row['n_dgw'])}", "Double Gameweek")
m3.metric("GWs remaining", f"{len(wc_scores)}", "to analyse")

st.markdown("---")

# ── Main chart ────────────────────────────────────────────────────────────────
st.markdown("### Wildcard Opportunity by Gameweek")
st.caption("Projected points total for the optimal 15-man squad in each remaining GW. Higher = better wildcard timing.")

# Color bars: gold for best, green for DGW-heavy, normal for rest
bar_colors = []
for _, row in wc_scores.iterrows():
    if int(row["gw"]) == best_gw:
        bar_colors.append("#FFD700")
    elif row["n_dgw"] >= 3:
        bar_colors.append("#00FF87")
    else:
        bar_colors.append("#04f5ff")

fig = go.Figure()
fig.add_trace(go.Bar(
    x=wc_scores["gw"].astype(str).tolist(),
    y=wc_scores["total_pts"].tolist(),
    marker_color=bar_colors,
    hovertemplate=(
        "GW%{x}<br>"
        "Projected pts: <b>%{y:.1f}</b><extra></extra>"
    ),
    text=wc_scores["total_pts"].round(1).tolist(),
    textposition="outside",
    textfont=dict(size=10),
))

# Annotate DGWs
for _, row in wc_scores.iterrows():
    if row["n_dgw"] >= 2:
        fig.add_annotation(
            x=str(int(row["gw"])),
            y=row["total_pts"] + 2,
            text=f"🟡 {int(row['n_dgw'])}x DGW",
            showarrow=False,
            font=dict(size=9, color="#f5c518"),
        )

fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=380,
    xaxis=dict(title="Gameweek", tickfont=dict(color="rgba(255,255,255,0.6)")),
    yaxis=dict(title="Projected Pts (15 players)", showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
    font=dict(color="rgba(255,255,255,0.8)"),
    margin=dict(t=20, b=20),
)
fig.add_hline(
    y=float(wc_scores["total_pts"].mean()),
    line_dash="dot",
    line_color="rgba(255,255,255,0.3)",
    annotation_text=f"Avg: {wc_scores['total_pts'].mean():.1f}",
    annotation_position="top right",
)
st.plotly_chart(fig, use_container_width=True)

# ── Legend ────────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='font-size:12px;color:rgba(255,255,255,0.4);'>"
    "<span style='color:#FFD700;'>■</span> Best GW &nbsp;&nbsp;"
    "<span style='color:#00FF87;'>■</span> DGW-heavy &nbsp;&nbsp;"
    "<span style='color:#04f5ff;'>■</span> Standard"
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ── Optimal squad preview ──────────────────────────────────────────────────────
st.markdown("### Preview Optimal Squad for any GW")

remaining_gws = wc_scores["gw"].tolist()
selected_gw = st.selectbox(
    "Select a gameweek to preview",
    remaining_gws,
    index=remaining_gws.index(best_gw) if best_gw in remaining_gws else 0,
    format_func=lambda g: f"GW{g}" + (" ⭐ Best" if g == best_gw else ""),
)

gw_row = wc_scores[wc_scores["gw"] == selected_gw].iloc[0]
gw_squad = gw_row["squad"]

col_info, col_squad = st.columns([1, 2])

with col_info:
    st.markdown(f"#### GW{selected_gw} — Optimal Squad")
    if not gw_squad.empty:
        total_cost = float(gw_squad["price"].sum()) if "price" in gw_squad.columns else 0.0
        st.metric("Projected total pts",  f"{gw_row['total_pts']:.1f}")
        st.metric("Squad cost",           f"£{total_cost:.1f}m")
        st.metric("DGW players",          f"{int(gw_row['n_dgw'])}")
        st.metric("BGW players (blank)",  f"{int(gw_row['n_bgw'])}")

        if int(gw_row["n_dgw"]) > 0:
            dgw_names = gw_squad[gw_squad["n_fixtures"] >= 2]["web_name"].tolist()
            st.success(f"DGW players: {', '.join(dgw_names)}")
        if int(gw_row["n_bgw"]) > 0:
            bgw_names = gw_squad[gw_squad["n_fixtures"] == 0]["web_name"].tolist()
            st.warning(f"Blanking: {', '.join(bgw_names)}")

with col_squad:
    st.markdown(_squad_preview_html(gw_squad, players_df), unsafe_allow_html=True)
