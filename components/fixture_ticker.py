"""
Fixture ticker component.

Renders a colour-coded grid of upcoming fixture difficulties
for a set of players or teams.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# FDR colour scale: 1=easiest (green), 5=hardest (red)
FDR_COLORS = {
    1: "#00FF87",   # bright green
    2: "#00c248",   # green
    3: "#e7e7e7",   # grey (neutral)
    4: "#ff8c00",   # orange
    5: "#ff0057",   # red
}
FDR_TEXT_COLOR = {
    1: "#000000",
    2: "#000000",
    3: "#333333",
    4: "#000000",
    5: "#ffffff",
}


def render_fixture_ticker(players_df: pd.DataFrame, top_n: int = 15) -> None:
    """
    Render a fixture difficulty ticker for the top N players.

    Shows a heat-map-style grid: rows = players, columns = upcoming GWs,
    cells coloured by FDR (1=green, 5=red).
    """
    if "upcoming_fixtures" not in players_df.columns:
        st.warning("No fixture data available.")
        return

    df = players_df.dropna(subset=["upcoming_fixtures"]).head(top_n).copy()
    if df.empty:
        st.info("No players to display.")
        return

    # Build grid: rows = players, columns = GWs
    gws_present = sorted(set(
        f["gw"]
        for fixtures in df["upcoming_fixtures"]
        if isinstance(fixtures, list)
        for f in fixtures
    ))

    player_labels = df["web_name"].tolist()

    z_values = []       # FDR values for colour
    text_values = []    # Labels inside cells
    hover_texts = []

    for _, row in df.iterrows():
        fxs = {f["gw"]: f for f in (row["upcoming_fixtures"] or [])}
        z_row, text_row, hover_row = [], [], []
        dgw_gws = set(row.get("dgw_gameweeks") or [])
        bgw_gws = set(row.get("bgw_gameweeks") or [])

        for gw in gws_present:
            if gw in fxs:
                f = fxs[gw]
                fdr = f["fdr"]
                opp = f["opponent"]
                h_a = "H" if f["home"] else "A"
                marker = " 2x" if gw in dgw_gws else ""
                z_row.append(fdr)
                text_row.append(f"{opp[:3].upper()} ({h_a}){marker}")
                hover_row.append(f"GW{gw}: {opp} ({h_a}) · FDR {fdr}{' · DOUBLE GW' if gw in dgw_gws else ''}")
            else:
                z_row.append(6)  # use 6 to get a distinct grey for BGW
                marker = "BGW" if gw in bgw_gws else "-"
                text_row.append(marker)
                hover_row.append(f"GW{gw}: {'Blank Gameweek · no fixture' if gw in bgw_gws else 'No fixture'}")
        z_values.append(z_row)
        text_values.append(text_row)
        hover_texts.append(hover_row)

    fig = go.Figure(data=go.Heatmap(
        z=z_values,
        x=[f"GW{gw}" for gw in gws_present],
        y=player_labels,
        text=text_values,
        hovertext=hover_texts,
        hoverinfo="text",
        texttemplate="%{text}",
        colorscale=[
            [0.0,   FDR_COLORS[1]],
            [0.2,   FDR_COLORS[2]],
            [0.4,   FDR_COLORS[3]],
            [0.6,   FDR_COLORS[4]],
            [0.8,   FDR_COLORS[5]],
            [1.0,   "#444444"],   # BGW · dark grey
        ],
        zmin=1, zmax=6,
        showscale=False,
        xgap=3,
        ygap=3,
    ))

    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=max(250, 40 * len(player_labels)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        yaxis=dict(autorange="reversed"),
    )

    st.plotly_chart(fig, use_container_width=True)
