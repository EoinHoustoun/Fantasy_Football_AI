"""
Value Lab · 10 seasons of FPL price-vs-points exploration.

Where does value actually live? Start-price vs total-points frontiers,
price-band ROI, DEFCON earners, price movers, and whether value repeats
season to season. All reads from the prebuilt archive · zero compute.
"""

from __future__ import annotations

import pandas as pd
from ui import charts
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
_groups = []
for pos, col in POS_COLORS.items():
    sub = view[view["position"] == pos]
    pts = [{
        "x": round(float(r["start_price"]), 1), "y": int(r["total_points"]),
        "name": str(r["web_name"]), "size": 8,
        "tip": (f"<b>{r['web_name']}</b> · {r['season']}<br/>"
                f"£{r['start_price']:.1f} → {r['total_points']:.0f} pts "
                f"({r['pts_per_million']:.1f} pts/£m)"),
    } for _, r in sub.iterrows()]
    if pts:
        _groups.append((pos, col, pts))
opt = charts.multi_scatter_option(_groups, x_name="GW1 price (£m)",
                                  y_name="Season points")
opt["yAxis"]["max"] = int(max(view["total_points"].max() * 1.05, 100))
for ppm, lab in ((20, "20 pts/£m"), (30, "30 pts/£m")):
    opt["series"].append({
        "name": lab, "type": "line", "data": [[3.8, 3.8 * ppm], [15, 15 * ppm]],
        "symbol": "none", "silent": True, "tooltip": {"show": False},
        "lineStyle": {"type": "dotted", "color": "rgba(255,255,255,0.25)", "width": 1},
        "itemStyle": {"color": "rgba(255,255,255,0.25)"}, "z": 1,
    })
charts.render(opt, height="520px", key="vl_frontier")

# ── Price-band ROI ────────────────────────────────────────────────────────────
_section("Return by price band",
         "Average points per £m by starting price. Cheap defenders are the engine room.")
view = view.copy()
view["band"] = pd.cut(view["start_price"],
                      bins=[3.5, 4.5, 5.5, 6.5, 8.0, 10.0, 16.0],
                      labels=["≤4.5", "4.6–5.5", "5.6–6.5", "6.6–8.0", "8.1–10.0", "10.0+"])
roi = (view.groupby(["band", "position"], observed=True)["pts_per_million"]
       .mean().reset_index())
_bands = [str(b) for b in roi["band"].cat.categories] if hasattr(roi["band"], "cat") \
    else sorted(roi["band"].astype(str).unique())
_series = []
for pos, col in POS_COLORS.items():
    sub = roi[roi["position"] == pos].set_index(roi[roi["position"] == pos]["band"].astype(str))
    if sub.empty:
        continue
    _series.append((pos, [round(float(sub["pts_per_million"].get(b, 0) or 0), 1)
                          for b in _bands], col))
opt = charts.grouped_bars_option(_bands, _series)
opt["tooltip"]["formatter"] = "{a} · {b}: {c} pts/£m"
opt["tooltip"]["trigger"] = "item"
charts.render(opt, height="380px", key="vl_roi_bands")

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
    dc = defcon.sort_values("defcon_points", ascending=False)
    opt = charts.bar_option(
        x=list(dc["web_name"]),
        y=[int(v) for v in dc["defcon_points"]],
        colors=[POS_COLORS.get(p, "#00FF87") for p in dc["position"]],
        horizontal=True)
    for item, (_, r) in zip(opt["series"][0]["data"], dc.iterrows()):
        item["tooltip"] = {"formatter": (
            f"<b>{r['web_name']}</b> ({r['position']})<br/>"
            f"{r['defcon_points']:.0f} DEFCON pts · £{r['start_price']:.1f} · "
            f"{r['total_points']:.0f} total")}
    charts.render(opt, height="380px", key="vl_defcon")

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
_rep_groups = []
for pos, col in POS_COLORS.items():
    sub = rep[rep["position"] == pos]
    pts = [{"x": round(float(r["pts_per_million"]), 1),
            "y": round(float(r["ppm_next"]), 1),
            "name": str(r["web_name"]), "size": 7}
           for _, r in sub.iterrows()]
    if pts:
        _rep_groups.append((pos, col, pts))
opt = charts.multi_scatter_option(_rep_groups, x_name="Pts/£m season N",
                                  y_name="Pts/£m season N+1")
for s in opt["series"]:
    for d in s["data"]:
        d["itemStyle"]["opacity"] = 0.5
charts.render(opt, height="420px", key="vl_repeat")
st.markdown(
    f'<div style="font-size:12px;color:{MUTED};">Season-to-season value correlation '
    f'(Spearman): <span style="color:#00FF87;font-weight:800;">{corr:.2f}</span> '
    f'across {len(rep):,} player-season pairs (min 900 mins both seasons).</div>',
    unsafe_allow_html=True)
