"""
Home · Matchday (Floodlit redesign, 2026-09-27).

The front door answers one question: what do I do before this deadline?

  hero        gameweek, live countdown, free transfers / bank / chips, the
              season's points per gameweek against the global average
  decisions   captain, best move, risks · every number from the shared engine
              (analytics/service), the same one My Team, Captain, Transfers
              and Claude's MCP server read
  market      where the crowd is moving, set against what the engine thinks
  briefing    the instant written read, with an optional local-AI rewrite

Motion: the hero's floodlight sweep (faster inside the last day), cards rise in
reading order, bars grow, hero numbers count in, the captain glows. All of it
switches off under prefers-reduced-motion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from analytics import brain, service
from components.animations import count_up, inject_global_animations
from components.loading import fpl_loader
from components.team_identity import face_html
from ui import theme
from ui.theme import var as V

inject_global_animations()


def _one(html: str) -> str:
    return "".join(seg.strip() for seg in html.splitlines())


def _label(txt: str, tone: str = "muted") -> str:
    return (f'<div style="font-size:11px;font-weight:700;letter-spacing:0.18em;'
            f'text-transform:uppercase;color:{V(tone)};">{txt}</div>')


# ── Shared state ──────────────────────────────────────────────────────────────
players_df = st.session_state.get("players_df")
bs = st.session_state.get("bootstrap") or {}
if players_df is None:
    st.info("Loading data… if this persists, use Refresh data in the rail.")
    st.stop()

team_id = int(st.session_state.get("squad_team_id") or service.default_team_id() or 0)
nxt = next((e for e in bs.get("events", []) if e.get("is_next")), None)
gw = int(nxt["id"]) if nxt else None

try:
    T = service.team(team_id)
except Exception:  # noqa: BLE001
    T = None
long = service.projections(allow_compute=False)
if long is None:
    brain.warm_async(bs, players_df, st.session_state.get("fixtures_df"))


# ── Hero ──────────────────────────────────────────────────────────────────────
def _countdown() -> Tuple[str, bool, str]:
    if not nxt:
        return "", False, ""
    dl = datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
    left = dl - datetime.now(timezone.utc)
    d, h, m = left.days, left.seconds // 3600, (left.seconds % 3600) // 60
    txt = ("%dd %dh %02dm" % (d, h, m)) if d >= 1 else ("%dh %02dm" % (h, m))
    local = dl.astimezone().strftime("%a %d %b, %H:%M")
    return txt, d < 1, local


def _season_bars() -> str:
    if not T or not T.get("gw_points"):
        return ""
    avg = {int(e["id"]): e.get("average_entry_score") for e in bs.get("events", [])}
    rows = T["gw_points"]
    top = max([r["points"] for r in rows] + [v or 0 for v in avg.values()] + [1])
    cols = []
    for r in rows:
        a = avg.get(int(r["gw"])) or 0
        beat = r["points"] >= a
        tone = V("mint") if beat else V("red")
        h = max(6, round(120 * r["points"] / top))
        ah = round(120 * a / top)
        cols.append(
            f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;">'
            f'<div class="ff-num" style="font-size:13px;font-weight:700;color:{tone};">{r["points"]}</div>'
            f'<div style="position:relative;width:100%;height:120px;display:flex;align-items:flex-end;">'
            f'<div class="ff-growy" style="width:100%;height:{h}px;border-radius:6px 6px 0 0;'
            f'background:{tone};opacity:{1 if beat else 0.85};"></div>'
            f'<div title="Average {a}" style="position:absolute;left:-3px;right:-3px;bottom:{ah}px;'
            f'height:2px;background:{V("text")};opacity:0.55;"></div></div>'
            f'<div style="font-size:12px;color:{V("muted2")};">GW{r["gw"]}</div></div>')
    return (f'<div style="display:flex;flex-direction:column;gap:10px;">'
            f'{_label("Points per gameweek · line = global average")}'
            f'<div style="display:flex;gap:10px;align-items:flex-end;">{"".join(cols)}</div></div>')


cd_txt, cd_hot, cd_local = _countdown()
chips_left = [{"freehit": "Free Hit", "wildcard": "Wildcard", "bboost": "Bench Boost",
               "3xc": "Triple Captain"}[c] for c in (T["chips"]["remaining"] if T else [])]
pills = []
if T:
    pills = [("%d free transfer%s" % (T["free_transfers"], "" if T["free_transfers"] == 1 else "s"), "mint"),
             ("£%.1fm in the bank" % T["bank"], "gold"),
             (("%s left · to GW%d" % (" · ".join(chips_left), T["chips"]["gw_hi"])) if chips_left
              else "No chips left this half", "cyan")]
pill_html = "".join(
    f'<span style="padding:7px 13px;border-radius:999px;font-size:13px;color:{V("text")};'
    f'border:1px solid {V(t)};background:{V("chip-bg")};">{txt}</span>' for txt, t in pills)
rank = ("rank %s" % f'{T["overall_rank"]:,}') if T and T.get("overall_rank") else ""
kicker = " · ".join(x for x in ((T or {}).get("team_name"), rank) if x)

st.markdown(_one(f"""
<div class="ff-rise ff-stack" style="position:relative;overflow:hidden;display:grid;
  grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:32px;padding:30px 34px;
  border-radius:22px;border:1px solid {V("line")};
  background:linear-gradient(135deg, rgba(0,255,135,0.07) 0%, {V("card")} 55%);">
  <div class="ff-sweep{' ff-hot' if cd_hot else ''}"></div>
  <div style="position:relative;display:flex;flex-direction:column;gap:12px;">
    {_label(kicker or "FPL Hub", "mint")}
    <div class="ff-display ff-hero-title" style="font-size:64px;font-weight:900;letter-spacing:-2.2px;
      line-height:0.95;color:{V("text")};white-space:nowrap;">Gameweek {gw or ""}</div>
    <div style="display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;">
      <div class="ff-display ff-num" style="font-size:36px;font-weight:800;white-space:nowrap;
        color:{V("red") if cd_hot else V("gold")};">{cd_txt}</div>
      <div style="font-size:15px;color:{V("muted")};">to the deadline · {cd_local}</div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:4px;">{pill_html}</div>
  </div>
  <div style="position:relative;display:flex;align-items:center;">{_season_bars()}</div>
