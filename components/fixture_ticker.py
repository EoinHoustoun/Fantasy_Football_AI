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


# ── Single-player strip (2026-07-27) ──────────────────────────────────────────
# The grid above predates the design system and keeps its own palette so the
# pages using it do not shift. Anything NEW uses the binding FDR tokens from
# CLAUDE.md: 1/2 green, 3 yellow, 4 orange, 5 red.
DS_FDR_COLORS = {1: "#00FF87", 2: "#00FF87", 3: "#FFD60A",
                 4: "#FF8C42", 5: "#FF4B4B"}
DS_FDR_TEXT = {1: "#04231a", 2: "#04231a", 3: "#3a2f00",
               4: "#2b1400", 5: "#ffffff"}


def fdr_color(fdr) -> tuple:
    """(background, text) for a fixture difficulty · design-system tokens."""
    try:
        k = int(round(float(fdr)))
    except (TypeError, ValueError):
        return "rgba(255,255,255,0.08)", "rgba(255,255,255,0.5)"
    k = max(1, min(5, k))
    return DS_FDR_COLORS[k], DS_FDR_TEXT[k]


def player_fixture_strip(fixtures_by_gw, team_id: int, gw_lo: int = 1,
                         gw_hi: int = 12, cell: int = 54) -> str:
    """One club's run as a colour-coded strip · opponent, venue, difficulty.

    `fixtures_by_gw` maps (team_id, gw) -> [(opponent_short, is_home, fdr)].
    A gameweek with no fixture renders as a BLANK cell and a gameweek with two
    stacks them, so doubles and blanks are visible rather than silently averaged.

    Returns collapsed HTML · st.markdown escapes raw HTML when an interpolated
    value leaves a whitespace-only line.
    """
    cells = []
    for gw in range(int(gw_lo), int(gw_hi) + 1):
        fx = fixtures_by_gw.get((int(team_id), gw), [])
        head = (f'<div style="font-size:9px;font-weight:800;letter-spacing:0.06em;'
                f'color:rgba(255,255,255,0.4);text-align:center;margin-bottom:3px;">'
                f'{gw}</div>')
        if not fx:
            body = (f'<div style="background:rgba(255,255,255,0.06);'
                    f'border:1px dashed rgba(255,255,255,0.18);border-radius:6px;'
                    f'padding:6px 2px;text-align:center;color:rgba(255,255,255,0.35);'
                    f'font-size:10px;font-weight:800;">BLANK</div>')
        else:
            rows = []
            for opp, is_home, fdr in fx:
                bg, fg = fdr_color(fdr)
                rows.append(
                    f'<div style="background:{bg};color:{fg};border-radius:6px;'
                    f'padding:5px 2px;text-align:center;font-weight:900;'
                    f'font-size:11px;line-height:1.15;">{str(opp).upper()}'
                    f'<div style="font-size:9px;font-weight:800;opacity:0.75;">'
                    f'{"H" if is_home else "A"}</div></div>')
            body = ('<div style="display:flex;flex-direction:column;gap:3px;">'
                    + "".join(rows) + '</div>')
        cells.append(f'<div style="flex:0 0 {cell}px;">{head}{body}</div>')

    html = ('<div style="display:flex;gap:5px;overflow-x:auto;padding:2px 0 6px;">'
            + "".join(cells) + '</div>')
    return " ".join(seg.strip() for seg in html.splitlines())


def run_summary(fixtures_by_gw, team_id: int, gw_lo: int = 1, gw_hi: int = 6) -> dict:
    """Mean difficulty, home count and blanks over a window · the one-line read."""
    fdrs, homes, blanks, n = [], 0, 0, 0
    for gw in range(int(gw_lo), int(gw_hi) + 1):
        fx = fixtures_by_gw.get((int(team_id), gw), [])
        if not fx:
            blanks += 1
            continue
        for _opp, is_home, fdr in fx:
            fdrs.append(float(fdr))
            homes += 1 if is_home else 0
            n += 1
    mean = round(sum(fdrs) / len(fdrs), 2) if fdrs else None
    return {"mean_fdr": mean, "home": homes, "games": n, "blanks": blanks}


# ── Scout's model-based difficulty (2026-07-27) ───────────────────────────────
def load_scout_ticker(path=None):
    """Fantasy Football Scout's fixture ratings · {(team_short, gw): fdr}.

    FPL's own difficulty is a fixed number per club: Palace at home to City and
    away to City score identically, which is plainly wrong. Scout's is
    model-based and varies by venue and opponent form, so it is the better read
    where the two disagree.

    A manual snapshot, like the projections · returns {} when absent so every
    caller falls back to the official rating rather than failing.
    """
    import csv
    from config import CACHE_DIR, NEXT_SEASON
    path = path or CACHE_DIR / ("scout_ticker_%s.csv" % NEXT_SEASON.replace("-", "_"))
    if not path.exists():
        return {}
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            try:
                out[(r["team"], int(r["gw"]))] = float(r["scout_fdr"])
            except (KeyError, TypeError, ValueError):
                continue
    return out
