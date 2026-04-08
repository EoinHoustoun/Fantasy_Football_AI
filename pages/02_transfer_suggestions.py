"""
Transfer Suggestions page.

Leads with a clear #1 transfer recommendation and plain-English reasoning.
If the top 3 are close in score, presents all three and lets the user decide.
Includes season-long fixture outlook, ceiling / haul-potential charts,
a Free Hit chip planner, and deeper score-breakdown tabs.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from config import HAUL_THRESHOLD, TWENTY_PLUS_THRESHOLD, ACCENT_COLOR, FIXTURE_LOOKAHEAD
from components.badges import render_badges

st.set_page_config(page_title="Transfer Suggestions — FPL Hub", layout="wide")

st.title("🔄 Transfer Suggestions")
st.caption("Your #1 transfer recommendation — with reasoning, season outlook, and haul potential.")


# ── Data loader ────────────────────────────────────────────────────────────────
def get_players():
    if "players_df" in st.session_state and st.session_state.players_df is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


players_df = get_players()

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
    position  = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    pos_filter = None if position == "All" else position

    price_range = st.slider("Price range (£m)", 3.5, 15.0, (4.0, 12.0), step=0.5)

    st.markdown("---")
    st.markdown("### 🃏 Free Hit Chip")
    playing_fh = st.toggle("I'm playing Free Hit this GW", value=False)
    free_hit_gw = None
    if playing_fh:
        from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
        _bs = fetch_bootstrap()
        _cur = get_current_gameweek(_bs)
        free_hit_gw = st.number_input(
            "Free Hit gameweek",
            min_value=_cur,
            max_value=38,
            value=_cur,
            step=1,
        )
        st.info(
            f"**Free Hit active — GW{free_hit_gw}.**  "
            "You can pick any 15 players this week with no budget constraints.  "
            "Recommendations below show the best players to target regardless of what you own."
        )

    st.markdown("---")
    with st.expander("⚙️ Score Weights (advanced)", expanded=False):
        st.caption("Tune what matters most to you this GW.")
        w_form     = st.slider("Form",            0.0, 1.0, 0.25, step=0.05)
        w_fixture  = st.slider("Fixture Ease",    0.0, 1.0, 0.25, step=0.05)
        w_xg       = st.slider("xG Potential",    0.0, 1.0, 0.20, step=0.05)
        w_value    = st.slider("Value (PPM)",      0.0, 1.0, 0.15, step=0.05)
        w_trend    = st.slider("Transfer Trend",   0.0, 1.0, 0.10, step=0.05)
        w_minutes  = st.slider("Minutes Security", 0.0, 1.0, 0.05, step=0.05)

    top_n = st.slider("Show top N in charts", 5, 30, 15)


custom_weights = {
    "form":             w_form,
    "fixture_ease":     w_fixture,
    "xg_potential":     w_xg,
    "value":            w_value,
    "ownership_trend":  w_trend,
    "minutes_security": w_minutes,
}

# ── Load owned players ────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _load_owned(team_id: int) -> list:
    from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek, get_team_squad
    bs  = fetch_bootstrap()
    gw  = get_current_gameweek(bs)
    squad, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad["web_name"].tolist()


owned_names = []
if squad_team_id and int(squad_team_id) > 0:
    try:
        owned_names = _load_owned(int(squad_team_id))
        # also keep session state in sync
        st.session_state.owned_names    = owned_names
        st.session_state.squad_team_id  = int(squad_team_id)
    except Exception:
        owned_names = st.session_state.get("owned_names", [])
else:
    owned_names = st.session_state.get("owned_names", [])

# ── Run recommendation engine ─────────────────────────────────────────────────
from analytics.transfer_engine import (
    get_top_recommendation,
    get_transfer_targets,
    score_players,
    estimate_season_points,
    estimate_ceiling,
    apply_free_hit_adjustment,
    get_free_hit_targets,
)

# Resolve fixtures_df for Free Hit adjustments
_fixtures_df = st.session_state.get("fixtures_df")
if _fixtures_df is None:
    from data.fetchers.fpl_api import fetch_bootstrap, get_fixtures_df as _get_fix, get_current_gameweek as _get_gw
    _bs = fetch_bootstrap()
    _fixtures_df = _get_fix(bootstrap=_bs)
    _current_gw  = _get_gw(_bs)
else:
    from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek as _get_gw
    _current_gw = _get_gw(fetch_bootstrap())

with st.spinner("Analysing transfer options..."):
    # When Free Hit is active, strip that GW from regular-squad projections
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

    # Full scored + enriched dataframe for charts (uses adjusted base_df)
    full_df = score_players(base_df, weights=custom_weights)
    full_df = estimate_season_points(full_df)
    full_df = estimate_ceiling(full_df)
    full_df = full_df[full_df["status"] == "a"].copy()
    if owned_names and not free_hit_gw:
        full_df = full_df[~full_df["web_name"].isin(owned_names)]
    if pos_filter:
        full_df = full_df[full_df["position"] == pos_filter]
    full_df = full_df.sort_values("transfer_score", ascending=False).reset_index(drop=True)

if free_hit_gw:
    st.info(
        f"**Free Hit active — GW{free_hit_gw}.** "
        f"GW{free_hit_gw} is excluded from all season projections and fixture difficulty averages "
        f"for your regular squad — it doesn't count because you'll play a completely different team that week. "
        f"See the **Season Outlook** tab for Free Hit targets."
    )

if reco["top"] is None:
    st.warning("No players match your filters. Try widening the price range or removing the position filter.")
    st.stop()

# ── Hero: #1 Transfer Recommendation ─────────────────────────────────────────
top = reco["top"]
is_close = reco["is_close"]

if is_close:
    st.markdown("## 🏆 It's close at the top — here are your top 3")
    st.markdown("The scores are very tight. Read the reasoning and pick the one that suits your squad.")
    st.markdown("")

    cols = st.columns(3)
    for i, item in enumerate(reco["close"]):
        p = item["player"]
        with cols[i]:
            rank_label = ["🥇 #1 Pick", "🥈 #2 Pick", "🥉 #3 Pick"][i]
            st.markdown(f"#### {rank_label}")
            m1, m2 = st.columns(2)
            m1.metric("Player", p["web_name"])
            m2.metric("Price", f"£{p['price']:.1f}m")
            m1.metric("Form", f"{float(p.get('form', 0)):.1f}")
            fdr_col = f"avg_fdr_next_6"
            avg_fdr = float(p.get(fdr_col, 3.0) or 3.0)
            m2.metric("Avg FDR", f"{avg_fdr:.1f}/5")
            proj = p.get("projected_season_pts")
            ceiling = p.get("ceiling_pts", 0)
            if proj:
                st.metric("Season Projection", f"{proj:.0f} pts")
            st.metric("Ceiling Score", f"{ceiling:.0f} pts")
            _bgw = p.get("bgw_gameweeks") or []
            _dgw = p.get("dgw_gameweeks") or []
            if isinstance(_bgw, list) and _bgw:
                st.warning(f"BGW: GW{', '.join(str(g) for g in _bgw)}")
            if isinstance(_dgw, list) and _dgw:
                st.success(f"DGW: GW{', '.join(str(g) for g in _dgw)}")
            st.markdown(item["reasoning"])
            if p.get("twenty_plus"):
                st.success("20+ point haul potential")
            elif p.get("haul_candidate"):
                st.info("Haul candidate (15+ ceiling)")

else:
    # Clear single recommendation
    st.markdown("## 🏆 Your #1 Transfer This Week")

    top_reasoning = reco["close"][0]["reasoning"] if reco["close"] else ""

    col_hero, col_stats = st.columns([2, 3])

    with col_hero:
        st.markdown(f"### {top['web_name']}")
        st.markdown(f"**{top.get('team', '')}** · {top.get('position', '')} · £{top.get('price', 0):.1f}m")

        badges = render_badges(top, size="sm")
        if badges:
            st.markdown(badges, unsafe_allow_html=True)

        fdr_col = f"avg_fdr_next_6"
        avg_fdr = float(top.get(fdr_col, 3.0) or 3.0)
        season_fdr = float(top.get("season_avg_fdr", 3.0) or 3.0)

        avg_mins = float(top.get("avg_minutes", 0) or 0)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Form", f"{float(top.get('form', 0)):.1f}")
        m2.metric("Avg FDR (next 6)", f"{avg_fdr:.1f}/5")
        m3.metric("Season Avg FDR", f"{season_fdr:.1f}/5")
        m4.metric("Avg Mins/Game", f"{avg_mins:.0f}" if avg_mins > 0 else "—")

        proj = top.get("projected_season_pts")
        ceiling = float(top.get("ceiling_pts", 0) or 0)
        m4, m5, m6 = st.columns(3)
        if proj:
            m4.metric("Season Projection", f"{proj:.0f} pts")
        m5.metric("Ceiling Score", f"{ceiling:.0f} pts")
        m6.metric("Transfer Score", f"{float(top.get('transfer_score', 0)):.3f}")

        if top.get("twenty_plus"):
            st.success("20+ point haul potential")
        elif top.get("haul_candidate"):
            st.info("Haul candidate (15+ ceiling)")

    with col_stats:
        st.markdown("#### Why this transfer?")
        st.markdown(top_reasoning)

        # Captain candidate note
        fdr_col_hero = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
        _pos   = str(top.get("position", ""))
        _form  = float(top.get("form", 0) or 0)
        _ceil  = float(top.get("ceiling_pts", 0) or 0)
        _fdr_h = float(top.get(fdr_col_hero, 3.0) or 3.0)
        if _pos in ("MID", "FWD") and _form >= 6 and _fdr_h <= 2.5:
            st.success("Also a strong captain candidate this week — form + fixture combination is excellent.")
        elif _pos in ("MID", "FWD") and _ceil >= TWENTY_PLUS_THRESHOLD:
            st.info("Worth considering as captain given 20+ point ceiling.")

        # Price movement alert
        _balance = int(top.get("transfer_balance", 0) or 0)
        _price_ch = float(top.get("price_change", 0) or 0)
        if _balance > 150_000:
            st.warning(f"Price rise likely — {_balance / 1000:.0f}k net transfers in this GW. Buy before the deadline.")
        elif _balance > 60_000:
            st.info(f"Rising in popularity — {_balance / 1000:.0f}k net in. May rise in price.")
        if _price_ch > 0:
            st.info(f"Already rose £{_price_ch:.1f}m this GW.")

        # BGW warning
        bgw_gws = top.get("bgw_gameweeks") or []
        dgw_gws = top.get("dgw_gameweeks") or []
        if isinstance(bgw_gws, list) and bgw_gws:
            st.warning(f"Blank GW alert: {top['web_name']} has no fixture in GW{', GW'.join(str(g) for g in bgw_gws)} — factor this into your timing.")
        if isinstance(dgw_gws, list) and dgw_gws:
            st.success(f"Double GW: {top['web_name']} plays TWICE in GW{', GW'.join(str(g) for g in dgw_gws)} — excellent time to own.")

        # Mini fixture ticker for the top pick
        if "upcoming_fixtures" in players_df.columns:
            player_fixture_row = players_df[players_df["web_name"] == top["web_name"]]
            if not player_fixture_row.empty:
                fixtures = player_fixture_row.iloc[0].get("upcoming_fixtures") or []
                if fixtures:
                    fdr_emoji = {1: "🟢", 2: "🟢", 3: "⚪", 4: "🟠", 5: "🔴"}
                    fixture_text = "  ".join(
                        f"{fdr_emoji.get(int(f['fdr']), '⚪')} **{f['opponent'][:3].upper()}** {'(H)' if f['home'] else '(A)'}"
                        for f in fixtures[:6]
                    )
                    st.markdown(f"**Next fixtures:** {fixture_text}")

st.markdown("---")

# ── Tabs: Season Outlook | Haul Potential | Rankings | Score Breakdown | Fixture Ticker ──
tab_season, tab_ceiling, tab_rankings, tab_breakdown, tab_fixtures = st.tabs([
    "📅 Season Outlook",
    "🎯 Haul Potential",
    "📋 All Rankings",
    "📊 Score Breakdown",
    "🗓️ Fixture Ticker",
])


# ── Tab: Season Outlook ────────────────────────────────────────────────────────
with tab_season:
    st.markdown("#### Projected Points — Rest of Season")
    st.caption(
        "Estimated total points from now until GW38. "
        "Based on points-per-game × remaining fixtures × fixture ease. "
        "Use this to find players who have both form AND a great schedule."
    )

    season_chart = full_df[["web_name", "team", "position", "price",
                              "projected_season_pts", "season_avg_fdr",
                              "remaining_fixtures", "points_per_game"]].head(top_n).copy()
    season_chart = season_chart.dropna(subset=["projected_season_pts"])
    season_chart = season_chart.sort_values("projected_season_pts", ascending=False)

    if not season_chart.empty:
        # Colour by season avg FDR
        fig_season = px.bar(
            season_chart,
            x="projected_season_pts",
            y="web_name",
            color="season_avg_fdr",
            color_continuous_scale="RdYlGn_r",
            range_color=[1.5, 4.0],
            orientation="h",
            hover_data=["team", "position", "price", "remaining_fixtures", "points_per_game"],
            title=f"Projected Season Points — Top {top_n} (colour = avg FDR, green = easier)",
            labels={
                "projected_season_pts": "Projected Points",
                "web_name": "Player",
                "season_avg_fdr": "Season Avg FDR",
            },
        )
        fig_season.update_layout(
            yaxis=dict(autorange="reversed"),
            height=max(400, 30 * len(season_chart)),
            coloraxis_colorbar=dict(title="FDR"),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_season, use_container_width=True)

    # Free Hit targets for the specific GW
    if free_hit_gw:
        st.markdown(f"---")
        st.markdown(f"#### Free Hit Targets — GW{free_hit_gw}")
        st.caption(
            f"Best players to pick for your Free Hit in GW{free_hit_gw}, "
            f"sorted by fixture difficulty in that specific week. "
            f"These are separate from your regular squad — pick whoever has the easiest game."
        )
        fh_targets = get_free_hit_targets(players_df, _fixtures_df, free_hit_gw, top_n=top_n)
        if not fh_targets.empty:
            fh_display = fh_targets.rename(columns={
                "web_name": "Player", "team": "Team", "position": "Pos",
                "price": "Price", "form": "Form", "total_points": "Season Pts",
                "fh_fdr": f"GW{free_hit_gw} FDR", "ownership": "Own%",
            })
            fh_display["Price"] = fh_display["Price"].apply(lambda x: f"£{x:.1f}m")
            st.dataframe(fh_display, use_container_width=True, hide_index=True)
        else:
            st.info(f"No fixture data available for GW{free_hit_gw} yet.")

    # Season fixture table
    st.markdown("#### Season Fixture Summary — Top Players")
    season_table = season_chart[["web_name", "team", "position", "price",
                                   "points_per_game", "remaining_fixtures",
                                   "season_avg_fdr", "projected_season_pts"]].copy()
    season_table.columns = ["Player", "Team", "Pos", "Price", "PPG",
                              "Games Left", "Season Avg FDR", "Projected Pts"]
    season_table["Price"] = season_table["Price"].apply(lambda x: f"£{x:.1f}m")
    st.dataframe(season_table, use_container_width=True, hide_index=True)


# ── Tab: Haul Potential ────────────────────────────────────────────────────────
with tab_ceiling:
    st.markdown("#### Ceiling Score — Who Can Score 20+ Points?")
    st.caption(
        "Ceiling score models a player's maximum single-game haul. "
        "It uses their xG/xA rate, position scoring (goals: GKP/DEF 6pts, MID 5pts, FWD 4pts), "
        "clean sheet value, and upcoming fixture ease. "
        "A **green bar** hits 20+. An **orange bar** hits 15+."
    )

    ceiling_chart = full_df[["web_name", "team", "position", "price",
                               "ceiling_pts", "haul_candidate", "twenty_plus",
                               f"avg_fdr_next_6"]].head(top_n * 2).copy()
    ceiling_chart = ceiling_chart.sort_values("ceiling_pts", ascending=False).head(top_n)

    if not ceiling_chart.empty:
        def _ceiling_color(row):
            if row["twenty_plus"]:
                return "20+ Haul"
            elif row["haul_candidate"]:
                return "15+ Haul"
            return "Standard"

        ceiling_chart["Tier"] = ceiling_chart.apply(_ceiling_color, axis=1)

        fig_ceil = px.bar(
            ceiling_chart,
            x="ceiling_pts",
            y="web_name",
            color="Tier",
            color_discrete_map={
                "20+ Haul":  ACCENT_COLOR,
                "15+ Haul":  "#FFA500",
                "Standard":  "#8888aa",
            },
            orientation="h",
            hover_data=["team", "position", "price", f"avg_fdr_next_6"],
            title=f"Single-Game Ceiling Points — Top {top_n}",
            labels={"ceiling_pts": "Ceiling Points", "web_name": "Player"},
        )
        fig_ceil.add_vline(x=TWENTY_PLUS_THRESHOLD, line_dash="dash",
                           line_color=ACCENT_COLOR,
                           annotation_text="20 pts", annotation_position="top right")
        fig_ceil.add_vline(x=HAUL_THRESHOLD, line_dash="dot",
                           line_color="#FFA500",
                           annotation_text="15 pts", annotation_position="bottom right")
        fig_ceil.update_layout(
            yaxis=dict(autorange="reversed"),
            height=max(400, 30 * len(ceiling_chart)),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_ceil, use_container_width=True)

    # List 20+ candidates explicitly
    twenty_players = ceiling_chart[ceiling_chart["twenty_plus"]].copy()
    if not twenty_players.empty:
        st.markdown(f"**{len(twenty_players)} player(s) with 20+ haul potential:**")
        for _, p in twenty_players.iterrows():
            fdr = float(p.get("avg_fdr_next_6", 3.0) or 3.0)
            st.markdown(
                f"- **{p['web_name']}** ({p['team']}, {p['position']}, £{p['price']:.1f}m) — "
                f"ceiling {p['ceiling_pts']:.0f} pts · next {6}-GW avg FDR {fdr:.1f}"
            )
    else:
        st.info("No players in the current filter hit a 20+ ceiling. Try widening position or price range.")


# ── Tab: All Rankings ──────────────────────────────────────────────────────────
with tab_rankings:
    suggestions = get_transfer_targets(
        players_df,
        position=pos_filter,
        min_price=price_range[0],
        max_price=price_range[1],
        top_n=top_n,
        weights=custom_weights,
    )
    if suggestions.empty:
        st.warning("No players match your filters.")
    else:
        from components.player_table import render_player_table
        render_player_table(suggestions, highlight_col="Score", height=600)


# ── Tab: Score Breakdown ───────────────────────────────────────────────────────
with tab_breakdown:
    score_cols = [c for c in ["score_form", "score_fixture", "score_xg", "score_value"]
                  if c in full_df.columns]

    if score_cols:
        chart_df = full_df[["web_name"] + score_cols].head(15).melt(
            id_vars="web_name",
            var_name="Component",
            value_name="Score",
        )
        chart_df["Component"] = chart_df["Component"].str.replace("score_", "").str.title()

        fig_breakdown = px.bar(
            chart_df,
            x="Score",
            y="web_name",
            color="Component",
            orientation="h",
            title="Score Component Breakdown (Top 15)",
            color_discrete_sequence=px.colors.qualitative.Set2,
            labels={"web_name": "Player"},
        )
        fig_breakdown.update_layout(
            yaxis=dict(autorange="reversed"),
            height=500,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_breakdown, use_container_width=True)

    # Form vs Price scatter
    fdr_col = next((c for c in full_df.columns if c.startswith("avg_fdr_next_")), None)
    if fdr_col and "form" in full_df.columns and "price" in full_df.columns:
        fig_scatter = px.scatter(
            full_df.head(50),
            x="price",
            y="form",
            size="transfer_score",
            color=fdr_col,
            color_continuous_scale="RdYlGn_r",
            hover_name="web_name",
            title="Form vs Price (bubble = transfer score, colour = FDR)",
            labels={"price": "Price (£m)", "form": "Form", fdr_col: "Avg FDR"},
        )
        fig_scatter.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=400)
        st.plotly_chart(fig_scatter, use_container_width=True)


# ── Tab: Fixture Ticker ────────────────────────────────────────────────────────
with tab_fixtures:
    if "upcoming_fixtures" in players_df.columns:
        fixture_data = players_df[["web_name", "upcoming_fixtures"]].copy()
        top_players = full_df.head(top_n)
        suggestions_with_fixtures = top_players.merge(fixture_data, on="web_name", how="left")
        from components.fixture_ticker import render_fixture_ticker
        render_fixture_ticker(suggestions_with_fixtures, top_n=min(top_n, len(suggestions_with_fixtures)))
    else:
        st.info("Fixture data not available.")