</div>"""), unsafe_allow_html=True)


# ── Decisions ─────────────────────────────────────────────────────────────────
def _section(title: str, lead: str = "") -> None:
    st.markdown(_one(
        f'<div style="display:flex;align-items:center;gap:14px;margin:28px 0 14px;">'
        f'<div class="ff-display" style="font-size:22px;font-weight:800;color:{V("text")};">{title}</div>'
        f'<div style="flex:1;height:1px;background:{V("line")};"></div>'
        f'<div style="font-size:13px;color:{V("muted2")};">{lead}</div></div>'),
        unsafe_allow_html=True)


_section("Your three decisions", "One engine behind every number · walk-forward tested")

if long is None or T is None:
    st.markdown(_one(
        f'<div class="ff-rise" style="padding:26px;border-radius:18px;border:1px solid {V("line")};'
        f'background:{V("card")};color:{V("muted")};font-size:15px;">Projections are rebuilding '
        f'after the last gameweek (a few minutes). This page fills itself in when they land.</div>'),
        unsafe_allow_html=True)
    st.stop()

codes = [p["code"] for p in T["squad"]]
by_code = {p["code"]: p for p in T["squad"]}
g0 = int(long["gw"].min())
wk = long[(long["gw"] == g0) & long["code"].isin(codes)].sort_values("xp", ascending=False)
top3 = wk.head(3)
card = (f'background:{V("card")};border:1px solid {V("line")};border-radius:18px;'
        f'padding:22px;display:flex;flex-direction:column;gap:14px;height:100%;box-sizing:border-box;')


def _captain_card() -> str:
    if top3.empty:
        return ""
    c = top3.iloc[0]
    fx = service.fixtures_for(int(c["team_id"]), [g0])[0]
    face = face_html(int(c["code"]), int(c["team_code"] or 1), c["position"] == "GKP", width=64)
    mx = float(top3["xp"].max()) or 1.0
    bars = "".join(
        f'<div style="display:flex;gap:10px;align-items:center;font-size:13px;">'
        f'<div style="width:96px;color:{V("muted")};white-space:nowrap;overflow:hidden;'
        f'text-overflow:ellipsis;">{r["web_name"]}</div>'
        f'<div style="flex:1;height:8px;border-radius:4px;background:{V("s2")};">'
        f'<div class="ff-grow" style="width:{100 * float(r["xp"]) / mx:.0f}%;height:8px;border-radius:4px;'
        f'background:{V("gold") if i == 0 else V("muted2")};"></div></div>'
        f'<div class="ff-num" style="width:36px;text-align:right;color:{V("text")};">{float(r["xp"]):.2f}</div></div>'
        for i, (_, r) in enumerate(top3.iterrows()))
    gap = float(top3.iloc[0]["xp"] - top3.iloc[1]["xp"]) if len(top3) > 1 else 0.0
    note = ("%.2f clear of the next best · %.2f expected goals · %d%% chance of 60+ minutes"
            % (gap, float(c["e_goals"]), round(100 * float(c["p60"]))))
    if gap < 0.3:
        note = "A coin flip with %s · " % top3.iloc[1]["web_name"] + note
    return _one(f"""
