"""
Transfers · rebuilt on the shared engine (2026-09-27).

The old page ranked a hand-weighted blend of form, fixture ease, xG, value,
transfer trend and minutes. Walk-forward, 30-day form ranks the next three
gameweeks at Spearman ~0.25 against ~0.5 for a real projection, and it
recommended Saka -> Groß and Haaland -> Kostoulas on a Brighton hot streak.

Three sections, one engine (`analytics/service.py`, which Claude's MCP server
also calls):

1. **Best single moves** · each priced on what the TEAM scores (best XI and
   captain every week), not on the incoming player's total, so a bench keeper
   upgrade is worth what a bench keeper is worth.
2. **Plan the next weeks** · the multi-week MILP: when to move, when to bank,
   captain per week, measured against holding.
3. **Target board** · everyone, per-gameweek xP, fixtures and minutes.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

from analytics import brain, service
from components import ff_table as T
from components.animations import inject_global_animations
from components.loading import LINES_SOLVER, fpl_loader
from components.team_identity import face_html, player_photo_url
from ui import theme
from ui.theme import var as V

inject_global_animations()


def _one(html: str) -> str:
    return "".join(seg.strip() for seg in html.splitlines())


def _label(txt: str, color: str = "muted") -> str:
    return (f'<div style="font-size:10px;font-weight:700;letter-spacing:0.14em;'
            f'text-transform:uppercase;color:{V(color)};">{txt}</div>')


def _section(title: str, lead: str, icon: str) -> None:
    st.markdown(_one(
        f'<div style="display:flex;align-items:center;gap:10px;margin:26px 0 10px;">'
        f'{theme.icon(icon, 20, V("mint"))}'
        f'<div class="ff-display" style="font-size:19px;font-weight:800;color:{V("text")};">{title}</div>'
        f'<div style="flex:1;height:1px;background:{V("line")};"></div></div>'
        f'<div style="font-size:13px;color:{V("muted")};margin:-4px 0 12px;">{lead}</div>'),
        unsafe_allow_html=True)


# ── Data ──────────────────────────────────────────────────────────────────────
team_id = int(st.session_state.get("squad_team_id") or service.default_team_id() or 0)
long = service.projections(allow_compute=False)
if long is None:
    brain.warm_async(st.session_state.get("bootstrap") or {}, st.session_state.get("players_df"),
                     st.session_state.get("fixtures_df"))
    st.info("Projections are rebuilding after the last gameweek. This takes a few "
            "minutes · reload shortly.")
    st.stop()

T_ = service.team(team_id)
GWS = sorted(long["gw"].unique())
first = int(GWS[0])

# ── Header ────────────────────────────────────────────────────────────────────
chips_left = ", ".join(c for c in T_["chips"]["remaining"]) or "none"
st.markdown(_one(
    f'<div class="fplh-animate-in" style="padding:14px 0 4px;">'
    f'<div class="ff-display" style="font-size:36px;font-weight:900;color:{V("text")};'
    f'letter-spacing:-0.8px;">Transfers</div>'
    f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">'
    + "".join(
        f'<span style="padding:5px 11px;border-radius:999px;border:1px solid {V("line")};'
        f'background:{V("card")};font-size:12.5px;color:{V("muted")};">{k} '
        f'<b class="ff-num" style="color:{V(c)};">{v}</b></span>'
        for k, v, c in (("Next", "GW%d" % first, "text"),
                        ("Free transfers", T_["free_transfers"], "mint"),
                        ("Bank", "£%.1fm" % T_["bank"], "gold"),
                        ("Chips left", {"freehit": "Free Hit", "wildcard": "Wildcard",
                                        "bboost": "Bench Boost", "3xc": "Triple Captain"}
                         .get(chips_left, chips_left), "cyan")))
    + '</div></div>'), unsafe_allow_html=True)

# ── 1 · Best single moves ─────────────────────────────────────────────────────
H = 6
bm = service.best_moves(team_id, horizon=H, top_n=6)
_section("Best single moves",
         "Each move priced on your team's points over GW%d-%d: best XI and captain every "
         "week, bench at a tenth. A move has to clear about 2 points to beat the noise."
         % (bm["gws"][0], bm["gws"][-1]), "swap_horiz")

pos_by_code = dict(zip(long["code"], long["position"]))
team_by_code = dict(zip(long["code"], long["team_code"]))


def _move_card(m: Dict, rank: int) -> str:
    good = m["gain"] >= 2.0
    tone = "mint" if good else ("gold" if m["gain"] > 0 else "muted")
    verdict = "Worth a transfer" if good else ("Marginal" if m["gain"] > 0 else "Hold")
    cost = m["cost_change"]
    cost_txt = ("+£%.1fm" % cost) if cost > 0 else ("£%.1fm back" % -cost if cost < 0 else "level")
    f_out = face_html(m["out_code"], team_by_code.get(m["out_code"], 1),
                      pos_by_code.get(m["out_code"]) == "GKP", width=46)
    f_in = face_html(m["in_code"], m.get("in_team_code") or team_by_code.get(m["in_code"], 1),
                     pos_by_code.get(m["in_code"]) == "GKP", width=46)
    return _one(
        f'<div class="fplh-card-hover" style="background:{V("card")};border:1px solid {V("line")};'
        f'border-top:3px solid {V(tone)};border-radius:14px;padding:14px 16px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'{_label("%d · %s" % (rank, verdict), tone)}'
        f'<div class="ff-display ff-num" style="font-size:24px;font-weight:900;color:{V(tone)};">'
        f'{"+" if m["gain"] >= 0 else ""}{m["gain"]:.1f}</div></div>'
        f'<div style="display:flex;align-items:center;gap:10px;margin-top:8px;">'
        f'<div style="text-align:center;opacity:0.75;">{f_out}<div style="font-size:12px;'
        f'color:{V("muted")};margin-top:3px;max-width:70px;overflow:hidden;text-overflow:ellipsis;'
        f'white-space:nowrap;">{m["out"]}</div></div>'
        f'<div style="flex:1;text-align:center;">{theme.icon("arrow_forward", 22, V(tone))}'
        f'<div style="font-size:11.5px;color:{V("muted")};">{cost_txt}</div></div>'
        f'<div style="text-align:center;">{f_in}<div style="font-size:12.5px;font-weight:700;'
        f'color:{V("text")};margin-top:3px;max-width:80px;overflow:hidden;text-overflow:ellipsis;'
        f'white-space:nowrap;">{m["in"]}</div></div></div></div>')


if bm["moves"]:
    cols = st.columns(3)
    for i, m in enumerate(bm["moves"][:6]):
        with cols[i % 3]:
            st.markdown(_move_card(m, i + 1), unsafe_allow_html=True)
            if st.button("Put in my planner", key="bm_%d" % i, use_container_width=True,
                         type="secondary"):
                r = service.save_plan_to_app([{"gw": first, "out": [m["out"]], "in": [m["in"]]}],
                                             team_id)
                st.toast("Drafted in My Team for GW%d" % first if r.get("ok") else r.get("error"))
else:
    st.info("No affordable move improves the team over this window.")

# ── 2 · Multi-week plan ───────────────────────────────────────────────────────
_section("Plan the next weeks",
         "One optimisation over the whole window: when to move, when to bank a transfer, "
         "who captains. Judged against holding your fifteen.", "route")

c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2])
with c1:
    horizon = st.select_slider("Weeks", options=[3, 4, 5, 6, 7, 8], value=6, key="tp_h")
with c2:
    friction = st.select_slider("Bar per move (pts)", options=[0.0, 1.0, 2.0, 3.0, 4.0],
                                value=2.0, key="tp_f",
                                help="A move must gain at least this much to be made. "
                                     "0 lets the solver churn on noise.")
with c3:
    decay = st.select_slider("Trust in later weeks", options=[0.8, 0.85, 0.9, 0.95, 1.0],
                             value=0.9, key="tp_d",
                             help="Week k counts decay^k. Lower = care more about the near term.")
with c4:
    st.markdown('<div style="height:26px;"></div>', unsafe_allow_html=True)
    run = st.button("Solve the plan", type="primary", use_container_width=True, key="tp_run")

_pkey = "tp_result::%d::%d" % (team_id, first)
if run:
    with fpl_loader("Solving %d weeks of transfers" % horizon, LINES_SOLVER):
        st.session_state[_pkey] = service.optimise(
            team_id, horizon, None, {"friction": friction, "decay": decay}, alternatives=2)
res = st.session_state.get(_pkey)


def _week_card(w: Dict) -> str:
    moves = "".join(
        f'<div style="display:flex;gap:6px;align-items:center;font-size:12.5px;margin:3px 0;">'
        f'<span style="color:{V("red")};">{o}</span>{theme.icon("arrow_forward", 14, V("muted"))}'
        f'<span style="color:{V("mint")};font-weight:700;">{i}</span></div>'
        for o, i in zip(w["out_names"], w["in_names"]))
    if not moves:
        moves = (f'<div style="font-size:12.5px;color:{V("muted")};">Bank the transfer</div>')
    hit = (f'<span style="color:{V("red")};font-weight:700;"> · -{4 * w["hits"]}</span>'
           if w["hits"] else "")
    return _one(
        f'<div style="background:{V("card")};border:1px solid {V("line")};border-radius:12px;'
        f'padding:12px 14px;min-height:150px;">'
        f'<div style="display:flex;justify-content:space-between;">'
        f'<div class="ff-display" style="font-size:18px;font-weight:900;color:{V("text")};">GW{w["gw"]}</div>'
        f'<div class="ff-num" style="font-size:13px;color:{V("cyan")};font-weight:700;">{w["xp"]:.1f} xP{hit}</div></div>'
        f'<div style="font-size:11px;color:{V("muted")};margin-bottom:6px;">{w["ft_before"]} FT · '
        f'£{w["bank_after"]:.1f}m after</div>{moves}'
        f'<div style="margin-top:8px;font-size:12px;color:{V("muted")};">Captain '
        f'<b style="color:{V("gold")};">{w["captain_name"]}</b></div></div>')


if res and res.get("best", {}).get("weeks"):
    best, hold = res["best"], res["hold"]
    gain = res.get("gain_vs_hold") or 0.0
    st.markdown(_one(
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 12px;">'
        + "".join(
            f'<div style="background:{V("card")};border:1px solid {V("line")};border-radius:12px;'
            f'padding:10px 16px;min-width:150px;">{_label(k)}'
            f'<div class="ff-display ff-num" style="font-size:24px;font-weight:900;color:{V(c)};">{v}</div></div>'
            for k, v, c in (("Plan xP", "%.1f" % best["xp_total"], "mint"),
                            ("If you hold", "%.1f" % hold["xp_total"], "muted"),
                            ("Gain, weighted", "%+.1f" % gain, "gold" if gain >= 2 else "muted"),
                            ("FTs left at end", best["ft_end"], "cyan")))
        + '</div>'), unsafe_allow_html=True)
    wk = best["weeks"]
    cols = st.columns(len(wk))
    for c, w in zip(cols, wk):
        with c:
            st.markdown(_week_card(w), unsafe_allow_html=True)
    b1, b2 = st.columns([1, 3])
    with b1:
        if st.button("Send this plan to My Team", key="tp_send", use_container_width=True):
            r = service.save_plan_to_app(
                [{"gw": w["gw"], "out": w["out_names"], "in": w["in_names"],
                  "captain": w["captain_name"]} for w in wk], team_id)
            st.toast("Drafted %d weeks in My Team" % len(r.get("saved_drafts", []))
                     if r.get("ok") else r.get("error"))
    if res.get("alternatives"):
        with st.expander("Other ways to play GW%d" % first):
            for a in res["alternatives"]:
                w0 = a["weeks"][0]
                mv = ", ".join("%s → %s" % (o, i) for o, i in zip(w0["out_names"], w0["in_names"])) or "hold"
                st.markdown(_one(
                    f'<div style="display:flex;justify-content:space-between;padding:8px 2px;'
                    f'border-bottom:1px solid {V("line")};font-size:13px;">'
                    f'<span style="color:{V("text")};">{mv}</span>'
                    f'<span class="ff-num" style="color:{V("muted")};">'
                    f'{a["objective"] - best["objective"]:+.1f} vs best</span></div>'),
                    unsafe_allow_html=True)
elif res:
    st.warning("The solver found no plan (%s)." % res.get("best", {}).get("status"))

# ── 3 · Target board ──────────────────────────────────────────────────────────
_section("Target board",
         "Everyone the engine projects, over the same window. Faces are clickable in "
         "the player card on My Team.", "table_rows")

f1, f2, f4, f3 = st.columns([2, 1.6, 1.4, 1])
with f4:
    max_own = st.select_slider("Owned by at most", options=[1, 3, 5, 10, 20, 50, 100], value=100,
                               key="tb_own", format_func=lambda v: "anyone" if v == 100 else "%d%%" % v,
                               help="Lower it to find differentials: good projections few managers hold.")
with f1:
    pos = st.segmented_control("Position", ["All", "GKP", "DEF", "MID", "FWD"], default="All",
                               key="tb_pos", label_visibility="collapsed") or "All"
with f2:
    maxp = st.slider("Max price", 3.5, 16.0, 16.0, 0.5, key="tb_max", label_visibility="collapsed")
with f3:
    hide_owned = st.toggle("Hide my players", value=True, key="tb_hide")

wg = GWS[:H]
summ = brain.summary(long, wg)
if pos != "All":
    summ = summ[summ["position"] == pos]
summ = summ[summ["price"] <= maxp]
if max_own < 100:
    summ = summ[summ["ownership"].fillna(0) <= max_own]
owned = {p["code"] for p in T_["squad"]}
if hide_owned:
    summ = summ[~summ["code"].isin(owned)]
summ = summ.head(40)
per = long[long["gw"].isin(wg)].pivot_table(index="code", columns="gw", values="xp", aggfunc="sum")


def _gw_cells(code: int) -> str:
    cells = []
    for g in wg:
        v = float(per.at[code, g]) if (code in per.index and g in per.columns and pd.notna(per.at[code, g])) else 0.0
        a = min(1.0, v / 7.0)
        cells.append(
            f'<span class="ff-num" style="display:inline-block;width:30px;text-align:center;'
            f'padding:2px 0;margin-right:2px;border-radius:4px;font-size:11.5px;'
            f'background:rgba(0,227,122,{0.08 + 0.5 * a:.2f});color:{V("text")};">{v:.1f}</span>')
    return "".join(cells)


rows = []
for _, r in summ.iterrows():
    c = int(r["code"])
    rows.append({"code": c, "web_name": r["web_name"],
                 "sub": "%s · %s" % (r["team_short"], r["position"]),
                 "price": r["price"], "xp_next": r["xp_next"], "xp_total": r["xp_total"],
                 "xmins": r["xmins"], "gws": _gw_cells(c), "own": r.get("ownership"),
                 "run": [{"opp": f.split("(")[0], "home": "(H)" in f, "fdr": 3}
                         for f in service.fixtures_for(int(r["team_id"]), wg[:4])]
                 if pd.notna(r.get("team_id")) else []})
maxx = max([x["xp_total"] for x in rows] + [1.0])
T.render(rows, [
    T.col_face("code", url_fn=player_photo_url),
    T.col_player("web_name", sub="sub"),
    T.col_num("price", "£m", fmt="%.1f"),
    T.col_num("xp_next", "GW%d" % first, fmt="%.2f"),
    T.col_bar("xp_total", "GW%d-%d" % (wg[0], wg[-1]), max_value=maxx, fmt="%.1f"),
    T.col_html("gws", "Per gameweek"),
    T.col_num("xmins", "xMins", fmt="%.0f"),
    T.col_num("own", "Owned %", fmt="%.1f"),
], key="target_board", max_height=520)

st.caption("xP = expected FPL points from the component model (minutes, goals, assists, "
           "clean sheet, bonus, DEFCON), scaled by FPL's current injury news. xMins = "
           "expected minutes per match over the window.")
