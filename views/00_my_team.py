"""
My Team · redesigned page.

Four-section layout designed around the manager's weekly decisions:

  1. HERO         · team identity, GW, deadline, 5-number stats strip
  2. THIS WEEK    · three decision cards (Captain · Sell alert · Opportunity)
  3. SQUAD        · pitch tabs, edit mode with scribble swap, pending swaps
  4. SEASON       · points history chart + inline summary

The edit-squad flow, scribble animation, and pending-swaps state are preserved
from the previous version but visually tightened.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from components.loading import LINES_GENERIC, LINES_SOLVER, LINES_SQUAD, fpl_loader

from ui import charts
from ui.charts import with_mark_line

from components.animations import (
    count_up,
    inject_global_animations,
    scribble_swap_overlay,
)

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

# ── Design tokens (local for now; will promote to a shared module next) ───────
POS_COLORS = {"GKP": "#00FF87", "DEF": "#04f5ff", "MID": "#e90052", "FWD": "#FF7B00"}
FDR_COLORS = {1: "#00FF87", 2: "#00FF87", 3: "#FFD60A", 4: "#FF8C42", 5: "#FF4B4B"}
SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"


def _shirt(team_code: int, is_gkp: bool) -> str:
    suffix = "_1" if is_gkp else ""
    return f"{SHIRT_BASE}/shirt_{team_code}{suffix}-66.png"


def _safe(val, default=0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return float(default)
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def _fdr_color(fdr: float) -> str:
    return FDR_COLORS.get(int(round(fdr)), "#FFD60A")


def _position_chip(pos: str) -> str:
    color = POS_COLORS.get(pos, "#888")
    return (
        f'<span style="background:{color};color:#000;border-radius:4px;'
        f'padding:2px 8px;font-weight:800;font-size:11px;letter-spacing:0.05em;">'
        f'{pos}</span>'
    )


def _mode_pill(title: str, sub: str, color: str) -> str:
    """A small centred status pill above the pitch (Actual vs Upcoming mode)."""
    return (
        f'<div style="display:flex;justify-content:center;margin:2px 0 10px;">'
        f'<div style="display:inline-flex;align-items:center;gap:10px;background:rgba(255,255,255,0.03);'
        f'border:1px solid {color}55;border-radius:999px;padding:6px 16px;">'
        f'<span style="width:7px;height:7px;border-radius:50%;background:{color};'
        f'box-shadow:0 0 10px {color};"></span>'
        f'<span style="font-family:\'Archivo\',sans-serif;font-size:12px;font-weight:800;'
        f'letter-spacing:0.06em;text-transform:uppercase;color:{color};">{title}</span>'
        f'<span style="font-size:12px;color:rgba(255,255,255,0.55);">{sub}</span>'
        f'</div></div>'
    )


# ── Scribble overlay (rendered at page root) ──────────────────────────────────
_pending_anim = st.session_state.pop("_swap_anim", None)
if _pending_anim:
    st.markdown(
        scribble_swap_overlay(
            out_name=_pending_anim.get("out", ""),
            in_name=_pending_anim.get("in", ""),
        ),
        unsafe_allow_html=True,
    )


# ── Data helpers ──────────────────────────────────────────────────────────────
def _get_players():
    if st.session_state.get("players_df") is not None:
        return st.session_state.players_df
    from data.processors.player_stats import build_player_universe
    from data.fetchers.understat import fetch_understat_players
    return build_player_universe(understat_df=fetch_understat_players())


@st.cache_data(ttl=1800, show_spinner=False)
def _load_team(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_team_info, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, entry_history = get_team_squad(team_id, gw, bootstrap=bs)
    team_info = fetch_team_info(team_id)
    return squad_df, entry_history, team_info


@st.cache_data(ttl=1800, show_spinner=False)
def _hist_squad(team_id: int, gw: int):
    """A past gameweek's squad + that GW's entry summary (points/rank/bench)."""
    from data.fetchers.fpl_api import get_team_squad
    return get_team_squad(team_id, gw, bootstrap=st.session_state.get("bootstrap"))


@st.cache_data(ttl=1800, show_spinner=False)
def _gw_points_map(gw: int):
    """{fpl_id: actual total points} for a gameweek (from the live endpoint)."""
    from data.fetchers.fpl_api import fetch_live_gw
    live = fetch_live_gw(gw)
    out = {}
    for e in (live.get("elements") or []):
        out[int(e.get("id"))] = int((e.get("stats") or {}).get("total_points", 0) or 0)
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _load_history(team_id: int):
    import requests
    resp = requests.get(
        f"https://fantasy.premierleague.com/api/entry/{team_id}/history/",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Team Lookup")
    from config import FPL_TEAM_ID
    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=int(FPL_TEAM_ID) if FPL_TEAM_ID else 1,
        step=1,
        help="Find your ID in the FPL URL: fantasy.premierleague.com/entry/XXXXXX/...",
    )
    st.caption("Enter any team ID to spy on a rival ⚡")

    st.markdown("---")
    budget_boost = st.slider(
        "Extra sale value (£m)",
        0.0, 5.0, 0.0, step=0.5,
        help="Expected gain if you sell a player above their purchase price · extends your swap budget.",
    )


# ── Load data ─────────────────────────────────────────────────────────────────
from data.fetchers.fpl_api import fetch_bootstrap, get_current_gameweek
bs         = fetch_bootstrap()
current_gw = get_current_gameweek(bs)

try:
    with fpl_loader(f"Fetching team {team_id}", LINES_SQUAD):
        squad_df, entry_history, team_info = _load_team(team_id, current_gw)
except Exception as e:
    st.error(f"Could not load team {team_id}: {e}")
    st.info("Check the team ID and try again.")
    st.stop()

# Cache for other pages
st.session_state.owned_names   = squad_df["web_name"].tolist()
st.session_state.squad_team_id = int(team_id)


# ── Deadline ─────────────────────────────────────────────────────────────────
def _next_deadline_fmt(bootstrap: dict) -> tuple[str, str]:
    for ev in bootstrap.get("events", []):
        if ev.get("is_next") or (ev.get("is_current") and not ev.get("finished")):
            raw = ev.get("deadline_time")
            if not raw:
                return "", "#00FF87"
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return "", "#00FF87"
            delta = dt - datetime.now(timezone.utc)
            secs = delta.total_seconds()
            if secs <= 0:
                return "Deadline passed", "#FF4B4B"
            days = delta.days
            hours, rem = divmod(delta.seconds, 3600)
            mins = rem // 60
            if days > 0:
                return f"{days}d {hours}h to deadline", "#00FF87" if days > 1 else "#FFA500"
            if hours > 0:
                return f"{hours}h {mins}m to deadline", "#FFA500" if hours > 6 else "#FF4B4B"
            return f"{mins}m to deadline", "#FF4B4B"
    return "", "#00FF87"


deadline_text, deadline_color = _next_deadline_fmt(bs)


# ── Squad basics ──────────────────────────────────────────────────────────────
team_name   = team_info.get("name", f"Team {team_id}")
manager     = f"{team_info.get('player_first_name', '')} {team_info.get('player_last_name', '')}".strip()
bank_m      = entry_history.get("bank", 0) / 10
value_m     = entry_history.get("value", 0) / 10
gw_pts      = entry_history.get("points", 0)
total_pts   = entry_history.get("total_points", 0)
overall_rank = entry_history.get("overall_rank", 0)
bench_pts    = entry_history.get("points_on_bench", 0)
transfer_cost = entry_history.get("event_transfers_cost", 0)
transfers_made = entry_history.get("event_transfers", 0)
active_chip  = team_info.get("active_chip") or None

xi    = squad_df[~squad_df["on_bench"]].copy()
bench = squad_df[squad_df["on_bench"]].copy()


# ── HERO ──────────────────────────────────────────────────────────────────────
def _rank_fmt(rank: int) -> str:
    if rank <= 0:
        return "-"
    if rank >= 1_000_000:
        return f"{rank/1_000_000:.2f}M"
    if rank >= 1_000:
        return f"{rank/1_000:.1f}K"
    return f"{rank:,}"


def _hero_stat(label: str, primary: str, accent: str, secondary: str = "") -> str:
    return f"""
<div style="flex:1;min-width:120px;padding:12px 16px;
     background:rgba(255,255,255,0.03);
     border:1px solid rgba(255,255,255,0.06);
     border-radius:10px;">
  <div style="font-size:10px;color:rgba(255,255,255,0.45);letter-spacing:0.14em;
       text-transform:uppercase;font-weight:800;">{label}</div>
  <div style="font-size:24px;font-weight:900;color:{accent};line-height:1.1;margin-top:4px;">
    {primary}
  </div>
  {f'<div style="font-size:11px;color:rgba(255,255,255,0.45);margin-top:2px;">{secondary}</div>' if secondary else ''}
</div>
"""


chip_label = (active_chip or "-").upper() if active_chip else "-"
deadline_pill = (
    f'<div style="display:inline-flex;align-items:center;gap:7px;'
    f'background:rgba(0,0,0,0.35);border:1px solid {deadline_color}66;'
    f'border-radius:999px;padding:6px 14px;backdrop-filter:blur(6px);">'
    f'<span style="font-size:12px;">🕒</span>'
    f'<span style="font-size:12px;font-weight:800;color:{deadline_color};">{deadline_text}</span>'
    f'</div>'
) if deadline_text else ""

hero_stats_html = (
    _hero_stat(f"GW{current_gw} Points", count_up(gw_pts - transfer_cost), "#00FF87",
               f"−{transfer_cost} hit" if transfer_cost else "No hits")
    + _hero_stat("Overall Rank", _rank_fmt(int(overall_rank or 0)), "#fff",
                 f"Total {total_pts:,}")
    + _hero_stat("Bank", f"£{bank_m:.2f}m", "#04f5ff",
                 f"Team £{value_m:.2f}m")
    + _hero_stat("Bench Points", count_up(bench_pts),
                 "#FF4B4B" if bench_pts > 8 else "#FFD60A" if bench_pts > 3 else "#fff",
                 f"{transfers_made} transfer{'s' if transfers_made != 1 else ''}")
    + _hero_stat("Active Chip", chip_label,
                 "#FFD700" if active_chip else "rgba(255,255,255,0.5)",
                 "" if active_chip else "No chip played")
)

st.markdown(
    f"""
<div class="fplh-animate-in" style="
    position:relative;padding:28px 32px;margin-bottom:22px;border-radius:18px;
    background:
      radial-gradient(circle at 0% 0%, rgba(0,255,135,0.12), transparent 55%),
      radial-gradient(circle at 100% 100%, rgba(55,0,60,0.35), transparent 65%),
      linear-gradient(135deg, rgba(22,26,34,0.96) 0%, rgba(14,17,22,0.98) 100%);
    border:1px solid rgba(255,255,255,0.08);
    font-family:'Inter','SF Pro Display',sans-serif;
    box-shadow:0 10px 30px rgba(0,0,0,0.35);
">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:24px;flex-wrap:wrap;">
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
        <span style="display:inline-block;width:7px;height:7px;border-radius:50%;
              background:#00FF87;box-shadow:0 0 10px #00FF87;"></span>
        <span style="font-size:11px;letter-spacing:0.22em;color:rgba(255,255,255,0.5);
              text-transform:uppercase;font-weight:800;">
          Gameweek {current_gw}{f' · Chip: {chip_label}' if active_chip else ''}
        </span>
      </div>
      <div style="font-size:40px;font-weight:900;color:#fff;letter-spacing:-1px;line-height:1;">
        {team_name}
      </div>
      <div style="font-size:13px;color:rgba(255,255,255,0.55);margin-top:6px;">
        {manager} &nbsp;·&nbsp; Team ID {int(team_id)}
      </div>
    </div>
    <div>{deadline_pill}</div>
  </div>

  <div style="display:flex;gap:10px;margin-top:22px;flex-wrap:wrap;">
    {hero_stats_html}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