<div class="ff-rise-2" style="{card}border-top:3px solid {V('gold')};">
  {_label("Captain", "gold")}
  <div style="display:flex;gap:16px;align-items:center;">
    <div class="fplh-captain-pulse" style="border-radius:14px;flex-shrink:0;width:64px;">{face}</div>
    <div style="min-width:0;flex:1;">
      <div class="ff-display" style="font-size:26px;font-weight:900;color:{V('text')};
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{c['web_name']}</div>
      <div style="display:flex;align-items:baseline;gap:8px;margin-top:2px;">
        <span class="ff-display ff-num" style="font-size:30px;font-weight:900;color:{V('gold')};">{float(c['xp']):.2f}</span>
        <span style="font-size:13px;color:{V('muted')};">xP GW{g0} · {fx}</span></div>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;gap:7px;">{bars}</div>
  <div style="font-size:13px;color:{V('muted')};line-height:1.5;">{note}</div>
</div>""")


bm = service.best_moves(team_id, horizon=6, top_n=3)
mv = bm["moves"][0] if bm.get("moves") else None
pos_code = dict(zip(long["code"], long["position"]))
team_code = dict(zip(long["code"], long["team_code"]))


def _move_card() -> str:
    if mv is None:
        return _one(f'<div class="ff-rise-3" style="{card}border-top:3px solid {V("mint")};">'
                    f'{_label("Best move", "mint")}<div class="ff-display" style="font-size:28px;'
                    f'font-weight:900;">Hold</div><div style="color:{V("muted")};">No affordable move '
                    f'improves your team over the next six weeks.</div></div>')
    f_out = face_html(mv["out_code"], team_code.get(mv["out_code"], 1), pos_code.get(mv["out_code"]) == "GKP", 56)
    f_in = face_html(mv["in_code"], mv.get("in_team_code") or team_code.get(mv["in_code"], 1),
                     pos_code.get(mv["in_code"]) == "GKP", 56)
    good = mv["gain"] >= 2.0
    tone = "mint" if good else "gold"
    cost = mv["cost_change"]
    cost_txt = ("+£%.1fm" % cost) if cost > 0 else ("£%.1fm back" % -cost if cost < 0 else "level money")
    verdict = ("worth a transfer · it clears the 2-point bar a move needs" if good
               else "marginal · under the 2-point bar a move needs")
    return _one(f"""
<div class="ff-rise-3" style="{card}border-top:3px solid {V(tone)};">
  <div style="display:flex;justify-content:space-between;">{_label("Best move", tone)}
    <div style="font-size:12px;color:{V('muted2')};">team xP GW{bm['gws'][0]}-{bm['gws'][-1]}</div></div>
  <div style="display:flex;gap:12px;align-items:center;">
    <div style="display:flex;flex-direction:column;align-items:center;gap:6px;opacity:0.7;flex-shrink:0;">
      {f_out}<div style="font-size:13px;color:{V('muted')};">{mv['out']}</div></div>
    <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;">
      {theme.icon("arrow_forward", 30, V(tone))}
      <div style="font-size:12px;color:{V('muted2')};">{cost_txt}</div></div>
    <div class="ff-swap-in" style="display:flex;flex-direction:column;align-items:center;gap:6px;flex-shrink:0;">
      {f_in}<div style="font-size:13px;font-weight:700;color:{V('text')};">{mv['in']}</div></div>
  </div>
  <div style="display:flex;align-items:baseline;gap:10px;">
    <div class="ff-display ff-num" style="font-size:40px;font-weight:900;color:{V(tone)};
      white-space:nowrap;flex-shrink:0;"><span>+</span><span>{count_up(max(mv['gain'], 0), 1)}</span></div>
    <div style="font-size:13px;color:{V('muted')};line-height:1.4;">points, {verdict}</div></div>
