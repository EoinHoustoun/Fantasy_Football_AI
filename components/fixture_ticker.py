"""
Fixture ticker component.

Renders a colour-coded grid of upcoming fixture difficulties
for a set of players or teams.
"""

import pandas as pd
import streamlit as st

from ui import charts


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

    cell_colors = dict(FDR_COLORS)
    cell_colors[6] = "#444444"   # BGW · dark grey
    text_colors = dict(FDR_TEXT_COLOR)
    text_colors[6] = "#aaaaaa"

    data = []
    for ri, (z_row, text_row, hover_row) in enumerate(
            zip(z_values, text_values, hover_texts)):
        for ci, (fdr, txt, hover) in enumerate(zip(z_row, text_row, hover_row)):
            data.append({
                "value": [ci, ri, fdr],
                "itemStyle": {"color": cell_colors.get(fdr, "#444444"),
                              "borderColor": "#0B0E13", "borderWidth": 3},
                "label": {"show": True, "formatter": txt, "fontSize": 10,
                          "color": text_colors.get(fdr, "#ffffff")},
                "tooltip": {"formatter": f"<b>{player_labels[ri]}</b><br/>{hover}"},
            })

    opt = {
        "backgroundColor": "transparent",
        "grid": {"left": 90, "right": 10, "top": 10, "bottom": 30},
        "tooltip": {"position": "top", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": "#eef1f5", "fontSize": 12}},
        "xAxis": {"type": "category", "data": [f"GW{gw}" for gw in gws_present],
                  "axisLabel": {"color": "rgba(236,241,245,0.55)", "fontSize": 10},
                  "axisTick": {"show": False}, "axisLine": {"show": False}},
        "yAxis": {"type": "category", "data": player_labels, "inverse": True,
                  "axisLabel": {"color": "rgba(236,241,245,0.55)", "fontSize": 11},
                  "axisTick": {"show": False}, "axisLine": {"show": False}},
        "series": [{"type": "heatmap", "data": data,
                    "emphasis": {"itemStyle": {"borderColor": "#fff",
                                               "borderWidth": 1}}}],
    }
    charts.render(opt, height=f"{max(250, 40 * len(player_labels))}px",
                  key="fixture_ticker")
