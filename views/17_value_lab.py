"""
Value Lab · 10 seasons of FPL price-vs-points exploration.

Where does value actually live? Start-price vs total-points frontiers,
price-band ROI, DEFCON earners, price movers, and whether value repeats
season to season. All reads from the prebuilt archive · zero compute.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components.animations import inject_global_animations
from config import ARCHIVE_SEASONS, LAST_COMPLETE_SEASON

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:14px 18px;")


@st.cache_data(ttl=24 * 3600)
def _summary() -> pd.DataFrame:
    from data.processors.archive import load_season_summary
    return load_season_summary()


def _section(title: str, sub: str = "") -> None:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:30px 0 4px;">'
        f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;'
        f'text-transform:uppercase;color:{MUTED};white-space:nowrap;">{title}</div>'
        f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>'
        + (f'<div style="font-size:12px;color:rgba(255,255,255,0.4);margin-bottom:10px;">{sub}</div>'
           if sub else ""),
        unsafe_allow_html=True,
    )


def _tile(label: str, value: str, sub: str, accent: str = "#fff") -> str:
    return (f'<div style="{CARD}min-width:150px;flex:1;">'
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.14em;color:{MUTED};'
            f'text-transform:uppercase;">{label}</div>'
            f'<div style="font-size:26px;font-weight:900;color:{accent};margin:2px 0;">{value}</div>'
            f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>')


summary = _summary()
if summary is None or summary.empty:
    st.error("Archive not built · run `python scripts/build_archive.py` first.")
    st.stop()

played = summary[summary["minutes"] >= 900].copy()

# ── Hero ──────────────────────────────────────────────────────────────────────
best_value = played.loc[played["pts_per_million"].idxmax()]
n_seasons = summary["season"].nunique()
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">🔬 Value Lab</div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    {n_seasons} seasons · {len(summary):,} player-seasons · where FPL value actually lives
  </div>
</div>""",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 6px;">'
    + _tile("Seasons", f"{n_seasons}", "2016-17 → 2025-26", "#04f5ff")
    + _tile("Best value ever", best_value["web_name"],
            f"{best_value['season']} · £{best_value['start_price']:.1f} → "
            f"{best_value['total_points']:.0f} pts", "#00FF87")
    + _tile("Pts per £m", f"{best_value['pts_per_million']:.1f}",
            "the bar every pick chases", "#FFD700")
    + "</div>",
    unsafe_allow_html=True,
)

# ── Controls ──────────────────────────────────────────────────────────────────
c1, c2 = st.columns([1, 3])
with c1:
    season_pick = st.selectbox(
        "Season", ["All seasons"] + ARCHIVE_SEASONS[::-1],
        index=1)  # default last complete season
view = played if season_pick == "All seasons" else played[played["season"] == season_pick]

# ── Value frontier ────────────────────────────────────────────────────────────
_section("The value frontier",
         "Start price vs season points. Above the dotted lines = elite value. Min 900 minutes.")
fig = px.scatter(
    view, x="start_price", y="total_points", color="position",
    hover_name="web_name",
    hover_data={"season": True, "pts_per_million": ":.1f",
                "start_price": ":.1f", "total_points": ":.0f"},
    color_discrete_map=POS_COLORS, opacity=0.75,
    labels={"start_price": "GW1 price (£m)", "total_points": "Season points"},
)
for ppm, lab in ((20, "20 pts/£m"), (30, "30 pts/£m")):
    fig.add_trace(go.Scatter(
        x=[3.8, 15], y=[3.8 * ppm, 15 * ppm], mode="lines",
        line=dict(color="rgba(255,255,255,0.25)", dash="dot", width=1),
        name=lab, hoverinfo="skip"))
fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font_color="#e2e2e2", height=520,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.06)", range=[0, max(view["total_points"].max() * 1.05, 100)]),
    margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(fig, use_container_width=True)

# ── Price-band ROI ────────────────────────────────────────────────────────────
_section("Return by price band",
         "Average points per £m by starting price. Cheap defenders are the engine room.")
view = view.copy()
view["band"] = pd.cut(view["start_price"],
                      bins=[3.5, 4.5, 5.5, 6.5, 8.0, 10.0, 16.0],
                      labels=["≤4.5", "4.6–5.5", "5.6–6.5", "6.6–8.0", "8.1–10.0", "10.0+"])
roi = (view.groupby(["band", "position"], observed=True)["pts_per_million"]
       .mean().reset_index())
