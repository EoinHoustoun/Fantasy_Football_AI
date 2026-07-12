"""
Chip Planner · Bench Boost & Triple Captain timing.

For each remaining GW projects your squad's scores and recommends
the optimal GW to play each chip.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from typing import List, Dict

# set_page_config is owned by the app.py router (st.navigation)

# ── Data helpers ───────────────────────────────────────────────────────────────

def _get_players():
    if st.session_state.get("players_df") is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


def _get_fixtures():
    if st.session_state.get("fixtures_df") is not None:
        return st.session_state.fixtures_df
    from data.fetchers.fpl_api import get_fixtures_df
    return get_fixtures_df()


@st.cache_data(ttl=1800, show_spinner=False)
def _load_squad(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad_df


# ── Score projection ───────────────────────────────────────────────────────────

def _project_player_gw(row: pd.Series, gw: int, fixtures_df: pd.DataFrame) -> float:
    """PPG × fixture ease for a specific GW. Returns 0 for BGW players."""
    tid = row.get("team_id")
    if not tid:
        return float(row.get("form", 3.0) or 3.0)

    gw_fix = fixtures_df[fixtures_df["gameweek"] == gw]
    home = gw_fix[gw_fix["home_team_id"] == tid]
    away = gw_fix[gw_fix["away_team_id"] == tid]

    ppg = float(row.get("form", 3.0) or 3.0)
    total = 0.0

    for _, f in home.iterrows():
        fdr = float(f.get("home_fdr", 3))
        ease = max(0.35, (4.5 - fdr) / 2.5)
        total += ppg * ease

    for _, f in away.iterrows():
        fdr = float(f.get("away_fdr", 3))
        ease = max(0.35, (4.5 - fdr) / 2.5)
        total += ppg * ease

    return round(total, 2)


def _build_gw_projections(squad_df: pd.DataFrame, fixtures_df: pd.DataFrame, current_gw: int) -> pd.DataFrame:
    """For every remaining GW compute XI total, bench total, TC extra, best captain."""
    xi    = squad_df[~squad_df["on_bench"]].copy()
    bench = squad_df[squad_df["on_bench"]].copy()
    rows  = []

    for gw in range(current_gw + 1, 39):
        xi_scores = [
            {"name": r["web_name"], "score": _project_player_gw(r, gw, fixtures_df)}
            for _, r in xi.iterrows()
        ]
        bench_scores = [
            _project_player_gw(r, gw, fixtures_df) for _, r in bench.iterrows()
        ]

        xi_total    = sum(s["score"] for s in xi_scores)
        bench_total = sum(bench_scores)

        best_cap    = max(xi_scores, key=lambda x: x["score"]) if xi_scores else {"name": "?", "score": 0}
        # Triple Captain gives 3× instead of 2×, so extra pts = 1× captain score
        tc_extra    = best_cap["score"]

        # Check DGW
        any_dgw = False
        for _, r in xi.iterrows():
            tid = r.get("team_id")
            if tid:
                gw_fix = fixtures_df[fixtures_df["gameweek"] == gw]
                games  = len(gw_fix[(gw_fix["home_team_id"] == tid) | (gw_fix["away_team_id"] == tid)])
                if games >= 2:
                    any_dgw = True
                    break

        rows.append({
            "GW":            gw,
            "xi_total":      round(xi_total, 1),
            "bench_total":   round(bench_total, 1),
            "bb_total":      round(xi_total + bench_total, 1),
            "tc_extra":      round(tc_extra, 1),
            "captain":       best_cap["name"],
            "captain_score": round(best_cap["score"], 1),
            "has_dgw":       any_dgw,
        })

    return pd.DataFrame(rows)


# ── UI helpers ─────────────────────────────────────────────────────────────────

def _chip_hero(title: str, best_gw: int, metric: float, sub: str, color: str, note: str = "") -> None:
    dgw_badge = ""
    st.markdown(
        f"""<div style="
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.08);
            border-top:4px solid {color};
            border-radius:12px;
            padding:24px 28px 20px;
            margin-bottom:8px;
        ">
          <div style="font-size:12px;color:rgba(255,255,255,0.4);text-transform:uppercase;
                      letter-spacing:0.12em;margin-bottom:6px;">{title}</div>
          <div style="font-size:48px;font-weight:900;color:{color};line-height:1;">GW{best_gw}</div>
          <div style="font-size:22px;font-weight:700;color:#fff;margin-top:6px;">{metric:+.1f} pts bonus</div>
          <div style="font-size:13px;color:rgba(255,255,255,0.5);margin-top:6px;">{sub}</div>
          {'<div style="font-size:12px;color:#FFD700;margin-top:8px;">⚡ ' + note + '</div>' if note else ''}
        </div>""",
        unsafe_allow_html=True,
    )


def _bar_chart(gw_df: pd.DataFrame, y_col: str, best_gw: int, title: str, color: str) -> None:
    colors = [
        "#FFD700" if row["GW"] == best_gw else (
            "#00FF87" if row["has_dgw"] else color
        )
        for _, row in gw_df.iterrows()
    ]
    fig = go.Figure(go.Bar(
        x=gw_df["GW"],
        y=gw_df[y_col],
        marker_color=colors,
        hovertemplate="GW%{x}: %{y:.1f} pts<extra></extra>",
    ))
    fig.update_layout(
        title=title,
        xaxis_title="Gameweek",
        yaxis_title="Projected pts",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e2e2",
        height=300,
        showlegend=False,
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _squad_cards(squad_df: pd.DataFrame, gw: int, fixtures_df: pd.DataFrame, on_bench: bool) -> None:
    rows = squad_df[squad_df["on_bench"] == on_bench].copy()
    rows["proj"] = rows.apply(lambda r: _project_player_gw(r, gw, fixtures_df), axis=1)
    rows = rows.sort_values("proj", ascending=False)
    cols = st.columns(len(rows))
    for i, (_, p) in enumerate(rows.iterrows()):
        tc = st.session_state.get("_chip_tc_player") == p["web_name"]
        border = "#FFD700" if tc else "rgba(255,255,255,0.1)"
        with cols[i]:
            st.markdown(
                f"""<div style="
                    background:rgba(255,255,255,0.04);
                    border:1px solid {border};
                    border-radius:8px;padding:10px 8px;text-align:center;
                ">
                  <div style="font-size:11px;color:rgba(255,255,255,0.4);">{p.get('position','')}</div>
                  <div style="font-size:13px;font-weight:700;color:#fff;">{p['web_name']}</div>
                  <div style="font-size:11px;color:rgba(255,255,255,0.4);">{p.get('team','')}</div>
                  <div style="font-size:17px;font-weight:800;color:{'#FFD700' if tc else '#00FF87'};margin-top:4px;">{p['proj']:.1f}</div>
                </div>""",
                unsafe_allow_html=True,
            )


# ── Page layout ────────────────────────────────────────────────────────────────

st.markdown(
    "<div style='padding:20px 0 4px;'>"
    "<div style='font-size:30px;font-weight:900;color:#FFD700;'>🎯 Chip Planner</div>"
    "<div style='font-size:14px;color:rgba(255,255,255,0.4);margin-top:4px;'>"
    "Optimal gameweek to play Bench Boost &amp; Triple Captain · based on your squad's projected scores."
    "</div></div>",
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
    st.markdown("### Your Team")
    from config import FPL_TEAM_ID
    team_id = st.number_input("FPL Team ID", min_value=1,
                               value=int(FPL_TEAM_ID or 1), step=1)

    st.markdown("---")
    st.markdown("### Chips Remaining")
    bb_available = st.checkbox("Bench Boost available", value=True)
    tc_available = st.checkbox("Triple Captain available", value=True)

    st.markdown("---")
    st.caption("⚡ DGW gameweeks shown in green on the charts.")
    st.caption("🏆 Optimal GW shown in gold.")

# Load
from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
bs         = fetch_bootstrap()
current_gw = get_current_gameweek(bs)
players_df = _get_players()
fixtures_df = _get_fixtures()

try:
    with st.spinner("Loading squad..."):
        squad_df = _load_squad(team_id, current_gw)
except Exception as e:
    st.error(f"Could not load team {team_id}: {e}")
    st.stop()

# Enrich with team_id
if "team_id" not in squad_df.columns and "fpl_id" in squad_df.columns:
    squad_df = squad_df.merge(
        players_df[["fpl_id", "team_id"]].drop_duplicates(),
        on="fpl_id", how="left",
    )

if fixtures_df is None or squad_df.empty:
    st.warning("Could not load squad or fixture data.")
    st.stop()

with st.spinner("Projecting GW scores..."):
    gw_df = _build_gw_projections(squad_df, fixtures_df, current_gw)

if gw_df.empty:
    st.info("No remaining gameweeks to plan for.")
    st.stop()

best_bb_row = gw_df.loc[gw_df["bench_total"].idxmax()]
best_tc_row = gw_df.loc[gw_df["tc_extra"].idxmax()]

# Store TC captain name for card highlighting
st.session_state["_chip_tc_player"] = best_tc_row["captain"]

# ── Hero cards ──────────────────────────────────────────────────────────────────
st.markdown("### Best GW for Each Chip")
h1, h2 = st.columns(2)

with h1:
    if bb_available:
        _chip_hero(
            "Bench Boost",
            int(best_bb_row["GW"]),
            float(best_bb_row["bench_total"]),
            f"Bench: {squad_df[squad_df['on_bench']]['web_name'].str.cat(sep=' · ')}",
            "#04f5ff",
            "DGW week · maximum bench coverage" if best_bb_row["has_dgw"] else "",
        )
    else:
        st.info("Bench Boost already played.")

with h2:
    if tc_available:
        _chip_hero(
            "Triple Captain",
            int(best_tc_row["GW"]),
            float(best_tc_row["tc_extra"]),
            f"Captain: {best_tc_row['captain']} ({best_tc_row['captain_score']:.1f} projected)",
            "#FFD700",
            "DGW · triple the double!" if best_tc_row["has_dgw"] else "",
        )
    else:
        st.info("Triple Captain already played.")

st.markdown("---")

# ── Charts ──────────────────────────────────────────────────────────────────────
tab_bb, tab_tc = st.tabs(["📊 Bench Boost Analysis", "👑 Triple Captain Analysis"])

with tab_bb:
    st.caption("Total projected points including bench · higher = better GW to play Bench Boost.")
    _bar_chart(gw_df, "bb_total", int(best_bb_row["GW"]), "Bench Boost Value by GW", "#04f5ff")

    st.markdown("#### Bench Breakdown · Best GW")
    xi_col, bench_col = st.columns([3, 1])
    with xi_col:
        st.markdown(f"**Starting XI · GW{int(best_bb_row['GW'])}**")
        _squad_cards(squad_df, int(best_bb_row["GW"]), fixtures_df, on_bench=False)
    with bench_col:
        st.markdown("**Bench**")
        bench_rows = squad_df[squad_df["on_bench"]].copy()
        bench_rows["proj"] = bench_rows.apply(
            lambda r: _project_player_gw(r, int(best_bb_row["GW"]), fixtures_df), axis=1
        )
        for _, p in bench_rows.sort_values("proj", ascending=False).iterrows():
            st.markdown(
                f"<div style='padding:6px 10px;border-left:3px solid #04f5ff;margin-bottom:4px;'>"
                f"<span style='font-weight:700;color:#fff;'>{p['web_name']}</span> "
                f"<span style='color:#04f5ff;float:right;font-weight:700;'>{p['proj']:.1f}</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("#### Full Schedule")
    show_df = gw_df[["GW", "xi_total", "bench_total", "bb_total", "has_dgw"]].copy()
    show_df.columns = ["GW", "XI Pts", "Bench Pts", "BB Total", "DGW"]
    show_df["DGW"] = show_df["DGW"].apply(lambda x: "⚡ Yes" if x else "")
    st.dataframe(show_df, use_container_width=True, hide_index=True)

with tab_tc:
    st.caption(
        "Extra points from Triple Captain vs regular captain (1× extra of captain score). "
        "Higher = better GW to play TC."
    )
    _bar_chart(gw_df, "tc_extra", int(best_tc_row["GW"]), "Triple Captain Extra Value by GW", "#FFD700")

    st.markdown("#### Captain Candidates · Best GW")
    _squad_cards(squad_df, int(best_tc_row["GW"]), fixtures_df, on_bench=False)

    st.markdown("#### Best Captain per GW")
    cap_df = gw_df[["GW", "captain", "captain_score", "tc_extra", "has_dgw"]].copy()
    cap_df.columns = ["GW", "Best Captain", "Cap Projected", "TC Extra", "DGW"]
    cap_df["DGW"] = cap_df["DGW"].apply(lambda x: "⚡" if x else "")
    st.dataframe(cap_df, use_container_width=True, hide_index=True)
