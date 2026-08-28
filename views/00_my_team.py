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

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd
import streamlit as st

from analytics import freshness as _freshness

from components.loading import LINES_GENERIC, LINES_SQUAD, fpl_loader

from ui import charts, theme
from ui.charts import with_mark_line

from components.animations import (
    count_up,
    inject_global_animations,
    scribble_swap_overlay,
)

_logger = logging.getLogger(__name__)

# set_page_config is owned by the app.py router (st.navigation)
inject_global_animations()

# ── Design tokens (local for now; will promote to a shared module next) ───────
POS_COLORS = {"GKP": "var(--ff-mint)", "DEF": "var(--ff-cyan)", "MID": "var(--ff-mag)", "FWD": "var(--ff-orange-v)"}
FDR_COLORS = {1: "var(--ff-mint)", 2: "var(--ff-mint)", 3: "#FFD60A", 4: "var(--ff-orange-v)", 5: "var(--ff-red)"}
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
        f'<div style="display:inline-flex;align-items:center;gap:10px;background:var(--ff-row-alt);'
        f'border:1px solid {color}55;border-radius:999px;padding:6px 16px;">'
        f'<span style="width:7px;height:7px;border-radius:50%;background:{color};'
        f'box-shadow:0 0 10px {color};"></span>'
        f'<span style="font-family:\'Archivo\',sans-serif;font-size:12px;font-weight:800;'
        f'letter-spacing:0.06em;text-transform:uppercase;color:{color};">{title}</span>'
        f'<span style="font-size:12px;color:var(--ff-muted2);">{sub}</span>'
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
    st.number_input(
        "Free transfers banked", min_value=1, max_value=5, value=1, step=1,
        key="banked_fts",
        help="FPL's public API does not publish this · tell the planner what "
             "you are carrying into next week.",
    )

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
    from ui.preseason import is_preseason
    if is_preseason():
        st.info(
            "🌱 Your squad appears here once 2026-27 team selection opens · no "
            "gameweek picks exist yet. Prices are set, so start shaping your "
            "opener on the 26/27 Draft and Scouting pages in the sidebar."
        )
    else:
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
                return "", "var(--ff-mint)"
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return "", "var(--ff-mint)"
            delta = dt - datetime.now(timezone.utc)
            secs = delta.total_seconds()
            if secs <= 0:
                return "Deadline passed", "var(--ff-red)"
            days = delta.days
            hours, rem = divmod(delta.seconds, 3600)
            mins = rem // 60
            if days > 0:
                return f"{days}d {hours}h to deadline", "var(--ff-mint)" if days > 1 else "var(--ff-orange)"
            if hours > 0:
                return f"{hours}h {mins}m to deadline", "var(--ff-orange)" if hours > 6 else "var(--ff-red)"
            return f"{mins}m to deadline", "var(--ff-red)"
    return "", "var(--ff-mint)"


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
     background:var(--ff-row-alt);
     border:1px solid var(--ff-row-alt);
     border-radius:10px;">
  <div style="font-size:10px;color:var(--ff-muted2);letter-spacing:0.14em;
       text-transform:uppercase;font-weight:800;">{label}</div>
  <div style="font-size:24px;font-weight:900;color:{accent};line-height:1.1;margin-top:4px;">
    {primary}
  </div>
  {f'<div style="font-size:11px;color:var(--ff-muted2);margin-top:2px;">{secondary}</div>' if secondary else ''}
</div>
"""


chip_label = (active_chip or "-").upper() if active_chip else "-"
deadline_pill = (
    f'<div style="display:inline-flex;align-items:center;gap:7px;'
    f'background:var(--ff-card);border:1px solid {deadline_color}66;'
    f'border-radius:999px;padding:6px 14px;backdrop-filter:blur(6px);">'
    f'<span style="font-size:12px;">🕒</span>'
    f'<span style="font-size:12px;font-weight:800;color:{deadline_color};">{deadline_text}</span>'
    f'</div>'
) if deadline_text else ""

hero_stats_html = (
    _hero_stat(f"GW{int(entry_history.get('event') or current_gw)} Points",
               count_up(gw_pts - transfer_cost), "var(--ff-mint)",
               f"−{transfer_cost} hit" if transfer_cost else "No hits")
    + _hero_stat("Overall Rank", _rank_fmt(int(overall_rank or 0)), "#fff",
                 f"Total {total_pts:,}")
    + _hero_stat("Bank", f"£{bank_m:.2f}m", "var(--ff-cyan)",
                 f"Team £{value_m:.2f}m")
    + _hero_stat("Bench Points", count_up(bench_pts),
                 "var(--ff-red)" if bench_pts > 8 else "#FFD60A" if bench_pts > 3 else "#fff",
                 f"{transfers_made} transfer{'s' if transfers_made != 1 else ''}")
    + _hero_stat("Active Chip", chip_label,
                 "var(--ff-gold)" if active_chip else "var(--ff-muted2)",
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
    border:1px solid var(--ff-row-alt);
    font-family:'Inter','SF Pro Display',sans-serif;
    box-shadow:0 10px 30px rgba(0,0,0,0.35);
">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:24px;flex-wrap:wrap;">
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
        <span style="display:inline-block;width:7px;height:7px;border-radius:50%;
              background:var(--ff-mint);box-shadow:0 0 10px var(--ff-mint);"></span>
        <span style="font-size:11px;letter-spacing:0.22em;color:var(--ff-muted2);
              text-transform:uppercase;font-weight:800;">
          Gameweek {current_gw}{f' · Chip: {chip_label}' if active_chip else ''}
        </span>
      </div>
      <div style="font-size:40px;font-weight:900;color:var(--ff-text);letter-spacing:-1px;line-height:1;">
        {team_name}
      </div>
      <div style="font-size:13px;color:var(--ff-muted2);margin-top:6px;">
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


# ── Shared projection · the Draft's engine, pointed at the real squad ────────
# One board, one projector, one transfer ledger and one player card across both
# pages. Everything below is keyed by the stable player `code`, never the
# season-local `fpl_id`. All of it is cached on the inputs stamp, so after the
# first build this costs a dict lookup per rerun.
from analytics import squad_rules as SR
from analytics import team_plan as TP
from analytics.grading import bench_boost_grade
from analytics.gw_projection import best_xi
from analytics.head_to_head import week_band
from components import ff_table as T
from components.pitch_view import render_squad_pitch
from components.team_identity import player_photo_url
from config import POSITIONS as _POSITIONS
from ui import live_projection as LP
from ui import player_card as PC
from ui import team_pitch_rows as ROWS
from ui.team_gap import gap_verdict

try:
    _LIVE = LP.projection(_freshness.inputs_stamp())
except Exception as _exc:  # noqa: BLE001 · a missing archive must not take the page down
    # The planner shows one friendly line for every failure here, so the real
    # cause has to reach the log or a broken fetcher is indistinguishable from
    # an archive that was simply never built.
    _logger.warning("live projection unavailable: %s", _exc, exc_info=True)
    _LIVE = {"board": None, "proj": None, "fix": {}, "pts_col": None, "scout": None,
             "price_bt": None, "validation": None, "board_stamp": "", "window": []}

BOARD, PROJ = _LIVE["board"], _LIVE["proj"]
PTS_COL, FIX = _LIVE["pts_col"], _LIVE["fix"]
_ELEMENT_BY_CODE = {int(p["code"]): p for p in bs["elements"]}
_CODE_BY_ID = {int(p["id"]): int(p["code"]) for p in bs["elements"]}
_PRICE_BY_CODE = {int(p["code"]): float(p["now_cost"]) / 10 for p in bs["elements"]}
_TEAM_SHORT = {int(t["id"]): t["short_name"] for t in bs["teams"]}
_TEAM_CODE = {int(t["id"]): int(t["code"]) for t in bs["teams"]}

# DEFCON hit rates, and the one card context the page reuses for cheap lookups.
# The context carrying the button callbacks is built per open in `_open_card`.
# Deliberately NOT named CARD: the Draft page shadowed its card CSS constant
# with exactly that name and spent an afternoon on it.
DEFCON = PC.defcon_per90(_LIVE["board_stamp"]) if BOARD is not None else pd.DataFrame()
_CARD_CTX = (PC.CardCtx(board=BOARD, proj=PROJ, pts_col=PTS_COL, fix=FIX, defcon=DEFCON,
                        scout=_LIVE["scout"], board_stamp=_LIVE["board_stamp"])
             if BOARD is not None else None)


def _sk(name: str) -> str:
    """Session keys namespaced by team id.

    The Draft namespaces its own by draft id, so `axe` and `pitch_nonce` on the
    two pages cannot collide, and neither can two team ids on this one.
    """
    return "%s::team%d" % (name, int(team_id))


for _k, _v in (("axe", []), ("sub_from", None), ("xi_override", {}),
               ("pitch_nonce", None), ("table_nonce", None), ("compare_pair", None)):
    st.session_state.setdefault(_sk(_k), _v)


# ── THIS WEEK'S DECISIONS · Captain · Sell · Opportunity ─────────────────────
st.markdown(
    '<div class="fplh-animate-in" style="margin:6px 0 14px;display:flex;'
    'align-items:center;gap:14px;">'
    '<div style="font-size:11px;letter-spacing:0.22em;color:var(--ff-muted2);'
    'text-transform:uppercase;font-weight:800;">This Gameweek\'s Decisions</div>'
    '<div style="flex:1;height:1px;background:var(--ff-row-alt);"></div>'
    '</div>',
    unsafe_allow_html=True,
)


def _fixture_pills(fixtures, n: int = 4) -> str:
    if not isinstance(fixtures, list) or not fixtures:
        return '<span style="color:var(--ff-muted2);font-size:11px;">-</span>'
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
def _scored_universe(_players, stamp: str):
    # `stamp` is the cache key. Streamlit refuses to hash `_players` because
    # of the underscore, so without it this ran once per process and a price
    # or form refresh never reached the opportunity card.
    from analytics.transfer_engine import score_players, estimate_ceiling
    d = estimate_ceiling(score_players(_players))
    return d[d["status"] == "a"].sort_values("transfer_score", ascending=False)

try:
    owned_names = set(squad_df["web_name"].tolist())
    opp_df = _scored_universe(
        players_df_all,
        _freshness.frame_stamp(players_df_all, "total_points", "now_cost", "form"))
    opp_df = opp_df[~opp_df["web_name"].isin(owned_names)]
    opp = opp_df.iloc[0] if not opp_df.empty else None
except Exception:
    opp = None


def _decision_card(kind: str, accent: str, header: str, body_html: str) -> str:
    return f"""
