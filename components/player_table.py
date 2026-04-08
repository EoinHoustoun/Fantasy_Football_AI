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
        "avg_fdr_next_6":       "FDR (6)",
        "avg_fdr_next_5":       "FDR (5)",
        "avg_fdr_next_4":       "FDR (4)",
    }
    display_df = display_df.rename(columns={k: v for k, v in rename_map.items() if k in display_df.columns})

    # ── Default number formats ─────────────────────────────────────────────────
    base_formats = {}
    col_formats = {
        "Price":        "£{:.1f}m",
        "Own%":         "{:.1f}%",
        "Form":         "{:.1f}",
        "PPG":          "{:.1f}",
        "PPM":          "{:.2f}",
        "Score":        "{:.3f}",
        "Diff Score":   "{:.3f}",
        "xG":           "{:.2f}",
        "xA":           "{:.2f}",
        "xG Gap":       "{:.2f}",
        "Haul Score":   "{:.3f}",
        "FDR (6)":      "{:.1f}",
        "FDR (5)":      "{:.1f}",
        "FDR (4)":      "{:.1f}",
    }
    if format_overrides:
        col_formats.update(format_overrides)

    active_formats = {k: v for k, v in col_formats.items() if k in display_df.columns}

    # ── Styling ───────────────────────────────────────────────────────────────
    styler = display_df.style.format(active_formats, na_rep="-")

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