if transfers_made > 1 and transfer_cost > 0:
    st.warning(f"**{transfers_made} transfers** this GW · {transfer_cost} pt hit applied.")


# ── Enrich squad with the fields we need for decisions ──────────────────────
from config import FIXTURE_LOOKAHEAD
_fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"

players_df_all = _get_players()

# Off-season the raw squad fetch carries form=0.0 for everyone (FPL's form is
# a 30-day average) · the universe self-heals it to points_per_game, so the
# squad always takes the universe's form. Fixes captain scores reading 0.
if "form" in players_df_all.columns:
    _form_fix = dict(zip(players_df_all["fpl_id"].astype(int),
                         pd.to_numeric(players_df_all["form"],
                                       errors="coerce").fillna(0.0)))
    squad_df["form"] = squad_df["fpl_id"].astype(int).map(_form_fix).fillna(
        pd.to_numeric(squad_df.get("form"), errors="coerce").fillna(0.0))

_enrich_cols = ["fpl_id"]
for c in (_fdr_col, "transfer_balance", "price_change", "ep_next",
          "upcoming_fixtures", "team_code"):
    if c in players_df_all.columns and c not in squad_df.columns:
        _enrich_cols.append(c)

squad_enriched = squad_df.merge(
    players_df_all[_enrich_cols], on="fpl_id", how="left",
) if len(_enrich_cols) > 1 else squad_df.copy()

# Attach short fixture codes
team_short_map = {t["name"]: t["short_name"] for t in bs["teams"]}

def _attach_short(fixtures):
    if not isinstance(fixtures, list):
        return fixtures
    return [
        {**f, "opp_short": team_short_map.get(f.get("opponent", ""), str(f.get("opponent", ""))[:3].upper())}
        for f in fixtures
    ]

if "upcoming_fixtures" in squad_enriched.columns:
    squad_enriched["upcoming_fixtures"] = squad_enriched["upcoming_fixtures"].apply(_attach_short)


# ── THIS WEEK'S DECISIONS · Captain · Sell · Opportunity ─────────────────────
st.markdown(
    '<div class="fplh-animate-in" style="margin:6px 0 14px;display:flex;'
    'align-items:center;gap:14px;">'
    '<div style="font-size:11px;letter-spacing:0.22em;color:rgba(255,255,255,0.55);'
    'text-transform:uppercase;font-weight:800;">This Gameweek\'s Decisions</div>'
    '<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div>'
    '</div>',
    unsafe_allow_html=True,
)


def _fixture_pills(fixtures, n: int = 4) -> str:
    if not isinstance(fixtures, list) or not fixtures:
        return '<span style="color:rgba(255,255,255,0.35);font-size:11px;">-</span>'
    pills = []
    for f in fixtures[:n]:
        opp = str(f.get("opp_short") or f.get("opponent", "?"))[:3].upper()
        home = bool(f.get("home", False))
        fdr = _safe(f.get("fdr"), 3.0)
        color = _fdr_color(fdr)
        pills.append(
            f'<span style="background:{color};color:#000;border-radius:4px;'
            f'padding:2px 6px;font-size:10px;font-weight:800;margin-right:4px;'
            f'display:inline-block;">{opp}{"·H" if home else "·A"}</span>'
        )
    return "".join(pills)


# ── Captain ranking (same fixture-weighted formula as before) ────────────────
cap_src = squad_enriched[~squad_enriched["on_bench"]].copy()
if _fdr_col in cap_src.columns:
    _fn = (cap_src["form"].fillna(0).astype(float) / 10.0).clip(0, 1)
    _fx = ((5.0 - cap_src[_fdr_col].fillna(3).astype(float)) / 4.0).clip(0, 1)
    cap_src["cap_score"] = (0.40 * _fn + 0.60 * _fx) * 10.0
else:
    cap_src["cap_score"] = cap_src["form"].fillna(0).astype(float)
cap_src = cap_src.sort_values("cap_score", ascending=False)

cap_top = cap_src.iloc[0] if not cap_src.empty else None

# ── Sell alerts ──────────────────────────────────────────────────────────────
def _sell_flags(p: pd.Series) -> list[str]:
    flags = []
    status = str(p.get("status", "a"))
    if status == "i":   flags.append("🚑 Injured")
    elif status == "s": flags.append("🚫 Suspended")
    elif status == "d": flags.append("⚠️ Doubt")
    form = float(p.get("form", 5) or 5)
    if form < 2.5:   flags.append(f"📉 Poor form ({form:.1f})")
    elif form < 3.5 and status not in ("i", "s"):
        flags.append(f"📉 Low form ({form:.1f})")
    fdr = p.get(_fdr_col) if _fdr_col in p else None
    if fdr is not None and float(fdr) > 3.8:
        flags.append(f"🔴 Tough run (FDR {float(fdr):.1f})")
    bal = int(p.get("transfer_balance", 0) or 0)
    if bal < -50_000:
        flags.append(f"📤 Mass sell ({abs(bal) // 1000:.0f}k out)")
    return flags


sell_candidates: list[tuple[pd.Series, list[str]]] = []
for _, p in squad_enriched[~squad_enriched["on_bench"]].iterrows():
    f = _sell_flags(p)
    if len(f) >= 2:
        sell_candidates.append((p, f))
sell_candidates.sort(key=lambda x: len(x[1]), reverse=True)

# ── Opportunity: top non-owned transfer target by transfer_score ─────────────
@st.cache_data(ttl=900, show_spinner=False)
def _scored_universe(_players):
    from analytics.transfer_engine import score_players, estimate_ceiling
    d = estimate_ceiling(score_players(_players))
    return d[d["status"] == "a"].sort_values("transfer_score", ascending=False)

try:
    owned_names = set(squad_df["web_name"].tolist())
    opp_df = _scored_universe(players_df_all)
    opp_df = opp_df[~opp_df["web_name"].isin(owned_names)]
    opp = opp_df.iloc[0] if not opp_df.empty else None
except Exception:
    opp = None


def _decision_card(kind: str, accent: str, header: str, body_html: str) -> str:
    return f"""
<div class="fplh-card-hover fplh-animate-in" style="
    background:rgba(22,26,34,0.85);
    border:1px solid rgba(255,255,255,0.08);
    border-top:3px solid {accent};
    border-radius:14px;padding:18px;
    font-family:'Inter',sans-serif;
    height:100%;
    display:flex;flex-direction:column;
">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
    <div style="font-size:11px;letter-spacing:0.18em;color:{accent};
         text-transform:uppercase;font-weight:900;">{header}</div>
    <div style="font-size:18px;">{kind}</div>
  </div>
  {body_html}
</div>
"""


# ── Captain card ─────────────────────────────────────────────────────────────
if cap_top is not None:
    ctop_code = int(cap_top.get("team_code", 1) or 1)
    ctop_shirt = _shirt(ctop_code, str(cap_top.get("position", "")) == "GKP")
    ctop_name = str(cap_top.get("web_name", "?"))
    ctop_team = str(cap_top.get("team", ""))
    ctop_pos  = str(cap_top.get("position", ""))
    ctop_score = float(cap_top["cap_score"])
    ctop_form = float(cap_top.get("form", 0) or 0)
    ctop_fdr = float(cap_top.get(_fdr_col, 3.0) or 3.0) if _fdr_col in cap_top else 3.0
    ctop_fix = _fixture_pills(cap_top.get("upcoming_fixtures"), n=4)

    cap_body = f"""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
  <div class="fplh-pop" style="position:relative;">
    <img src="{ctop_shirt}" width="62"
         onerror="this.src='{SHIRT_BASE}/shirt_1-66.png'"
         style="filter:drop-shadow(0 4px 6px rgba(0,0,0,0.45));"/>
    <div class="fplh-captain-pulse" style="position:absolute;top:-6px;right:-6px;
         background:#FFD700;color:#000;border-radius:50%;width:24px;height:24px;
         line-height:24px;text-align:center;font-weight:900;font-size:12px;">C</div>
  </div>
  <div style="flex:1;min-width:0;">
    <div style="font-size:18px;font-weight:900;color:#fff;white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;">{ctop_name}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.55);margin-top:2px;">
      {_position_chip(ctop_pos)} <span style="margin-left:6px;">{ctop_team}</span>
    </div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:22px;font-weight:900;color:#FFD700;line-height:1;">{ctop_score:.2f}</div>
    <div style="font-size:9px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">SCORE</div>
  </div>
</div>
<div style="display:flex;gap:14px;margin-bottom:10px;">
  <div><div style="font-size:14px;font-weight:800;color:#fff;">{ctop_form:.2f}</div>
       <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">FORM</div></div>
  <div><div style="font-size:14px;font-weight:800;color:{_fdr_color(ctop_fdr)};">{ctop_fdr:.2f}</div>
       <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">FDR{FIXTURE_LOOKAHEAD}</div></div>
</div>
<div style="margin-top:auto;">{ctop_fix}</div>
"""
    cap_card_html = _decision_card("🏆", "#FFD700", "Captain Pick", cap_body)
else:
    cap_card_html = _decision_card("🏆", "#FFD700", "Captain Pick",
                                    '<div style="color:rgba(255,255,255,0.5);">No data.</div>')


# ── Sell card ────────────────────────────────────────────────────────────────
if sell_candidates:
    worst, flags = sell_candidates[0]
    wcode = int(worst.get("team_code", 1) or 1)
    wshirt = _shirt(wcode, str(worst.get("position", "")) == "GKP")
    wname = str(worst.get("web_name", "?"))
    wteam = str(worst.get("team", ""))
    wpos  = str(worst.get("position", ""))
    flag_html = "".join(
        f'<span style="display:inline-block;background:rgba(255,75,75,0.08);'
        f'border:1px solid rgba(255,75,75,0.3);color:#fff;border-radius:4px;'
        f'padding:2px 8px;font-size:11px;margin:2px 4px 2px 0;">{f}</span>'
        for f in flags[:4]
    )
    others = len(sell_candidates) - 1
    others_html = (
        f'<div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:10px;">'
        f'+{others} other player{"s" if others > 1 else ""} flagged</div>'
        if others > 0 else ""
    )

    sell_body = f"""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
  <img src="{wshirt}" width="56"
       onerror="this.src='{SHIRT_BASE}/shirt_1-66.png'"
       style="filter:drop-shadow(0 4px 6px rgba(0,0,0,0.45));"/>
  <div style="flex:1;min-width:0;">
    <div style="font-size:18px;font-weight:900;color:#fff;white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;">{wname}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.55);margin-top:2px;">
      {_position_chip(wpos)} <span style="margin-left:6px;">{wteam}</span>
    </div>
  </div>
</div>
<div style="margin-top:4px;margin-bottom:4px;">{flag_html}</div>
{others_html}
"""
    sell_card_html = _decision_card("⚠️", "#FF4B4B", "Sell Alert", sell_body)
else:
    sell_card_html = _decision_card(
        "✅", "#00FF87", "Sell Alert",
        '<div style="font-size:14px;color:rgba(255,255,255,0.75);line-height:1.5;">'
        'No major concerns in your starting XI. Everyone\'s playing and firing.'
        '</div>'
    )