<div class="fplh-card-hover fplh-animate-in" style="
    background:rgba(22,26,34,0.85);
    border:1px solid var(--ff-row-alt);
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
         background:var(--ff-gold);color:#000;border-radius:50%;width:24px;height:24px;
         line-height:24px;text-align:center;font-weight:900;font-size:12px;">C</div>
  </div>
  <div style="flex:1;min-width:0;">
    <div style="font-size:18px;font-weight:900;color:var(--ff-text);white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;">{ctop_name}</div>
    <div style="font-size:11px;color:var(--ff-muted2);margin-top:2px;">
      {_position_chip(ctop_pos)} <span style="margin-left:6px;">{ctop_team}</span>
    </div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:22px;font-weight:900;color:var(--ff-gold);line-height:1;">{ctop_score:.2f}</div>
    <div style="font-size:9px;color:var(--ff-muted2);letter-spacing:0.1em;">SCORE</div>
  </div>
</div>
<div style="display:flex;gap:14px;margin-bottom:10px;">
  <div><div style="font-size:14px;font-weight:800;color:var(--ff-text);">{ctop_form:.2f}</div>
       <div style="font-size:9px;color:var(--ff-muted2);letter-spacing:0.1em;">FORM</div></div>
  <div><div style="font-size:14px;font-weight:800;color:{_fdr_color(ctop_fdr)};">{ctop_fdr:.2f}</div>
       <div style="font-size:9px;color:var(--ff-muted2);letter-spacing:0.1em;">FDR{FIXTURE_LOOKAHEAD}</div></div>
</div>
<div style="margin-top:auto;">{ctop_fix}</div>
"""
    cap_card_html = _decision_card("🏆", "var(--ff-gold)", "Captain Pick", cap_body)
else:
    cap_card_html = _decision_card("🏆", "var(--ff-gold)", "Captain Pick",
                                    '<div style="color:var(--ff-muted2);">No data.</div>')


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
        f'border:1px solid rgba(255,75,75,0.3);color:var(--ff-text);border-radius:4px;'
        f'padding:2px 8px;font-size:11px;margin:2px 4px 2px 0;">{f}</span>'
        for f in flags[:4]
    )
    others = len(sell_candidates) - 1
    others_html = (
        f'<div style="font-size:11px;color:var(--ff-muted2);margin-top:10px;">'
        f'+{others} other player{"s" if others > 1 else ""} flagged</div>'
        if others > 0 else ""
    )

    sell_body = f"""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
  <img src="{wshirt}" width="56"
       onerror="this.src='{SHIRT_BASE}/shirt_1-66.png'"
       style="filter:drop-shadow(0 4px 6px rgba(0,0,0,0.45));"/>
  <div style="flex:1;min-width:0;">
    <div style="font-size:18px;font-weight:900;color:var(--ff-text);white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;">{wname}</div>
    <div style="font-size:11px;color:var(--ff-muted2);margin-top:2px;">
      {_position_chip(wpos)} <span style="margin-left:6px;">{wteam}</span>
    </div>
  </div>
</div>
<div style="margin-top:4px;margin-bottom:4px;">{flag_html}</div>
{others_html}
"""
    sell_card_html = _decision_card("⚠️", "var(--ff-red)", "Sell Alert", sell_body)
else:
    sell_card_html = _decision_card(
        "✅", "var(--ff-mint)", "Sell Alert",
        '<div style="font-size:14px;color:var(--ff-muted);line-height:1.5;">'
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
        'color:var(--ff-mint);border-radius:4px;padding:2px 7px;font-size:10px;font-weight:800;'
        'letter-spacing:0.05em;margin-left:6px;">IN BUDGET</span>'
        if afford else ""
    )

    opp_body = f"""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;">
  <img src="{oshirt}" width="56"
       onerror="this.src='{SHIRT_BASE}/shirt_1-66.png'"
       style="filter:drop-shadow(0 4px 6px rgba(0,0,0,0.45));"/>
  <div style="flex:1;min-width:0;">
    <div style="font-size:18px;font-weight:900;color:var(--ff-text);white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;">{oname}{aff_badge}</div>
    <div style="font-size:11px;color:var(--ff-muted2);margin-top:2px;">
      {_position_chip(opos)} <span style="margin-left:6px;">{oteam} · £{oprice:.2f}m</span>
    </div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:22px;font-weight:900;color:var(--ff-mint);line-height:1;">{oscore:.2f}</div>
    <div style="font-size:9px;color:var(--ff-muted2);letter-spacing:0.1em;">SCORE</div>
  </div>
</div>
<div style="display:flex;gap:14px;">
  <div><div style="font-size:14px;font-weight:800;color:var(--ff-text);">{oform:.2f}</div>
       <div style="font-size:9px;color:var(--ff-muted2);letter-spacing:0.1em;">FORM</div></div>
  <div><div style="font-size:14px;font-weight:800;color:var(--ff-cyan);">{oep:.2f}</div>
       <div style="font-size:9px;color:var(--ff-muted2);letter-spacing:0.1em;">xP NEXT</div></div>