</div>""")


def _risk_card() -> str:
    flagged = [p for p in T["squad"] if (p.get("status") or "a") != "a"]
    flagged.sort(key=lambda p: (p["on_bench"], p.get("chance") if p.get("chance") is not None else 0))
    rows = []
    for p in flagged[:3]:
        ch = p.get("chance")
        ch_txt = ("%d%%" % ch) if ch is not None and not pd.isna(ch) else "?"
        face = face_html(p["code"], team_code.get(p["code"], 1), p["position"] == "GKP", 44)
        rows.append(
            f'<div style="display:flex;gap:12px;align-items:center;padding:10px 12px;border-radius:12px;'
            f'background:{V("row-alt")};"><div style="flex-shrink:0;width:44px;">{face}</div>'
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-weight:700;color:{V("text")};white-space:nowrap;overflow:hidden;'
            f'text-overflow:ellipsis;">{p["name"]}</div>'
            f'<div style="font-size:12.5px;color:{V("muted")};white-space:nowrap;overflow:hidden;'
            f'text-overflow:ellipsis;">{"Bench · " if p["on_bench"] else ""}{p.get("news") or "flagged"}</div></div>'
            f'<div class="ff-display ff-num" style="font-size:20px;font-weight:900;color:{V("orange")};">{ch_txt}</div></div>')
    body = ("".join(rows) if rows else
            f'<div style="font-size:15px;color:{V("muted")};">Everyone is available.</div>')
    return _one(f"""
<div class="ff-rise-4" style="{card}border-top:3px solid {V('red') if rows else V('mint')};">
  {_label("Risks in your fifteen", "red" if rows else "mint")}
  {body}
  <div style="font-size:13px;color:{V('muted2')};">Already priced into every xP on this page.</div>
