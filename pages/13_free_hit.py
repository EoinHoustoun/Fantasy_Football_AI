"""
Free Hit Optimizer — finds the highest-scoring 15-man squad for a specific GW
using ML predictions, then compares it position-by-position to your current team.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

st.set_page_config(page_title="Free Hit — FPL Hub", layout="wide")

SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}
POS_ORDER  = ["GKP", "DEF", "MID", "FWD"]


# ── Data helpers ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def run_model(current_gw: int, captain_gw: int):
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    from analytics.points_model import run_pipeline

    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    players_df = build_player_universe(bootstrap=bs, understat_df=understat_df)

    fixtures_raw = fetch_fixtures()
    fixtures_df  = get_fixtures_df(fixtures_raw, bs)
    gw_fix = fixtures_df[fixtures_df["gameweek"] == captain_gw]
    fdr_map = {}
    for _, row in gw_fix.iterrows():
        fdr_map[int(row["home_team_id"])] = float(row["home_fdr"])
        fdr_map[int(row["away_team_id"])] = float(row["away_fdr"])

    predictions, metrics = run_pipeline(players_df, current_gw, fdr_map=fdr_map)
    return predictions, metrics, players_df


@st.cache_data(ttl=1800, show_spinner=False)
def load_squad_info(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_team_info, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, entry_history = get_team_squad(team_id, gw, bootstrap=bs)
    team_info = fetch_team_info(team_id)
    return squad_df, entry_history, team_info


def get_next_gw(bootstrap: dict, current_gw: int) -> int:
    for e in bootstrap["events"]:
        if e.get("is_next"):
            return e["id"]
    return current_gw + 1


# ── HTML helpers ───────────────────────────────────────────────────────────────

def _shirt_url(team_code: int, is_gkp: bool) -> str:
    t = "2" if is_gkp else "1"
    return f"{SHIRT_BASE}/shirt_{team_code}_{t}-66.png"


def _squad_grid_html(squad: pd.DataFrame, players_df: pd.DataFrame, title: str, accent: str) -> str:
    """Render a squad as a position-grouped grid of shirt cards."""
    if squad.empty:
        return f"<p style='color:rgba(255,255,255,0.4);'>{title}: no data</p>"

    # Merge team_code
    if "team_code" not in squad.columns:
        tc = players_df[["web_name", "team_code"]].drop_duplicates("web_name")
        squad = squad.merge(tc, on="web_name", how="left")

    fallback = f"{SHIRT_BASE}/shirt_1_1-66.png"
    html_parts = [
        f"<div style='font-size:13px;font-weight:700;color:{accent};"
        f"letter-spacing:0.05em;margin-bottom:12px;'>{title}</div>"
    ]

    for pos in POS_ORDER:
        pos_players = squad[squad["position"] == pos].sort_values("predicted_pts", ascending=False)
        if pos_players.empty:
            continue
        pc = POS_COLORS.get(pos, "#888")
        cards = []
        for _, p in pos_players.iterrows():
            code  = int(p.get("team_code", 1) or 1)
            shirt = _shirt_url(code, pos == "GKP")
            name  = str(p.get("web_name", "?"))
            name  = (name[:8] + ".") if len(name) > 9 else name
            pts   = float(p.get("predicted_pts", 0) or 0)
            price = float(p.get("price", 0) or 0)
            cards.append(
                f'<div style="text-align:center;width:72px;">'
                f'<img src="{shirt}" width="42" onerror="this.src=\'{fallback}\'"/>'
                f'<div style="font-size:10px;color:#fff;font-weight:700;margin-top:3px;'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{name}</div>'
                f'<div style="font-size:10px;color:#00FF87;font-weight:700;">{pts:.1f}pt</div>'
                f'<div style="font-size:9px;color:rgba(255,255,255,0.35);">£{price:.1f}m</div>'
                f'</div>'
            )
        html_parts.append(
            f'<div style="margin-bottom:10px;">'
            f'<div style="font-size:9px;font-weight:700;color:{pc};'
            f'letter-spacing:2px;margin-bottom:5px;">{pos}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:6px;">{"".join(cards)}</div>'
            f'</div>'
        )

    return (
        f'<div style="font-family:sans-serif;background:rgba(255,255,255,0.03);'
        f'border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:18px;">'
        + "".join(html_parts) + "</div>"
    )


def _comparison_chart(breakdown: pd.DataFrame, optimal_total: float, your_total: float) -> go.Figure:
    """Side-by-side bar chart: your pts vs optimal pts per position."""
    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="Your Team",
        x=breakdown["position"].tolist(),
        y=breakdown["your_pts"].tolist(),
        marker_color="#04f5ff",
        text=breakdown["your_pts"].round(1).tolist(),
        textposition="outside",
        hovertemplate="%{x}: <b>%{y:.1f} pts</b><extra>Your team</extra>",
    ))
    fig.add_trace(go.Bar(
        name="Optimal Free Hit",
        x=breakdown["position"].tolist(),
        y=breakdown["optimal_pts"].tolist(),
        marker_color="#00FF87",
        text=breakdown["optimal_pts"].round(1).tolist(),
        textposition="outside",
        hovertemplate="%{x}: <b>%{y:.1f} pts</b><extra>Optimal team</extra>",
    ))

    fig.update_layout(
        barmode="group",
        title=f"Position-by-Position Comparison  |  Your XI: {your_total:.1f}pts  vs  Optimal XI: {optimal_total:.1f}pts",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=340,
        legend=dict(bgcolor="rgba(0,0,0,0.3)", bordercolor="rgba(255,255,255,0.1)", borderwidth=1),
        font=dict(color="rgba(255,255,255,0.8)"),
        xaxis=dict(tickfont=dict(size=13, color="#e2e2e2")),
        yaxis=dict(title="Predicted pts", gridcolor="rgba(255,255,255,0.06)", showgrid=True),
        margin=dict(t=60, b=10),
    )
    return fig


def _delta_cards_html(breakdown: pd.DataFrame) -> str:
    """Show per-position gain/loss as colourful summary cards."""
    cards = []
    for _, row in breakdown.iterrows():
        pos   = str(row["position"])
        diff  = float(row["difference"])
        opt   = float(row["optimal_pts"])
        yours = float(row["your_pts"])
        pc    = POS_COLORS.get(pos, "#888")
        diff_color = "#00FF87" if diff > 0.5 else "#FF4B4B" if diff < -0.5 else "#aaa"
        sign = "+" if diff >= 0 else ""
        verb = "better" if diff > 0 else "worse" if diff < 0 else "same"
        cards.append(
            f'<div style="flex:1;background:rgba(255,255,255,0.03);'
            f'border:1px solid rgba(255,255,255,0.08);border-top:3px solid {pc};'
            f'border-radius:10px;padding:16px;text-align:center;font-family:sans-serif;">'
            f'<div style="font-size:11px;font-weight:700;color:{pc};letter-spacing:2px;margin-bottom:6px;">{pos}</div>'
            f'<div style="font-size:28px;font-weight:900;color:{diff_color};line-height:1;">{sign}{diff:.1f}</div>'
            f'<div style="font-size:11px;color:rgba(255,255,255,0.4);margin-top:4px;">'
            f'pts {verb}</div>'
            f'<div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:6px;">'
            f'{yours:.1f} → {opt:.1f}</div>'
            f'</div>'
        )
    return f'<div style="display:flex;gap:12px;margin:16px 0;">{"".join(cards)}</div>'


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("🎯 Free Hit Optimizer")
st.caption("Find the highest-scoring 15-man squad for a specific gameweek, then see exactly where you gain and lose vs your current team.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Settings")
    from config import FPL_TEAM_ID
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input("Your FPL Team ID", min_value=1, value=default_id, step=1)
    budget  = st.slider("Budget (£m)", min_value=95.0, max_value=105.0, value=100.0, step=0.5,
                        help="Use your team value + bank from My Team page for the most accurate result.")
    st.markdown("---")
    st.markdown("**How it works**")
    st.caption(
        "The ML model predicts each player's points for the target GW. "
        "The optimizer then picks the 15-player squad that maximises "
        "total predicted XI points within FPL squad constraints and your budget. "
        "Then we show exactly how much each position gains or loses vs your current squad."
    )

# ── Load ──────────────────────────────────────────────────────────────────────
from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
bs         = fetch_bootstrap()
current_gw = get_current_gameweek(bs)
target_gw  = get_next_gw(bs, current_gw)

st.caption(f"Optimised for **Gameweek {target_gw}** · Budget: **£{budget:.1f}m**")

with st.spinner("Training model & building optimal squad..."):
    predictions, metrics, players_df = run_model(current_gw, target_gw)

# Merge team_code into predictions for shirt rendering
if "team_code" not in predictions.columns:
    tc = players_df[["web_name", "team_code"]].drop_duplicates("web_name")
    predictions = predictions.merge(tc, on="web_name", how="left")

# Filter out managers / players with no position
predictions = predictions[predictions["position"].notna()].copy()

mae = metrics["mae"]

# ── Build optimal squad ────────────────────────────────────────────────────────
from analytics.points_model import optimize_free_hit_squad, select_best_xi, compare_squads

optimal_squad = optimize_free_hit_squad(predictions, budget=budget)
optimal_xi    = select_best_xi(optimal_squad)

total_cost = float(optimal_squad["price"].sum()) if not optimal_squad.empty else 0.0
opt_total  = float(optimal_xi["predicted_pts"].sum()) if not optimal_xi.empty else 0.0

# ── Load user squad if team_id provided ───────────────────────────────────────
comparison = None
squad_df   = None
if team_id and team_id > 0:
    try:
        with st.spinner(f"Loading your squad {team_id}..."):
            squad_df, entry_history, team_info = load_squad_info(team_id, current_gw)

        # Merge predictions onto user squad
        user_preds = squad_df.merge(
            predictions[["web_name", "predicted_pts", "position", "price",
                         "team_code", "next_gw_fdr", "roll_pts_4"]],
            on="web_name", how="left",
            suffixes=("", "_pred"),
        )
        for col in ["position", "price"]:
            if col + "_pred" in user_preds.columns:
                user_preds[col] = user_preds[col].fillna(user_preds[col + "_pred"])
        user_preds["predicted_pts"] = user_preds["predicted_pts"].fillna(0)

        # Use bank + team value as actual budget suggestion
        bank_m  = entry_history.get("bank", 0) / 10
        value_m = entry_history.get("value", 0) / 10
        suggested_budget = round(bank_m + value_m, 1)
        team_name = team_info.get("name", f"Team {team_id}")

        with st.sidebar:
            st.info(f"**{team_name}**\nBank: £{bank_m:.1f}m\nTeam value: £{value_m:.1f}m\n**Suggested budget: £{suggested_budget:.1f}m**")

        comparison = compare_squads(optimal_squad, user_preds)

    except Exception as e:
        st.sidebar.warning(f"Could not load squad: {e}")

# ── Top summary metrics ────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric(f"Optimal XI predicted pts", f"{opt_total:.1f}")
m2.metric("Squad cost",               f"£{total_cost:.1f}m")
m3.metric("Model MAE",                f"±{mae:.1f} pts",
          help="Typical error per player prediction")
if comparison:
    gain = comparison["gain"]
    m4.metric("Gain vs your current XI",
              f"{'+' if gain >= 0 else ''}{gain:.1f} pts",
              delta_color="normal" if gain >= 0 else "inverse")
else:
    m4.metric("Players available", f"{len(predictions):,}")

st.markdown("---")

# ── Comparison section ────────────────────────────────────────────────────────
if comparison:
    st.markdown(f"### {team_name} vs Optimal Free Hit — GW{target_gw}")
    bd = comparison["breakdown"]

    # Delta cards
    st.markdown(_delta_cards_html(bd), unsafe_allow_html=True)

    # Side-by-side bar chart
    fig_cmp = _comparison_chart(bd, comparison["optimal_total"], comparison["your_total"])
    st.plotly_chart(fig_cmp, use_container_width=True)

    # Narrative summary
    top_gain = bd.loc[bd["difference"].idxmax()]
    top_loss = bd.loc[bd["difference"].idxmin()]
    narrative_parts = []
    for _, row in bd.iterrows():
        d = float(row["difference"])
        pos = str(row["position"])
        if d > 1:
            narrative_parts.append(f"**{pos}** outscores your current {pos}s by **+{d:.1f} pts**")
        elif d < -1:
            narrative_parts.append(f"**{pos}** is weaker than your current {pos}s by **{d:.1f} pts**")
    if narrative_parts:
        overall = comparison["gain"]
        sign = "+" if overall >= 0 else ""
        st.markdown(
            f"<div style='padding:14px 18px;background:rgba(0,255,135,0.06);"
            f"border-left:3px solid #00FF87;border-radius:8px;font-size:13px;'>"
            f"<b>Summary:</b> {' · '.join(narrative_parts)}. "
            f"Overall the optimal Free Hit XI scores <b>{sign}{overall:.1f} pts</b> "
            f"{'more' if overall >= 0 else 'fewer'} than your current team.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Side-by-side squad grids
    col_yours, col_opt = st.columns(2)
    with col_yours:
        your_xi = comparison["your_xi"]
        st.markdown(
            _squad_grid_html(your_xi, players_df, f"Your Current XI — {comparison['your_total']:.1f} pts", "#04f5ff"),
            unsafe_allow_html=True,
        )
    with col_opt:
        st.markdown(
            _squad_grid_html(comparison["optimal_xi"], players_df, f"Optimal Free Hit XI — {comparison['optimal_total']:.1f} pts", "#00FF87"),
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Swaps: players in optimal but not in your squad
    st.markdown("### Key Differences")
    your_names  = set(comparison["your_xi"]["web_name"].tolist())
    opt_names   = set(comparison["optimal_xi"]["web_name"].tolist())
    to_bring_in = comparison["optimal_xi"][~comparison["optimal_xi"]["web_name"].isin(your_names)].copy()
    to_drop     = comparison["your_xi"][~comparison["your_xi"]["web_name"].isin(opt_names)].copy()

    if not to_bring_in.empty or not to_drop.empty:
        sw1, sw2 = st.columns(2)
        with sw1:
            st.markdown("**Bring in for Free Hit**")
            for _, row in to_bring_in.sort_values("predicted_pts", ascending=False).iterrows():
                pos = str(row.get("position", ""))
                pc  = POS_COLORS.get(pos, "#888")
                pts = float(row.get("predicted_pts", 0))
                st.markdown(
                    f"<div style='padding:8px 14px;background:rgba(0,255,135,0.07);"
                    f"border-left:3px solid #00FF87;border-radius:6px;margin-bottom:6px;"
                    f"font-family:sans-serif;font-size:13px;'>"
                    f"<span style='background:{pc};color:#000;border-radius:3px;"
                    f"padding:0 5px;font-weight:700;font-size:10px;margin-right:8px;'>{pos}</span>"
                    f"<b>{row.get('web_name','?')}</b> ({row.get('team','')}) "
                    f"· £{float(row.get('price',0)):.1f}m "
                    f"· <span style='color:#00FF87;font-weight:700;'>{pts:.1f} pts</span></div>",
                    unsafe_allow_html=True,
                )
        with sw2:
            st.markdown("**Drop for Free Hit**")
            for _, row in to_drop.sort_values("predicted_pts").iterrows():
                pos = str(row.get("position", ""))
                pc  = POS_COLORS.get(pos, "#888")
                pts = float(row.get("predicted_pts", 0))
                st.markdown(
                    f"<div style='padding:8px 14px;background:rgba(255,75,75,0.07);"
                    f"border-left:3px solid #FF4B4B;border-radius:6px;margin-bottom:6px;"
                    f"font-family:sans-serif;font-size:13px;'>"
                    f"<span style='background:{pc};color:#000;border-radius:3px;"
                    f"padding:0 5px;font-weight:700;font-size:10px;margin-right:8px;'>{pos}</span>"
                    f"<b>{row.get('web_name','?')}</b> ({row.get('team','')}) "
                    f"· £{float(row.get('price',0)):.1f}m "
                    f"· <span style='color:#FF4B4B;font-weight:700;'>{pts:.1f} pts</span></div>",
                    unsafe_allow_html=True,
                )
    st.markdown("---")

else:
    st.info("Enter your FPL Team ID in the sidebar to compare the optimal team against your current squad.")

# ── Optimal squad standalone ───────────────────────────────────────────────────
st.markdown(f"### Optimal Free Hit Squad — GW{target_gw}")
st.caption(f"Best 15 players within £{budget:.1f}m · Squad cost: £{total_cost:.1f}m")

col_grid, col_table = st.columns([1, 1])

with col_grid:
    st.markdown(
        _squad_grid_html(optimal_xi, players_df, f"Starting XI — {opt_total:.1f} predicted pts", "#00FF87"),
        unsafe_allow_html=True,
    )
    # Bench
    bench = optimal_squad[~optimal_squad.index.isin(optimal_xi.index)]
    if not bench.empty:
        bench_total = float(bench["predicted_pts"].sum())
        st.markdown(
            _squad_grid_html(bench, players_df, f"Bench — {bench_total:.1f} predicted pts", "rgba(255,255,255,0.3)"),
            unsafe_allow_html=True,
        )

with col_table:
    display_cols = ["web_name", "team", "position", "price", "predicted_pts",
                    "next_gw_fdr", "roll_pts_4", "ownership"]
    display_cols = [c for c in display_cols if c in optimal_squad.columns]
    tbl = optimal_squad[display_cols].copy()
    tbl = tbl.sort_values("predicted_pts", ascending=False)
    tbl["price"] = tbl["price"].apply(lambda x: f"£{x:.1f}m")
    if "ownership" in tbl.columns:
        tbl["ownership"] = tbl["ownership"].apply(lambda x: f"{x:.1f}%")
    tbl = tbl.rename(columns={
        "web_name": "Player", "team": "Team", "position": "Pos",
        "price": "Price", "predicted_pts": "Predicted pts",
        "next_gw_fdr": "FDR", "roll_pts_4": "Avg last 4",
        "ownership": "Own%",
    })
    if "Predicted pts" in tbl.columns:
        tbl["Predicted pts"] = tbl["Predicted pts"].round(1)
    if "Avg last 4" in tbl.columns:
        tbl["Avg last 4"] = tbl["Avg last 4"].round(1)
    st.dataframe(tbl, use_container_width=True, hide_index=True)

    # Position breakdown
    pos_sum = optimal_xi.groupby("position")["predicted_pts"].sum().reindex(POS_ORDER).fillna(0)
    fig_pie = px.pie(
        values=pos_sum.values,
        names=pos_sum.index,
        color=pos_sum.index,
        color_discrete_map=POS_COLORS,
        title="Points by position (optimal XI)",
        hole=0.5,
    )
    fig_pie.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        height=220,
        margin=dict(t=40, b=0, l=0, r=0),
        font=dict(color="rgba(255,255,255,0.7)", size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        showlegend=True,
    )
    st.plotly_chart(fig_pie, use_container_width=True)