fig2 = px.bar(roi, x="band", y="pts_per_million", color="position", barmode="group",
              color_discrete_map=POS_COLORS,
              labels={"band": "GW1 price band (£m)", "pts_per_million": "Avg pts per £m"})
fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                   font_color="#e2e2e2", height=380,
                   legend=dict(orientation="h", yanchor="bottom", y=1.02),
                   xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                   yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                   margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(fig2, use_container_width=True)

# ── Archetype leaderboards ────────────────────────────────────────────────────
_section("Archetypes", "The three squads every winning team is built from.")
arch_cols = st.columns(3)
archetypes = [
    ("💎 Budget enablers", view[view["start_price"] <= 4.5], "#00FF87"),
    ("⚙️ Mid-price engines", view[(view["start_price"] > 4.5) & (view["start_price"] <= 8.0)], "#04f5ff"),
    ("👑 Premium anchors", view[view["start_price"] > 8.0], "#FFD700"),
]
for col, (title, grp, accent) in zip(arch_cols, archetypes):
    top5 = grp.nlargest(5, "pts_per_million" if accent != "#FFD700" else "total_points")
    rows = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:5px 0;'
        f'border-bottom:1px solid rgba(255,255,255,0.05);font-size:12px;">'
        f'<span style="color:#fff;font-weight:700;">{r["web_name"][:14]}'
        f'<span style="color:rgba(255,255,255,0.35);font-weight:400;"> '
        f'{r["season"][2:] if season_pick == "All seasons" else ""}</span></span>'
        f'<span style="color:{accent};font-weight:800;">£{r["start_price"]:.1f} · '
        f'{r["total_points"]:.0f}</span></div>'
        for _, r in top5.iterrows())
    with col:
        st.markdown(
            f'<div class="fplh-card-hover" style="{CARD}border-top:3px solid {accent};">'
            f'<div style="font-size:13px;font-weight:800;color:#fff;margin-bottom:8px;">{title}</div>'
            f'{rows}</div>', unsafe_allow_html=True)

# ── DEFCON earners (2025-26) ──────────────────────────────────────────────────
defcon = summary[(summary["season"] == LAST_COMPLETE_SEASON)
                 & summary["defcon_points"].notna()
                 & (summary["minutes"] >= 900)].nlargest(10, "defcon_points")
if not defcon.empty:
    _section("DEFCON earners · 2025-26",
             "Defensive-contribution points (CBIT / CBIRT thresholds). The new value frontier.")
    fig3 = px.bar(defcon.sort_values("defcon_points"),
                  x="defcon_points", y="web_name", orientation="h",
                  color="position", color_discrete_map=POS_COLORS,
                  hover_data={"start_price": ":.1f", "total_points": ":.0f"},
                  labels={"defcon_points": "DEFCON points", "web_name": ""})
    fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       font_color="#e2e2e2", height=380, showlegend=False,
                       xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                       margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig3, use_container_width=True)

# ── Does value repeat? ────────────────────────────────────────────────────────
_section("Does value repeat?",
         "Pts/£m one season vs the next, same player. The cloud says: a bit · "
         "chase underlying role, not last year's rank.")
pairs = []
for s_n, s_next in zip(ARCHIVE_SEASONS[:-1], ARCHIVE_SEASONS[1:]):
    a = played[played["season"] == s_n][["code", "web_name", "position", "pts_per_million"]]
    b = played[played["season"] == s_next][["code", "pts_per_million"]].rename(
        columns={"pts_per_million": "ppm_next"})
    pairs.append(a.merge(b, on="code"))
rep = pd.concat(pairs, ignore_index=True)
corr = rep["pts_per_million"].corr(rep["ppm_next"], method="spearman")
fig4 = px.scatter(rep, x="pts_per_million", y="ppm_next", color="position",
                  hover_name="web_name", color_discrete_map=POS_COLORS, opacity=0.5,
                  labels={"pts_per_million": "Pts/£m season N",
                          "ppm_next": "Pts/£m season N+1"})
fig4.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                   font_color="#e2e2e2", height=420,
                   legend=dict(orientation="h", yanchor="bottom", y=1.02),
                   xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                   yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                   margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(fig4, use_container_width=True)
st.markdown(
    f'<div style="font-size:12px;color:{MUTED};">Season-to-season value correlation '
    f'(Spearman): <span style="color:#00FF87;font-weight:800;">{corr:.2f}</span> '
    f'across {len(rep):,} player-season pairs (min 900 mins both seasons).</div>',
    unsafe_allow_html=True)