# ── Opportunity card ─────────────────────────────────────────────────────────
if opp is not None:
    ocode = int(opp.get("team_code", 1) or 1)
    oshirt = _shirt(ocode, str(opp.get("position", "")) == "GKP")
    oname = str(opp.get("web_name", "?"))
    oteam = str(opp.get("team", ""))
    opos  = str(opp.get("position", ""))
    oprice = float(opp.get("price", 0) or 0)
    oscore = float(opp.get("transfer_score", 0) or 0)
    oform = float(opp.get("form", 0) or 0)
    oep = float(opp.get("ep_next", 0) or 0)
    afford = oprice <= (bank_m + budget_boost + 15)   # 15 = rough swap headroom
    aff_badge = (
        '<span style="background:rgba(0,255,135,0.12);border:1px solid rgba(0,255,135,0.4);'
        'color:#00FF87;border-radius:4px;padding:2px 7px;font-size:10px;font-weight:800;'
        'letter-spacing:0.05em;margin-left:6px;">IN BUDGET</span>'
        if afford else ""
    )

    opp_body = f"""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
  <img src="{oshirt}" width="56"
       onerror="this.src='{SHIRT_BASE}/shirt_1-66.png'"
       style="filter:drop-shadow(0 4px 6px rgba(0,0,0,0.45));"/>
  <div style="flex:1;min-width:0;">
    <div style="font-size:18px;font-weight:900;color:#fff;white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;">{oname}{aff_badge}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.55);margin-top:2px;">
      {_position_chip(opos)} <span style="margin-left:6px;">{oteam} · £{oprice:.2f}m</span>
    </div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:22px;font-weight:900;color:#00FF87;line-height:1;">{oscore:.2f}</div>
    <div style="font-size:9px;color:rgba(255,255,255,0.5);letter-spacing:0.1em;">SCORE</div>
  </div>
</div>
<div style="display:flex;gap:14px;">
  <div><div style="font-size:14px;font-weight:800;color:#fff;">{oform:.2f}</div>
       <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">FORM</div></div>
  <div><div style="font-size:14px;font-weight:800;color:#04f5ff;">{oep:.2f}</div>
       <div style="font-size:9px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;">xP NEXT</div></div>
</div>
"""
    opp_card_html = _decision_card("🔄", "#00FF87", "Opportunity", opp_body)
else:
    opp_card_html = _decision_card("🔄", "#00FF87", "Opportunity",
                                    '<div style="color:rgba(255,255,255,0.5);">No data.</div>')


st.markdown(
    '<div class="fplh-stagger" style="display:grid;'
    'grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:4px;">'
    + cap_card_html + sell_card_html + opp_card_html
    + '</div>',
    unsafe_allow_html=True,
)

# Small deep-link row under the decisions panel
link_cols = st.columns(3)
with link_cols[0]:
    st.page_link("views/06_captain_picker.py", label="Full captain breakdown →")
with link_cols[1]:
    st.page_link("views/07_buy_sell.py",       label="Full sell analysis →")
with link_cols[2]:
    st.page_link("views/02_transfer_suggestions.py", label="All transfer targets →")


