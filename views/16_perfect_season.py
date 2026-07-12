"""
Perfect Season · what hindsight-optimal 2025-26 FPL looked like.

Reads cached MILP results (scripts/run_perfect_season.py, one JSON per
hit-policy scenario). GW-by-GW replay on a real pitch with kits,
benchmarked against Eoin's actual season and the global winner.

Scenarios:
  Unlimited hits   · pure hindsight ceiling (takes absurd hit counts)
  Realistic hits   · ≤1 hit per GW, ≤6 all season (the playable ceiling)
  No hits          · free transfers only
  Set & forget     · one squad bought GW1, never touched
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from ui import charts
import streamlit as st

from components.animations import inject_global_animations
from components.pitch_view import render_squad_pitch
from config import CACHE_DIR, LAST_COMPLETE_SEASON

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

MUTED = "rgba(255,255,255,0.5)"
CARD = ("background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);"
        "border-radius:12px;padding:14px 18px;")

SEASON_KEY = LAST_COMPLETE_SEASON.replace("-", "_")
ARCHIVE_DIR = CACHE_DIR / "archive"
MY_HISTORY = ARCHIVE_DIR / f"my_entry_history_{SEASON_KEY}.json"

SCENARIO_FILES = [
    ("Unlimited hits", CACHE_DIR / f"perfect_season_{SEASON_KEY}.json", "#00FF87"),
    ("Realistic hits (≤6)", CACHE_DIR / f"perfect_season_{SEASON_KEY}_limited.json", "#FFD700"),
    ("No hits", CACHE_DIR / f"perfect_season_{SEASON_KEY}_nohits.json", "#04f5ff"),
]
SET_AND_FORGET = "Set & forget"


@st.cache_data(ttl=1800, show_spinner=False)
def _load_all():
    scenarios = {}
    for label, path, accent in SCENARIO_FILES:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                scenarios[label] = {"data": json.load(f), "accent": accent}
        except ValueError:
            continue  # partial file from an interrupted run
    mine = None
    if MY_HISTORY.exists():
        with open(MY_HISTORY) as f:
            mine = json.load(f).get("current", [])
    team_codes = {}
    short_names = {}
    bs_path = ARCHIVE_DIR / f"fpl_bootstrap_{SEASON_KEY}_final.json"
    if bs_path.exists():
        with open(bs_path) as f:
            bs = json.load(f)
        team_codes = {int(e["code"]): int(e["team_code"]) for e in bs["elements"]}
        short_names = {int(t["id"]): t["short_name"] for t in bs["teams"]}
    return scenarios, mine, team_codes, short_names


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _replay_lookup():
    """(code, gw) → {pts, fixture_label 'ARS (H)'} for everyone in any squad."""
    from data.processors.archive import load_gw_archive
    _, _, _, short_names = _load_all()
    arch = load_gw_archive()
    if arch is None:
        return {}
    df = arch[arch["season"] == LAST_COMPLETE_SEASON].copy()
    df["opp"] = (df["opponent_team"].map(short_names).fillna("?")
                 + df["was_home"].map(lambda h: " (H)" if h else " (A)"))
    out = {}
    for (code, gw), g in df.groupby(["code", "gw"]):
        out[(int(code), int(gw))] = {
            "pts": float(g["total_points"].sum()),
            "label": " + ".join(g["opp"].tolist()),
        }
    return out


from components.loading import fpl_loader, LINES_SOLVER
with fpl_loader("Replaying the perfect season", LINES_SOLVER):
    scenarios, mine, team_codes, short_names = _load_all()
    replay = _replay_lookup()
if not scenarios:
    st.error("Perfect Season not computed yet · run "
             "`python scripts/run_perfect_season.py` (takes ~30 min).")
    st.stop()

base = next(iter(scenarios.values()))["data"]   # any file carries saf + players
players = base["players"]
saf = base["set_and_forget"]
bench_marks = base["benchmarks"]
my_total = bench_marks.get("my_total") or (mine[-1]["total_points"] if mine else None)


def _name(code) -> str:
    return players.get(str(code), {}).get("web_name", f"#{code}")


def _pos(code) -> str:
    return players.get(str(code), {}).get("position", "MID")


def _pitch_players(squad, xi, captain, gw=None, prices=None):
    rows = []
    for c in squad:
        info = replay.get((int(c), int(gw))) if gw is not None else None
        rows.append({
            "web_name": _name(c),
            "position": _pos(c),
            "team_code": team_codes.get(int(c), 1),
            "on_bench": c not in set(xi),
            "is_captain": c == captain,
            "stat": info["pts"] if info else None,
            "fixture_label": info["label"] if info else ("-" if gw is not None else None),
            "price": (prices or {}).get(c),
        })
    return rows


def _section(title: str, sub: str = "") -> None:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:28px 0 10px;">'
        f'<div style="font-size:11px;font-weight:800;letter-spacing:0.22em;'
        f'text-transform:uppercase;color:{MUTED};white-space:nowrap;">{title}</div>'
        f'<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div></div>'
        + (f'<div style="font-size:12px;color:rgba(255,255,255,0.4);margin-bottom:10px;">{sub}</div>'
           if sub else ""),
        unsafe_allow_html=True,
    )


# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div class="fplh-animate-in" style="padding:18px 0 6px;font-family:'Inter',sans-serif;">
  <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1.2px;">
    🏆 The Perfect Season</div>
  <div style="font-size:14px;color:{MUTED};margin-top:4px;">
    {LAST_COMPLETE_SEASON} with perfect hindsight · pick a hit policy and see
    the ceiling
  </div>
</div>""",
    unsafe_allow_html=True,
)

