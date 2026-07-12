"""
Styled player table component.

Renders a sortable, colour-coded DataFrame as a Streamlit table
with consistent styling across all pages.
"""

import pandas as pd
import streamlit as st
from typing import Optional

from config import ACCENT_COLOR, DANGER_COLOR, WARNING_COLOR


def render_player_table(
    df: pd.DataFrame,
    highlight_col: Optional[str] = None,
    format_overrides: Optional[dict] = None,
    height: int = 400,
) -> None:
    """
    Render a styled player DataFrame.

    All numeric stats are rounded to 2 decimal places for a clean,
    professional look. Price shown as £X.Xm, Own% as percentage.

    Args:
        df: DataFrame to display
        highlight_col: Column to colour-gradient highlight (e.g. "transfer_score")
        format_overrides: Dict of {col: format_string} e.g. {"price": "£{:.1f}m"}
        height: Table height in pixels
    """
    display_df = df.copy()

    # ── Column renaming for readability ───────────────────────────────────────
    rename_map = {
        "web_name":             "Player",
        "team":                 "Team",
        "position":             "Pos",
        "price":                "Price",
        "ownership":            "Own%",
        "form":                 "Form",
        "total_points":         "Pts",
        "points_per_game":      "PPG",
        "points_per_million":   "PPM",
        "transfer_score":       "Score",
        "differential_score":   "Diff Score",
        "xg":                   "xG",
        "xa":                   "xA",
        "xg_gap":               "xG Gap",
        "goals_scored":         "Goals",
        "assists":              "Assists",
        "haul_potential":       "Haul Score",
        "ceiling_pts":          "Ceiling",
        "projected_season_pts": "Season Proj",
        "ep_next":              "xP",
        "avg_fdr_next_6":       "FDR (6)",
        "avg_fdr_next_5":       "FDR (5)",
        "avg_fdr_next_4":       "FDR (4)",
    }
    display_df = display_df.rename(columns={k: v for k, v in rename_map.items() if k in display_df.columns})

    # ── Number formats · everything rounded to 2dp ────────────────────────────
    col_formats = {
        "Price":        "£{:.2f}m",
        "Own%":         "{:.2f}%",
        "Form":         "{:.2f}",
        "PPG":          "{:.2f}",
        "PPM":          "{:.2f}",
        "Score":        "{:.2f}",
        "Diff Score":   "{:.2f}",
        "xG":           "{:.2f}",
        "xA":           "{:.2f}",
        "xG Gap":       "{:.2f}",
        "Haul Score":   "{:.2f}",
        "Ceiling":      "{:.2f}",
        "Season Proj":  "{:.2f}",
        "xP":           "{:.2f}",
        "FDR (6)":      "{:.2f}",
        "FDR (5)":      "{:.2f}",
        "FDR (4)":      "{:.2f}",
    }
    if format_overrides:
        col_formats.update(format_overrides)

    active_formats = {k: v for k, v in col_formats.items() if k in display_df.columns}

    # ── Styling ───────────────────────────────────────────────────────────────
    styler = (
        display_df.style
        .format(active_formats, na_rep="-")
        .set_properties(**{
            "font-family": "'Inter', 'SF Pro Display', sans-serif",
            "font-size": "13px",
            "padding": "8px 10px",
        })
        .set_table_styles([
            {"selector": "th",
             "props": [("background", "rgba(255,255,255,0.04)"),
                       ("color", "rgba(255,255,255,0.75)"),
                       ("font-weight", "700"),
                       ("text-transform", "uppercase"),
                       ("letter-spacing", "0.04em"),
                       ("font-size", "11px"),
                       ("padding", "10px 10px"),
                       ("border-bottom", "1px solid rgba(255,255,255,0.1)")]},
            {"selector": "td",
             "props": [("border-bottom", "1px solid rgba(255,255,255,0.04)")]},
            {"selector": "tr:hover td",
             "props": [("background", "rgba(255,255,255,0.03)")]},
        ])
    )

    if highlight_col and highlight_col in display_df.columns:
        styler = styler.bar(
            subset=[highlight_col],
            color=["#d65f5f", "#5fba7d"],
            align="mid",
        )

    # Low ownership = muted blue background (differential appeal)
    if "Own%" in display_df.columns:
        styler = styler.bar(
            subset=["Own%"],
            color="#4da6ff",
            align="left",
        )

    st.dataframe(
        styler,
        use_container_width=True,
        height=height,
        hide_index=True,
    )
