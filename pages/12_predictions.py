"""
GW Points Predictions — ML model trained on this season's GW-by-GW data.

Model: Random Forest trained on vaastav historical data (GW1 → current).
Features: rolling pts, rolling xGI, rolling minutes, form, price, was_home, position.
Evaluated on a temporal holdout (last 30% of GWs) for honest out-of-sample RMSE.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

st.set_page_config(page_title="Predictions — FPL Hub", layout="wide")

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#ff6900"}
SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"


# ── Data loading ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def run_model(current_gw: int, captain_gw: int):
    """Train model and return predictions + metrics. Cached 6 hours."""
    from data.fetchers.fpl_api import fetch_bootstrap, fetch_fixtures, get_fixtures_df
    from data.fetchers.understat import fetch_understat_players
    from data.processors.player_stats import build_player_universe
    from analytics.points_model import run_pipeline

    bs = fetch_bootstrap()
    understat_df = fetch_understat_players()
    players_df = build_player_universe(bootstrap=bs, understat_df=understat_df)

    # Build next-GW FDR map
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
def load_squad(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad_df


def get_next_gw(bootstrap: dict, current_gw: int) -> int:
    for e in bootstrap["events"]:
        if e.get("is_next"):
            return e["id"]
    return current_gw + 1


# ── HTML helpers ────────────────────────────────────────────────────────────────

def _prediction_card(player: pd.Series, rank: int, mae: float) -> str:
    """Render a single player prediction card."""
    name    = str(player.get("web_name", "?"))
    team    = str(player.get("team", ""))
    pos     = str(player.get("position", ""))
    price   = float(player.get("price", 0) or 0)
    pts     = float(player.get("predicted_pts", 0) or 0)
    low     = max(0, pts - mae)
    high    = pts + mae
    fdr     = float(player.get("next_gw_fdr", 3.0) or 3.0)
    form    = float(player.get("form", 0) or 0)
    own     = float(player.get("ownership", 0) or 0)
    roll4   = float(player.get("roll_pts_4", 0) or 0)

    pos_col   = POS_COLORS.get(pos, "#888")
    fdr_color = {1:"#00FF87",2:"#00FF87",3:"#FFA500",4:"#FF6B6B",5:"#FF4B4B"}.get(int(fdr),"#FFA500")
    rank_labels = {1:"🥇",2:"🥈",3:"🥉"}
    rank_str = rank_labels.get(rank, f"#{rank}")

    return f"""
    <div style="
        background:rgba(255,255,255,0.03);
        border:1px solid rgba(255,255,255,0.09);
        border-left:3px solid {pos_col};
        border-radius:10px;
        padding:14px 16px;
        display:flex;
        align-items:center;
        gap:16px;
        font-family:sans-serif;
        margin-bottom:8px;
    ">
      <div style="font-size:20px;width:32px;text-align:center;flex-shrink:0;">{rank_str}</div>
      <div style="flex:1;min-width:0;">
        <div style="font-size:15px;font-weight:800;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{name}</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.4);">
          <span style="background:{pos_col};color:#000;border-radius:2px;padding:0 5px;font-weight:700;font-size:10px;margin-right:5px;">{pos}</span>
          {team} · £{price:.1f}m · {own:.1f}% owned
        </div>
      </div>
      <div style="display:flex;gap:18px;flex-shrink:0;text-align:center;">
        <div>
          <div style="font-size:20px;font-weight:900;color:#00FF87;">{pts:.1f}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.35);">Predicted</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.25);">{low:.1f}–{high:.1f}</div>
        </div>
        <div>
          <div style="font-size:16px;font-weight:700;color:#04f5ff;">{roll4:.1f}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.35);">Avg last 4</div>
        </div>
        <div>
          <div style="font-size:16px;font-weight:700;color:{fdr_color};">{fdr:.0f}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.35);">FDR</div>
        </div>
      </div>
    </div>
    """


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("🤖 GW Predictions")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Your Squad")
    from config import FPL_TEAM_ID
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input("FPL Team ID", min_value=1, value=default_id, step=1)
    pos_filter = st.selectbox("Position filter", ["All", "GKP", "DEF", "MID", "FWD"])
    top_n = st.slider("Show top N players", 10, 50, 20, step=5)
    st.markdown("---")
    st.markdown("**About the model**")
    st.caption(
        "Random Forest trained on this season's GW-by-GW data. "
        "Features: rolling pts, xGI, minutes, form, price, position, home/away. "
        "RMSE measured on last 30% of GWs (out-of-sample)."
    )

# Load
from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
bs = fetch_bootstrap()
current_gw  = get_current_gameweek(bs)
captain_gw  = get_next_gw(bs, current_gw)

st.caption(f"Predictions for **Gameweek {captain_gw}** · Model trained on GW1–{current_gw}")

with st.spinner("Training model and generating predictions..."):
    predictions, metrics, players_df = run_model(current_gw, captain_gw)

mae  = metrics["mae"]
rmse = metrics["rmse"]
r2   = metrics["r2"]

# Filter out managers (players with no FPL position match)
predictions = predictions[predictions["position"].notna()].copy()

# ── Model accuracy header ──────────────────────────────────────────────────────
st.markdown("### Model Accuracy")
st.caption(
    f"Tested on GW{metrics['test_gws'][0]}–{metrics['test_gws'][1]} "
    f"({metrics['n_test']:,} player-GW predictions). "
    f"Trained on GW{metrics['train_gws'][0]}–{metrics['train_gws'][1]}."
)

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "RMSE",
    f"{rmse:.2f} pts",
    help="Root Mean Squared Error — penalises big misses more heavily than small ones.",
)
m2.metric(
    "MAE",
    f"{mae:.2f} pts",
    help="Mean Absolute Error — on average, predictions are this many points off.",
)
m3.metric(
    "R²",
    f"{r2:.3f}",
    help="Proportion of variance explained. FPL is inherently noisy — 0.28 is solid.",
)
m4.metric(
    "Prediction range",
    f"±{mae:.1f} pts",
    help="Use this as the typical error band around any single prediction.",
)

# Friendly interpretation
if mae < 1.5:
    interp_col, interp_txt = "#00FF87", f"On average predictions are **{mae:.1f} pts off** per player per GW — a solid baseline."
elif mae < 2.5:
    interp_col, interp_txt = "#FFA500", f"Predictions average **{mae:.1f} pts off** — decent for FPL's inherent randomness."
else:
    interp_col, interp_txt = "#FF4B4B", f"Average error of **{mae:.1f} pts** — use predictions directionally, not literally."

st.markdown(
    f"<div style='padding:10px 16px;background:rgba(255,255,255,0.03);"
    f"border-left:3px solid {interp_col};border-radius:6px;font-size:13px;'>"
    f"{interp_txt} Predicting Bruno Fernandes to score 5.1 pts means: likely between "
    f"{max(0, 5.1 - mae):.1f} and {5.1 + mae:.1f} pts.</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ── Charts row ─────────────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns([1, 1, 1])

with col_a:
    # RMSE by position bar chart
    pos_rmse = metrics.get("pos_rmse", {})
    if pos_rmse:
        pos_df = pd.DataFrame(
            [(pos, v) for pos, v in pos_rmse.items()],
            columns=["Position", "RMSE"],
        ).sort_values("RMSE")
        fig_pos = px.bar(
            pos_df, x="Position", y="RMSE",
            color="Position",
            color_discrete_map=POS_COLORS,
            title="RMSE by Position",
            labels={"RMSE": "RMSE (pts)"},
            text=pos_df["RMSE"].round(2),
        )
        fig_pos.update_traces(textposition="outside")
        fig_pos.update_layout(
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=260,
            font=dict(color="rgba(255,255,255,0.7)"),
            margin=dict(t=40, b=10),
            yaxis=dict(range=[0, pos_df["RMSE"].max() * 1.3]),
        )
        st.plotly_chart(fig_pos, use_container_width=True)

with col_b:
    # Feature importances
    imp = metrics.get("importances", {})
    if imp:
        FEATURE_LABELS = {
            "roll_pts_4":    "Avg pts (last 4 GWs)",
            "roll_xgi_4":    "xGI (last 4 GWs)",
            "roll_xgc_4":    "xGC (last 4 GWs)",
            "roll_mins_4":   "Minutes (last 4 GWs)",
            "roll_starts_4": "Start rate (last 4 GWs)",
            "roll_xp_4":     "xP (last 4 GWs)",
            "cum_ppg":       "Season PPG",
            "price_m":       "Price (£m)",
            "was_home":      "Home / Away",
            "is_gkp":        "Position: GKP",
            "is_def":        "Position: DEF",
            "is_mid":        "Position: MID",
            "is_fwd":        "Position: FWD",
        }
        imp_df = pd.DataFrame(
            [(FEATURE_LABELS.get(k, k), v) for k, v in imp.items()],
            columns=["Feature", "Importance"],
        ).sort_values("Importance")
        fig_imp = px.bar(
            imp_df, x="Importance", y="Feature",
            orientation="h",
            title="What drives the model",
            color="Importance",
            color_continuous_scale=["#16213e", "#00FF87"],
        )
        fig_imp.update_layout(
            coloraxis_showscale=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=260,
            font=dict(color="rgba(255,255,255,0.7)", size=11),
            margin=dict(t=40, b=10, l=0),
            xaxis=dict(showgrid=False, showticklabels=False),
        )
        st.plotly_chart(fig_imp, use_container_width=True)

with col_c:
    # Predicted vs actual scatter (test set sample)
    test_df = metrics.get("test_df")
    if test_df is not None and not test_df.empty:
        sample = test_df.sample(min(1000, len(test_df)), random_state=42)
        fig_scatter = px.scatter(
            sample,
            x="total_points",
            y="predicted",
            color="position",
            color_discrete_map=POS_COLORS,
            opacity=0.4,
            title="Predicted vs Actual (test set)",
            labels={"total_points": "Actual pts", "predicted": "Predicted pts"},
        )
        # Perfect prediction line
        max_val = max(float(sample["total_points"].max()), float(sample["predicted"].max()))
        fig_scatter.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.2)", dash="dash", width=1),
            showlegend=False,
            hoverinfo="skip",
        ))
        fig_scatter.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=260,
            font=dict(color="rgba(255,255,255,0.7)"),
            margin=dict(t=40, b=10),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

st.markdown("---")

# ── Your squad predictions ─────────────────────────────────────────────────────
squad_df = None
if team_id and team_id > 0:
    try:
        with st.spinner(f"Loading squad {team_id}..."):
            squad_df = load_squad(team_id, current_gw)
    except Exception:
        st.sidebar.warning("Could not load squad.")

if squad_df is not None:
    st.markdown(f"### Your Squad — GW{captain_gw} Predictions")
    owned_names = set(squad_df["web_name"].tolist())
    squad_preds = predictions[predictions["web_name"].isin(owned_names)].copy()

    if not squad_preds.empty:
        total_pred = squad_preds["predicted_pts"].sum()
        xi_preds   = squad_preds.sort_values("predicted_pts", ascending=False).head(11)
        xi_total   = xi_preds["predicted_pts"].sum()

        sq1, sq2, sq3 = st.columns(3)
        sq1.metric("Full squad predicted pts",  f"{total_pred:.1f}")
        sq2.metric("Best XI predicted pts",     f"{xi_total:.1f}")
        sq3.metric("Top predicted player",
                   squad_preds.iloc[0]["web_name"],
                   f"{squad_preds.iloc[0]['predicted_pts']:.1f} pts")

        cards_html = "".join(
            _prediction_card(squad_preds.iloc[i], i + 1, mae)
            for i in range(len(squad_preds))
        )
        st.markdown(cards_html, unsafe_allow_html=True)
    else:
        st.info("No squad players matched in predictions.")

    st.markdown("---")

# ── Global top predictions ─────────────────────────────────────────────────────
st.markdown(f"### Top Predicted Players — GW{captain_gw}")

preds_filtered = predictions.copy()
if pos_filter != "All":
    preds_filtered = preds_filtered[preds_filtered["position"] == pos_filter]
preds_filtered = preds_filtered.head(top_n)

if not preds_filtered.empty:
    col_cards, col_chart = st.columns([1, 1])

    with col_cards:
        cards_html = "".join(
            _prediction_card(preds_filtered.iloc[i], i + 1, mae)
            for i in range(min(10, len(preds_filtered)))
        )
        st.markdown(cards_html, unsafe_allow_html=True)

    with col_chart:
        fig_top = px.bar(
            preds_filtered.head(15),
            x="predicted_pts",
            y="web_name",
            color="position",
            orientation="h",
            color_discrete_map=POS_COLORS,
            error_x=preds_filtered.head(15)["predicted_pts"] * 0.35,
            title=f"Top 15 Predicted — GW{captain_gw}",
            labels={"predicted_pts": "Predicted pts", "web_name": ""},
        )
        fig_top.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=420,
            yaxis=dict(autorange="reversed"),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            font=dict(color="rgba(255,255,255,0.7)"),
            margin=dict(t=40, b=10, l=0),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(fig_top, use_container_width=True)

st.markdown("---")

# ── Model misses ──────────────────────────────────────────────────────────────
st.markdown("### Where the Model Gets It Wrong")
st.caption("Players the model consistently over-predicts or under-predicts in the test set.")

player_errors = metrics.get("player_errors")
if player_errors is not None and not player_errors.empty:
    # Filter out managers (no FPL position = likely manager)
    tracked_names = set(predictions["web_name"].tolist())
    pe = player_errors[
        (player_errors["name"].isin(tracked_names)) |
        (player_errors["gw_count"] >= 3)
    ].copy()

    col_over, col_under = st.columns(2)

    with col_over:
        st.markdown("**Over-predicted** *(model too optimistic)*")
        over = pe.nlargest(8, "mean_error")[["name", "actual_avg", "pred_avg", "mean_error", "gw_count"]]
        over = over.rename(columns={
            "name": "Player", "actual_avg": "Actual avg",
            "pred_avg": "Predicted avg", "mean_error": "Over by (pts)", "gw_count": "GWs",
        })
        over["Actual avg"]    = over["Actual avg"].round(1)
        over["Predicted avg"] = over["Predicted avg"].round(1)
        over["Over by (pts)"] = over["Over by (pts)"].round(1)
        st.dataframe(over, use_container_width=True, hide_index=True)
        st.caption("These players tend to blank or rotate more than their stats suggest.")

    with col_under:
        st.markdown("**Under-predicted** *(model too pessimistic)*")
        # Filter out managers first
        manager_keywords = ["Glasner", "Emery", "Howe", "Amorim", "Pereira", "Slot", "Maresca",
                            "Iraola", "Juric", "O'Neil", "Arteta", "Guardiola", "ten Hag",
                            "Postecoglou", "Moyes", "Dyche", "Farke", "Nuno"]
        pe_no_mgr = pe[~pe["name"].apply(
            lambda n: any(kw.lower() in str(n).lower() for kw in manager_keywords)
        )]
        under = pe_no_mgr.nsmallest(8, "mean_error")[["name", "actual_avg", "pred_avg", "mean_error", "gw_count"]]
        under = under.rename(columns={
            "name": "Player", "actual_avg": "Actual avg",
            "pred_avg": "Predicted avg", "mean_error": "Under by (pts)", "gw_count": "GWs",
        })
        under["Actual avg"]     = under["Actual avg"].round(1)
        under["Predicted avg"]  = under["Predicted avg"].round(1)
        under["Under by (pts)"] = under["Under by (pts)"].round(1)
        st.dataframe(under, use_container_width=True, hide_index=True)
        st.caption("These players regularly outperform their rolling stats — maybe set pieces, penalties, or squad role improved.")

st.markdown("---")

# ── Defcon Monsters ────────────────────────────────────────────────────────────
st.markdown("### 🛡️ Defcon Monsters")
st.caption(
    "Players most likely to rack up defensive contributions (clearances, blocks, interceptions, tackles). "
    "DEF need 10+ actions for +2 pts · MID/FWD need 12+. "
    "Score = reliability % × consistency (rewards 9,12,10,11 over 2,18,1,20)."
)

_defcon_cols = ["defcon_cbit_per_game", "defcon_pct", "defcon_consistency", "defcon_monster_score",
                "defcon_threshold", "defcon_games"]
_has_defcon  = all(c in players_df.columns for c in _defcon_cols[:4])

if not _has_defcon:
    st.info("DEFCON stats not yet available — they load with the player data. Try refreshing.")
else:
    _dc_pos_filter = st.radio(
        "Position",
        ["DEF", "MID / FWD", "All"],
        horizontal=True,
        key="defcon_pos",
    )

    dc_df = players_df.copy()
    dc_df = dc_df[dc_df["defcon_monster_score"].notna() & (dc_df["defcon_monster_score"] > 0)]

    if _dc_pos_filter == "DEF":
        dc_df = dc_df[dc_df["position"] == "DEF"]
    elif _dc_pos_filter == "MID / FWD":
        dc_df = dc_df[dc_df["position"].isin(["MID", "FWD"])]

    dc_df = dc_df.nlargest(20, "defcon_monster_score")

    if dc_df.empty:
        st.info("No DEFCON data for this filter.")
    else:
        # Horizontal bar chart
        dc_chart = dc_df.head(15).sort_values("defcon_monster_score")
        colors = [POS_COLORS.get(str(p).upper(), "#aaa") for p in dc_chart["position"]]

        fig_dc = go.Figure(go.Bar(
            x=dc_chart["defcon_monster_score"],
            y=dc_chart["web_name"],
            orientation="h",
            marker_color=colors,
            customdata=dc_chart[["defcon_pct", "defcon_consistency", "defcon_cbit_per_game", "avg_minutes", "position"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Monster Score: %{x:.2f}<br>"
                "Hit Rate: %{customdata[0]:.0%}<br>"
                "Consistency: %{customdata[1]:.2f}<br>"
                "Avg CBIT: %{customdata[2]:.1f}<br>"
                "Position: %{customdata[3]}<extra></extra>"
            ),
        ))
        fig_dc.update_layout(
            title="Defcon Monster Score (reliability × consistency)",
            xaxis_title="Monster Score",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e2e2",
            height=420,
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.0)"),
        )
        st.plotly_chart(fig_dc, use_container_width=True)

        # Table
        show_dc = dc_df[["web_name", "team", "position", "price",
                          "defcon_cbit_per_game", "defcon_pct", "defcon_consistency",
                          "defcon_monster_score", "defcon_games"]].copy()
        show_dc.columns = ["Player", "Team", "Pos", "Price",
                            "Avg CBIT", "Hit Rate", "Consistency",
                            "Monster Score", "Games"]
        show_dc["Price"]        = show_dc["Price"].apply(lambda x: f"£{x:.1f}m")
        show_dc["Hit Rate"]     = show_dc["Hit Rate"].apply(lambda x: f"{x:.0%}")
        show_dc["Consistency"]  = show_dc["Consistency"].round(2)
        show_dc["Monster Score"] = show_dc["Monster Score"].round(3)
        show_dc["Avg CBIT"]  = show_dc["Avg CBIT"].round(1)
        st.dataframe(show_dc, use_container_width=True, hide_index=True)

        with st.expander("ℹ️ How is this calculated?"):
            st.markdown("""