# scoreboard across every computed scenario
tiles = []
for label, info in scenarios.items():
    d = info["data"]
    tiles.append((label, f"{d['grand_total']:.0f}",
                  f"{d['perfect'].get('total_hits', 0)} hits taken", info["accent"]))
tiles.append((SET_AND_FORGET, f"{saf['total_points']:.0f}",
              "one squad, never touched", "#e90052"))
if my_total:
    tiles.append(("Eoin actual", f"{my_total}", "Vicario Kart", "#FF8C42"))
if bench_marks.get("winner_total"):
    tiles.append(("Global winner", f"{bench_marks['winner_total']}",
                  "best human, no hindsight", "#c084fc"))

st.markdown(
    '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;">'
    + "".join(
        f'<div style="{CARD}flex:1;min-width:140px;">'
        f'<div style="font-size:10px;font-weight:800;letter-spacing:0.12em;color:{MUTED};'
        f'text-transform:uppercase;">{lab}</div>'
        f'<div style="font-size:26px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>'
        for lab, val, sub, acc in tiles)
    + "</div>",
    unsafe_allow_html=True,
)

# ── Scenario picker ───────────────────────────────────────────────────────────
mode = st.radio("Scenario", list(scenarios.keys()) + [SET_AND_FORGET],
                horizontal=True, label_visibility="collapsed")

# ══════════════════════════════════════════════════════════════════════════════
if mode == SET_AND_FORGET:
    # ── Set & forget view ─────────────────────────────────────────────────────
    prices = {int(c): players.get(str(c), {}).get("start_price") for c in saf["squad_codes"]}
    season_pts = {}
    for g in saf["per_gw"]:
        for c in g["xi"]:
            season_pts[c] = season_pts.get(c, 0)
    # season totals per squad player (XI appearances + captain doubles)
    _section(f"The £{saf['squad_cost']:.1f}m squad that scores "
             f"{saf['total_points']:.0f} without a single transfer",
             "Slide through the season to see the optimal XI and armband each week.")
    gw_pick = st.slider("Gameweek", 1, len(saf["per_gw"]), 1, key="saf_gw")
    g = saf["per_gw"][gw_pick - 1]
    st.markdown(
        f'<div style="margin-bottom:10px;"><span style="background:rgba(233,0,82,0.12);'
        f'border:1px solid rgba(233,0,82,0.4);color:#e90052;font-size:12px;font-weight:800;'
        f'padding:4px 12px;border-radius:20px;">GW{g["gw"]} · {g["points"]:.0f} pts</span></div>',
        unsafe_allow_html=True)
    render_squad_pitch(
        _pitch_players(saf["squad_codes"], g["xi"], g["captain"],
                       gw=g["gw"], prices=prices),
        stat_label="pts", title_right=f"GW{g['gw']}")
    weekly = pd.DataFrame(saf["per_gw"])
    opt = charts.bar_option(x=list(weekly["gw"]),
                            y=[round(float(v), 1) for v in weekly["points"]],
                            color="#e90052")
    opt["tooltip"]["formatter"] = "GW{b}: {c} pts"
    charts.render(opt, height="260px", key="ps_saf_weekly")

