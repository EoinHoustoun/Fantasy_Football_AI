"""
Transfer Planner · plan moves with instant net-gain verdicts.

Pick a player to sell and a player to buy; get a live verdict (strong upgrade /
net positive / lateral / net negative / avoid) with the reasoning and a
"strongly consider X instead" nudge. Chain several moves into a plan and see the
hit cost, bank, and net projected points gain over your chosen horizon.

Reuses analytics.transfer_engine.score_players for the per-player component
scores (form / fixtures / threat / value / minutes) that drive the verdicts.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from typing import Optional, Dict, Any, List

from components.animations import inject_global_animations
from components.team_identity import shirt_html, team_dot
from config import FPL_TEAM_ID

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
POS_ORDER = ["GKP", "DEF", "MID", "FWD"]
MUTED = "rgba(255,255,255,0.5)"


# ── Data ────────────────────────────────────────────────────────────────────────
def _get_data():
    ss = st.session_state
    if ss.get("players_df") is not None:
        return ss.players_df, ss.get("fixtures_df"), ss.get("bootstrap")
    from data.processors.player_stats import build_player_universe
    from data.fetchers.fpl_api import fetch_bootstrap, get_fixtures_df
    from data.fetchers.understat import fetch_understat_players
    bs = fetch_bootstrap()
    return (build_player_universe(bootstrap=bs, understat_df=fetch_understat_players()),
            get_fixtures_df(bootstrap=bs), bs)


players_df, fixtures_df, bootstrap = _get_data()
if players_df is None:
    st.info("Loading data… use **🔄 Refresh Data** in the sidebar if this persists.")
    st.stop()

from data.fetchers.fpl_api import get_current_gameweek, get_team_squad
current_gw = get_current_gameweek(bootstrap)

from analytics.transfer_engine import score_players
scored = score_players(players_df).set_index("fpl_id", drop=False)


st.markdown(
    f"""<div style="padding:16px 0 4px;font-family:'Inter',sans-serif;">
      <div style="font-size:38px;font-weight:900;color:#fff;letter-spacing:-1.1px;">🗓️ Transfer Planner</div>
      <div style="font-size:14px;color:{MUTED};margin-top:2px;">
        Sell → buy, with an instant verdict on every move. Build a multi-transfer plan and see the net gain.</div>
    </div>""",
    unsafe_allow_html=True,
)

# ── Controls ────────────────────────────────────────────────────────────────────
_default_id = st.session_state.get("squad_team_id") or (int(FPL_TEAM_ID) if FPL_TEAM_ID else 38148)
c_id, c_ft, c_hz = st.columns([1.4, 1, 1])
with c_id:
    team_id = st.number_input("FPL Team ID", min_value=1, value=int(_default_id), step=1,
                              key="planner_team_id")
with c_ft:
    free_transfers = st.number_input("Free transfers", min_value=0, max_value=5, value=1, step=1,
                                     help="Moves beyond this cost −4 pts each.")
with c_hz:
    horizon = st.slider("Plan horizon (GWs)", 1, 8, 6,
                        help="How many gameweeks this plan is meant to cover.")
st.session_state.squad_team_id = int(team_id)

try:
    squad_df, entry_history = get_team_squad(int(team_id), current_gw, bootstrap=bootstrap)
except Exception:
    st.error("Couldn't load that squad · check the Team ID.")
    st.stop()

bank = float(entry_history.get("bank", 0) or 0) / 10.0
owned_ids = set(squad_df["fpl_id"].tolist())

# Enrich squad rows with scored fields (transfer_score, ep_next, team_short, components)
enrich = scored.reindex(squad_df["fpl_id"].tolist())
squad = squad_df.merge(
    enrich[["transfer_score", "ep_next", "team_short", "score_form", "score_fixture",
            "score_xg", "score_value", "score_minutes"]],
    left_on="fpl_id", right_index=True, how="left", suffixes=("", "_s"),
)


# ── Move verdict engine ─────────────────────────────────────────────────────────
def _verdict(sell: pd.Series, buy: pd.Series) -> Dict[str, Any]:
    ds  = float(buy.get("transfer_score") or 0) - float(sell.get("transfer_score") or 0)
    dep = float(buy.get("ep_next") or 0) - float(sell.get("ep_next") or 0)
    afford = float(buy.get("price") or 0) <= bank + float(sell.get("price") or 0) + 1e-6
    buy_ok = str(buy.get("status", "a")) == "a"

    if not afford:
        tone, label, color, icon = "bad", "Over budget", "#FF4B4B", "⛔"
    elif not buy_ok:
        tone, label, color, icon = "warn", "Buying a flagged player", "#FF8C42", "🚑"
    elif ds >= 0.12:
        tone, label, color, icon = "great", "Strong upgrade · go for it", "#00FF87", "✅"
    elif ds >= 0.04:
        tone, label, color, icon = "good", "Net positive move", "#00FF87", "✅"
    elif ds > -0.04:
        tone, label, color, icon = "fine", "Lateral · a fine move", "#FFD700", "➖"
    elif ds > -0.12:
        tone, label, color, icon = "poor", "Net negative move", "#FF8C42", "⚠️"
    else:
        tone, label, color, icon = "bad", "Downgrade · avoid", "#FF4B4B", "⛔"

    # component reasoning
    comps = [("form", "score_form"), ("fixtures", "score_fixture"), ("threat", "score_xg"),
             ("value", "score_value"), ("minutes", "score_minutes")]
    ups, downs = [], []
    for label_c, col in comps:
        d = float(buy.get(col) or 0) - float(sell.get(col) or 0)
        if d >= 0.12:
            ups.append(label_c)
        elif d <= -0.12:
            downs.append(label_c)

    return {"tone": tone, "label": label, "color": color, "icon": icon,
            "ds": ds, "dep": dep, "afford": afford, "ups": ups, "downs": downs}


def _best_alternative(sell: pd.Series, exclude_ids: set) -> Optional[pd.Series]:
    budget = bank + float(sell.get("price") or 0)
    pos = str(sell.get("position", ""))
    alts = scored[(scored["position"] == pos) & (scored["status"] == "a") &
                  (scored["price"] <= budget + 1e-6) & (~scored["fpl_id"].isin(exclude_ids))]
    if alts.empty:
        return None
    return alts.sort_values("transfer_score", ascending=False).iloc[0]


# ── Current squad ───────────────────────────────────────────────────────────────
st.markdown("##### Your squad")
st.caption(f"Bank £{bank:.1f}m · {len(owned_ids)} players · scores over the next {horizon} GWs")

for pos in POS_ORDER:
    group = squad[squad["position"] == pos]
    if group.empty:
        continue
    chips = []
    for _, r in group.sort_values("transfer_score", ascending=False).iterrows():
        ts = float(r.get("transfer_score") or 0)
        flag = "" if str(r.get("status", "a")) == "a" else " 🚑"
        chips.append(
            f'<div style="display:inline-flex;align-items:center;gap:7px;background:rgba(22,26,34,0.85);'
            f'border:1px solid rgba(255,255,255,0.08);border-radius:9px;padding:6px 10px;margin:3px;">'
            f'{team_dot(r.get("team_short"), size=11)}'
            f'<span style="font-size:12px;font-weight:700;color:#fff;">{r.get("web_name","?")}{flag}</span>'
            f'<span style="font-size:11px;color:{MUTED};">£{float(r.get("price") or 0):.1f}m</span>'
            f'<span style="font-size:11px;font-weight:800;color:#04f5ff;">{ts:.2f}</span></div>'
        )
    st.markdown(
        f'<div style="margin:2px 0;"><span style="display:inline-block;background:{POS_COLORS[pos]};'
        f'color:#000;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:900;margin-right:6px;">{pos}</span>'
        + "".join(chips) + "</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Plan a move ─────────────────────────────────────────────────────────────────
st.markdown("##### Plan a move")

mv1, mv2 = st.columns(2)
with mv1:
    sell_name = st.selectbox(
        "Sell", options=squad.sort_values(["position", "web_name"])["web_name"].tolist(),
        key="planner_sell")
sell_row = squad[squad["web_name"] == sell_name].iloc[0]
sell_pos = str(sell_row.get("position", ""))
budget = bank + float(sell_row.get("price") or 0)

# candidate buys: same position, affordable, available, not already owned
buy_pool = scored[(scored["position"] == sell_pos) & (scored["status"] == "a") &
                  (scored["price"] <= budget + 1e-6) & (~scored["fpl_id"].isin(owned_ids))]
buy_pool = buy_pool.sort_values("transfer_score", ascending=False)

with mv2:
    if buy_pool.empty:
        st.selectbox("Buy", options=["- no affordable options -"], key="planner_buy_empty")
        st.warning("No affordable replacements at this position within your budget.")
        st.stop()
    buy_labels = [f"{r.web_name}  · £{r.price:.1f}m  · {r.transfer_score:.2f}"
                  for r in buy_pool.itertuples()]
    buy_choice = st.selectbox(f"Buy (budget £{budget:.1f}m)", options=buy_labels, key="planner_buy")
buy_row = buy_pool.iloc[buy_labels.index(buy_choice)]

# ── Live verdict ────────────────────────────────────────────────────────────────
v = _verdict(sell_row, buy_row)
alt = _best_alternative(sell_row, exclude_ids=owned_ids | {int(buy_row["fpl_id"])})
gain_h = v["dep"] * horizon

_reason = []
if v["ups"]:
    _reason.append(f'<span style="color:#00FF87;">▲ better {", ".join(v["ups"])}</span>')
if v["downs"]:
    _reason.append(f'<span style="color:#FF8C42;">▼ worse {", ".join(v["downs"])}</span>')
_reason_html = " &nbsp;·&nbsp; ".join(_reason) if _reason else '<span style="color:rgba(255,255,255,0.4);">evenly matched across the board</span>'

_nudge = ""
if alt is not None and float(alt["transfer_score"]) - float(buy_row["transfer_score"]) >= 0.05:
    _nudge = (
        f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);'
        f'font-size:12px;color:rgba(255,255,255,0.7);">💡 Strongly consider '
        f'<b style="color:#fff;">{alt["web_name"]}</b> instead · higher score '
        f'({float(alt["transfer_score"]):.2f} vs {float(buy_row["transfer_score"]):.2f}) at £{float(alt["price"]):.1f}m.</div>'
    )

st.markdown(
    f"""
