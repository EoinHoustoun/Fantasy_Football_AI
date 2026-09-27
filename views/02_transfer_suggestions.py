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

# ── 0 · Your fifteen over the horizon · exit weeks ─────────────────────────────
from ui import transfer_viz as TV
from ui.charts import render as _render

_em = service.squad_exit_map(team_id, horizon=8)
_section("Your fifteen, week by week",
         "Expected points per gameweek. A red outline is an exit week: someone you can "
         "afford in that position outscores him by a point or more.", "grid_view")
charts_h = 44 + 34 * len(_em["rows"])
_render(TV.squad_heat_option(_em["rows"], _em["gws"]), height="%dpx" % charts_h, key="squad_heat")
_exits = [r for r in _em["rows"] if r["exit_gw"] and r["position"] != "GKP" or
          (r["exit_gw"] and r["position"] == "GKP" and r["weeks_beaten"] < len(_em["gws"]))]
if _exits:
    st.markdown(_one(
        f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin:-4px 0 6px;">'
        + "".join(f'<span style="padding:5px 11px;border-radius:999px;border:1px solid {V("red")};'
                  f'font-size:12.5px;color:{V("text")};">{r["name"]} · exit GW{r["exit_gw"]}'
                  f'<span style="color:{V("muted2")};"> · beaten {r["weeks_beaten"]} of {len(_em["gws"])}</span></span>'
                  for r in sorted(_exits, key=lambda r: (r["exit_gw"], -r["weeks_beaten"])))
        + '</div>'), unsafe_allow_html=True)

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
    # The card carries the AUDITED verdict (timing, robustness, both players'
    # background checks), not just the raw gain.
    try:
        d = service.move_dossier(int(m["out_code"]), int(m["in_code"]), team_id)
        verdict, tone = d["verdict"], d["tone"]
        n_warn = sum(1 for f in d["flags"] if f["level"] in ("warn", "bad"))
    except Exception:  # noqa: BLE001 · a card without its audit still shows the gain
        verdict, tone, n_warn = ("Worth a transfer" if m["gain"] >= 2 else "Marginal"), "gold", 0
    warn_html = (f'<div style="font-size:11.5px;color:{V("gold")};margin-top:8px;">'
                 f'{theme.icon("warning", 14, V("gold"))} {n_warn} thing{"s" if n_warn != 1 else ""} '
                 f'to check</div>') if n_warn else (
                 f'<div style="font-size:11.5px;color:{V("mint")};margin-top:8px;">'
                 f'{theme.icon("check_circle", 14, V("mint"))} background check clean</div>')
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
        f'white-space:nowrap;">{m["in"]}</div></div></div>{warn_html}</div>')


if bm["moves"]:
    cols = st.columns(3)
    for i, m in enumerate(bm["moves"][:6]):
        with cols[i % 3]:
            st.markdown(_move_card(m, i + 1), unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Check it", key="bmc_%d" % i, icon=":material/fact_check:",
                             use_container_width=True, type="primary"):
                    st.session_state["dossier"] = (int(m["out_code"]), int(m["in_code"]))
            with b2:
                if st.button("To planner", key="bm_%d" % i, icon=":material/playlist_add:",
                             use_container_width=True):
                    r = service.save_plan_to_app([{"gw": first, "out": [m["out_code"]], "in": [m["in_code"]]}],
                                                 team_id)
                    st.toast("Drafted in My Team for GW%d" % first if r.get("ok") else r.get("error"))
else:
    st.info("No affordable move improves the team over this window.")

# ── 1b · Check any move · the dossier ─────────────────────────────────────────
_section("Check a move", "Background check before you spend a transfer: timing, robustness "
         "across horizons, and why you might want to keep him.", "fact_check")