</div>""")


c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(_captain_card(), unsafe_allow_html=True)
    st.page_link("views/06_captain_picker.py", label="Captain detail →")
with c2:
    st.markdown(_move_card(), unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if mv is not None and st.button("Put it in my planner", key="home_draft", type="primary",
                                        use_container_width=True):
            r = service.save_plan_to_app([{"gw": g0, "out": [mv["out"]], "in": [mv["in"]]}], team_id)
            st.toast("Drafted in My Team for GW%d" % g0 if r.get("ok") else str(r.get("error")))
    with b2:
        st.page_link("views/02_transfer_suggestions.py", label="Solve six weeks →")
with c3:
    st.markdown(_risk_card(), unsafe_allow_html=True)
    st.page_link("views/08_injuries.py", label="Injury news →")


# ── The market vs the engine ──────────────────────────────────────────────────
_section("The market this week", "Where the crowd is moving, against what the engine expects")
summ = brain.summary(long, sorted(long["gw"].unique())[:6]).set_index("code")
pdf = players_df.set_index("code") if "code" in players_df.columns else None


def _market_tile(kicker: str, tone: str, code: Optional[int], big: str, sub: str) -> str:
    face = ""
    if code is not None and code in summ.index:
        face = face_html(int(code), int(summ.at[code, "team_code"] or 1),
                         summ.at[code, "position"] == "GKP", 40)
    return _one(
        f'<div style="background:{V("card")};border:1px solid {V("line")};border-radius:14px;'
        f'padding:14px 16px;display:flex;gap:12px;align-items:center;">'
        f'<div style="flex-shrink:0;width:40px;">{face}</div>'
        f'<div style="min-width:0;">{_label(kicker, tone)}'
        f'<div class="ff-display" style="font-size:19px;font-weight:800;color:{V("text")};margin-top:4px;">{big}</div>'
        f'<div style="font-size:12.5px;color:{V("muted")};">{sub}</div></div></div>')


tiles: List[str] = []
if pdf is not None:
    tin = players_df.nlargest(1, "transfers_in_event").iloc[0]
    tout = players_df.nlargest(1, "transfers_out_event").iloc[0]

    def _rank(code) -> str:
        if code not in summ.index:
            return "not projected"
        pos = summ.at[code, "position"]
        r = int((summ[summ["position"] == pos]["xp_total"] > summ.at[code, "xp_total"]).sum()) + 1
        return "engine: #%d %s over six weeks" % (r, pos)

    tiles.append(_market_tile("Most bought", "cyan", int(tin["code"]), tin["web_name"],
                              "+%s this week · %s" % (f'{int(tin["transfers_in_event"]):,}', _rank(int(tin["code"])))))
    tiles.append(_market_tile("Most sold", "red", int(tout["code"]), tout["web_name"],
                              "-%s this week · %s" % (f'{int(tout["transfers_out_event"]):,}', _rank(int(tout["code"])))))
owned = set(codes)
best_not = summ[~summ.index.isin(owned)].sort_values("xp_total", ascending=False)
if not best_not.empty:
    b = best_not.iloc[0]
    tiles.append(_market_tile("Engine's top pick you don't own", "mint", int(b.name), b["web_name"],
                              "%.1f xP over six weeks · £%.1fm" % (b["xp_total"], b["price"])))
dif = best_not[best_not["ownership"].fillna(100) < 5]
if not dif.empty:
    d = dif.iloc[0]
    tiles.append(_market_tile("Best differential under 5%", "mag", int(d.name), d["web_name"],
                              "%.1f xP over six weeks · %.1f%% owned" % (d["xp_total"], d["ownership"])))
cols = st.columns(max(1, len(tiles)))
for c, t in zip(cols, tiles):
    with c:
        st.markdown(t, unsafe_allow_html=True)


# ── Briefing · instant template, optional local-AI rewrite ────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _ai_rewrite(facts_key: Tuple[Tuple[str, object], ...]) -> Optional[str]:
    from ai.briefing import ai_briefing
    return ai_briefing(dict(facts_key))


cap_row = top3.iloc[0] if not top3.empty else None
flag = next((p for p in T["squad"] if (p.get("status") or "a") != "a" and not p["on_bench"]), None)
ctx: Dict[str, object] = {
    "gw": gw, "deadline_text": cd_txt,
    "captain": cap_row["web_name"] if cap_row is not None else None,
    "captain_xp": "%.2f" % float(cap_row["xp"]) if cap_row is not None else None,
    "transfer_in": ("%s for %s" % (mv["in"], mv["out"])) if mv else None,
    "transfer_xp": ("+%.1f over six weeks" % mv["gain"]) if mv else None,
    "chip": ("%s still to play before GW%d" % (" and ".join(chips_left), T["chips"]["gw_hi"])
             if chips_left else "No chips left this half"),
    "risks": ("%s (%s)" % (flag["name"], flag.get("news") or "flagged")) if flag else None,
}
key = tuple(sorted(ctx.items(), key=lambda kv: kv[0]))
try:
    from ai.briefing import template_briefing, used_ai
    tmpl, ai_ok = template_briefing(ctx), used_ai()
except Exception:  # noqa: BLE001
    tmpl, ai_ok = None, False

if tmpl:
    _section("The briefing")
    done = st.session_state.get("_briefing_ai_cache", {}).get(key)
    slot = st.empty()

    def _brief(text: str, ai: bool) -> str:
        return _one(
            f'<div style="background:{V("card")};border:1px solid {V("line")};border-radius:16px;'
            f'padding:18px 22px;font-size:15px;line-height:1.65;color:{V("text")};">'
            f'<span style="font-size:11px;font-weight:700;letter-spacing:0.16em;margin-right:10px;'
            f'color:{V("mint") if ai else V("muted2")};">{"AI" if ai else "AUTO"}</span>{text}</div>')

    slot.markdown(_brief(done or tmpl, bool(done)), unsafe_allow_html=True)
    if ai_ok and not done:
        if st.button("Rewrite with the local model", key="briefing_ai_btn"):
            with fpl_loader("The gaffer is thinking", ["Reading your gameweek…", "Choosing the words…"]):
                got = _ai_rewrite(key)
            if got:
                st.session_state.setdefault("_briefing_ai_cache", {})[key] = got
                slot.markdown(_brief(got, True), unsafe_allow_html=True)


# ── Ask Claude ────────────────────────────────────────────────────────────────
_section("Ask Claude", "The same engine is wired into Claude Code as the fpl tools")
asks = ["Plan my next six weeks but keep Saka",
        "Compare Mbeumo and Rogers over the next six gameweeks",
        "Who should captain if Haaland is benched?",
        "Put the best plan in my My Team planner"]
st.markdown(_one(
    f'<div class="ff-stack" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;">'
    + "".join(f'<div style="padding:14px 16px;border-radius:14px;background:{V("card")};'
              f'border:1px solid {V("line")};font-size:14px;color:{V("text")};">'
              f'{theme.icon("chat", 18, V("mint"))} &nbsp;{a}</div>' for a in asks)
    + '</div>'), unsafe_allow_html=True)

with st.expander("Looking at another manager?"):
    tid = st.number_input("FPL Team ID", min_value=1, value=team_id or 1, step=1, key="home_team_id",
                          help="Find it in the FPL website URL: /entry/<ID>/")
    if int(tid) != team_id:
        st.session_state.squad_team_id = int(tid)
        st.rerun()