**Defensive BPS (proxy for CBIT):** We strip attacking returns from each player's per-GW BPS
(removing goals × 18, assists × 9, clean sheets × 12, saves × 2) to isolate the defensive
contribution component. This approximates clearances + blocks + interceptions + tackles.

**Hit Rate:** % of recent games where adjusted BPS hit the position threshold (DEF: 8, MID/FWD: 10).

**Consistency:** 1 − coefficient of variation. A player scoring 9,12,10,11 scores higher
than one scoring 2,18,1,20 even if both average the same — you can't rely on the spiky player.

**Monster Score = Hit Rate × Consistency** — the overall signal for likely DEFCON bonus points.
            """)

st.markdown("---")

# ── Full predictions table ─────────────────────────────────────────────────────
with st.expander(f"📋 Full predictions table — GW{captain_gw} ({len(predictions)} players)"):
    display = predictions[[
        "web_name", "team", "position", "price", "ownership",
        "predicted_pts", "next_gw_fdr", "roll_pts_4", "form",
    ]].copy()
    display.columns = ["Player", "Team", "Pos", "Price", "Own%",
                       "Predicted pts", "Next FDR", "Avg last 4 GWs", "Form"]
    display["Price"]       = display["Price"].apply(lambda x: f"£{x:.1f}m")
    display["Own%"]        = display["Own%"].apply(lambda x: f"{x:.1f}%")
    display["Predicted pts"] = display["Predicted pts"].round(1)
    display["Avg last 4 GWs"] = display["Avg last 4 GWs"].round(1)
    if pos_filter != "All":
        display = display[display["Pos"] == pos_filter]
    st.dataframe(display, use_container_width=True, hide_index=True)
