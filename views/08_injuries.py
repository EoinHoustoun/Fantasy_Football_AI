"""
Injuries · who is out, and when they are back (rebuilt 2026-09-27).

FPL's news carries the return date in words ("Expected back 11 Oct",
"Suspended until 17 Oct"). Read into a RETURN GAMEWEEK it becomes a planning
signal: a player back in GW8 is an entry point, a starter out until GW10 is an
exit. Players who have left the league are separated out rather than mixed in.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from analytics import service
from components import ff_table as T
from components.animations import count_up, inject_global_animations
from components.team_identity import face_html, player_photo_url
from ui import charts, theme
from ui.page import header, section, tiles
from ui.theme import fill, var as V

inject_global_animations()
header("Injuries", "Who is out, when they are back, and what it means for your fifteen.",
       kicker="This week", icon="medical_services")

bs = st.session_state.get("bootstrap") or {}
players = st.session_state.get("players_df")
if players is None:
    players = service.inputs()["players"]
events = [(int(e["id"]), datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")))
          for e in bs.get("events", []) if e.get("deadline_time")]
next_gw = next((int(e["id"]) for e in bs.get("events", []) if e.get("is_next")), 1)
_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                       "Sep", "Oct", "Nov", "Dec"], 1)}


def return_gw(news: str) -> Optional[int]:
    """'Expected back 11 Oct' / 'Suspended until 17 Oct' -> the first gameweek
    whose deadline falls after that date."""
    m = re.search(r"(?:back|until)\s+(\d{1,2})\s+([A-Z][a-z]{2})", news or "")
    if not m or m.group(2) not in _MONTHS:
        return None
    now = datetime.now(timezone.utc)
    mon = _MONTHS[m.group(2)]
    year = now.year + (1 if mon < 7 and now.month >= 7 else 0)
    try:
        d = datetime(year, mon, int(m.group(1)), tzinfo=timezone.utc)
    except ValueError:
        return None
    return next((g for g, dl in events if dl > d), None)


fl = players[players["status"].fillna("a") != "a"].copy()
left = fl["news"].fillna("").str.contains("joined|loan|left", case=False) | (fl["status"] == "u")
gone, fl = fl[left], fl[~left].copy()
fl["ret_gw"] = [return_gw(n) for n in fl["news"].fillna("")]
fl["dated"] = fl["ret_gw"].notna()
fl["chance"] = pd.to_numeric(fl["chance_of_playing_next_round"], errors="coerce")
# 75% doubts usually play: treat them as back for the next gameweek.
fl.loc[fl["ret_gw"].isna() & (fl["chance"] >= 75), "ret_gw"] = next_gw
fl["when"] = fl.apply(lambda r: ("GW%d" % r["ret_gw"]) if pd.notna(r["ret_gw"]) else "unknown", axis=1)

long = service.projections(allow_compute=False)
xp_next = (long[long["gw"] == long["gw"].min()].groupby("code")["xp"].sum()
           if long is not None else pd.Series(dtype=float))

try:
    T_ = service.team()
    mine = {p["code"]: p for p in T_["squad"]}
except Exception:  # noqa: BLE001
    mine = {}
mine_fl = fl[fl["code"].isin(mine)]

tiles([
    ("In your fifteen", count_up(len(mine_fl)), "flagged right now", "red" if len(mine_fl) else "mint"),
    ("Back within 3 GWs", count_up(int((fl["ret_gw"] <= next_gw + 2).sum())), "dated returns and 75% doubts", "mint"),
    ("No return date", count_up(int(fl["ret_gw"].isna().sum())), "injured, date unknown", "orange"),
    ("Left the league", count_up(len(gone)), "transferred abroad or down", "text"),
])

# ── Your fifteen ──────────────────────────────────────────────────────────────
section("Your fifteen", "Every flag in your squad, with when he should be back and what the "
        "engine still expects from him next gameweek.", "shield_person")
if mine_fl.empty:
    st.markdown(f'<div style="padding:16px;border-radius:14px;background:{V("card")};'
                f'border-left:3px solid {V("mint")};color:{V("text")};">Everyone in your fifteen is '
                f'available.</div>', unsafe_allow_html=True)
else:
    cols = st.columns(min(3, len(mine_fl)))
    for c, (_, r) in zip(cols * 3, mine_fl.iterrows()):
        ch = r["chance"]
        tone = "orange" if (pd.notna(ch) and ch >= 50) else "red"
        pct = 0 if pd.isna(ch) else int(ch)
        bench = mine.get(int(r["code"]), {}).get("on_bench")
        with c:
            st.markdown(
                f'<div class="ff-rise" style="display:flex;gap:14px;align-items:center;padding:14px 16px;'
                f'border-radius:14px;background:{V("card")};border:1px solid {V("line")};'
                f'border-top:3px solid {V(tone)};">'
                f'<div style="width:56px;flex-shrink:0;">{face_html(int(r["code"]), int(r["team_code"] or 1), r["position"] == "GKP", 56)}</div>'
                f'<div style="flex:1;min-width:0;"><div style="font-weight:800;color:{V("text")};font-size:16px;">'
                f'{r["web_name"]}<span style="font-size:12px;color:{V("muted2")};font-weight:500;">'
                f'{" · bench" if bench else " · starting XI"}</span></div>'
                f'<div style="font-size:12.5px;color:{V("muted")};">{r["news"] or "flagged"}</div>'
                f'<div style="font-size:12.5px;color:{V("text")};margin-top:4px;">Back: <b>{r["when"]}</b> · '
                f'engine GW{next_gw} <b class="ff-num">{float(xp_next.get(int(r["code"]), 0)):.2f}</b> xP</div></div>'
                f'<div style="width:58px;height:58px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;'
                f'justify-content:center;background:conic-gradient({V(tone)} {pct * 3.6}deg, {V("row-alt")} 0);">'
                f'<div class="ff-display ff-num" style="width:44px;height:44px;border-radius:50%;background:{V("bg2")};'
                f'display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:900;'
                f'color:{V(tone)};">{pct}%</div></div></div>', unsafe_allow_html=True)

# ── Who is coming back ────────────────────────────────────────────────────────
section("Who is coming back",
        "Players with a dated return, placed on the gameweek they should be available. Higher = "
        "owned by more managers. A good player back soon is an entry point; 75% doubts are in "
        "the board below.",
        "event_available")
back = fl[fl["dated"] & (fl["ret_gw"] <= next_gw + 7)].copy()
back = back.sort_values("ownership", ascending=False).head(24)
_faces = set(back.head(10)["code"]) | (set(back["code"]) & set(mine))
if back.empty:
    st.caption("No dated returns in the next eight gameweeks.")
else:
    gws = list(range(next_gw, next_gw + 8))
    data = []
    for _, r in back.iterrows():
        big = int(r["code"]) in _faces
        data.append({"value": [gws.index(int(r["ret_gw"])), round(float(r["ownership"] or 0), 1)],
                     "name": r["web_name"],
                     "symbol": "image://" + player_photo_url(int(r["code"])) if big else "circle",
                     "symbolSize": 38 if big else 10,
                     "itemStyle": {"color": fill("mint")},
                     "label": {"show": big, "formatter": r["web_name"], "position": "bottom",
                               "color": fill("text"), "fontSize": 10}})
    from streamlit_echarts import JsCode
    opt = {"backgroundColor": "transparent", "animationDuration": 1100,
           "grid": {"left": 50, "right": 24, "top": 20, "bottom": 40},
           "tooltip": {**charts._tooltip(), "trigger": "item",
                       "formatter": JsCode("function(p){return p.name+' · owned '+p.value[1]+'%';}").js_code},
           "xAxis": {**charts._axis("category", ["GW%d" % g for g in gws]), "boundaryGap": True},
           "yAxis": {**charts._axis("value"), "name": "Owned %", "type": "log", "min": 0.1,
                     "nameTextStyle": {"color": fill("muted2")}},
           "series": [{"type": "scatter", "data": data}]}
    charts.render(opt, height="380px", key="inj_returns")

# ── The board ─────────────────────────────────────────────────────────────────
section("Everyone flagged", "Sorted by ownership. Chance is FPL's figure for next gameweek.",
        "list_alt")
f1, f2 = st.columns([2, 1])
with f1:
    pos = st.segmented_control("Position", ["All", "GKP", "DEF", "MID", "FWD"], default="All",
                               key="inj_pos", label_visibility="collapsed") or "All"
with f2:
    min_own = st.select_slider("Owned by at least", [0.0, 0.5, 1.0, 2.0, 5.0, 10.0], value=1.0,
                               key="inj_own", format_func=lambda v: "%g%%" % v)
bd = fl if pos == "All" else fl[fl["position"] == pos]
bd = bd[bd["ownership"].fillna(0) >= min_own].sort_values("ownership", ascending=False)
_ST = {"i": "Injured", "d": "Doubtful", "s": "Suspended", "n": "Unavailable"}
rows = [{"code": int(r["code"]), "web_name": r["web_name"],
         "sub": "%s · %s" % (r["team_short"], r["position"]),
         "status": _ST.get(r["status"], r["status"]),
         "chance": None if pd.isna(r["chance"]) else float(r["chance"]),
         "when": r["when"], "news": r["news"] or "",
         "own": float(r["ownership"] or 0)} for _, r in bd.iterrows()]
T.render(rows, [
    T.col_face("code", url_fn=player_photo_url),
    T.col_player("web_name", sub="sub"),
    T.col_chip("status", "Status", lambda v: fill("orange-v") if v == "Doubtful" else fill("red-v")),
    T.col_num("chance", "Chance %", fmt="%.0f", empty="none given"),
    T.col_text("when", "Back"),
    T.col_text("news", "News"),
    T.col_num("own", "Owned %", fmt="%.1f"),
], key="inj_board", max_height=520, empty="Nobody flagged at this ownership.")

section("By club", "Flagged players per club, a rough read on squad depth trouble.", "groups")
counts = fl.groupby("team")["code"].count().sort_values()
opt = charts.bar_option(list(counts.index), [int(v) for v in counts.values], horizontal=True,
                        colors=charts.color_ramp([float(v) for v in counts.values],
                                                 fill("orange"), fill("red")))
opt["grid"]["left"] = 110
charts.render(opt, height="%dpx" % max(260, 22 * len(counts)), key="inj_by_club")

if not gone.empty:
    with st.expander("Left the league (%d)" % len(gone)):
        st.caption(", ".join("%s (%s)" % (r["web_name"], r["news"]) for _, r in gone.iterrows()))