<div class="fplh-animate-in" style="background:rgba(22,26,34,0.85);border:1px solid {v['color']}66;
     border-left:4px solid {v['color']};border-radius:14px;padding:18px 20px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
    <span style="font-size:26px;">{v['icon']}</span>
    <span style="font-size:19px;font-weight:900;color:{v['color']};">{v['label']}</span>
    <span style="flex:1;"></span>
    <span style="font-size:13px;color:{MUTED};">
      score {('+' if v['ds']>=0 else '')}{v['ds']:.2f} · {('+' if v['dep']>=0 else '')}{v['dep']:.1f} xP/GW ·
      <b style="color:{'#00FF87' if gain_h>=0 else '#FF4B4B'};">{('+' if gain_h>=0 else '')}{gain_h:.1f} pts over {horizon} GW</b></span>
  </div>
  <div style="margin-top:10px;font-size:13px;">
    <b style="color:#fff;">{sell_row.get('web_name','?')}</b>
    <span style="color:{MUTED};">→</span>
    <b style="color:#fff;">{buy_row.get('web_name','?')}</b>
    &nbsp;&nbsp;{_reason_html}
  </div>
  {_nudge}
</div>
""",
    unsafe_allow_html=True,
)

# ── Add to plan ─────────────────────────────────────────────────────────────────
if "planner_moves" not in st.session_state:
    st.session_state.planner_moves = []

b1, b2, _ = st.columns([1, 1, 2])
with b1:
    if st.button("➕ Add to plan", use_container_width=True):
        st.session_state.planner_moves.append({
            "out_id": int(sell_row["fpl_id"]), "out": str(sell_row["web_name"]),
            "in_id": int(buy_row["fpl_id"]), "in": str(buy_row["web_name"]),
            "cost": float(buy_row["price"]) - float(sell_row["price"]),
            "dep": float(v["dep"]), "ds": float(v["ds"]), "tone": v["tone"], "label": v["label"],
        })
        st.toast(f"{v['icon']} {v['label']} · {sell_row['web_name']} → {buy_row['web_name']}")
with b2:
    if st.session_state.planner_moves and st.button("🗑️ Clear plan", use_container_width=True):
        st.session_state.planner_moves = []
        st.rerun()

# ── Plan summary ────────────────────────────────────────────────────────────────
moves: List[dict] = st.session_state.planner_moves
if moves:
    st.markdown("---")
    st.markdown(f"##### Your plan · {len(moves)} transfer{'s' if len(moves) != 1 else ''}")

    n_hits = max(0, len(moves) - int(free_transfers))
    hit_pts = n_hits * 4
    net_cost = sum(m["cost"] for m in moves)
    raw_gain = sum(m["dep"] for m in moves) * horizon
    net_gain = raw_gain - hit_pts

    for i, m in enumerate(moves):
        _c = {"great": "#00FF87", "good": "#00FF87", "fine": "#FFD700",
              "poor": "#FF8C42", "warn": "#FF8C42", "bad": "#FF4B4B"}.get(m["tone"], "#fff")
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.03);'
            f'border-left:3px solid {_c};border-radius:8px;padding:8px 12px;margin-bottom:6px;font-family:\'Inter\',sans-serif;">'
            f'<span style="color:{MUTED};font-size:12px;width:20px;">{i+1}</span>'
            f'<span style="font-size:13px;color:#fff;font-weight:700;">{m["out"]} → {m["in"]}</span>'
            f'<span style="flex:1;"></span>'
            f'<span style="font-size:12px;color:{_c};font-weight:800;">{m["label"]}</span>'
            f'<span style="font-size:12px;color:{MUTED};width:80px;text-align:right;">'
            f'{("+" if m["dep"]>=0 else "")}{m["dep"]:.1f} xP/GW</span></div>',
            unsafe_allow_html=True,
        )

    bank_after = bank - net_cost
    over = bank_after < -1e-6
    cards = [
        ("Transfers", f"{len(moves)}", f"{n_hits} hit{'s' if n_hits != 1 else ''} (−{hit_pts})", "#04f5ff"),
        ("Bank after", f"£{bank_after:.1f}m", "over budget!" if over else "affordable", "#FF4B4B" if over else "#00FF87"),
        ("Raw gain", f"{('+' if raw_gain>=0 else '')}{raw_gain:.0f} pts", f"over {horizon} GW", "#00FF87" if raw_gain >= 0 else "#FF4B4B"),
        ("Net of hits", f"{('+' if net_gain>=0 else '')}{net_gain:.0f} pts", "the number that matters", "#00FF87" if net_gain >= 0 else "#FF4B4B"),
    ]
    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;">' + "".join(
            f'<div style="flex:1;min-width:150px;background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);'
            f'border-radius:12px;padding:14px 16px;font-family:\'Inter\',sans-serif;">'
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.12em;color:{MUTED};text-transform:uppercase;">{lab}</div>'
            f'<div style="font-size:24px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
            f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>'
            for lab, val, sub, acc in cards
        ) + "</div>",
        unsafe_allow_html=True,
    )

    _overall = ("This plan projects to **gain points even after the hits** · worth doing."
                if net_gain > 0 else
                "This plan **loses points once hits are counted** · bank the transfer or rethink it."
                if net_gain < 0 else "This plan is roughly neutral · no rush.")
    st.caption(_overall)
else:
    st.caption("Add a move above to start building a plan.")