_squad = sorted(T_["squad"], key=lambda p: ({"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}[p["position"]], p["name"]))
_sel = st.session_state.get("dossier")
if not _sel and bm.get("moves"):
    _sel = (int(bm["moves"][0]["out_code"]), int(bm["moves"][0]["in_code"]))
_out_default = next((i for i, p in enumerate(_squad) if _sel and p["code"] == _sel[0]), 0)
c_o, c_i = st.columns(2)
with c_o:
    _out = st.selectbox("Sell", _squad, index=_out_default, key="dos_out",
                        format_func=lambda p: "%s · %s · £%.1fm" % (p["name"], p["team"], p["sell_price"]))
_summ6 = brain.summary(long, GWS[:6])
_cands = _summ6[(_summ6["position"] == _out["position"])
                & (~_summ6["code"].isin([p["code"] for p in T_["squad"]]))
                & (_summ6["price"] <= T_["bank"] + _out["sell_price"] + 1e-9)].head(40)
_opts = [int(c) for c in _cands["code"]]
_lab = dict(zip(_cands["code"].astype(int), _cands.apply(
    lambda r: "%s · %s · £%.1fm · %.1f xP" % (r["web_name"], r["team_short"], r["price"], r["xp_total"]), axis=1)))
_in_default = _opts.index(_sel[1]) if (_sel and _sel[1] in _opts and _sel[0] == _out["code"]) else 0
with c_i:
    _in = st.selectbox("Buy (affordable, same position, by six-week xP)", _opts, index=_in_default,
                       key="dos_in_%d" % _out["code"], format_func=lambda c: _lab.get(c, str(c)))

if _in is not None:
    D = service.move_dossier(int(_out["code"]), int(_in), team_id)
    po, pi = D["out"], D["in"]
    tone = D["tone"]
    tg = D["team_gain_6"]
    fo = face_html(po["code"], team_by_code.get(po["code"], 1), po["position"] == "GKP", 64)
    fi = face_html(pi["code"], team_by_code.get(pi["code"], 1), pi["position"] == "GKP", 64)
    st.markdown(_one(f"""
<div class="ff-rise" style="display:grid;grid-template-columns:auto 1fr auto;gap:22px;align-items:center;
  padding:18px 22px;border-radius:18px;background:{V('card')};border:1px solid {V('line')};
  border-left:4px solid {V(tone)};margin:6px 0 12px;">
  <div style="display:flex;align-items:center;gap:14px;">
    <div style="text-align:center;opacity:0.8;"><div style="width:64px;">{fo}</div>
      <div style="font-size:12.5px;color:{V('muted')};margin-top:4px;">{po['name']}</div></div>
    {theme.icon("arrow_forward", 30, V(tone))}
    <div class="ff-swap-in" style="text-align:center;"><div style="width:64px;">{fi}</div>
      <div style="font-size:12.5px;font-weight:700;color:{V('text')};margin-top:4px;">{pi['name']}</div></div>
  </div>
  <div>
    <div class="ff-display" style="font-size:30px;font-weight:900;color:{V(tone)};">{D['verdict']}</div>
    <div style="font-size:14px;color:{V('muted')};margin-top:2px;">{D['why']}.</div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:{V('muted2')};">Team xP, 6 weeks</div>
    <div class="ff-display ff-num" style="font-size:34px;font-weight:900;color:{V(tone)};">{'' if tg is None else ('%+.1f' % tg)}</div>
  </div>
</div>"""), unsafe_allow_html=True)

    g1, g2 = st.columns([1.6, 1])
    with g1:
        st.markdown(_label("Week by week · entry point pinned"), unsafe_allow_html=True)
        _render(TV.xp_duel_option(D["gws"], D["out_xp"], D["in_xp"], po["name"], pi["name"],
                                  po["code"], pi["code"], D["out_fixtures"], D["in_fixtures"],
                                  D["timing"].get("best_week")), height="300px",
                key="duel_%d_%d" % (po["code"], pi["code"]))
    with g2:
        st.markdown(_label("When to make it · team points if made that week"), unsafe_allow_html=True)
        _render(TV.timing_option(D["timing"]), height="150px", key="tim_%d_%d" % (po["code"], pi["code"]))
        st.markdown(_label("Does it win on every horizon? · team points"), unsafe_allow_html=True)
        _render(TV.horizon_option(D["horizons"]), height="130px", key="hz_%d_%d" % (po["code"], pi["code"]))

    ICON = {"good": ("check_circle", "mint"), "warn": ("warning", "gold"),
            "bad": ("block", "red"), "info": ("info", "cyan")}
    f1, f2 = st.columns([1.15, 1])
    with f1:
        st.markdown(_label("Background check"), unsafe_allow_html=True)
        flags = D["flags"] or [{"level": "good", "side": "move", "text": "Nothing found against it."}]
        st.markdown(_one("".join(
            f'<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;margin:6px 0;'
            f'border-radius:12px;background:{V("row-alt")};">'
            f'{theme.icon(ICON[f["level"]][0], 20, V(ICON[f["level"]][1]))}'
            f'<div style="font-size:13.5px;line-height:1.5;color:{V("text")};">'
            f'<span style="font-size:10.5px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;'
            f'color:{V("muted2")};margin-right:6px;">{ {"out": "keep?", "in": "buy?", "move": "move"}[f["side"]] }</span>'
            f'{f["text"]}</div></div>' for f in flags)), unsafe_allow_html=True)
    with f2:
        st.markdown(_label("This season, side by side"), unsafe_allow_html=True)

        def _row(label, a, b, better="high", fmt="%s"):
            try:
                fa, fb = float(a), float(b)
                wa = (fa > fb) if better == "high" else (fa < fb)
                wb = (fb > fa) if better == "high" else (fb < fa)
            except (TypeError, ValueError):
                wa = wb = False
            show = lambda v: "·" if v is None else (fmt % v)
            return (f'<tr><td style="padding:6px 8px;color:{V("muted")};font-size:12.5px;">{label}</td>'
                    f'<td class="ff-num" style="padding:6px 8px;text-align:right;color:{V("mint") if wa else V("text")};'
                    f'font-weight:{700 if wa else 500};">{show(a)}</td>'
                    f'<td class="ff-num" style="padding:6px 8px;text-align:right;color:{V("mint") if wb else V("text")};'
                    f'font-weight:{700 if wb else 500};">{show(b)}</td></tr>')

        mins = lambda p: " ".join(str(m) for m in p["mins_list"]) or "·"
        tbl = (f'<table style="width:100%;border-collapse:collapse;background:{V("card")};border-radius:12px;">'
               f'<tr><th></th><th style="text-align:right;padding:6px 8px;font-size:12px;color:{V("red")};">{po["name"]}</th>'
               f'<th style="text-align:right;padding:6px 8px;font-size:12px;color:{V("mint")};">{pi["name"]}</th></tr>'
               + _row("Minutes by GW", mins(po), mins(pi))
               + _row("Starts", po["starts"], pi["starts"], fmt="%d")
               + _row("xGI per 90", po["xgi90"], pi["xgi90"], fmt="%.2f")
               + _row("G+A per 90", po["ga90"], pi["ga90"], fmt="%.2f")
               + _row("Luck (G+A minus xGI)", po["luck"], pi["luck"], better="low", fmt="%+.1f")
               + _row("Points per start", po["pts_per_start"], pi["pts_per_start"], fmt="%.1f")
               + _row("DEFCON hit rate", None if po["defcon_rate"] is None else round(100 * po["defcon_rate"]),
                      None if pi["defcon_rate"] is None else round(100 * pi["defcon_rate"]), fmt="%d%%")
               + _row("Penalty order", po["penalties"], pi["penalties"], better="low", fmt="%d")
               + _row("Price £m", po["price"], pi["price"], better="low", fmt="%.1f")
               + _row("Difficulty GW%d-%d" % tuple(D["ease_after"]["gws"]), D["ease_after"]["out"],
                      D["ease_after"]["in"], better="low", fmt="%.2f")
               + '</table>')
        st.markdown(_one(tbl), unsafe_allow_html=True)
        st.caption("Luck is noise (r = -0.01 with later luck); xGI per 90 is the signal (r = 0.53).")

    if st.button("Draft this move in My Team", key="dos_draft", icon=":material/playlist_add:",
                 type="primary"):
        wk = D["timing"].get("best_week") or first
        r = service.save_plan_to_app([{"gw": int(wk), "out": [po["code"]], "in": [pi["code"]]}], team_id)
        st.toast("Drafted for GW%d in My Team" % wk if r.get("ok") else str(r.get("error")))

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
            team_id, horizon, None, {"friction": friction, "decay": decay}, alternatives=0)
        st.session_state[_pkey]["_args"] = (horizon, friction, decay)
res = st.session_state.get(_pkey)


def _mini_face(code: int, size: int = 26) -> str:
    return (f'<span style="display:inline-block;width:{size}px;flex-shrink:0;">'
            f'{face_html(int(code), team_by_code.get(int(code), 1), pos_by_code.get(int(code)) == "GKP", size)}'
            f'</span>')


def _week_card(w: Dict, raw: Dict) -> str:
    moves = "".join(
        f'<div style="display:flex;gap:5px;align-items:center;font-size:12px;margin:5px 0;">'
        f'{_mini_face(oc, 22)}<span style="color:{V("red")};overflow:hidden;text-overflow:ellipsis;'
        f'white-space:nowrap;max-width:60px;">{o}</span>{theme.icon("arrow_forward", 13, V("muted"))}'
        f'{_mini_face(ic, 22)}<span style="color:{V("mint")};font-weight:700;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;max-width:64px;">{i}</span></div>'
        for o, i, oc, ic in zip(w["out_names"], w["in_names"], raw["out"], raw["in"]))
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
    raw_wk = res["_raw"]["best"]["weeks"]
    cols = st.columns(len(wk))
    for c, w, rw in zip(cols, wk, raw_wk):
        with c:
            st.markdown(_week_card(w, rw), unsafe_allow_html=True)

    # Holding windows: every player the plan buys, when he arrives and when (if
    # ever) the plan sells him again, with the move's background-check verdict.
    plan_gws = [w["gw"] for w in raw_wk]
    stints = []
    for k, rw in enumerate(raw_wk):
        for oc, ic in zip(rw["out"], rw["in"]):
            leave = next((raw_wk[j]["gw"] for j in range(k + 1, len(raw_wk)) if ic in raw_wk[j]["out"]), None)
            stints.append({"in": ic, "out": oc, "from": rw["gw"], "to": leave})
    if stints:
        _section("Who the plan brings in, and for how long",
                 "Each bar is a stay in your squad. A bar that stops is a planned exit; one "
                 "that runs off the end is kept.", "timeline")
        name_of = dict(zip(long["code"], long["web_name"]))
        n = len(plan_gws)
        head = "".join(f'<div style="text-align:center;font-size:11px;color:{V("muted2")};">GW{g}</div>'
                       for g in plan_gws)
        rows_html = []
        for st_ in stints:
            try:
                d = service.move_dossier(int(st_["out"]), int(st_["in"]), team_id)
                vt, tn = d["verdict"], d["tone"]
            except Exception:  # noqa: BLE001
                vt, tn = "", "muted"
            a = plan_gws.index(st_["from"])
            b = plan_gws.index(st_["to"]) if st_["to"] in plan_gws else n
            span = (f'<div class="ff-grow" style="grid-column:{a + 1} / {b + 1};height:26px;border-radius:8px;'
                    f'background:linear-gradient(90deg,{V("mint")},rgba(0,255,135,0.35));display:flex;'
                    f'align-items:center;padding:0 10px;font-size:11.5px;font-weight:700;color:{V("bg")};">'
                    f'{"GW%d → GW%d" % (st_["from"], st_["to"] - 1) if st_["to"] else "from GW%d, kept" % st_["from"]}</div>')
            rows_html.append(
                f'<div style="display:grid;grid-template-columns:230px 1fr 150px;gap:12px;align-items:center;'
                f'padding:8px 0;border-bottom:1px solid {V("line")};">'
                f'<div style="display:flex;align-items:center;gap:8px;">{_mini_face(st_["in"], 34)}'
                f'<div><div style="font-weight:700;color:{V("text")};font-size:13.5px;">{name_of.get(st_["in"], "")}</div>'
                f'<div style="font-size:12px;color:{V("muted")};">for {name_of.get(st_["out"], "")}</div></div></div>'
                f'<div style="display:grid;grid-template-columns:repeat({n},minmax(0,1fr));gap:4px;">{span}</div>'
                f'<div style="font-size:12.5px;font-weight:700;color:{V(tn)};text-align:right;">{vt}</div></div>')
        st.markdown(_one(
            f'<div style="background:{V("card")};border:1px solid {V("line")};border-radius:14px;padding:10px 16px;">'
            f'<div style="display:grid;grid-template-columns:230px 1fr 150px;gap:12px;">'
            f'<div></div><div style="display:grid;grid-template-columns:repeat({n},minmax(0,1fr));gap:4px;">{head}</div>'
            f'<div style="text-align:right;font-size:11px;color:{V("muted2")};">background check</div></div>'
            + "".join(rows_html) + '</div>'), unsafe_allow_html=True)
    b1, b2 = st.columns([1, 3])
    with b1:
        if st.button("Send this plan to My Team", key="tp_send", use_container_width=True):
            r = service.save_plan_to_app(
                [{"gw": w["gw"], "out": w["out_names"], "in": w["in_names"],
                  "captain": w["captain_name"]} for w in wk], team_id)
            st.toast("Drafted %d weeks in My Team" % len(r.get("saved_drafts", []))
                     if r.get("ok") else r.get("error"))
    if not res.get("alternatives") and st.button("Show other ways to play GW%d" % first,
                                                  key="tp_alts", icon=":material/alt_route:"):
        h_, f_, d_ = res.get("_args", (6, 2.0, 0.9))
        with fpl_loader("Finding the next-best plans", LINES_SOLVER):
            alt = service.optimise(team_id, h_, None, {"friction": f_, "decay": d_}, alternatives=2)
        res["alternatives"] = alt["alternatives"]
        st.session_state[_pkey] = res
    if res.get("alternatives"):
        with st.expander("Other ways to play GW%d" % first, expanded=True):
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
