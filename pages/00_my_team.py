"""
My Team page.

Shows a manager's current squad, pitch view, sell candidates,
captain pick, transfer suggestions, and points history.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="My Team — FPL Hub", layout="wide")

# ── Data helpers ───────────────────────────────────────────────────────────────

def _get_players():
    if st.session_state.get("players_df") is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


@st.cache_data(ttl=1800, show_spinner=False)
def _load_team(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_team_info, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, entry_history = get_team_squad(team_id, gw, bootstrap=bs)
    team_info = fetch_team_info(team_id)
    return squad_df, entry_history, team_info


@st.cache_data(ttl=3600, show_spinner=False)
def _load_history(team_id: int):
    import requests
    resp = requests.get(
        f"https://fantasy.premierleague.com/api/entry/{team_id}/history/",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Team Lookup")
    from config import FPL_TEAM_ID
    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=int(FPL_TEAM_ID) if FPL_TEAM_ID else 1,
        step=1,
        help="Find your ID in the FPL URL: fantasy.premierleague.com/entry/XXXXXX/...",
    )
    st.caption("Enter any team ID to spy on a rival ⚡")

    st.markdown("---")
    st.markdown("### Transfer Filters")
    pos_filter   = st.selectbox("Replace position", ["All", "GKP", "DEF", "MID", "FWD"])
    budget_boost = st.slider(
        "Extra budget (£m)",
        0.0, 5.0, 0.0, step=0.5,
        help="Add your expected sale value here to see what you can afford",
    )


# ── Load data ──────────────────────────────────────────────────────────────────
from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
bs         = fetch_bootstrap()
current_gw = get_current_gameweek(bs)

try:
    with st.spinner(f"Loading team {team_id}..."):
        squad_df, entry_history, team_info = _load_team(team_id, current_gw)
except Exception as e:
    st.error(f"Could not load team {team_id}: {e}")
    st.info("Check the team ID and try again.")
    st.stop()

# Cache owned names for Transfer Suggestions page
st.session_state.owned_names     = squad_df["web_name"].tolist()
st.session_state.squad_team_id   = int(team_id)

xi    = squad_df[~squad_df["on_bench"]].copy()
bench = squad_df[squad_df["on_bench"]].copy()

# ── Header ─────────────────────────────────────────────────────────────────────
team_name = team_info.get("name", f"Team {team_id}")
manager   = f"{team_info.get('player_first_name', '')} {team_info.get('player_last_name', '')}".strip()

bank_m       = entry_history.get("bank", 0) / 10
value_m      = entry_history.get("value", 0) / 10
gw_pts       = entry_history.get("points", 0)
total_pts    = entry_history.get("total_points", 0)
overall_rank = entry_history.get("overall_rank", 0)
bench_pts    = entry_history.get("points_on_bench", 0)
transfer_cost = entry_history.get("event_transfers_cost", 0)
transfers_made = entry_history.get("event_transfers", 0)
active_chip  = team_info.get("active_chip") or "None"

st.markdown(
    f"<div style='padding:20px 0 8px;'>"
    f"<div style='font-size:28px;font-weight:900;color:#fff;letter-spacing:-0.5px;'>{team_name}</div>"
    f"<div style='font-size:13px;color:rgba(255,255,255,0.4);margin-top:2px;'>"
    f"Manager: {manager} &nbsp;·&nbsp; GW{current_gw}</div>"
    f"</div>",
    unsafe_allow_html=True,
)

# ── Key stats strip ────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric(f"GW{current_gw} Points", f"{gw_pts - transfer_cost}",
          delta=f"-{transfer_cost} hit" if transfer_cost else None,
          delta_color="inverse")
m2.metric("Total Points",   f"{total_pts:,}")
m3.metric("Overall Rank",   f"{overall_rank:,}")
m4.metric("Bank",           f"£{bank_m:.1f}m")
m5.metric("Team Value",     f"£{value_m:.1f}m")

# Secondary stats row
s1, s2, s3 = st.columns(3)
s1.metric("Bench Points",  bench_pts, help="Points left on bench this GW")
s2.metric("Transfers",     f"{transfers_made} made",
          delta=f"-{transfer_cost} pts" if transfer_cost else "Free",
          delta_color="inverse" if transfer_cost else "off")
s3.metric("Active Chip",   active_chip if active_chip != "None" else "—")

if transfers_made > 1 and transfer_cost > 0:
    st.warning(f"**{transfers_made} transfers** made this GW — {transfer_cost} pt hit applied.")

st.markdown("---")

# ── Squad view ─────────────────────────────────────────────────────────────────
tab_pitch, tab_table = st.tabs(["⚽ Pitch View", "📋 Squad Table"])

with tab_pitch:
    if "team_code" not in squad_df.columns:
        players_df_local = _get_players()
        if "team_code" in players_df_local.columns:
            squad_df = squad_df.merge(
                players_df_local[["fpl_id", "team_code"]],
                on="fpl_id", how="left",
            )
        else:
            squad_df["team_code"] = 1
    from components.pitch_view import render_pitch_view
    render_pitch_view(squad_df)

with tab_table:
    def _squad_table(df: pd.DataFrame) -> None:
        display = df[[
            "web_name", "team", "position", "price",
            "form", "total_points", "ownership",
            "is_captain", "is_vice_captain", "status", "news",
        ]].copy()
        display["Role"] = ""
        display.loc[display["is_captain"],      "Role"] = "©"
        display.loc[display["is_vice_captain"], "Role"] = "VC"
        display = display.drop(columns=["is_captain", "is_vice_captain"])
        display = display.rename(columns={
            "web_name": "Player", "team": "Team", "position": "Pos",
            "price": "Price", "form": "Form", "total_points": "Season Pts",
            "ownership": "Own%", "status": "Status", "news": "News",
        })
        display["Status"] = display["Status"].map(
            {"a": "✅", "d": "⚠️", "i": "🚑", "s": "🚫", "u": "❓"}
        ).fillna("?")
        display["Price"] = display["Price"].apply(lambda x: f"£{x:.1f}m")
        display["Own%"]  = display["Own%"].apply(lambda x: f"{x:.1f}%")
        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "Role":   st.column_config.TextColumn(width="small"),
                "Status": st.column_config.TextColumn(width="small"),
                "News":   st.column_config.TextColumn(width="large"),
            },
        )

    xi_col, bench_col = st.columns([3, 1])
    with xi_col:
        st.markdown("**Starting XI**")
        _squad_table(xi)
    with bench_col:
        st.markdown("**Bench**")
        _squad_table(bench)

st.markdown("---")

# ── Captain & Sell — side by side ─────────────────────────────────────────────
cap_col, sell_col = st.columns([1, 1])

with cap_col:
    st.markdown("### Captain Pick")
    players_df    = _get_players()
    from config import FIXTURE_LOOKAHEAD
    _fdr_col      = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
    squad_enriched = squad_df.merge(
        players_df[["fpl_id", _fdr_col, "transfer_balance", "price_change"]],
        on="fpl_id", how="left",
    )
    cap_candidates = squad_enriched[~squad_enriched["on_bench"]].copy()
    cap_candidates["cap_score"] = (
        cap_candidates["form"].fillna(0).astype(float) *
        (6 - cap_candidates[_fdr_col].fillna(3).astype(float))
    )
    cap_candidates = cap_candidates.sort_values("cap_score", ascending=False)

    for rank_i, (_, p) in enumerate(cap_candidates.head(3).iterrows()):
        fdr_val  = float(p.get(_fdr_col, 3.0) or 3.0)
        form_val = float(p.get("form", 0) or 0)
        border   = "#FFD700" if rank_i == 0 else "rgba(255,255,255,0.08)"
        label    = "© Captain" if rank_i == 0 else ("VC" if rank_i == 1 else f"#{rank_i + 1}")
        color    = "#FFD700" if rank_i == 0 else ("#c0c0c0" if rank_i == 1 else "rgba(255,255,255,0.4)")
        st.markdown(
            f"""<div style="
                background:rgba(255,255,255,0.03);
                border:1px solid {border};
                border-radius:8px;padding:12px 16px;
                margin-bottom:6px;display:flex;
                align-items:center;justify-content:space-between;
            ">
              <div>
                <div style="font-size:11px;color:{color};font-weight:700;text-transform:uppercase;
                            letter-spacing:0.08em;">{label}</div>
                <div style="font-size:16px;font-weight:700;color:#fff;">{p['web_name']}</div>
                <div style="font-size:12px;color:rgba(255,255,255,0.4);">{p.get('team','')} · {p.get('position','')}</div>
              </div>
              <div style="text-align:right;">
                <div style="font-size:20px;font-weight:800;color:{color};">{form_val:.1f}</div>
                <div style="font-size:11px;color:rgba(255,255,255,0.4);">form</div>
                <div style="font-size:13px;color:rgba(255,255,255,0.5);">FDR {fdr_val:.1f}</div>
              </div>
            </div>""",
            unsafe_allow_html=True,
        )

with sell_col:
    st.markdown("### Sell Candidates")
    st.caption("Players with 2+ concerns — poor form, tough run, or fitness doubts.")
    _fdr_col2 = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
    sell_flags = []
    for _, p in squad_enriched[~squad_enriched["on_bench"]].iterrows():
        flags = []
        status = str(p.get("status", "a"))
        if status == "i":
            flags.append("🚑 Injured")
        elif status == "s":
            flags.append("🚫 Suspended")
        elif status == "d":
            flags.append("⚠️ Doubt")
        form = float(p.get("form", 5) or 5)
        if form < 2.5:
            flags.append(f"📉 Poor form ({form:.1f})")
        elif form < 3.5 and status not in ("i", "s"):
            flags.append(f"📉 Low form ({form:.1f})")
        fdr = p.get(_fdr_col2)
        if fdr is not None and float(fdr) > 3.8:
            flags.append(f"🔴 Tough run (FDR {float(fdr):.1f})")
        balance = int(p.get("transfer_balance", 0) or 0)
        if balance < -50_000:
            flags.append(f"📤 Selling ({abs(balance) // 1000:.0f}k net out)")
        if len(flags) >= 2:
            sell_flags.append((p["web_name"], p.get("team", ""), p.get("position", ""), flags))

    if sell_flags:
        for name, team, pos, flags in sell_flags:
            st.markdown(
                f"""<div style="
                    background:rgba(255,75,75,0.05);
                    border:1px solid rgba(255,75,75,0.2);
                    border-left:3px solid #FF4B4B;
                    border-radius:8px;padding:10px 14px;margin-bottom:6px;
                ">
                  <div style="font-weight:700;color:#fff;">{name}
                    <span style="font-size:11px;color:rgba(255,255,255,0.4);font-weight:400;"> {team} · {pos}</span>
                  </div>
                  <div style="font-size:12px;color:rgba(255,255,255,0.5);margin-top:4px;">
                    {"&nbsp; · &nbsp;".join(flags)}</div>
                </div>""",
                unsafe_allow_html=True,
            )
    else:
        st.success("No major sell concerns in your starting XI right now. ✅")

st.markdown("---")

# ── Transfer Suggestions ───────────────────────────────────────────────────────
st.markdown("### Transfer Suggestions")
st.caption("Best available targets you can afford — excluding your current squad.")

players_df       = _get_players()
available_budget = bank_m + budget_boost
owned_names      = set(squad_df["web_name"].tolist())
pos              = None if pos_filter == "All" else pos_filter

from analytics.transfer_engine import get_transfer_targets
suggestions = get_transfer_targets(
    players_df,
    position=pos,
    max_price=available_budget if available_budget > 4.0 else None,
    top_n=15,
)
if not suggestions.empty:
    suggestions = suggestions[~suggestions["web_name"].isin(owned_names)].reset_index(drop=True)

if suggestions.empty:
    st.info(f"No affordable targets found with £{available_budget:.1f}m. Try the budget slider in the sidebar.")
else:
    if available_budget > 0:
        label = f"£{available_budget:.1f}m"
        if budget_boost:
            label += f" (bank + £{budget_boost:.1f}m sale)"
        st.caption(f"Budget: {label}")
    from components.player_table import render_player_table
    render_player_table(suggestions, highlight_col="Score", height=450)

st.markdown("---")

# ── Points History ─────────────────────────────────────────────────────────────
st.markdown("### Points History")

try:
    history    = _load_history(team_id)
    gw_history = history.get("current", [])

    if gw_history:
        hist_df = pd.DataFrame(gw_history)
        hist_df["net_points"] = hist_df["points"] - hist_df["event_transfers_cost"]
        season_avg = hist_df["net_points"].mean()

        fig = go.Figure()
        # Fill above average green, below red
        fig.add_trace(go.Bar(
            x=hist_df["event"],
            y=hist_df["net_points"],
            marker_color=[
                "#00FF87" if p >= season_avg else "#FF4B4B"
                for p in hist_df["net_points"]
            ],
            hovertemplate="GW%{x}: %{y} pts<extra></extra>",
        ))
        fig.add_hline(
            y=season_avg,
            line_dash="dash",
            line_color="rgba(255,255,255,0.35)",
            annotation_text=f"Season avg: {season_avg:.1f}",
            annotation_position="top right",
        )
        fig.update_layout(
            xaxis_title="Gameweek",
            yaxis_title="Points",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e2e2",
            height=280,
            showlegend=False,
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            margin=dict(t=20),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Mini stat cards
        c1, c2, c3, c4 = st.columns(4)
        best_row  = hist_df.loc[hist_df["net_points"].idxmax()]
        worst_row = hist_df.loc[hist_df["net_points"].idxmin()]
        c1.metric("Best GW",   f"GW{int(best_row['event'])}",  f"{int(best_row['net_points'])} pts")
        c2.metric("Worst GW",  f"GW{int(worst_row['event'])}", f"{int(worst_row['net_points'])} pts")
        c3.metric("Total Hits", f"{hist_df['event_transfers_cost'].sum()} pts lost")
        if "points_on_bench" in hist_df.columns:
            total_bench = int(hist_df["points_on_bench"].sum())
            avg_bench   = hist_df["points_on_bench"].mean()
            c4.metric("Bench Losses", f"{total_bench} pts",
                      f"{avg_bench:.1f}/GW avg",
                      delta_color="inverse",
                      help="Points left on your bench all season")

except Exception as e:
    st.warning(f"Could not load points history: {e}")