# ── Shared replacement panel (edit mode + future-GW planner) ─────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _gw_stats(fpl_id: int) -> list:
    """Per-GW stat lines for one player (element-summary), for column charts."""
    import requests
    try:
        r = requests.get(
            f"https://fantasy.premierleague.com/api/element-summary/{int(fpl_id)}/",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        r.raise_for_status()
        hist = r.json().get("history", []) or []
    except Exception:  # noqa: BLE001 · charts degrade to season snapshot
        return []
    keep = ("round", "total_points", "minutes", "goals_scored", "assists",
            "bonus", "defensive_contribution", "expected_goals",
            "expected_goal_involvements")
    return [{k: h.get(k) for k in keep} for h in hist]


@st.dialog("Column leaders", width="large")
def _column_chart_dialog(label: str, season_col: str, gw_field, pool: pd.DataFrame) -> None:
    """Top ten of one stat across the current candidate pool. Per-GW stats get
    a window slider (default the last 6 gameweeks · slide out to the season)."""
    from components.team_identity import team_color as _tc
    st.markdown(
        f'<div style="font-family:\'Archivo\',sans-serif;font-size:20px;'
        f'font-weight:900;color:#fff;">Top ten · {label}</div>',
        unsafe_allow_html=True)
    top = pool.dropna(subset=[season_col]).nlargest(15, season_col)
    if top.empty:
        st.info("No data for this column.")
        return
    if gw_field:
        n = st.slider("Window · last N gameweeks", 2, 38, 6,
                      key=f"colchart_n_{season_col}")
        rows = []
        with fpl_loader(f"Fetching gameweek histories", LINES_GENERIC):
            for _, r in top.iterrows():
                hist = _gw_stats(int(r["fpl_id"]))
                vals = [float(h.get(gw_field) or 0) for h in hist][-int(n):]
                rows.append((str(r["web_name"]), round(sum(vals), 1),
                             r.get("team_short")))
        rows.sort(key=lambda x: -x[1])
        rows = rows[:10]
        sub = f"summed over the last {int(n)} gameweeks · candidates ranked live"
    else:
        rows = [(str(r["web_name"]), round(float(r[season_col] or 0), 1),
                 r.get("team_short")) for _, r in top.head(10).iterrows()]
        sub = "current season snapshot"
    st.caption(sub)
    opt = charts.bar_option(
        x=[nm for nm, _, _ in rows], y=[v for _, v, _ in rows],
        colors=[_tc(ts) for _, _, ts in rows], horizontal=True)
    for item, (_nm, v, _ts) in zip(opt["series"][0]["data"], rows):
        item["label"] = {"show": True, "position": "right", "formatter": f"{v:g}",
                         "color": "rgba(255,255,255,0.75)", "fontSize": 11}
    opt["grid"]["left"] = 110
    opt["grid"]["right"] = 46
    charts.render(opt, height="340px", key=f"colchart_{season_col}")


def _replacement_panel(out_name: str, out_pos: str, out_price: float,
                       avail_budget: float, owned_ids: set,
                       key_prefix: str = "repl", out_id: int = 0,
                       xp_map=None):
    """The axed banner + searchable, sortable list of affordable replacements.

    Returns ("sign", row) the run a Sign button is pressed, ("compare", row)
    when a head-to-head is requested, ("cancel", None) when the axe is
    cancelled, else (None, None).
    """
    from components.team_identity import team_color as _team_color

    st.markdown(
        f"""<div style="padding:12px 16px;
            background:linear-gradient(135deg,rgba(255,75,75,0.10),rgba(0,0,0,0.4));
            border:1px dashed #FF4B4B;border-radius:10px;margin-bottom:10px;" class="fplh-animate-in">
        <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.12em;
             text-transform:uppercase;font-weight:700;">Axed</div>
        <div style="font-size:20px;font-weight:900;color:#fff;font-family:'Archivo',sans-serif;
             text-decoration:line-through #FF4B4B 3px;">{out_name}</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.55);margin-top:3px;">
         {out_pos} · £{out_price:.2f}m · budget £{avail_budget:.2f}m</div>
        </div>""",
        unsafe_allow_html=True,
    )

    pool = players_df_all[
        (players_df_all["position"] == out_pos)
        & (players_df_all["price"] <= avail_budget + 0.01)
        & (players_df_all["status"] == "a")
        & (~players_df_all["fpl_id"].isin(owned_ids))
    ].copy()
    if xp_map:   # planner mode · xP for the VIEWED week, not FPL's ep_next
        pool["ep_next"] = pool["fpl_id"].astype(int).map(xp_map).fillna(0.0)

    from analytics.price_radar import price_flags
    _pflags = price_flags(players_df_all)

    _fdr_repl = _fdr_col if _fdr_col in pool.columns else next(
        (c for c in pool.columns if c.startswith("avg_fdr_next_")), None
    )
    _xg_col  = next((c for c in ("xg", "fpl_xg", "expected_goals")
                     if c in pool.columns), None)
    _xgi_col = next((c for c in ("xgi", "fpl_xgi_per90", "expected_goal_involvements_per_90")
                     if c in pool.columns), None)

    _search = st.text_input("Search", key=f"{key_prefix}_search",
                            placeholder="filter by name…", label_visibility="collapsed")
    _f1, _f2 = st.columns(2)
    with _f1:
        _clubs = ["All clubs"] + sorted(pool["team"].dropna().unique().tolist())
        _club = st.selectbox("Club", _clubs, key=f"{key_prefix}_club",
                             label_visibility="collapsed")
    with _f2:
        _opts = ["Best (form+fixtures)", "Total points", "Form", "xP next GW"]
        if _xg_col:  _opts.append("xG")
        if _xgi_col: _opts.append("xGI/90")
        _opts += ["Best fixtures", "Value", "Cheapest"]
        _sortby = st.selectbox("Sort", _opts, key=f"{key_prefix}_sort",
                               label_visibility="collapsed")
    _show_all = st.toggle("Show every affordable option", key=f"{key_prefix}_show_all")

    cand = pool
    if _search:
        cand = cand[cand["web_name"].str.contains(_search, case=False, na=False)]
    if _club != "All clubs":
        cand = cand[cand["team"] == _club]

    if not cand.empty:
        if _sortby == "Total points" and "total_points" in cand.columns:
            cand = cand.sort_values("total_points", ascending=False)
        elif _sortby == "Form":
            cand = cand.sort_values("form", ascending=False)
        elif _sortby == "xP next GW" and "ep_next" in cand.columns:
            cand = cand.sort_values("ep_next", ascending=False)
        elif _sortby == "xG" and _xg_col:
            cand = cand.sort_values(_xg_col, ascending=False)
        elif _sortby == "xGI/90" and _xgi_col:
            cand = cand.sort_values(_xgi_col, ascending=False)
        elif _sortby == "Best fixtures" and _fdr_repl:
            cand = cand.sort_values(_fdr_repl, ascending=True)
        elif _sortby == "Value" and "points_per_million" in cand.columns:
            cand = cand.sort_values("points_per_million", ascending=False)
        elif _sortby == "Cheapest":
            cand = cand.sort_values("price", ascending=True)
        else:  # Best · form + xP + fixtures. Form and xP are player-level
            # signals, so the list ranks PLAYERS, not clubs (fixture ease is
            # club-level and used to clump the list by team).
            _form_n = (cand["form"].fillna(0).astype(float) / 10.0).clip(0, 1)
            _fix_n = ((5.0 - cand[_fdr_repl].fillna(3).astype(float)) / 4.0).clip(0, 1) if _fdr_repl else 0.5
            if "ep_next" in cand.columns:
                _xp = pd.to_numeric(cand["ep_next"], errors="coerce").fillna(0.0)
                _xp_n = (_xp / _xp.max()).clip(0, 1) if _xp.max() > 0 else 0.0
            else:
                _xp_n = 0.0
            cand = cand.assign(_rank_score=0.45 * _form_n + 0.30 * _xp_n + 0.25 * _fix_n)
            cand = cand.sort_values("_rank_score", ascending=False)

    _total = len(cand)
    cand = (cand if _show_all else cand.head(20)).reset_index(drop=True)
    st.markdown(
        f"<div style='margin:8px 0 6px;font-size:12px;color:rgba(255,255,255,0.6);'>"
        f"{_total} option{'s' if _total != 1 else ''} within £{avail_budget:.1f}m"
        f"{' · top 20' if not _show_all and _total > 20 else ''}</div>",
        unsafe_allow_html=True,
    )
    if cand.empty:
        st.info("No affordable replacements match those filters.")

    def _price_badge(pc) -> str:
        f = _pflags.get(int(pc["fpl_id"]))
        if f == "rise":
            return ('<span style="color:#00FF87;font-weight:900;" '
                    'title="Price likely to rise soon">▲</span>')
        if f == "fall":
            return ('<span style="color:#FF4B4B;font-weight:900;" '
                    'title="Price likely to fall soon">▼</span>')
        return ""

    # ── Sortable stats table · pick your columns, sort any header, chart any
    # column (📊 → top ten with a gameweek-window slider), select a row to act.
    from components.team_identity import shirt_url as _srl
    st.markdown(
        f"""<style>
        div[class*="st-key-{key_prefix}_"] button {{
            font-size: 11px !important; padding: 1px 6px !important;
            min-height: 26px !important; width: 100%;
        }}</style>""", unsafe_allow_html=True)

    # label: (universe column, per-GW field for the chart window, format)
    _COLS = {
        "Form":   ("form", "total_points", "%.1f"),
        "xP":     ("ep_next", None, "%.1f"),
        "Pts":    ("total_points", "total_points", "%d"),
        "Mins":   ("avg_minutes", "minutes", "%d"),
        "Goals":  ("goals_scored", "goals_scored", "%d"),
        "DEFCON": ("defensive_contribution", "defensive_contribution", "%d"),
        "Assists": ("assists", "assists", "%d"),
        "xG":     ("xg", "expected_goals", "%.1f"),
        "xGI/90": ("fpl_xgi_per90", "expected_goal_involvements", "%.2f"),
        "Bonus":  ("bonus", "bonus", "%d"),
        "Own%":   ("ownership", None, "%.1f"),
        "Pts/£m": ("points_per_million", None, "%.1f"),
    }
    _defaults = ["Form", "xP", "Pts", "Mins", "Goals", "DEFCON"]

    # Backfill any missing stat columns straight from the bootstrap · on BOTH
    # the display rows and the full pool (the chart dialog ranks the pool).
    _bs = st.session_state.get("bootstrap") or {}
    _by_id = {int(e["id"]): e for e in _bs.get("elements", [])}
    for _df in (pool, cand):
        for _lbl, (_col, _f, _fmt) in _COLS.items():
            if _col not in _df.columns:
                _df[_col] = pd.to_numeric(
                    _df["fpl_id"].astype(int).map(
                        lambda i: _by_id.get(i, {}).get(_col)),
                    errors="coerce")

    _picked = st.multiselect(
        "Columns", list(_COLS.keys()), default=_defaults,
        key=f"{key_prefix}_cols", label_visibility="collapsed",
        placeholder="Choose stat columns…")

    # 📊 chart buttons · one per active column, three per row
    if _picked:
        for _ri in range(0, len(_picked), 3):
            _chunk = _picked[_ri:_ri + 3]
            _ccols = st.columns(3)
            for _cc, _lbl in zip(_ccols, _chunk):
                with _cc:
                    if st.button(f"📊 {_lbl}", key=f"{key_prefix}_chart_{_COLS[_lbl][0]}",
                                 use_container_width=True,
                                 help=f"Top ten by {_lbl} · with a gameweek window"):
                        _column_chart_dialog(_lbl, _COLS[_lbl][0], _COLS[_lbl][1], pool)

    _show = cand.copy()
    _show["_kit"] = [
        _srl(int(tc or 1), str(pos) == "GKP")
        for tc, pos in zip(_show.get("team_code", 1), _show["position"])]
    _flag_map = {"rise": "▲", "fall": "▼"}
    _show["_move"] = _show["fpl_id"].astype(int).map(
        lambda i: _flag_map.get(_pflags.get(i), ""))
    _tbl_cols = ["_kit", "web_name", "price", "_move"] + [
        _COLS[l][0] for l in _picked]
    _cfg = {
        "_kit": st.column_config.ImageColumn("", width=34),
        "web_name": st.column_config.TextColumn("Player", width=110),
        "price": st.column_config.NumberColumn("£", format="%.1f", width=52),
        "_move": st.column_config.TextColumn("Δ£", width=34,
                                             help="▲ price rise likely · ▼ fall"),
    }
    for _lbl in _picked:
        _col, _f, _fmt = _COLS[_lbl]
        _cfg[_col] = st.column_config.NumberColumn(_lbl, format=_fmt, width=60)

    _event = st.dataframe(
        _show[_tbl_cols], column_config=_cfg, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        height=min(520, 42 + 35 * len(_show)),
        key=f"{key_prefix}_tbl")

    result = (None, None)
    _sel_rows = (_event.selection.rows
                 if _event and hasattr(_event, "selection") else [])
    if _sel_rows:
        _pc = cand.iloc[_sel_rows[0]]
        _b1, _b2, _sp = st.columns([1.3, 1.3, 2])
        with _b1:
            if st.button(f"✅ Sign {str(_pc['web_name'])[:12]}",
                         key=f"{key_prefix}_sign_sel", type="primary",
                         use_container_width=True):
                result = ("sign", _pc)
        with _b2:
            if st.button(f"⚖ vs {out_name[:10]}", key=f"{key_prefix}_cmp_sel",
                         use_container_width=True,
                         help=f"Head-to-head: {out_name} vs {_pc['web_name']}"):
                result = ("compare", _pc)
    else:
        st.caption("Select a row to sign or compare · click any header to sort.")

    if st.button("Cancel axe", key=f"{key_prefix}_cancel"):
        result = ("cancel", None)
    return result


@st.cache_data(ttl=900, show_spinner=False)
def _xp_horizon_cached(first_gw: int, horizon: int, _players, _bootstrap):
    """Shared multi-GW xP surface (analytics/xp_engine) · df indexed by fpl_id
    with one column per GW. Fixtures are rebuilt with the sim weeks appended
    (the session copy holds only real fixtures)."""
    from analytics.xp_engine import project_horizon
    from data.fetchers.fpl_api import get_fixtures_df
    from data.processors.player_stats import _append_simulated_gw
    fx = get_fixtures_df(bootstrap=_bootstrap)
    if first_gw > 38:   # off-season sandbox · simulated future weeks
        for off in range(horizon):
            fx = _append_simulated_gw(fx, source_gw=1 + off, new_gw=first_gw + off)
    return project_horizon(_players, fx, first_gw, horizon)


def _xp_horizon():
    """(horizon_df, first_gw, horizon) for the planner window, or None."""
    from config import SIM_HORIZON
    _cur = int(st.session_state.get("current_gw") or current_gw or 1)
    first = _cur + 1
    if first > 38 and not st.session_state.get("simulating_gw"):
        return None
    horizon = SIM_HORIZON if first > 38 else max(1, min(SIM_HORIZON, 39 - first))
    try:
        return (_xp_horizon_cached(first, horizon, players_df_all, bs),
                first, horizon)
    except Exception:  # noqa: BLE001 · projections are an enhancement, not a dependency
        return None


@st.dialog("Head to head", width="large")
def _h2h_dialog(out_id: int, in_id: int) -> None:
    """One-v-one · the player you're axing vs the player you'd sign."""
    from components.team_identity import shirt_html as _sh, team_color as _tc
    from ui.player_detail import radar_percentiles
    from ui import charts as _ch

    rows = {}
    for pid in (out_id, in_id):
        m = players_df_all[players_df_all["fpl_id"] == int(pid)]
        if m.empty:
            st.info("Player data unavailable.")
            return
        rows[pid] = m.iloc[0]
    p_out, p_in = rows[out_id], rows[in_id]

    def _head(r, accent, tag):
        fx = _attach_short(r.get("upcoming_fixtures"))
        pills = _fixture_pills(fx, n=5)
        return (
            f'<div style="border:1px solid {accent}55;border-top:3px solid {accent};'
            f'border-radius:12px;padding:14px 16px;background:rgba(22,26,34,0.85);">'
            f'<div style="font-size:10px;letter-spacing:0.16em;text-transform:uppercase;'
            f'font-weight:900;color:{accent};margin-bottom:8px;">{tag}</div>'
            f'<div style="display:flex;align-items:center;gap:12px;">'
            f'{_sh(int(r.get("team_code", 1) or 1), is_gkp=str(r.get("position")) == "GKP", width=50)}'
            f'<div><div style="font-family:\'Archivo\',sans-serif;font-size:20px;'
            f'font-weight:900;color:#fff;">{r.get("web_name", "?")}</div>'
            f'<div style="font-size:12px;color:rgba(255,255,255,0.55);">'
            f'{r.get("team", "?")} · {r.get("position", "?")} · £{float(r.get("price", 0) or 0):.1f}m</div></div></div>'
            f'<div style="margin-top:10px;">{pills}</div></div>'
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_head(p_out, "#FF4B4B", "Out"), unsafe_allow_html=True)
    with c2:
        st.markdown(_head(p_in, "#00FF87", "In"), unsafe_allow_html=True)

    # Stat-by-stat · winner highlighted per row
    _stats = [("Form", "form", 1), ("xP next", "ep_next", 1),
              ("Season pts", "total_points", 0), ("xGI/90", "fpl_xgi_per90", 2),
              ("Minutes", "minutes", 0), ("Owned %", "ownership", 1),
              ("Pts/£m", "points_per_million", 1)]
    _rows_html = ""
    for label, col, dp in _stats:
        if col not in players_df_all.columns:
            continue
        vo = float(p_out.get(col, 0) or 0)
        vi = float(p_in.get(col, 0) or 0)
        co = "#FF4B4B" if vo > vi else "rgba(255,255,255,0.65)"
        ci = "#00FF87" if vi > vo else "rgba(255,255,255,0.65)"
        _rows_html += (
            f'<div style="display:flex;align-items:center;padding:5px 0;'
            f'border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'<div style="flex:1;text-align:right;font-weight:800;color:{co};'
            f'font-family:\'Archivo\',sans-serif;">{vo:.{dp}f}</div>'
            f'<div style="width:110px;text-align:center;font-size:10px;letter-spacing:0.12em;'
            f'text-transform:uppercase;color:rgba(255,255,255,0.45);font-weight:700;">{label}</div>'
            f'<div style="flex:1;font-weight:800;color:{ci};'
            f'font-family:\'Archivo\',sans-serif;">{vi:.{dp}f}</div></div>'
        )
    _hz = _xp_horizon()
    if _hz is not None:
        _hdf, _hfirst, _hn = _hz
        _vo5 = float(_hdf["xp_total"].get(int(out_id), 0.0))
        _vi5 = float(_hdf["xp_total"].get(int(in_id), 0.0))
        _co5 = "#FF4B4B" if _vo5 > _vi5 else "rgba(255,255,255,0.65)"
        _ci5 = "#00FF87" if _vi5 > _vo5 else "rgba(255,255,255,0.65)"
        _rows_html += (
            f'<div style="display:flex;align-items:center;padding:5px 0;">'
            f'<div style="flex:1;text-align:right;font-weight:800;color:{_co5};'
            f'font-family:\'Archivo\',sans-serif;">{_vo5:.1f}</div>'
            f'<div style="width:110px;text-align:center;font-size:10px;letter-spacing:0.12em;'
            f'text-transform:uppercase;color:#FFD700;font-weight:800;">xP next {_hn} GWs</div>'
            f'<div style="flex:1;font-weight:800;color:{_ci5};'
            f'font-family:\'Archivo\',sans-serif;">{_vi5:.1f}</div></div>'
        )
    st.markdown(f'<div style="margin:12px 0 4px;">{_rows_html}</div>',
                unsafe_allow_html=True)

    # Verdict + radar overlay
    _xp_gain = float(p_in.get("ep_next", 0) or 0) - float(p_out.get("ep_next", 0) or 0)
    _price_d = float(p_out.get("price", 0) or 0) - float(p_in.get("price", 0) or 0)
    _vcol = "#00FF87" if _xp_gain >= 0 else "#FF4B4B"
    st.markdown(
        f'<div style="text-align:center;padding:8px;font-size:13px;color:rgba(255,255,255,0.7);">'
        f'This move buys <b style="color:{_vcol};">{_xp_gain:+.1f} xP</b> next GW and '
        f'{"banks" if _price_d >= 0 else "costs"} '
        f'<b style="color:#04f5ff;">£{abs(_price_d):.1f}m</b></div>',
        unsafe_allow_html=True,
    )
    ind_o, val_o = radar_percentiles(players_df_all, p_out)
    ind_i, val_i = radar_percentiles(players_df_all, p_in)
    if len(ind_o) >= 3 and len(ind_o) == len(ind_i):
        charts.render(_ch.radar_compare_option(ind_o, [
            (str(p_out.get("web_name", "Out")), val_o, "#FF4B4B", 0.14),
            (str(p_in.get("web_name", "In")), val_i, "#00FF87", 0.24),
        ]), height="300px", key=f"h2h_{out_id}_{in_id}")


# ── SQUAD ─────────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin:30px 0 12px;display:flex;align-items:center;gap:14px;">'
    '<div style="font-size:11px;letter-spacing:0.22em;color:rgba(255,255,255,0.55);'
    'text-transform:uppercase;font-weight:800;">Squad</div>'
    '<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div>'
    '</div>',
    unsafe_allow_html=True,
)