else:
    # ── Transfer-scenario view ────────────────────────────────────────────────
    sel = scenarios[mode]["data"]
    accent = scenarios[mode]["accent"]
    perfect = sel["perfect"]
    per_gw = perfect["per_gw"]
    grand = sel["grand_total"]

    # points race
    _section("The points race", "Cumulative net points, perfect vs reality.")
    gws = [g["gw"] for g in per_gw]
    perfect_cum = pd.Series([g["net_points"] for g in per_gw]).cumsum()
    race = [(f"Perfect ({mode})", list(zip(gws, [float(v) for v in perfect_cum])),
             accent)]
    if mine:
        race.append(("Eoin (Vicario Kart)",
                     [(e["event"], e["total_points"]) for e in mine], "#FF8C42"))
    opt = charts.multi_line_option(race, x_name="Gameweek", y_name="Total points")
    chip_marks = [(g["gw"], "+".join(g["chips"])) for g in per_gw if g["chips"]]
    if chip_marks:
        charts.with_vertical_marks(opt, chip_marks)
    charts.render(opt, height="420px", key=f"ps_race_{mode}")

    # stats strip
    n_transfers = sum(len(g["transfers_in"]) for g in per_gw)
    total_hits = perfect.get("total_hits", 0)
    hold_counts = pd.Series([c for g in per_gw for c in g["squad"]]).value_counts()
    cap_counts = pd.Series([g["captain"] for g in per_gw]).value_counts()
    best_gw = max(per_gw, key=lambda g: g["net_points"])

    _section("How this scenario played it")
    facts = [
        ("Total", f"{grand:.0f}", "incl. Free Hit gains", accent),
        ("Transfers", f"{n_transfers}", f"{total_hits} hits ({total_hits * 4} pts paid)", "#04f5ff"),
        ("Most held", _name(hold_counts.index[0]), f"{hold_counts.iloc[0]} of 38 GWs", "#00FF87"),
        ("Top captain", _name(cap_counts.index[0]), f"{cap_counts.iloc[0]} armbands", "#FFD700"),
        ("Best GW", f"GW{best_gw['gw']}",
         f"{best_gw['net_points']:.0f} pts"
         + (f" ({'+'.join(best_gw['chips'])})" if best_gw["chips"] else ""), "#e90052"),
    ]
    for f_ in sel.get("free_hit", []):
        facts.append((f"Free Hit H{f_['half']}", f"GW{f_['gw']}",
                      f"+{f_['gain']:.0f} pts vs holding", "#FF8C42"))
    st.markdown(
        '<div class="fplh-stagger" style="display:flex;gap:10px;flex-wrap:wrap;">'
        + "".join(
            f'<div class="fplh-card-hover" style="{CARD}flex:1;min-width:150px;">'
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.12em;color:{MUTED};'
            f'text-transform:uppercase;">{lab}</div>'
            f'<div style="font-size:19px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
            f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>'
            for lab, val, sub, acc in facts)
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── GW replay on the pitch ────────────────────────────────────────────────
    _section("Gameweek replay", "Scrub through the perfect manager's season · kits and all.")
    gw_pick = st.slider("Gameweek", 1, len(per_gw), 1, key=f"gw_{mode}")
    g = per_gw[gw_pick - 1]

    meta_bits = [f"{g['net_points']:.0f} pts", f"bank £{g['bank']:.1f}m",
                 f"squad £{g['squad_value']:.1f}m"]
    if g["chips"]:
        meta_bits.append("🃏 " + "+".join(g["chips"]))
    if g["hit_cost"]:
        meta_bits.append(f"−{g['hit_cost']} hit")
    st.markdown(
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">'
        + "".join(f'<span style="background:rgba(0,255,135,0.08);border:1px solid '
                  f'rgba(0,255,135,0.3);color:#00FF87;font-size:12px;font-weight:800;'
                  f'padding:4px 12px;border-radius:20px;">{b}</span>' for b in meta_bits)
        + "</div>", unsafe_allow_html=True)

    if g["transfers_in"]:
        st.markdown(
            '<div style="margin-bottom:12px;font-size:13px;">'
            + " · ".join(
                f'<span style="color:#FF4B4B;">{_name(o)} ➜</span> '
                f'<span style="color:#00FF87;font-weight:800;">{_name(i)}</span>'
                for o, i in zip(g["transfers_out"], g["transfers_in"]))
            + "</div>", unsafe_allow_html=True)

    render_squad_pitch(
        _pitch_players(g["squad"], g["xi"], g["captain"], gw=g["gw"]),
        stat_label="pts", title_right=f"GW{g['gw']}")

    # ── lessons ───────────────────────────────────────────────────────────────
    _section("What this scenario teaches")
    top_holds = [(_name(c), int(n)) for c, n in hold_counts.head(8).items()]
    cap_spread = [(_name(c), int(n)) for c, n in cap_counts.head(5).items()]
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f'<div style="{CARD}"><div style="font-size:13px;font-weight:800;color:#fff;'
            f'margin-bottom:8px;">🧲 Core holds · buy and forget</div>'
            + "".join(
                f'<div style="display:flex;justify-content:space-between;padding:5px 0;'
                f'border-bottom:1px solid rgba(255,255,255,0.05);font-size:12px;">'
                f'<span style="color:#fff;font-weight:700;">{n}</span>'
                f'<span style="color:#00FF87;font-weight:800;">{c}/38 GWs</span></div>'
                for n, c in top_holds)
            + "</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(
            f'<div style="{CARD}"><div style="font-size:13px;font-weight:800;color:#fff;'
            f'margin-bottom:8px;">🎯 Armband distribution</div>'
            + "".join(
                f'<div style="display:flex;justify-content:space-between;padding:5px 0;'
                f'border-bottom:1px solid rgba(255,255,255,0.05);font-size:12px;">'
                f'<span style="color:#fff;font-weight:700;">{n}</span>'
                f'<span style="color:#FFD700;font-weight:800;">{c} GWs</span></div>'
                for n, c in cap_spread)
            + "</div>", unsafe_allow_html=True)

st.markdown(
    '<div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:18px;">'
    + " · ".join(base.get("notes", [])) + "</div>",
    unsafe_allow_html=True)