</div>
"""
    opp_card_html = _decision_card("🔄", "var(--ff-mint)", "Opportunity", opp_body)
else:
    opp_card_html = _decision_card("🔄", "var(--ff-mint)", "Opportunity",
                                    '<div style="color:var(--ff-muted2);">No data.</div>')


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
        f'font-weight:900;color:var(--ff-text);">Top ten · {label}</div>',
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
                             r.get("team_short"), r.get("code")))
        rows.sort(key=lambda x: -x[1])
        rows = rows[:10]
        sub = f"summed over the last {int(n)} gameweeks · candidates ranked live"
    else:
        rows = [(str(r["web_name"]), round(float(r[season_col] or 0), 1),
                 r.get("team_short"), r.get("code"))
                for _, r in top.head(10).iterrows()]
        sub = "current season snapshot"
    st.caption(sub)
    from components.team_identity import player_photo_url as _ppu
    opt = charts.bar_option(
        x=[nm for nm, _, _, _ in rows], y=[v for _, v, _, _ in rows],
        colors=[_tc(ts) for _, _, ts, _ in rows], horizontal=True)
    for item, (_nm, v, _ts, _cd) in zip(opt["series"][0]["data"], rows):
        item["label"] = {"show": True, "position": "right", "formatter": f"{v:g}",
                         # Canvas, not the DOM · var(--ff-*) resolves to nothing here.
                         "color": theme.fill("muted"), "fontSize": 11}
    charts.with_image_labels(opt, [_ppu(cd) for _, _, _, cd in rows])
    opt["grid"]["left"] = 150
    opt["grid"]["right"] = 46
    charts.render(opt, height="380px", key=f"colchart_{season_col}")


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
            background:linear-gradient(135deg,rgba(255,75,75,0.10),var(--ff-card));
            border:1px dashed var(--ff-red);border-radius:10px;margin-bottom:10px;" class="fplh-animate-in">
        <div style="font-size:11px;color:var(--ff-muted2);letter-spacing:0.12em;
             text-transform:uppercase;font-weight:700;">Axed</div>
        <div style="font-size:20px;font-weight:900;color:var(--ff-text);font-family:'Archivo',sans-serif;
             text-decoration:line-through var(--ff-red) 3px;">{out_name}</div>
        <div style="font-size:12px;color:var(--ff-muted2);margin-top:3px;">
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
        f"<div style='margin:8px 0 6px;font-size:12px;color:var(--ff-muted);'>"
        f"{_total} option{'s' if _total != 1 else ''} within £{avail_budget:.1f}m"
        f"{' · top 20' if not _show_all and _total > 20 else ''}</div>",
        unsafe_allow_html=True,
    )
    if cand.empty:
        st.info("No affordable replacements match those filters.")

    def _price_badge(pc) -> str:
        f = _pflags.get(int(pc["fpl_id"]))
        if f == "rise":
            return ('<span style="color:var(--ff-mint);font-weight:900;" '
                    'title="Price likely to rise soon">▲</span>')
        if f == "fall":
            return ('<span style="color:var(--ff-red);font-weight:900;" '
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

    # label: (universe column, per-GW field for the chart window, format, help)
    # Every stat states its WINDOW so a number is never ambiguous.
    _COLS = {
        "Form":    ("form", "total_points", "%.1f",
                    "FPL form · average points per match over the last 30 days "
                    "(off-season: whole-season points per game)"),
        "xP":      ("ep_next", None, "%.1f",
                    "Projected points for the gameweek you are planning"),
        "Pts":     ("total_points", "total_points", "%d",
                    "Total points · full 2025-26 season"),
        "Mins/G":  ("avg_minutes", "minutes", "%d",
                    "Average minutes per appearance, full season · 90 = plays "
                    "full games when he plays"),
        "Goals":   ("goals_scored", "goals_scored", "%d",
                    "Goals · full 2025-26 season"),
        "DEF acts": ("defensive_contribution", "defensive_contribution", "%d",
                     "Defensive actions (tackles, interceptions, CBI, "
                     "recoveries) · full 2025-26 season · the raw volume "
                     "behind DEFCON points"),
        "Assists": ("assists", "assists", "%d",
                    "Assists · full 2025-26 season"),
        "xG":      ("xg", "expected_goals", "%.1f",
                    "Expected goals · full 2025-26 season"),
        "xGI/90":  ("fpl_xgi_per90", "expected_goal_involvements", "%.2f",
                    "Expected goal involvements per 90 minutes · season rate"),
        "Bonus":   ("bonus", "bonus", "%d",
                    "Bonus points · full 2025-26 season"),
        "Own%":    ("ownership", None, "%.1f",
                    "Owned by % of all managers · right now"),
        "Pts/£m":  ("points_per_million", None, "%.1f",
                    "Season points per £m of current price"),
    }
    _defaults = ["Form", "xP", "Pts", "Mins/G", "Goals", "DEF acts"]

    # Backfill any missing stat columns straight from the bootstrap · on BOTH
    # the display rows and the full pool (the chart dialog ranks the pool).
    _bs = st.session_state.get("bootstrap") or {}
    _by_id = {int(e["id"]): e for e in _bs.get("elements", [])}
    for _df in (pool, cand):
        for _lbl, (_col, _f, _fmt, _hlp) in _COLS.items():
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
    for _lbl in _picked:
        _c = _COLS[_lbl][0]
        _show[_c] = pd.to_numeric(_show[_c], errors="coerce")
    _show["_kit"] = [
        _srl(int(tc or 1), str(pos) == "GKP")
        for tc, pos in zip(_show.get("team_code", 1), _show["position"])]
    _flag_map = {"rise": "▲", "fall": "▼"}
    _show["_move"] = _show["fpl_id"].astype(int).map(
        lambda i: _flag_map.get(_pflags.get(i), ""))
    _tbl_cols = ["_kit", "web_name", "price", "_move"] + [
        _COLS[l][0] for l in _picked]
    def _col(kind, *a, **k):
        # Column pinning shipped in newer Streamlit · degrade gracefully.
        try:
            return kind(*a, **k)
        except TypeError:
            k.pop("pinned", None)
            return kind(*a, **k)

    _cfg = {
        "_kit": _col(st.column_config.ImageColumn, "", width=34, pinned=True),
        "web_name": _col(st.column_config.TextColumn, "Player", width=110,
                         pinned=True),
        "price": st.column_config.NumberColumn("£", format="%.1f", width=52,
                                               help="Current price"),
        "_move": st.column_config.TextColumn("Δ£", width=34,
                                             help="▲ price rise likely · ▼ fall"),
    }
    for _lbl in _picked:
        _col, _f, _fmt, _hlp = _COLS[_lbl]
        _cfg[_col] = st.column_config.NumberColumn(_lbl, format=_fmt, width=60,
                                                   help=_hlp)

    _event = st.dataframe(
        _show[_tbl_cols], column_config=_cfg, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        use_container_width=True,
        height=min(520, 42 + 35 * len(_show)),
        key=f"{key_prefix}_tbl")

    result = (None, None)
    _sel_rows = (_event.selection.rows
                 if _event and hasattr(_event, "selection") else [])
    if _sel_rows:
        _pc = cand.iloc[_sel_rows[0]]
        st.markdown(
            f'<div style="padding:8px 14px;margin:2px 0 6px;border-radius:10px;'
            f'background:linear-gradient(135deg,rgba(0,255,135,0.10),var(--ff-card));'
            f'border:1px solid rgba(0,255,135,0.35);font-size:13px;color:var(--ff-text);">'
            f'Selected: <b style="color:var(--ff-mint);">{_pc["web_name"]}</b> '
            f'<span style="color:var(--ff-muted2);">£{float(_pc["price"]):.1f}m · '
            f'replaces {out_name}</span></div>',
            unsafe_allow_html=True)
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
        st.markdown(
            '<div style="padding:6px 12px;font-size:12px;color:var(--ff-muted2);">'
            '👆 <b>Tick a row</b> (leftmost column) to sign or compare · '
            'click any header to sort · 📊 charts the column.</div>',
            unsafe_allow_html=True)

    if st.button("Cancel axe", key=f"{key_prefix}_cancel"):
        result = ("cancel", None)
    return result


@st.cache_data(ttl=900, show_spinner=False)
def _xp_horizon_cached(first_gw: int, horizon: int, _players, _bootstrap,
                       stamp: str):
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
        return (_xp_horizon_cached(
                    first, horizon, players_df_all, bs,
                    _freshness.frame_stamp(players_df_all, "total_points",
                                           "now_cost", "form")),
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

    from components.team_identity import player_photo_url as _ppu2

    def _head(r, accent, tag):
        fx = _attach_short(r.get("upcoming_fixtures"))
        pills = _fixture_pills(fx, n=5)
        _kit_html = _sh(int(r.get("team_code", 1) or 1),
                        is_gkp=str(r.get("position")) == "GKP", width=50)
        _photo = _ppu2(r.get("code"))
        _face = (f'<img src="{_photo}" width="52" loading="lazy" '
                 f'style="border-radius:8px;" '
                 f"onerror=\"this.outerHTML='{_kit_html.replace(chr(34), chr(39))}';\"/>"
                 ) if _photo else _kit_html
        return (
            f'<div style="border:1px solid {accent}55;border-top:3px solid {accent};'
            f'border-radius:12px;padding:14px 16px;background:rgba(22,26,34,0.85);">'
            f'<div style="font-size:10px;letter-spacing:0.16em;text-transform:uppercase;'
            f'font-weight:900;color:{accent};margin-bottom:8px;">{tag}</div>'
            f'<div style="display:flex;align-items:center;gap:12px;">'
            f'{_face}'
            f'<div><div style="font-family:\'Archivo\',sans-serif;font-size:20px;'
            f'font-weight:900;color:var(--ff-text);">{r.get("web_name", "?")}</div>'
            f'<div style="font-size:12px;color:var(--ff-muted2);">'
            f'{r.get("team", "?")} · {r.get("position", "?")} · £{float(r.get("price", 0) or 0):.1f}m</div></div></div>'
            f'<div style="margin-top:10px;">{pills}</div></div>'
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_head(p_out, "var(--ff-red)", "Out"), unsafe_allow_html=True)
    with c2:
        st.markdown(_head(p_in, "var(--ff-mint)", "In"), unsafe_allow_html=True)

    # Stat-by-stat · winner highlighted per row
    _stats = [("Form (30d)", "form", 1), ("xP next GW", "ep_next", 1),
              ("Season pts", "total_points", 0), ("xGI/90", "fpl_xgi_per90", 2),
              ("Season mins", "minutes", 0), ("Owned %", "ownership", 1),
              ("Pts/£m", "points_per_million", 1)]
    _rows_html = ""
    for label, col, dp in _stats:
        if col not in players_df_all.columns:
            continue
        vo = float(p_out.get(col, 0) or 0)
        vi = float(p_in.get(col, 0) or 0)
        co = "var(--ff-red)" if vo > vi else "var(--ff-muted)"
        ci = "var(--ff-mint)" if vi > vo else "var(--ff-muted)"
        _rows_html += (
            f'<div style="display:flex;align-items:center;padding:5px 0;'
            f'border-bottom:1px solid var(--ff-row-alt);">'
            f'<div style="flex:1;text-align:right;font-weight:800;color:{co};'
            f'font-family:\'Archivo\',sans-serif;">{vo:.{dp}f}</div>'
            f'<div style="width:110px;text-align:center;font-size:10px;letter-spacing:0.12em;'
            f'text-transform:uppercase;color:var(--ff-muted2);font-weight:700;">{label}</div>'
            f'<div style="flex:1;font-weight:800;color:{ci};'
            f'font-family:\'Archivo\',sans-serif;">{vi:.{dp}f}</div></div>'
        )
    _hz = _xp_horizon()
    if _hz is not None:
        _hdf, _hfirst, _hn = _hz
        _vo5 = float(_hdf["xp_total"].get(int(out_id), 0.0))
        _vi5 = float(_hdf["xp_total"].get(int(in_id), 0.0))
        _co5 = "var(--ff-red)" if _vo5 > _vi5 else "var(--ff-muted)"
        _ci5 = "var(--ff-mint)" if _vi5 > _vo5 else "var(--ff-muted)"
        _rows_html += (
            f'<div style="display:flex;align-items:center;padding:5px 0;">'
            f'<div style="flex:1;text-align:right;font-weight:800;color:{_co5};'
            f'font-family:\'Archivo\',sans-serif;">{_vo5:.1f}</div>'
            f'<div style="width:110px;text-align:center;font-size:10px;letter-spacing:0.12em;'
            f'text-transform:uppercase;color:var(--ff-gold);font-weight:800;">xP next {_hn} GWs</div>'
            f'<div style="flex:1;font-weight:800;color:{_ci5};'
            f'font-family:\'Archivo\',sans-serif;">{_vi5:.1f}</div></div>'
        )
    st.markdown(f'<div style="margin:12px 0 4px;">{_rows_html}</div>',
                unsafe_allow_html=True)

    # Verdict + radar overlay
    _xp_gain = float(p_in.get("ep_next", 0) or 0) - float(p_out.get("ep_next", 0) or 0)
    _price_d = float(p_out.get("price", 0) or 0) - float(p_in.get("price", 0) or 0)
    _vcol = "var(--ff-mint)" if _xp_gain >= 0 else "var(--ff-red)"
    st.markdown(
        f'<div style="text-align:center;padding:8px;font-size:13px;color:var(--ff-muted);">'
        f'This move buys <b style="color:{_vcol};">{_xp_gain:+.1f} xP</b> next GW and '
        f'{"banks" if _price_d >= 0 else "costs"} '
        f'<b style="color:var(--ff-cyan);">£{abs(_price_d):.1f}m</b></div>',
        unsafe_allow_html=True,
    )
    ind_o, val_o = radar_percentiles(players_df_all, p_out)
    ind_i, val_i = radar_percentiles(players_df_all, p_in)
    if len(ind_o) >= 3 and len(ind_o) == len(ind_i):
        charts.render(_ch.radar_compare_option(ind_o, [
            (str(p_out.get("web_name", "Out")), val_o, "var(--ff-red)", 0.14),
            (str(p_in.get("web_name", "In")), val_i, "var(--ff-mint)", 0.24),
        ]), height="300px", key=f"h2h_{out_id}_{in_id}")


# ── FORWARD-WEEK PLANNER ──────────────────────────────────────────────────────
# Scrub past the current gameweek and this is what answers "what is the best
# move this week?". It runs the SAME engine as the 26/27 Draft: one projector
# (`ui.live_projection`), one transfer ledger (`analytics.team_plan`), one
# player card (`ui.player_card`) and one table component. The row shapes the
# pitch and the table expect are unit-tested in `ui/team_pitch_rows.py`.


def _flat(html: str) -> str:
    """One line of HTML.

    CLAUDE.md rule 6b · a whitespace-only line makes `st.markdown` stop passing
    raw HTML through and render the rest as literal text.
    """
    return "".join(seg.strip() for seg in html.splitlines())


def _dedupe(click, nonce_key: str):
    """Act on a component click only when it is a NEW one.

    A bidirectional component replays its LAST value on every rerun, so without
    this a dialog reopens whenever an unrelated widget moves. CLAUDE.md rule 4b,
    learned the hard way on the Draft.
    """
    if not click:
        return None
    if click.get("nonce") == st.session_state.get(nonce_key):
        return None
    st.session_state[nonce_key] = click.get("nonce")
    return click


def _planner_squad(codes_now):
    """The fifteen for the viewed week as board rows, in slot order.

    A player the board has no row for (should not happen in season, guarded
    anyway) keeps his name, club and price from the bootstrap and projects at
    zero, rather than arriving as a row of NaN that renders as "nan" on a shirt.
    """
    frame = BOARD.drop_duplicates("code").set_index("code").reindex(codes_now)
    missing = [int(c) for c in frame.index[frame["web_name"].isna()]]
    for c in missing:
        el = _ELEMENT_BY_CODE.get(int(c))
        if el is None:
            continue
        tid = int(el.get("team", 0) or 0)
        for col, val in (("web_name", el.get("web_name", "Unknown")),
                         ("position", _POSITIONS.get(el.get("element_type"), "MID")),
                         ("team_id", tid),
                         ("team_code", _TEAM_CODE.get(tid, 1)),
                         ("team_short", _TEAM_SHORT.get(tid, "?")),
                         ("actual_price", float(el.get("now_cost", 0) or 0) / 10)):
            if col in frame.columns:
                frame.at[int(c), col] = val
    return frame.reset_index(), missing


def _open_card(code: int, gw: int, codes_now) -> None:
    """The Draft's player card, with My Team's own actions wired into it."""
    owned = {int(c) for c in codes_now}

    def _replace(c):
        cur = [int(x) for x in st.session_state[_sk("axe")]]
        if int(c) not in cur:
            cur.append(int(c))
        st.session_state[_sk("axe")] = cur
        st.rerun()

    def _captain(c):
        plans, drafts = TP.load(int(team_id), _CODE_BY_ID)
        e = dict(drafts.get(int(gw)) or plans.get(int(gw)) or TP.empty_entry())
        e["captain"] = int(c)
        TP.save_draft(int(team_id), int(gw), e)
        st.rerun()

    def _compare(c):
        axed = [int(x) for x in st.session_state[_sk("axe")]]
        if not axed:
            st.toast("Mark a player with ✕ first")
            return
        st.session_state[_sk("compare_pair")] = (axed[0], int(c))
        st.rerun()

    ctx = PC.CardCtx(board=BOARD, proj=PROJ, pts_col=PTS_COL, fix=FIX, defcon=DEFCON,
                     scout=_LIVE["scout"], board_stamp=_LIVE["board_stamp"],
                     on_replace=_replace, on_compare=_compare, on_captain=_captain,
                     captain_gw=int(gw), in_squad=lambda c: int(c) in owned,
                     current_gw=int(gw))
    PC.open_player_card(ctx, int(code))


def _captain_and_xi(entry, xi, pos_by, gw, playing, manual_xi):
    """Honour a saved armband, promoting him into the XI when that is legal.

    Returns `(xi, captain, stuck)`. A saved captain sitting on the bench used to
    be replaced silently by the auto pick, so the card's "⭐ Captain for GWn"
    looked like it had done nothing. Swapping him for the weakest starter of his
    own position is what the user meant by pressing it; when even that would
    break the formation we hand back `stuck` so the caller can say why rather
    than leaving the armband somewhere the user did not put it.

    `manual_xi` says the eleven on screen was chosen by hand for this week, and
    it VETOES the promotion. The two-tap swap on the pitch writes only
    `xi_override` and never touches `entry["captain"]`, so benching your own
    captain used to be undone on the next rerun by the promotion above: the
    kit went back into the eleven and the bench tap looked broken. The most
    recent explicit instruction wins, and a tap on the pitch is more recent and
    more specific than an armband saved earlier.
    """
    def _auto():
        return max(playing or list(xi), key=lambda c: PROJ.points(c, gw), default=None)

    saved = entry.get("captain")
    saved = int(saved) if saved is not None else None
    if saved is None or saved not in pos_by:
        return xi, _auto(), None
    if saved in xi:
        return xi, saved, None
    if not manual_xi:
        same_pos = [c for c in xi if pos_by.get(c) == pos_by.get(saved)]
        if same_pos:
            drop = min(same_pos, key=lambda c: PROJ.points(c, gw))
            promoted = (set(xi) - {drop}) | {saved}
            if SR.is_legal_xi(promoted, pos_by):
                return promoted, saved, None
    return xi, _auto(), saved


def _money_strip(wk, led, bank_m_after, xi_pts, band, bench_pts, chip,
                 n_match, n_asked) -> None:
    """The constraints every decision on this page runs into, above everything.

    Free transfers, moves made, hits, money, the week's points with its 80%
    band, and how much of that total is a real match forecast rather than a
    fixture shape.
    """
    free_before = wk["available_before"] if wk else led["available_now"]
    used = wk["used"] if wk else 0
    hits = wk["hits"] if wk else 0
    # A chip week has unlimited transfers and costs nothing, so a count and a
    # hit warning are both wrong there.
    wild = bool(wk and wk.get("wildcard")) or chip in ("WC", "FH")
    grade = bench_boost_grade(bench_pts)
    tiles = [
        ("Free", "∞" if wild else str(free_before),
         "var(--ff-mag)" if wild else ("var(--ff-mint)" if free_before else "var(--ff-orange)"),
         "chip week, all free" if wild else "bank of %d" % led["cap"]),
        ("Moves", str(used), "var(--ff-cyan)" if used else "var(--ff-text)", "this week"),
        ("Hits", ("−%d" % (hits * 4)) if hits else "0",
         "var(--ff-red)" if hits else "var(--ff-text)", "%d × −4" % hits),
        ("Bank", "£%.1fm" % bank_m_after,
         "var(--ff-cyan)" if bank_m_after >= 0 else "var(--ff-red)", "after moves"),
        ("%s xP" % ("Squad" if chip == "BB" else "XI"), "%.0f" % xi_pts, "var(--ff-gold)",
         "%.0f to %.0f · 80%%" % (band["lo"], band["hi"])),
        ("Bench", "%.1f" % bench_pts, "var(--ff-text)",
         grade["call"] if chip == "BB" else "not boosted"),
        ("Forecasts", "%d/%d" % (n_match, n_asked),
         "var(--ff-mint)" if n_match >= n_asked * 0.8 else "var(--ff-text)",
         "on match forecasts" if n_match else "fixture shape"),
    ]
    body = "".join(
        "<div style='flex:1;min-width:112px;background:var(--ff-card);"
        "border:1px solid var(--ff-line);border-radius:12px;padding:10px 12px;'>"
        "<div style='font-size:10px;font-weight:800;letter-spacing:0.14em;"
        "text-transform:uppercase;color:var(--ff-muted);'>%s</div>"
        "<div class='ff-display' style='font-size:22px;font-weight:900;color:%s;'>%s</div>"
        "<div style='font-size:11px;color:var(--ff-muted);'>%s</div></div>"
        % (lab, col, val, sub) for lab, val, col, sub in tiles)
    st.markdown(_flat("<div style='display:flex;gap:10px;flex-wrap:wrap;"
                      "margin:8px 0 14px 0;'>" + body + "</div>"),
                unsafe_allow_html=True)


def _handle_pitch_click(click, gw, xi, codes_now, pos_by, sub_from, swap_targets,
                        entry) -> None:
    action, cid = click.get("action"), int(click.get("id") or 0)
    if action == "detail":
        _open_card(cid, gw, codes_now)
    elif action in ("axe", "unaxe"):
        # ✕ marks a player out and ✕ again takes him off the list, so several
        # can be queued and filled one by one from the table.
        cur = [int(c) for c in st.session_state[_sk("axe")]]
        if action == "axe" and cid not in cur:
            cur.append(cid)
        elif action == "unaxe" and cid in cur:
            cur.remove(cid)
        st.session_state[_sk("axe")] = cur
        st.rerun(scope="fragment")
    elif action == "bench":
        # First tap arms the swap, second completes it. Tapping the armed player
        # again cancels, which is the only way out that needs no extra control.
        if sub_from == cid:
            st.session_state[_sk("sub_from")] = None
        elif sub_from is not None and cid in swap_targets:
            new_xi = ((set(xi) - {sub_from}) | {cid} if sub_from in xi
                      else (set(xi) - {cid}) | {sub_from})
            if SR.is_legal_xi(new_xi, pos_by):
                st.session_state[_sk("xi_override")][int(gw)] = new_xi
            st.session_state[_sk("sub_from")] = None
        else:
            st.session_state[_sk("sub_from")] = cid
        st.rerun(scope="fragment")


def _transfer_desk(axed, sq, gw, entry, bank_m_after, codes_now) -> None:
    """Who you could have instead, for the first player in the axe queue.

    Budget is pooled across everyone marked, because marking two players and
    shopping with one player's money is not the choice the manager is making.
    """
    names = {int(r["code"]): str(r["web_name"]) for _, r in sq.iterrows()}
    target = int(axed[0])
    out_rows = sq[sq["code"].astype(int) == target]
    if out_rows.empty:
        return
    out_row = out_rows.iloc[0]
    pooled = float(bank_m_after) + sum(_PRICE_BY_CODE.get(int(c), 0.0) for c in axed)
    st.markdown("**Replacing:** " + " · ".join(names.get(int(c), str(c)) for c in axed)
                + "  ·  £%.1fm to spend" % pooled
                + ("  ·  filling %s first" % names.get(target, str(target))
                   if len(axed) > 1 else ""))

    # Position, budget AND the 3-per-club cap counted after the marked players
    # are sold · a signing that would leave four from one club is not available,
    # and showing it would be offering a move the game rejects.
    pool = ROWS.eligible_pool(BOARD, codes_now, axed, str(out_row["position"]), pooled)
    if pool.empty:
        st.info("No %s is available for £%.1fm within the 3-per-club limit. "
                "Free more money, mark a different player, or keep him."
                % (out_row["position"], pooled))
        return
    pool = pool.sort_values(PTS_COL, ascending=False).head(60)
    rows = ROWS.candidate_rows(pool, gw, PROJ, FIX, out_row, PTS_COL,
                               dc_hit_fn=lambda c, p: PC.dc_hit(_CARD_CTX, c, p),
                               glyph_fn=PC.setpiece_glyphs)
    cols = [T.col_face("code", url_fn=player_photo_url),
            T.col_player("web_name", "Player", sub="team_short", action="inspect"),
            T.col_chip("position", "Pos", color_fn=theme.pos_color),
            T.col_num("actual_price", "£m", fmt="%.1f"),
            T.col_num("d_price", "Δ£m", fmt="%+.1f",
                      color_fn=lambda v: theme.fill("mint") if v <= 0 else theme.fill("red")),
            T.col_run("run", "GW%d-%d" % (gw, gw + 2)),
            T.col_num("gw_pts", "GW%d" % gw, fmt="%.1f"),
            # The match model has no row for every player. A bare dot there
            # reads as a rendering bug rather than the real answer.
            T.col_num("mins", "Mins", fmt="%.0f", empty="no forecast",
                      color_fn=lambda v: theme.fill("red") if v < 45 else None),
            T.col_num("dc_hit", "DEFCON", fmt="%.0f%%", empty="-"),
            T.col_html("setp", ""),
            T.col_num("season", "Season", fmt="%.0f"),
            T.col_num("per_m", "Per £m", fmt="%.1f"),
            T.col_num("spread", "±", fmt="%.0f%%", empty="-"),
            T.col_chip("confidence", "Conf.", color_fn=PC.conf_color),
            T.col_action("code", "swap", "Swap in")]
    click = _dedupe(T.render(rows, cols, key=_sk("cands"), max_height=440),
                    _sk("table_nonce"))
    if click:
        cid = int(click.get("id") or 0)
        if click.get("action") == "inspect":
            _open_card(cid, gw, codes_now)
        elif click.get("action") == "swap":
            e = dict(entry)
            e["swaps"] = dict(e.get("swaps") or {})
            e["swaps"][target] = cid
            TP.save_draft(int(team_id), int(gw), e)
            st.session_state[_sk("axe")] = [int(c) for c in axed if int(c) != target]
            st.rerun(scope="fragment")


@st.cache_data(show_spinner=False, ttl=1800)
def _gap_sim(gw: int, now: tuple, after: tuple, board_stamp: str) -> Dict:
    """Is the gap real? · current squad vs the squad after this week's moves.

    `board_stamp` is what actually keys the cache against `BOARD`/`PROJ`, which
    this closes over as module globals rather than taking them as arguments ·
    both are already fully described by that stamp.
    """
    from analytics.head_to_head import simulate_drafts
    from ui.team_gap import gap_entries

    ents = gap_entries(BOARD, list(now), list(after), gw)
    return simulate_drafts(ents, PROJ, BOARD, gw, min(38, gw + 4), n_sims=1500)


@st.dialog("Head to head", width="large")
def _compare_dialog(a_code: int, b_code: int, gw: int) -> None:
    """Player vs player, on the same engine every other comparison in the app uses."""
    from analytics.head_to_head import compare_players, player_profile, verdict

    rows = {c: BOARD[BOARD["code"] == c] for c in (a_code, b_code)}
    if any(r.empty for r in rows.values()):
        st.info("Player data unavailable.")
        return
    profs = [player_profile(rows[c].iloc[0], pts_col=PTS_COL, defcon=DEFCON, proj=PROJ,
                            from_gw=gw, horizon=6) for c in (a_code, b_code)]
    cmp = compare_players(profs)
    v = verdict(cmp, profs)
    st.markdown(_flat(
        f"<div style='border-left:3px solid var(--ff-{v['tone']});padding:10px 14px;"
        f"margin-bottom:14px;'><b style='color:var(--ff-text);'>{v['headline']}</b>"
        + (f"<div style='color:var(--ff-muted2);margin-top:4px;'>{v['detail']}</div>"
           if v["detail"] else "") + "</div>"), unsafe_allow_html=True)

    cols = st.columns(2)
    for col, p in zip(cols, profs):
        with col:
            st.markdown(_flat(
                f"<div style='text-align:center;'>"
                f"<div class='ff-display' style='font-size:16px;font-weight:900;"
                f"color:var(--ff-text);'>{p['name']}</div>"
                f"<div style='font-size:11px;color:var(--ff-muted2);'>"
                f"{p['team']} · {p['position']} · £{p['price']:.1f}m</div></div>"),
                unsafe_allow_html=True)

    axes = cmp["axes"]
    if axes:
        inds = [{"name": a["label"], "max": 1.0} for a in axes]
        series = []
        for i, p in enumerate(profs):
            vals = [(a["scaled"][i] if a["scaled"][i] is not None else 0) for a in axes]
            col = theme.fill(["mint", "gold"][i % 2])
            series.append((p["name"], [round(v, 3) for v in vals], col, 0.16))
        charts.render(charts.radar_compare_option(inds, series), height="320px",
                      key=f"gap_cmp_radar_{a_code}_{b_code}")


def _save_row(gw, entry, plans, drafts, start_codes, codes_now) -> None:
    """Chip, save, reset, clear.

    `plans`, `drafts`, `start_codes` and `codes_now` are carried for the
    "is the gap real?" Monte Carlo that lands beside these buttons next.
    """
    if entry.get("swaps"):
        codes_before = TP.effective_codes(start_codes, plans, {}, gw - 1)
        sim = _gap_sim(gw, tuple(sorted(codes_before)), tuple(sorted(codes_now)),
                       _LIVE["board_stamp"])
        v = gap_verdict(sim)
        st.markdown(_flat(
            f"<div style='border-left:3px solid var(--ff-{v['tone']});padding:8px 12px;'>"
            f"{v['text']} <span style='color:var(--ff-muted2);'>(GW{gw}-"
            f"{min(38, gw + 4)}, 1,500 sims, shared noise)</span></div>"),
            unsafe_allow_html=True)

    chips = ["None", "BB", "TC", "WC", "FH"]
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.6])
    chip = c4.selectbox("Chip", chips, key=_sk("chip%d" % gw),
                        index=chips.index(entry.get("chip") or "None"),
                        help="Bench Boost counts the bench, Triple Captain triples the "
                             "armband, Wildcard and Free Hit make every move free · a "
                             "Free Hit squad reverts the following week.")
    if chip != (entry.get("chip") or "None"):
        e = dict(entry)
        e["chip"] = None if chip == "None" else chip
        TP.save_draft(int(team_id), int(gw), e)
        st.rerun(scope="fragment")
    # These three write to disk, which is one of the three sanctioned reasons to
    # call st.rerun() from a button (CLAUDE.md rule 5): the widgets above were
    # built before the write, so without it they show the old plan.
    #
    # Reset and Clear must also DROP the chip widget's own key. The selectbox is
    # keyed, so its value outlives the entry it came from: without the pop, a
    # week whose chip was just cleared on disk re-reads "BB" off the widget on
    # the next run and the `chip != entry` branch above writes it straight back
    # as a fresh draft. A chip could never be taken off, and Clear re-dirtied
    # the week it had just cleaned.
    def _drop_chip_widget() -> None:
        st.session_state.pop(_sk("chip%d" % gw), None)

    if c1.button("💾 Save GW%d plan" % gw, key=_sk("save%d" % gw), type="primary",
                 use_container_width=True):
        TP.save_plan(int(team_id), int(gw), entry)
        st.session_state[_sk("axe")] = []
        st.toast("Saved · GW%d plan" % gw)
        st.rerun()
    if c2.button("↩ Reset to saved", key=_sk("reset%d" % gw), use_container_width=True):
        TP.clear_draft(int(team_id), int(gw))
        st.session_state[_sk("axe")] = []
        _drop_chip_widget()
        st.rerun()
    if c3.button("🧹 Clear this week", key=_sk("clear%d" % gw), use_container_width=True):
        TP.save_plan(int(team_id), int(gw), TP.empty_entry())
        st.session_state[_sk("axe")] = []
        _drop_chip_widget()
        st.rerun()


@st.fragment
def _planner_fragment(view_gw: int, plan_first: int, bank_m_now: float) -> None:
    """A future gameweek, planned on the pitch itself.

    Runs as a fragment so an axe, a signing, a bench or a chip redraws only this
    block. In-block actions use `st.rerun(scope="fragment")`; the dialogs and
    the disk writes keep app scope (CLAUDE.md rule 5).
    """
    if PROJ is None:
        st.error("Archive not built · run `python scripts/build_archive.py` first.")
        return
    pair = st.session_state[_sk("compare_pair")]
    if pair:
        st.session_state[_sk("compare_pair")] = None
        _compare_dialog(int(pair[0]), int(pair[1]), int(view_gw))
    plans, drafts = TP.load(int(team_id), _CODE_BY_ID)
    entry = dict(drafts.get(view_gw) or plans.get(view_gw) or TP.empty_entry())
    start_codes = [int(c) for c in squad_df["code"]]
    codes_now = TP.effective_codes(start_codes, plans, drafts, view_gw)
    sq, missing = _planner_squad(codes_now)
    if missing:
        st.warning("%d player(s) have no projection on the board · shown at 0."
                   % len(missing))
    st.markdown(_mode_pill(
        "Planning · GW%d" % view_gw,
        ("unsaved changes · save below" if view_gw in drafts
         else "saved plan" if view_gw in plans else "no moves yet"),
        "var(--ff-gold)"), unsafe_allow_html=True)

    # ── XI, captain, chip ────────────────────────────────────────────────────
    names = {int(r["code"]): str(r["web_name"]) for _, r in sq.iterrows()}
    pos_by = {int(r["code"]): str(r["position"]) for _, r in sq.iterrows()}
    xi = set(best_xi(sq, PROJ, view_gw))
    manual = st.session_state[_sk("xi_override")].get(view_gw)
    manual_xi = False
    if manual:
        # A saved override can name a player who has since been transferred out,
        # so it is filtered and re-checked rather than trusted.
        manual = {int(c) for c in manual if int(c) in pos_by}
        if SR.is_legal_xi(manual, pos_by):
            xi = manual
            manual_xi = True
    chip = entry.get("chip")
    # A captain who does not start scores you nothing twice, so the armband is
    # gated on expected minutes. Silence (None) is not a statement that he is
    # out, so it stays eligible · the Draft's rule.
    playing = [c for c in xi
               if PROJ.expected_minutes(c, view_gw) is None
               or (PROJ.expected_minutes(c, view_gw) or 0) >= 45]
    xi, captain, _stuck = _captain_and_xi(entry, xi, pos_by, view_gw, playing,
                                          manual_xi)
    if _stuck is not None:
        st.caption("Saved captain %s is benched this week · the armband goes to %s."
                   % (names.get(_stuck, str(_stuck)),
                      names.get(captain, "the top starter")))
    xi_pts = (sum(PROJ.points(c, view_gw) for c in xi)
              + (PROJ.points(captain, view_gw) if captain else 0)
              * (2 if chip == "TC" else 1))
    bench_pts = sum(PROJ.points(c, view_gw) for c in codes_now if c not in xi)
    if chip == "BB":
        xi_pts += bench_pts
    # An 80% band, closed form · this strip redraws on every click.
    band = week_band(list(xi), PROJ, BOARD, view_gw, captain=captain)
    n_match, n_asked = PROJ.coverage(codes_now, view_gw)

    # ── Money strip ──────────────────────────────────────────────────────────
    banked_now = int(st.session_state.get("banked_fts", 1))
    led = TP.ledger(plans, drafts, view_gw, start_codes, first_gw=int(plan_first),
                    banked_now=banked_now)
    wk = next((w for w in led["weeks"]
               if w["gw"] == view_gw and w["gw"] >= int(plan_first)), None)
    bank_m_after = TP.bank_after(bank_m_now, _PRICE_BY_CODE, start_codes, plans,
                                 drafts, view_gw)
    _money_strip(wk, led, bank_m_after, xi_pts, band, bench_pts, chip, n_match, n_asked)

    # ── Pitch ────────────────────────────────────────────────────────────────
    axed = [int(c) for c in st.session_state[_sk("axe")] if int(c) in set(codes_now)]
    st.session_state[_sk("axe")] = axed
    sub_from = st.session_state[_sk("sub_from")]
    swap_targets = set()
    if sub_from is not None and int(sub_from) in pos_by:
        sub_from = int(sub_from)
        if sub_from in xi:
            swap_targets = set(SR.legal_swaps(sub_from, xi, codes_now, pos_by))
        else:
            # A benched player was tapped: light every starter he could replace.
            swap_targets = {c for c in xi
                            if SR.is_legal_xi((set(xi) - {c}) | {sub_from}, pos_by)}
    else:
        # An armed player who has since been transferred out · drop him from
        # state too, or the key holds a stale code for the rest of the session.
        sub_from = None
        st.session_state[_sk("sub_from")] = None
    rows = ROWS.pitch_rows(sq, view_gw, PROJ, FIX, xi, captain, axed, sub_from,
                           swap_targets)
    click = _dedupe(render_squad_pitch(
        rows, stat_label="xP", title_right="GW%d plan" % view_gw, interactive=True,
        compact=True,
        # The same number as the tile · the pitch would otherwise sum the cards
        # and quietly drop the captain's double.
        xi_total_override=round(xi_pts, 1),
        total_label="SQUAD" if chip == "BB" else "XI",
        key=_sk("pitch")), _sk("pitch_nonce"))
    if click:
        _handle_pitch_click(click, view_gw, xi, codes_now, pos_by, sub_from,
                            swap_targets, entry)
    if sub_from is not None:
        st.info("Swapping **%s**. Tap a glowing kit to bring him on, or tap him "
                "again to cancel." % names.get(sub_from, "him"))

    # ── Axe queue and candidates ─────────────────────────────────────────────
    if axed:
        _transfer_desk(axed, sq, view_gw, entry, bank_m_after, codes_now)

    _save_row(view_gw, entry, plans, drafts, start_codes, codes_now)


# ── SQUAD ─────────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin:30px 0 12px;display:flex;align-items:center;gap:14px;">'
    '<div style="font-size:11px;letter-spacing:0.22em;color:var(--ff-muted2);'
    'text-transform:uppercase;font-weight:800;">Squad</div>'
    '<div style="flex:1;height:1px;background:var(--ff-row-alt);"></div>'
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
    _dcol = "var(--ff-mint)" if _delta > 0.05 else "var(--ff-red)" if _delta < -0.05 else "var(--ff-muted)"
    _tiles = [
        ("Formation", _formation, "GKP · DEF · MID · FWD", "var(--ff-cyan)"),
        ("Projected XI", f"{_cur:.1f} xP", "captain doubled", "var(--ff-mint)"),
        ("Vs your saved XI", f"{'+' if _delta >= 0 else ''}{_delta:.1f} xP",
         "improvement" if _delta > 0.05 else "worse" if _delta < -0.05 else "no change", _dcol),
    ]
    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 4px;">' + "".join(
            f'<div style="flex:1;min-width:150px;background:rgba(22,26,34,0.85);border:1px solid var(--ff-row-alt);'
            f'border-radius:12px;padding:14px 16px;font-family:\'Inter\',sans-serif;">'
            f'<div style="font-size:10px;font-weight:800;letter-spacing:0.12em;color:var(--ff-muted2);text-transform:uppercase;">{lab}</div>'
            f'<div style="font-size:24px;font-weight:900;color:{acc};margin:2px 0;">{val}</div>'
            f'<div style="font-size:11px;color:var(--ff-muted2);">{sub}</div></div>'
            for lab, val, sub, acc in _tiles
        ) + "</div>",
        unsafe_allow_html=True,
    )

    # ── XI + bench display ────────────────────────────────────────────────────
    def _pill(i, bench=False):
        d = _info[i]
        tag = ""
        if i == _lu["captain"]:
            tag = '<span style="color:var(--ff-gold);font-weight:900;">Ⓒ</span> '
        elif i == _lu["vice"]:
            tag = '<span style="color:#bbb;font-weight:900;">Ⓥ</span> '
        flag = "" if d["status"] == "a" else " 🚑"
        op = "0.6" if bench else "1"
        return (f'<div style="display:inline-flex;align-items:center;gap:7px;background:rgba(22,26,34,0.85);'
                f'border:1px solid var(--ff-row-alt);border-radius:9px;padding:6px 10px;margin:3px;opacity:{op};">'
                f'{team_dot(d["short"], size=11)}<span style="font-size:12px;font-weight:700;color:var(--ff-text);">{tag}{d["name"]}{flag}</span>'
                f'<span style="font-size:11px;font-weight:800;color:var(--ff-mint);">{d["ep"]:.1f}</span></div>')

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
        '<div style="margin:8px 0 2px;"><span style="display:inline-block;background:var(--ff-line);'
        'color:var(--ff-text);border-radius:4px;padding:1px 8px;font-size:10px;font-weight:900;margin-right:6px;">BENCH</span>'
        + "".join(_pill(i, bench=True) for i in _lu["bench"]) + "</div>",
        unsafe_allow_html=True,
    )

    if st.button("↺ Reset to saved XI", key="lu_reset"):
        st.session_state.pop("lineup", None)
        st.rerun()

with tab_pitch:
    # The whole Pitch View tab is a FRAGMENT · scrubbing, dialogs, edit
    # mode and the nested planner fragment rerun without touching the
    # rest of the page. Widget clicks auto-scope; explicit reruns inside
    # already use scope="fragment" where they should.
    @st.fragment
    def _pitch_tab() -> None:
        # squad_df is reassigned below (enrichment merges are idempotent) ·
        # without this the function-wrap would shadow it as an unbound local.
        global squad_df
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
        from config import SIM_HORIZON

        # ── Deep link (?gw=41 jumps the scrubber) ────────────────────────────────
        _qp = st.query_params
        if "gw" in _qp:
            try:
                st.session_state.pitch_gw = int(_qp["gw"])
            except (TypeError, ValueError):
                pass
            del _qp["gw"]

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

        st.caption("◀ scrub back through the season · forward past "
                   f"GW{_cur} to plan transfers on the pitch ▶")
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
            # The forward-week planner lives at module level (see
            # FORWARD-WEEK PLANNER above) and runs as its own fragment, so
            # an axe, a signing, a bench or a chip redraws only that block.
            _planner_fragment(view_gw, _plan_first, bank_m)
        elif _is_upcoming:
            st.markdown(_mode_pill(f"Upcoming · GW{view_gw}", "your pick team · projected xP & fixtures",
                                   "var(--ff-cyan)"), unsafe_allow_html=True)
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
                st.markdown(_mode_pill(f"Actual · GW{view_gw}", _sub, "var(--ff-mint)"),
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
                    "<div style='margin:2px 0 6px;font-size:13px;color:var(--ff-muted2);"
                    "letter-spacing:0.12em;text-transform:uppercase;font-weight:700;'>"
                    "Tap ✕ to axe a player</div>",
                    unsafe_allow_html=True,
                )
                _axe_row(_by_pos["GKP"]); _axe_row(_by_pos["DEF"])
                _axe_row(_by_pos["MID"]); _axe_row(_by_pos["FWD"])
                st.markdown(
                    "<div style='margin:10px 0 6px;font-size:12px;color:var(--ff-muted2);"
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
                        "color:var(--ff-text);margin-top:6px;'>Replacements appear here</div>"
                        "<div style='font-size:12px;color:var(--ff-muted2);margin-top:4px;'>"
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
                "<div style='margin-top:18px;font-size:14px;font-weight:800;color:var(--ff-text);'>"
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
                            background:var(--ff-row-alt);
                            border:1px solid var(--ff-row-alt);
                            border-left:3px solid var(--ff-mint);
                            border-radius:8px;padding:10px 14px;margin-bottom:6px;
                        ">
                          <span style="color:var(--ff-muted2);text-decoration:line-through;">
                           {swap['out_name']}</span>
                          <span style="color:var(--ff-muted2);margin:0 10px;">→</span>
                          <span style="color:var(--ff-mint);font-weight:800;">{swap['in_name']}</span>
                          <span style="font-size:11px;color:var(--ff-muted2);margin-left:10px;">
                           {swap['position']} · {delta_str}</span>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                with cols[1]:
                    if st.button("↩", key=f"undo_swap_{i}", help="Undo this swap"):
                        st.session_state.pending_swaps.pop(i)

            if st.button("Clear all pending swaps", key="clear_all_swaps"):
                st.session_state.pending_swaps = []



    _pitch_tab()
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
    '<div style="font-size:11px;letter-spacing:0.22em;color:var(--ff-muted2);'
    'text-transform:uppercase;font-weight:800;">Season Trend</div>'
    '<div style="flex:1;height:1px;background:var(--ff-row-alt);"></div>'
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
            _hero_stat("Best GW", f"{count_up(best_row['net_points'])} pts", "var(--ff-mint)",
                       f"GW{int(best_row['event'])}")
            + _hero_stat("Worst GW", f"{count_up(worst_row['net_points'])} pts", "var(--ff-red)",
                         f"GW{int(worst_row['event'])}")
            + _hero_stat("Season Avg", f"{count_up(season_avg, 1)} pts", "#fff",
                         f"over {len(hist_df)} GWs")
            + _hero_stat("Bench Loss", f"{count_up(total_bench)} pts", "var(--ff-orange)",
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
            colors=[theme.fill("mint") if p >= season_avg else theme.fill("red")
                    for p in hist_df["net_points"]],
        )
        opt["tooltip"]["formatter"] = "GW{b}: {c} pts"
        charts.render(with_mark_line(opt, season_avg, f"Avg: {season_avg:.1f}"),
                      height="280px", key="mt_net_points")

except Exception as e:
    st.warning(f"Could not load points history: {e}")