tab_pitch, tab_lineup, tab_table = st.tabs(["⚽ Pitch View", "✏️ Lineup", "📋 Squad Table"])

with tab_lineup:
    from collections import Counter
    from components.team_identity import team_dot

    st.caption("Rearrange your XI and bench and set your captain · instant projected-points "
               "feedback. Planning only (doesn't write back to FPL).")

    # Enrich a local copy with ep_next + team_short for scoring and dots.
    _ldf = squad_df.copy()
    _mc = ["fpl_id"]
    for _c in ("ep_next", "team_short"):
        if _c in players_df_all.columns and _c not in _ldf.columns:
            _mc.append(_c)
    if len(_mc) > 1:
        _ldf = _ldf.merge(players_df_all[_mc], on="fpl_id", how="left")

    _info = {
        int(r.fpl_id): {
            "name": str(r.web_name), "pos": str(r.position),
            "ep": float(getattr(r, "ep_next", 0) or 0),
            "short": getattr(r, "team_short", None),
            "status": str(getattr(r, "status", "a")),
            "price": float(getattr(r, "price", 0) or 0),
        } for r in _ldf.itertuples()
    }

    _orig_starters = [int(r.fpl_id) for r in _ldf.itertuples() if not bool(r.on_bench)]
    _orig_captain  = next((int(r.fpl_id) for r in _ldf.itertuples() if bool(r.is_captain)), None)

    # Working lineup lives in session_state; reset when the team id changes.
    _lu = st.session_state.get("lineup")
    if not _lu or _lu.get("team_id") != int(team_id):
        _bench_ids = [int(r.fpl_id) for r in _ldf.sort_values("squad_position").itertuples()
                      if bool(r.on_bench)]
        _lu = {"team_id": int(team_id), "starters": list(_orig_starters), "bench": _bench_ids,
               "captain": _orig_captain,
               "vice": next((int(r.fpl_id) for r in _ldf.itertuples() if bool(r.is_vice_captain)), None)}
        st.session_state.lineup = _lu

    _FMIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
    _FMAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}

    def _cnt(ids):
        return Counter(_info[i]["pos"] for i in ids)

    def _valid(ids):
        c = _cnt(ids)
        return len(ids) == 11 and all(_FMIN[p] <= c.get(p, 0) <= _FMAX[p] for p in _FMIN)

    # ── Substitution control ──────────────────────────────────────────────────
    _n2id = {_info[i]["name"]: i for i in _lu["starters"] + _lu["bench"]}
    s1, s2, s3 = st.columns([2, 2, 1])
    with s1:
        _off = st.selectbox("Take off (XI)", [_info[i]["name"] for i in _lu["starters"]], key="lu_off")
    with s2:
        _on = st.selectbox("Bring on (bench)", [_info[i]["name"] for i in _lu["bench"]], key="lu_on")
    with s3:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        _do_swap = st.button("🔁 Swap", use_container_width=True)

    if _do_swap:
        _oid, _iid = _n2id[_off], _n2id[_on]
        _new = [_iid if x == _oid else x for x in _lu["starters"]]
        if (_info[_oid]["pos"] == "GKP") != (_info[_iid]["pos"] == "GKP"):
            st.session_state._lu_msg = ("err", "A goalkeeper can only be swapped with a goalkeeper.")
        elif not _valid(_new):
            c = _cnt(_new)
            st.session_state._lu_msg = ("err", f"That breaks your formation "
                f"({c.get('DEF',0)}-{c.get('MID',0)}-{c.get('FWD',0)}) · need ≥3 DEF, ≥2 MID, ≥1 FWD.")
        else:
            _lu["bench"] = [_oid if x == _iid else x for x in _lu["bench"]]
            _lu["starters"] = _new
            if _lu["captain"] not in _lu["starters"]:
                _lu["captain"] = _iid
            if _lu["vice"] not in _lu["starters"]:
                _lu["vice"] = _iid
            st.session_state.lineup = _lu
            st.session_state._lu_msg = ("ok", f"Subbed {_info[_oid]['name']} → {_info[_iid]['name']}.")

    _msg = st.session_state.pop("_lu_msg", None)
    if _msg:
        (st.success if _msg[0] == "ok" else st.error)(_msg[1])

    # ── Captain / vice ────────────────────────────────────────────────────────
    _cap_names = [_info[i]["name"] for i in _lu["starters"]]
    p1, p2 = st.columns(2)
    with p1:
        _cs = st.selectbox("Captain (2×)", _cap_names,
                           index=_cap_names.index(_info[_lu["captain"]]["name"]) if _lu["captain"] in _lu["starters"] else 0,
                           key="lu_cap")
        _lu["captain"] = _n2id[_cs]
    with p2:
        _vs = st.selectbox("Vice-captain", _cap_names,
                           index=_cap_names.index(_info[_lu["vice"]]["name"]) if _lu["vice"] in _lu["starters"] else 0,
                           key="lu_vice")
        _lu["vice"] = _n2id[_vs]
    st.session_state.lineup = _lu

    # ── Projected-points feedback ─────────────────────────────────────────────
    def _xp(starters, cap):
        return sum(_info[i]["ep"] for i in starters) + (_info[cap]["ep"] if cap in _info else 0)

    _cur, _orig = _xp(_lu["starters"], _lu["captain"]), _xp(_orig_starters, _orig_captain)
    _delta = _cur - _orig
    _c = _cnt(_lu["starters"])
    _formation = f"{_c.get('DEF',0)}-{_c.get('MID',0)}-{_c.get('FWD',0)}"
    _dcol = "#00FF87" if _delta > 0.05 else "#FF4B4B" if _delta < -0.05 else "rgba(255,255,255,0.6)"
    _tiles = [
        ("Formation", _formation, "GKP · DEF · MID · FWD", "#04f5ff"),
        ("Projected XI", f"{_cur:.1f} xP", "captain doubled", "#00FF87"),
        ("Vs your saved XI", f"{'+' if _delta >= 0 else ''}{_delta:.1f} xP",
         "improvement" if _delta > 0.05 else "worse" if _delta < -0.05 else "no change", _dcol),
    ]
    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 4px;">' + "".join(
            f'<div style="flex:1;min-width:150px;background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);'
            f'border-radius:12px;padding:14px 16px;font-family:\'Inter\',sans-serif;">'
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.12em;color:rgba(255,255,255,0.5);text-transform:uppercase;">{lab}</div>'
            f'<div style="font-size:24px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
            f'<div style="font-size:11px;color:rgba(255,255,255,0.45);">{sub}</div></div>'
            for lab, val, sub, acc in _tiles
        ) + "</div>",
        unsafe_allow_html=True,
    )

    # ── XI + bench display ────────────────────────────────────────────────────
    def _pill(i, bench=False):
        d = _info[i]
        tag = ""
        if i == _lu["captain"]:
            tag = '<span style="color:#FFD700;font-weight:900;">Ⓒ</span> '
        elif i == _lu["vice"]:
            tag = '<span style="color:#bbb;font-weight:900;">Ⓥ</span> '
        flag = "" if d["status"] == "a" else " 🚑"
        op = "0.6" if bench else "1"
        return (f'<div style="display:inline-flex;align-items:center;gap:7px;background:rgba(22,26,34,0.85);'
                f'border:1px solid rgba(255,255,255,0.08);border-radius:9px;padding:6px 10px;margin:3px;opacity:{op};">'
                f'{team_dot(d["short"], size=11)}<span style="font-size:12px;font-weight:700;color:#fff;">{tag}{d["name"]}{flag}</span>'
                f'<span style="font-size:11px;font-weight:800;color:#00FF87;">{d["ep"]:.1f}</span></div>')

    for _pos in ["GKP", "DEF", "MID", "FWD"]:
        _row = [i for i in _lu["starters"] if _info[i]["pos"] == _pos]
        if _row:
            st.markdown(
                f'<div style="margin:2px 0;"><span style="display:inline-block;background:{POS_COLORS.get(_pos, "#888")};'
                f'color:#000;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:900;margin-right:6px;">{_pos}</span>'
                + "".join(_pill(i) for i in _row) + "</div>",
                unsafe_allow_html=True,
            )
    st.markdown(
        '<div style="margin:8px 0 2px;"><span style="display:inline-block;background:rgba(255,255,255,0.12);'
        'color:#fff;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:900;margin-right:6px;">BENCH</span>'
        + "".join(_pill(i, bench=True) for i in _lu["bench"]) + "</div>",
        unsafe_allow_html=True,
    )

    if st.button("↺ Reset to saved XI", key="lu_reset"):
        st.session_state.pop("lineup", None)
        st.rerun()

with tab_pitch:
    # Ensure squad has team_code (redundant safety after fetcher fix)
    if "team_code" not in squad_df.columns:
        if "team_code" in players_df_all.columns:
            squad_df = squad_df.merge(
                players_df_all[["fpl_id", "team_code"]], on="fpl_id", how="left",
            )
        else:
            squad_df["team_code"] = 1

    # Merge enrichment (ep_next, fixtures, markers) for the pitch cards
    _pitch_cols = ["fpl_id"]
    for _c in ("ep_next", "upcoming_fixtures", "team_short",
               "penalties_order", "defcon_monster_score"):
        if _c in players_df_all.columns and _c not in squad_df.columns:
            _pitch_cols.append(_c)
    if len(_pitch_cols) > 1:
        squad_df = squad_df.merge(players_df_all[_pitch_cols], on="fpl_id", how="left")

    if "upcoming_fixtures" in squad_df.columns:
        squad_df["upcoming_fixtures"] = squad_df["upcoming_fixtures"].apply(_attach_short)

    from components.pitch_view import render_pitch_view, render_squad_pitch
    from components.loading import LINES_SQUAD, fpl_loader
    from analytics import squad_planner as planner
    from config import SIM_HORIZON

    # ── Deep link (?gw=41 jumps the scrubber) ────────────────────────────────
    _qp = st.query_params
    if "gw" in _qp:
        try:
            st.session_state.pitch_gw = int(_qp["gw"])
        except (TypeError, ValueError):
            pass
        del _qp["gw"]

    @st.dialog("Player intel", width="large")
    def _player_dialog(pid: int, plan_gw: Optional[int] = None) -> None:
        from ui.player_detail import render_player_detail
        render_player_detail(pid, players_df_all, key_prefix="dlg")
        if plan_gw:
            _nm = players_df_all.loc[players_df_all["fpl_id"] == int(pid), "web_name"]
            _nm = str(_nm.iloc[0]) if not _nm.empty else "him"
            if st.button(f"⭐ Captain {_nm} for GW{plan_gw}", key=f"dlg_cap_{pid}",
                         type="primary", use_container_width=True):
                _drafts = planner.load_drafts(int(team_id))
                _e = dict(_drafts[plan_gw]) if plan_gw in _drafts else                     dict(planner.normalize_entry(
                        planner.load_plans(int(team_id)).get(plan_gw, [])))
                _e["captain"] = int(pid)
                planner.save_draft(int(team_id), plan_gw, _e)
                st.toast(f"Captained · {_nm} for GW{plan_gw}")
                st.rerun()

    # ── Timeline scrubber · history ↔ current ↔ future plan ─────────────────
    # Scrub back through played gameweeks (actual points, to GW1), sit on the
    # current one (pick team), or scrub FORWARD into planning weeks: transfer
    # players on the pitch itself, save the plan, bank free transfers.
    _events = {int(e["id"]): e for e in bs.get("events", [])}
    _cur = int(current_gw) if current_gw else 1
    _sim_on = bool(st.session_state.get("simulating_gw"))
    _plan_first = _cur + 1
    _plan_last = (_cur + SIM_HORIZON) if _sim_on else min(38, _cur + SIM_HORIZON)
    _max_gw = max(_cur, _plan_last)
    if "pitch_gw" not in st.session_state:
        st.session_state.pitch_gw = _cur
    st.session_state.pitch_gw = max(1, min(_max_gw, int(st.session_state.pitch_gw)))

    def _nudge_gw(delta: int) -> None:
        st.session_state.pitch_gw = max(1, min(_max_gw, int(st.session_state.pitch_gw) + delta))

    _cprev, _cmid, _cnext = st.columns([1.1, 3, 1.1])
    with _cprev:
        st.button("◀ Prev GW", key="pitch_prev", on_click=_nudge_gw, args=(-1,),
                  disabled=st.session_state.pitch_gw <= 1, use_container_width=True)
    with _cnext:
        st.button("Next GW ▶", key="pitch_next", on_click=_nudge_gw, args=(1,),
                  disabled=st.session_state.pitch_gw >= _max_gw, use_container_width=True)
    with _cmid:
        if _max_gw > 1:
            st.slider("Gameweek", 1, _max_gw, key="pitch_gw", label_visibility="collapsed")
    view_gw = int(st.session_state.pitch_gw)

    _finished = bool(_events.get(view_gw, {}).get("finished", False))
    _is_upcoming = (view_gw == _cur) and not _finished

    if view_gw > _cur:
        # The planner reruns as a FRAGMENT · axe/sign/chip clicks re-execute
        # only this block (fast), not the whole page. st.rerun inside uses
        # scope="fragment"; dialogs keep app-scope reruns.
        @st.fragment
        def _planner_fragment() -> None:
            # ══ PLANNER · a future gameweek, transfers made on the pitch ═════════
            # Working moves (pending) live on DISK as a draft, because ✕/kit taps
            # reload the page and would wipe session state.
            plans = planner.load_plans(int(team_id))
            drafts = planner.load_drafts(int(team_id))
            entry = dict(drafts[view_gw]) if view_gw in drafts \
                else dict(planner.normalize_entry(plans.get(view_gw, [])))
            pending = list(entry.get("transfers", []))
            chip = entry.get("chip")

            # Squad after every EARLIER saved week, then this week's pending moves.
            prev_plans = {g: t for g, t in plans.items() if g < view_gw}
            eff_base = planner.effective_squad(
                squad_df, players_df_all, prev_plans,
                up_to_gw=view_gw - 1, first_gw=_plan_first)
            eff_now = planner.effective_squad(
                eff_base, players_df_all, {view_gw: entry},
                up_to_gw=view_gw, first_gw=view_gw)
            if "upcoming_fixtures" in eff_now.columns:
                eff_now["upcoming_fixtures"] = eff_now["upcoming_fixtures"].apply(_attach_short)
            _in_ids = {int(t["in_id"]) for t in pending}
            eff_now["_is_new"] = eff_now["fpl_id"].astype(int).isin(_in_ids)

            # Per-GW xP from the shared engine · the pitch shows THIS week's
            # projection, not FPL's generic next-GW estimate.
            _hz = _xp_horizon()
            _xp_gw_map = {}
            if _hz is not None:
                from analytics.xp_engine import xp_for_gw
                _xp_gw_map = xp_for_gw(_hz[0], view_gw)
                if _xp_gw_map:
                    eff_now["ep_next"] = eff_now["fpl_id"].astype(int).map(
                        _xp_gw_map).fillna(eff_now.get("ep_next"))

            # Transfer economy for THIS week
            fts   = planner.free_transfers_for(prev_plans, view_gw, _plan_first)
            used  = len(pending)
            cost  = planner.hit_cost(used, fts, chip=chip)

            # What the moves actually buy: xP in minus xP out, net of the hit.
            # Uses THIS week's projection when the engine has one.
            if _xp_gw_map:
                _xp_by_id = _xp_gw_map
            else:
                _xp_by_id = dict(zip(players_df_all["fpl_id"].astype(int),
                                     pd.to_numeric(players_df_all.get("ep_next"),
                                                   errors="coerce").fillna(0.0)))
            xp_swing = sum(_xp_by_id.get(int(t["in_id"]), 0.0)
                           - _xp_by_id.get(int(t["out_id"]), 0.0) for t in pending)
            net_gain = xp_swing - cost
            bank_now = planner.bank_after(bank_m, prev_plans, view_gw - 1, _plan_first,
                                          extra_pending=pending)
            _saved = planner.normalize_entry(plans.get(view_gw, [])) == \
                planner.normalize_entry(entry)

            # Squad xP this week · XI + captain extra (TC ×3, BB adds the bench)
            _ids = eff_now["fpl_id"].astype(int)
            if _xp_gw_map:
                _xpv = _ids.map(_xp_gw_map).fillna(0.0)
            else:
                _xpv = pd.to_numeric(eff_now.get("ep_next"), errors="coerce").fillna(0.0)
            _xi = ~eff_now["on_bench"].astype(bool)
            squad_xp = float(_xpv[_xi].sum())
            _cap_xp = float(_xpv[_xi & eff_now["is_captain"].astype(bool)].sum())
            squad_xp += _cap_xp * (2.0 if chip == "TC" else 1.0)
            if chip == "BB":
                squad_xp += float(_xpv[~_xi].sum())

            # ── ✨ Optimise · write a suggested 5-week plan into the drafts ──────
            @st.dialog("Suggested plan", width="large")
            def _plan_summary_dialog(notes, plan_map, summary, first_gw_, horizon_):
                st.markdown(
                    f'<div style="text-align:center;padding:4px 0 10px;">'
                    f'<span style="font-family:\'Archivo\',sans-serif;font-size:26px;'
                    f'font-weight:900;color:#00FF87;">+{summary["net"]:.1f} xP</span>'
                    f'<span style="font-size:12px;color:rgba(255,255,255,0.55);"> net over '
                    f'{horizon_} weeks · {summary["hits"]} hit{"s" if summary["hits"] != 1 else ""}'
                    f'</span></div>', unsafe_allow_html=True)
                for n in notes:
                    st.markdown(
                        f'<div style="background:rgba(255,255,255,0.03);border:1px solid '
                        f'rgba(255,255,255,0.08);border-left:3px solid #FFD700;border-radius:8px;'
                        f'padding:8px 12px;margin-bottom:5px;font-size:13px;color:'
                        f'rgba(255,255,255,0.85);">{n}</div>', unsafe_allow_html=True)
                st.caption("Written to the timeline as drafts · scrub through the weeks to "
                           "review, tweak any move, then save week by week. Or:")
                if st.button("💾 Save the entire plan", type="primary",
                             use_container_width=True, key="opt_save_all"):
                    for g in range(first_gw_, first_gw_ + horizon_):
                        planner.save_plan(int(team_id), g, plan_map.get(g, []))
                        planner.clear_draft(int(team_id), g)
                    st.toast("Saved · the full suggested plan")
                    st.rerun()

            _oc1, _oc2 = st.columns([1.6, 1])
            with _oc1:
                if st.button("✨ Optimise my next 5 weeks", key="optimise_plan",
                             use_container_width=True,
                             help="Suggests the best transfer path over the horizon: "
                                  "like-for-like swaps ranked by projected points, "
                                  "respecting budget, club limits, free-transfer "
                                  "banking and the -4 hit rule."):
                    _hz_opt = _xp_horizon()
                    if _hz_opt is None:
                        st.warning("Projections unavailable right now.")
                    else:
                        from analytics.plan_optimizer import suggest_plan
                        _hdf, _hfirst, _hn = _hz_opt
                        _base = squad_df.copy()
                        if "team_id" not in _base.columns:
                            _base = _base.merge(players_df_all[["fpl_id", "team_id"]],
                                                on="fpl_id", how="left")
                        with fpl_loader("Optimising your next 5 weeks", LINES_SOLVER):
                            _plan_map, _notes, _sumry = suggest_plan(
                                _base, players_df_all, _hdf, _hfirst, _hn, bank_m)
                        for g in range(_hfirst, _hfirst + _hn):
                            planner.save_draft(int(team_id), g, _plan_map.get(g, []))
                        _plan_summary_dialog(_notes, _plan_map, _sumry, _hfirst, _hn)
            with _oc2:
                if st.button("🧹 Discard all drafts", key="optimise_clear",
                             use_container_width=True,
                             help="Drops every unsaved draft week · saved plans stay."):
                    for g in range(_plan_first, _plan_last + 1):
                        planner.clear_draft(int(team_id), g)
                    st.rerun(scope="fragment")

            # ── Chip for this week (each chip once across the plan) ─────────────
            _chip_labels = {None: "No chip", "BB": "Bench Boost", "TC": "Triple Captain",
                            "WC": "Wildcard", "FH": "Free Hit"}
            _used_elsewhere = set()
            for _g in range(_plan_first, _plan_last + 1):
                if _g == view_gw:
                    continue
                _src = drafts.get(_g) or plans.get(_g)
                if _src and planner.normalize_entry(_src).get("chip"):
                    _used_elsewhere.add(planner.normalize_entry(_src)["chip"])
            _chip_opts = [c for c in (None, "BB", "TC", "WC", "FH")
                          if c == chip or c not in _used_elsewhere]
            _cc1, _cc2 = st.columns([1, 2.2])
            with _cc1:
                _chip_pick = st.selectbox(
                    "Chip this week", _chip_opts,
                    index=_chip_opts.index(chip) if chip in _chip_opts else 0,
                    format_func=lambda c: _chip_labels[c],
                    key=f"chip_pick_{view_gw}",
                    help="Bench Boost counts your bench; Triple Captain triples the "
                         "armband; Wildcard and Free Hit make every move free · a "
                         "Free Hit squad reverts the following week.")
            if _chip_pick != chip:
                entry["chip"] = _chip_pick
                planner.save_draft(int(team_id), view_gw, entry)
                st.rerun(scope="fragment")

            _hit_html = (
                f'<div style="background:#FF4B4B;color:#fff;border-radius:8px;padding:6px 14px;'
                f'font-weight:900;font-size:15px;font-family:\'Archivo\',sans-serif;'
                f'box-shadow:0 0 18px rgba(255,75,75,0.45);">−{cost} pts hit</div>'
            ) if cost > 0 else ""
            _save_dot = ("#00FF87" if _saved else "#FFA500")
            _save_txt = ("Saved" if _saved else "Unsaved changes")

            def _chipbox(label, value, color="#fff"):
                return (f'<div style="text-align:center;padding:6px 14px;">'
                        f'<div style="font-size:18px;font-weight:900;color:{color};'
                        f'font-family:\'Archivo\',sans-serif;">{value}</div>'
                        f'<div style="font-size:9px;letter-spacing:0.14em;color:rgba(255,255,255,0.5);'
                        f'text-transform:uppercase;font-weight:800;">{label}</div></div>')

            st.markdown(
                f'<div class="fplh-animate-in" style="display:flex;align-items:center;gap:8px;'
                f'flex-wrap:wrap;justify-content:space-between;margin:4px 0 10px;padding:8px 14px;'
                f'background:linear-gradient(135deg,rgba(255,215,0,0.07),rgba(0,0,0,0.35));'
                f'border:1px solid rgba(255,215,0,0.30);border-radius:12px;">'
                f'<div style="display:flex;align-items:center;gap:10px;">'
                f'<span style="background:#FFD700;color:#000;border-radius:6px;padding:3px 10px;'
                f'font-size:11px;font-weight:900;letter-spacing:0.08em;">PLANNING · GW{view_gw}</span>'
                + (f'<span style="background:#c084fc;color:#000;border-radius:6px;padding:3px 10px;'
                   f'font-size:11px;font-weight:900;letter-spacing:0.08em;">'
                   + {"BB": "BENCH BOOST", "TC": "TRIPLE CAPTAIN", "WC": "WILDCARD",
                      "FH": "FREE HIT"}.get(chip, "")
                   + '</span>' if chip else "")
                + f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;'
                f'color:rgba(255,255,255,0.6);"><span style="width:7px;height:7px;border-radius:50%;'
                f'background:{_save_dot};"></span>{_save_txt}</span></div>'
                f'<div style="display:flex;align-items:center;gap:2px;">'
                + _chipbox("Transfers", used, "#fff")
                + _chipbox("Free", "∞" if chip in ("WC", "FH") else fts, "#00FF87")
                + _chipbox("Bank", f"£{bank_now:.1f}m", "#04f5ff")
                + _chipbox("Squad xP", f"{squad_xp:.0f}", "#FFD700")
                + (_chipbox("Net xP", f"{net_gain:+.1f}",
                            "#00FF87" if net_gain >= 0 else "#FF4B4B") if used else "")
                + f'{_hit_html}</div></div>',
                unsafe_allow_html=True,
            )

            _axes = st.session_state.get("plan_axes", [])
            # Drop queue entries that no longer exist in the squad (already signed)
            _sq_ids = set(eff_now["fpl_id"].astype(int).tolist())
            _axes = [a for a in _axes if int(a["id"]) in _sq_ids]
            st.session_state.plan_axes = _axes
            eff_now["_is_axed"] = eff_now["fpl_id"].astype(int).isin(
                {int(a["id"]) for a in _axes})

            if _axes:
                _pcol, _rcol = st.columns([1.35, 1], gap="large")
            else:
                _pcol = st.container()
            with _pcol:
                _click = render_pitch_view(eff_now, interactive=True, fixture_gw=view_gw,
                                           title_right=f"GW{view_gw} plan")

            # Handle a FRESH pitch click (the component re-reports its last value
            # every rerun · the nonce dedupes).
            if _click and _click.get("nonce") != st.session_state.get("_pitch_nonce"):
                st.session_state._pitch_nonce = _click.get("nonce")
                _cid = int(_click.get("id", 0) or 0)
                if _click.get("action") == "detail" and _cid:
                    _player_dialog(_cid, plan_gw=view_gw)
                elif _click.get("action") == "axe" and _cid:
                    if _cid in _in_ids:
                        # Axing a player you just signed = undo that move.
                        entry["transfers"] = [
                            t for t in pending if int(t["in_id"]) != _cid]
                        planner.save_draft(int(team_id), view_gw, entry)
                        st.rerun(scope="fragment")
                    if _cid in {int(a["id"]) for a in _axes}:
                        # ✕ on an already-queued player = keep him after all
                        st.session_state.plan_axes = [
                            a for a in _axes if int(a["id"]) != _cid]
                        st.rerun(scope="fragment")
                    _row = eff_now[eff_now["fpl_id"].astype(int) == _cid]
                    if not _row.empty:
                        _r = _row.iloc[0]
                        _axes.append({
                            "id": _cid, "name": str(_r["web_name"]),
                            "pos": str(_r["position"]), "price": float(_r["price"]),
                        })
                        st.session_state.plan_axes = _axes
                        st.rerun(scope="fragment")
            if _axes:
                with _rcol:
                    # Which axed slot are we filling? (✕ as many as you like ·
                    # the pooled budget assumes every queued player is sold)
                    if len(_axes) > 1:
                        _sel_name = st.radio(
                            "Replacing", [a["name"] for a in _axes],
                            horizontal=True, key=f"axe_pick_{view_gw}",
                            label_visibility="collapsed")
                        _swap = next(a for a in _axes if a["name"] == _sel_name)
                    else:
                        _swap = _axes[0]
                    _budget = bank_now + sum(float(a["price"]) for a in _axes)
                    _owned = set(eff_now["fpl_id"].astype(int).tolist())
                    _action, _pick = _replacement_panel(
                        _swap["name"], _swap["pos"], float(_swap["price"]),
                        _budget, _owned, key_prefix=f"plan{view_gw}",
                        out_id=int(_swap["id"]), xp_map=_xp_gw_map or None)
                    if _action == "compare" and _pick is not None:
                        _h2h_dialog(int(_swap["id"]), int(_pick["fpl_id"]))
                    elif _action == "sign" and _pick is not None:
                        pending.append({
                            "out_id":    int(_swap["id"]),
                            "out_name":  _swap["name"],
                            "in_id":     int(_pick["fpl_id"]),
                            "in_name":   str(_pick["web_name"]),
                            "position":  _swap["pos"],
                            "price_out": float(_swap["price"]),
                            "price_in":  float(_pick["price"]),
                        })
                        entry["transfers"] = pending
                        planner.save_draft(int(team_id), view_gw, entry)
                        st.session_state.plan_axes = [
                            a for a in _axes if int(a["id"]) != int(_swap["id"])]
                        # No scribble overlay here: the planner needs st.rerun(scope="fragment") so
                        # the pitch above refreshes, and overlay + rerun race (rule 5).
                        st.rerun(scope="fragment")
                    elif _action == "cancel":
                        st.session_state.plan_axes = [
                            a for a in _axes if int(a["id"]) != int(_swap["id"])]
                        st.rerun(scope="fragment")

            # This week's moves + save controls
            if pending:
                st.markdown(
                    "<div style='margin-top:12px;font-size:13px;font-weight:800;color:#fff;'>"
                    f"GW{view_gw} moves</div>", unsafe_allow_html=True)
                for _i, _t in enumerate(pending):
                    _c1, _c2 = st.columns([10, 1])
                    with _c1:
                        st.markdown(
                            f"<div style='background:rgba(255,255,255,0.03);border:1px solid "
                            f"rgba(255,255,255,0.08);border-left:3px solid #00FF87;border-radius:8px;"
                            f"padding:8px 12px;margin-bottom:5px;'>"
                            f"<span style='color:rgba(255,255,255,0.45);text-decoration:line-through;'>"
                            f"{_t['out_name']}</span>"
                            f"<span style='color:rgba(255,255,255,0.5);margin:0 8px;'>→</span>"
                            f"<span style='color:#00FF87;font-weight:800;'>{_t['in_name']}</span>"
                            f"<span style='font-size:11px;color:rgba(255,255,255,0.4);margin-left:8px;'>"
                            f"£{_t['price_out']:.1f}m → £{_t['price_in']:.1f}m</span></div>",
                            unsafe_allow_html=True)
                    with _c2:
                        if st.button("↩", key=f"plan_undo_{view_gw}_{_i}", help="Undo this move"):
                            pending.pop(_i)
                            entry["transfers"] = pending
                            planner.save_draft(int(team_id), view_gw, entry)
                            st.rerun(scope="fragment")

            _b1, _b2, _b3 = st.columns([1.4, 1, 1])
            with _b1:
                if st.button(f"💾 Save GW{view_gw} plan", key=f"plan_save_{view_gw}",
                             type="primary", disabled=_saved, use_container_width=True):
                    planner.save_plan(int(team_id), view_gw, entry)
                    planner.clear_draft(int(team_id), view_gw)
                    st.toast(f"Saved · GW{view_gw} plan ({used} transfer{'s' if used != 1 else ''})")
                    st.rerun(scope="fragment")
            with _b2:
                if st.button("Reset to saved", key=f"plan_reset_{view_gw}",
                             disabled=_saved, use_container_width=True):
                    planner.clear_draft(int(team_id), view_gw)
                    st.rerun(scope="fragment")
            with _b3:
                if st.button("Clear this week", key=f"plan_clear_{view_gw}",
                             disabled=not (pending or chip or entry.get("captain")
                                           or plans.get(view_gw)),
                             use_container_width=True):
                    planner.save_plan(int(team_id), view_gw, [])
                    planner.clear_draft(int(team_id), view_gw)
                    st.rerun(scope="fragment")


        _planner_fragment()
    elif _is_upcoming:
        st.markdown(_mode_pill(f"Upcoming · GW{view_gw}", "your pick team · projected xP & fixtures",
                               "#04f5ff"), unsafe_allow_html=True)
        render_pitch_view(squad_df)
    else:
        try:
            with fpl_loader(f"Rewinding to GW{view_gw}", LINES_SQUAD):
                _hdf, _hist = _hist_squad(int(team_id), view_gw)
                _pts = _gw_points_map(view_gw)
            _tshort = {int(t["id"]): t["short_name"] for t in bs.get("teams", [])}
            _players = []
            for _, r in _hdf.iterrows():
                _players.append({
                    "web_name":   r["web_name"],
                    "position":   r["position"],
                    "team_code":  int(r.get("team_code", 1) or 1),
                    "team_short": _tshort.get(int(r.get("team_id", 0) or 0), "?"),
                    "on_bench":   bool(r["on_bench"]),
                    "is_captain": bool(r.get("is_captain", False)),
                    "stat":       _pts.get(int(r["fpl_id"]), 0),
                })
            _gwtot = (_hist or {}).get("points")
            _sub = f"{_gwtot} pts scored" if _gwtot is not None else "actual points"
            st.markdown(_mode_pill(f"Actual · GW{view_gw}", _sub, "#00FF87"),
                        unsafe_allow_html=True)
            render_squad_pitch(_players, stat_label="pts", title_right=f"Gameweek {view_gw}")
            if view_gw != _max_gw:
                st.caption("Viewing history · the transfer tools below act on your current team.")
        except Exception:  # noqa: BLE001 · history unavailable → fall back to the live pitch
            st.info(f"Couldn't load GW{view_gw} history right now · showing your current team.")
            render_pitch_view(squad_df)

    # ── Player deep-dive (ℹ️) ─────────────────────────────────────────────────
    st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
    with st.expander("🔍 Player deep-dive · why a player is (or isn't) delivering"):
        _sq = squad_df.copy()
        _sq["fpl_id"] = _sq["fpl_id"].astype(int)
        _name_by_id = dict(zip(_sq["fpl_id"], _sq["web_name"]))
        _opt_ids = _sq["fpl_id"].tolist()
        _cap_ids = _sq[_sq["is_captain"] == True]["fpl_id"].tolist()  # noqa: E712
        _default_id = _cap_ids[0] if _cap_ids else (_opt_ids[0] if _opt_ids else None)
        if _default_id is not None:
            _sel_id = st.selectbox(
                "Inspect a player", _opt_ids, index=_opt_ids.index(_default_id),
                format_func=lambda i: _name_by_id.get(i, str(i)), key="deepdive_player",
            )
            from ui.player_detail import render_player_detail
            render_player_detail(int(_sel_id), players_df_all, key_prefix="mt")

    # ── Edit Squad mode ───────────────────────────────────────────────────────
    st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)
    edit_mode = st.toggle(
        "🔁 Pick Team / Transfers · tap a player to replace them",
        value=False,
        key="my_team_edit_mode",
        help="Tap any player to axe them, then browse the full list of replacements "
             "(search + sort by form, fixtures, xP, value or price) and sign one in.",
    )

    if edit_mode:
        from components.team_identity import team_color as _team_color
        st.markdown(
            """<style>
            div[data-testid="stButton"] > button[kind="secondary"] {
                font-size: 11px !important;
                padding: 2px 8px !important;
                min-height: 26px !important;
                width: 100%;
            }
            </style>""",
            unsafe_allow_html=True,
        )

        # Two-column workbench: axe grid (in formation) on the left, the live
        # replacement table on the right · opens the moment you tap ✕ on a player.
        _axe_col, _repl_col = st.columns([1.15, 1], gap="large")

        with _axe_col:
            def _axe_row(players_iter) -> None:
                players_list = list(players_iter)
                if not players_list:
                    return
                cols = st.columns(len(players_list))
                for col, (_, p) in zip(cols, players_list):
                    with col:
                        if st.button(f"✕ {p['web_name'][:9]}", key=f"axe_{int(p['fpl_id'])}",
                                     use_container_width=True):
                            st.session_state.swap_out_fpl_id = int(p["fpl_id"])
                            st.session_state.swap_out_name = str(p["web_name"])
                            st.session_state.swap_out_position = str(p["position"])
                            st.session_state.swap_out_price = float(p["price"])

            xi_sorted    = squad_df[~squad_df["on_bench"]].sort_values("squad_position")
            bench_sorted = squad_df[squad_df["on_bench"]].sort_values("squad_position")
            _by_pos = {pos: [(i, r) for i, r in xi_sorted.iterrows() if r["position"] == pos]
                       for pos in ("GKP", "DEF", "MID", "FWD")}

            st.markdown(
                "<div style='margin:2px 0 6px;font-size:13px;color:rgba(255,255,255,0.5);"
                "letter-spacing:0.12em;text-transform:uppercase;font-weight:700;'>"
                "Tap ✕ to axe a player</div>",
                unsafe_allow_html=True,
            )
            _axe_row(_by_pos["GKP"]); _axe_row(_by_pos["DEF"])
            _axe_row(_by_pos["MID"]); _axe_row(_by_pos["FWD"])
            st.markdown(
                "<div style='margin:10px 0 6px;font-size:12px;color:rgba(255,255,255,0.4);"
                "letter-spacing:0.12em;text-transform:uppercase;font-weight:700;'>Bench</div>",
                unsafe_allow_html=True,
            )
            _axe_row(list(bench_sorted.iterrows()))

        with _repl_col:
            swap_out_id = st.session_state.get("swap_out_fpl_id")
            if not swap_out_id:
                st.markdown(
                    "<div class='ff-glass' style='padding:24px 20px;text-align:center;'>"
                    "<div style='font-size:30px;'>🔁</div>"
                    "<div style='font-family:\"Archivo\",sans-serif;font-size:15px;font-weight:800;"
                    "color:#fff;margin-top:6px;'>Replacements appear here</div>"
                    "<div style='font-size:12px;color:rgba(255,255,255,0.5);margin-top:4px;'>"
                    "Tap ✕ on any player to browse who you can sign in · filter by club, "
                    "position and sort by points, xG, form or value.</div></div>",
                    unsafe_allow_html=True,
                )
            else:
                out_name = st.session_state.get("swap_out_name", "?")
                out_pos  = st.session_state.get("swap_out_position", "MID")
                out_price = float(st.session_state.get("swap_out_price", 0.0))
                avail_budget = bank_m + budget_boost + out_price
                owned_ids = set(squad_df["fpl_id"].tolist())

                _action, _pick = _replacement_panel(
                    out_name, out_pos, out_price, avail_budget, owned_ids,
                    key_prefix="repl", out_id=int(swap_out_id))
                if _action == "compare" and _pick is not None:
                    _h2h_dialog(int(swap_out_id), int(_pick["fpl_id"]))
                elif _action == "sign" and _pick is not None:
                    pending = st.session_state.get("pending_swaps", [])
                    pending.append({
                        "out_id":    int(swap_out_id),
                        "out_name":  out_name,
                        "in_id":     int(_pick["fpl_id"]),
                        "in_name":   str(_pick["web_name"]),
                        "position":  out_pos,
                        "price_out": out_price,
                        "price_in":  float(_pick["price"]),
                    })
                    st.session_state.pending_swaps = pending
                    st.session_state._swap_anim = {"out": out_name, "in": str(_pick["web_name"])}
                    for k in ("swap_out_fpl_id", "swap_out_name",
                              "swap_out_position", "swap_out_price"):
                        st.session_state.pop(k, None)
                elif _action == "cancel":
                    for k in ("swap_out_fpl_id", "swap_out_name",
                              "swap_out_position", "swap_out_price"):
                        st.session_state.pop(k, None)

    # ── Pending swaps ─────────────────────────────────────────────────────────
    pending_swaps = st.session_state.get("pending_swaps", [])
    if pending_swaps:
        st.markdown(
            "<div style='margin-top:18px;font-size:14px;font-weight:800;color:#fff;'>"
            "📝 Pending Swaps (not yet applied to FPL)</div>",
            unsafe_allow_html=True,
        )
        for i, swap in enumerate(pending_swaps):
            cols = st.columns([10, 1])
            delta = swap["price_out"] - swap["price_in"]
            delta_str = f"+£{delta:.2f}m bank" if delta > 0 else (
                f"−£{abs(delta):.2f}m bank" if delta < 0 else "level on price"
            )
            with cols[0]:
                st.markdown(
                    f"""<div class="fplh-animate-in" style="
                        background:rgba(255,255,255,0.03);
                        border:1px solid rgba(255,255,255,0.08);
                        border-left:3px solid #00FF87;
                        border-radius:8px;padding:10px 14px;margin-bottom:6px;
                    ">
                      <span style="color:rgba(255,255,255,0.45);text-decoration:line-through;">
                       {swap['out_name']}</span>
                      <span style="color:rgba(255,255,255,0.5);margin:0 10px;">→</span>
                      <span style="color:#00FF87;font-weight:800;">{swap['in_name']}</span>
                      <span style="font-size:11px;color:rgba(255,255,255,0.4);margin-left:10px;">
                       {swap['position']} · {delta_str}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with cols[1]:
                if st.button("↩", key=f"undo_swap_{i}", help="Undo this swap"):
                    st.session_state.pending_swaps.pop(i)

        if st.button("Clear all pending swaps", key="clear_all_swaps"):
            st.session_state.pending_swaps = []


with tab_table:
    def _squad_table(df: pd.DataFrame) -> None:
        display = df[[
            "web_name", "team", "position", "price",
            "form", "total_points", "ownership",
            "is_captain", "is_vice_captain", "status",
        ]].copy()
        display["Role"] = ""
        display.loc[display["is_captain"],      "Role"] = "©"
        display.loc[display["is_vice_captain"], "Role"] = "VC"
        display = display.drop(columns=["is_captain", "is_vice_captain"])
        display = display.rename(columns={
            "web_name": "Player", "team": "Team", "position": "Pos",
            "price": "Price", "form": "Form", "total_points": "Season Pts",
            "ownership": "Own%", "status": "Fit",
        })
        display["Fit"] = display["Fit"].map(
            {"a": "✅", "d": "⚠️", "i": "🚑", "s": "🚫", "u": "❓"}
        ).fillna("?")
        display["Price"] = display["Price"].apply(lambda x: f"£{x:.2f}m")
        display["Own%"]  = display["Own%"].apply(lambda x: f"{x:.1f}%")
        display["Form"]  = display["Form"].apply(lambda x: f"{x:.2f}")
        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "Role": st.column_config.TextColumn(width="small"),
                "Fit":  st.column_config.TextColumn(width="small"),
            },
        )

    xi_col, bench_col = st.columns([3, 1])
    with xi_col:
        st.markdown("**Starting XI**")
        _squad_table(xi)
    with bench_col:
        st.markdown("**Bench**")
        _squad_table(bench)


# ── SEASON TREND ──────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin:30px 0 12px;display:flex;align-items:center;gap:14px;">'
    '<div style="font-size:11px;letter-spacing:0.22em;color:rgba(255,255,255,0.55);'
    'text-transform:uppercase;font-weight:800;">Season Trend</div>'
    '<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div>'
    '</div>',
    unsafe_allow_html=True,
)

try:
    history    = _load_history(team_id)
    gw_history = history.get("current", [])

    if gw_history:
        hist_df = pd.DataFrame(gw_history)
        hist_df["net_points"] = hist_df["points"] - hist_df["event_transfers_cost"]
        season_avg = float(hist_df["net_points"].mean())

        # Summary strip (cleaner than 4-up st.metric)
        best_row  = hist_df.loc[hist_df["net_points"].idxmax()]
        worst_row = hist_df.loc[hist_df["net_points"].idxmin()]
        total_hits = int(hist_df["event_transfers_cost"].sum())
        total_bench = int(hist_df["points_on_bench"].sum()) if "points_on_bench" in hist_df.columns else 0

        summary_html = (
            _hero_stat("Best GW", f"{count_up(best_row['net_points'])} pts", "#00FF87",
                       f"GW{int(best_row['event'])}")
            + _hero_stat("Worst GW", f"{count_up(worst_row['net_points'])} pts", "#FF4B4B",
                         f"GW{int(worst_row['event'])}")
            + _hero_stat("Season Avg", f"{count_up(season_avg, 1)} pts", "#fff",
                         f"over {len(hist_df)} GWs")
            + _hero_stat("Bench Loss", f"{count_up(total_bench)} pts", "#FFA500",
                         f"Total hits: −{total_hits}")
        )
        st.markdown(
            f'<div class="fplh-animate-in" style="display:flex;gap:10px;margin-bottom:16px;'
            f'flex-wrap:wrap;">{summary_html}</div>',
            unsafe_allow_html=True,
        )

        opt = charts.bar_option(
            x=list(hist_df["event"]),
            y=[int(p) for p in hist_df["net_points"]],
            colors=["#00FF87" if p >= season_avg else "#FF4B4B"
                    for p in hist_df["net_points"]],
        )
        opt["tooltip"]["formatter"] = "GW{b}: {c} pts"
        charts.render(with_mark_line(opt, season_avg, f"Avg: {season_avg:.1f}"),
                      height="280px", key="mt_net_points")

except Exception as e:
    st.warning(f"Could not load points history: {e}")
