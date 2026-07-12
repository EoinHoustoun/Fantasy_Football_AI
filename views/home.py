"""
Home · Gameweek command center.

The app's front door. Answers "what do I do this gameweek?" at a glance for any
FPL team ID: recommended captain, best transfer target, chip timing, and squad
risk flags · each linking into the dedicated page for the full analysis. Below
that sits the GW hero and a live-pulse strip of the week's biggest movers.

Reuses the importable engines (get_team_squad, get_top_recommendation) and data
already on players_df (ep_next, DGW flags, status). The deep captain/chip models
live inside their own pages; here we surface a fast headline and link out.

set_page_config, global CSS, animations, and the core data load are owned by the
app.py router (st.navigation entrypoint) · not re-declared here.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from config import FPL_TEAM_ID
from components.team_identity import team_dot, team_color


# ── Gaffer's Briefing (local-AI narrative; cached so it doesn't re-run each rerun) ─
@st.cache_data(ttl=1800, show_spinner=False)
def _gaffers_briefing_ai(facts_key: Tuple[Tuple[str, object], ...]) -> Optional[str]:
    """LLM briefing from a hashable facts key. Cached per unique situation.

    Returns None if Ollama is unavailable/slow so the caller keeps the template.
    """
    from ai.briefing import ai_briefing
    return ai_briefing(dict(facts_key))


def _briefing_card_html(text: str, ai_live: bool) -> str:
    badge = (
        '<span style="font-size:9px;font-weight:800;letter-spacing:0.12em;'
        'text-transform:uppercase;color:#00FF87;background:rgba(0,255,135,0.10);'
        'border:1px solid rgba(0,255,135,0.35);border-radius:999px;padding:2px 8px;">'
        '✨ AI</span>'
        if ai_live else
        '<span style="font-size:9px;font-weight:800;letter-spacing:0.12em;'
        'text-transform:uppercase;color:rgba(255,255,255,0.45);'
        'background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.12);'
        'border-radius:999px;padding:2px 8px;">Auto</span>'
    )
    return f"""
<div class="fplh-card-hover fplh-animate-in" style="
    margin-top:16px;background:rgba(22,26,34,0.85);
    border:1px solid rgba(255,255,255,0.08);border-left:3px solid #FFD700;
    border-radius:14px;padding:16px 20px;font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
    <span style="font-size:15px;">🎙️</span>
    <span style="font-size:11px;letter-spacing:0.2em;color:rgba(255,255,255,0.5);
         text-transform:uppercase;font-weight:800;">Gaffer's Briefing</span>
    {badge}
  </div>
  <div style="font-size:14px;line-height:1.6;color:#eef1f5;">{text}</div>
</div>"""


# ── Branding asset ─────────────────────────────────────────────────────────────
_PL_LOGO_PATH = Path(__file__).parent.parent / "assets" / "prem_symbol.jpg"


@st.cache_data(show_spinner=False)
def _pl_logo_data_url() -> str:
    if not _PL_LOGO_PATH.exists():
        return ""
    with open(_PL_LOGO_PATH, "rb") as f:
        b = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/jpeg;base64,{b}"


PL_LOGO_URL = _pl_logo_data_url()


# ── Read shared state (populated by the app.py router) ─────────────────────────
players_df = st.session_state.get("players_df")
bs          = st.session_state.get("bootstrap") or {}
fixtures_df = st.session_state.get("fixtures_df")
current_gw  = st.session_state.get("current_gw")
season_phase = st.session_state.get("season_phase") or {}

if players_df is None:
    st.info("Loading data… if this persists, use **🔄 Refresh Data** in the sidebar.")
    st.stop()


# ── Cached squad loader ─────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _load_squad(team_id: int, gw: int) -> Optional[pd.DataFrame]:
    from data.fetchers.fpl_api import get_team_squad
    squad_df, _ = get_team_squad(team_id, gw, bootstrap=st.session_state.get("bootstrap"))
    return squad_df


@st.cache_data(ttl=1800, show_spinner=False)
def _best_transfer_in(owned_names: Tuple[str, ...]):
    """Top player to buy in, excluding those already owned. Returns a Series or None."""
    from analytics.transfer_engine import get_top_recommendation
    reco = get_top_recommendation(players_df, owned_names=list(owned_names))
    return reco.get("top") if isinstance(reco, dict) else None


# ── Deadline countdown ─────────────────────────────────────────────────────────
def _next_deadline(bootstrap: dict) -> Optional[datetime]:
    for ev in bootstrap.get("events", []):
        if ev.get("is_next") or (ev.get("is_current") and not ev.get("finished")):
            raw = ev.get("deadline_time")
            if raw:
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    return None
    return None


def _format_countdown(dt: datetime) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    delta = dt - now
    if delta.total_seconds() <= 0:
        return "Deadline passed", "#FF4B4B"
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes = rem // 60
    if days > 0:
        return f"{days}d {hours}h to deadline", "#00FF87" if days > 1 else "#FFA500"
    if hours > 0:
        return f"{hours}h {minutes}m to deadline", "#FFA500" if hours > 6 else "#FF4B4B"
    return f"{minutes}m to deadline", "#FF4B4B"


deadline = _next_deadline(bs)
deadline_text, deadline_color = ("", "#00FF87")
if deadline:
    deadline_text, deadline_color = _format_countdown(deadline)


# ── Hero ────────────────────────────────────────────────────────────────────────
_lion_bg = f"url('{PL_LOGO_URL}') no-repeat right center / contain" if PL_LOGO_URL else ""
_hero_background_layers = [
    "radial-gradient(circle at top left, rgba(0,255,135,0.18), transparent 55%)",
    "radial-gradient(circle at bottom right, rgba(55,0,60,0.35), transparent 65%)",
    "linear-gradient(90deg, rgba(14,17,22,0.98) 0%, rgba(14,17,22,0.92) 45%, rgba(14,17,22,0.4) 70%, rgba(14,17,22,0) 100%)",
    _lion_bg if _lion_bg else "linear-gradient(135deg, #1a1f2b, #0e1116)",
]
_hero_bg_css = ", ".join([l for l in _hero_background_layers if l])

_deadline_pill = ""
if deadline_text:
    _deadline_pill = (
        f'<div style="background:rgba(0,0,0,0.35);border:1px solid {deadline_color}66;'
        f'border-radius:999px;padding:9px 18px;display:inline-flex;align-items:center;'
        f'gap:8px;backdrop-filter:blur(8px);">'
        f'<span style="font-size:14px;">🕒</span>'
        f'<span style="font-size:13px;font-weight:800;color:{deadline_color};'
        f'letter-spacing:0.02em;">{deadline_text}</span></div>'
    )

st.markdown(
    f"""
<div class="fplh-animate-in" style="
    position:relative;padding:42px 40px;margin-bottom:22px;border-radius:20px;
    min-height:180px;background: {_hero_bg_css};
    border:1px solid rgba(255,255,255,0.08);
    font-family:'Inter','SF Pro Display',sans-serif;overflow:hidden;
    box-shadow:0 10px 40px rgba(0,0,0,0.35);">
  <div style="position:relative;z-index:1;max-width:60%;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
      <span style="display:inline-block;width:6px;height:6px;border-radius:50%;
             background:#00FF87;box-shadow:0 0 10px #00FF87;"></span>
      <span style="font-size:11px;letter-spacing:0.24em;color:rgba(255,255,255,0.55);
             text-transform:uppercase;font-weight:800;">FPL Analytics Hub</span>
    </div>
    <div style="font-size:48px;font-weight:900;color:#fff;letter-spacing:-1.3px;
         line-height:1;margin-bottom:14px;">
      Gameweek <span style="color:#00FF87;">{current_gw if current_gw is not None else "-"}</span>
    </div>
    {_deadline_pill}
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ── Honest data-status banner (frames the summer changeover) ───────────────────
_sim = st.session_state.get("simulating_gw")
_phase = season_phase.get("phase", "unknown")
if _sim:
    st.markdown(
        f"""
<div class="fplh-animate-in" style="display:flex;align-items:center;gap:12px;
     background:rgba(4,245,255,0.06);border:1px solid #04f5ff55;border-left:3px solid #04f5ff;
     border-radius:12px;padding:12px 16px;margin-bottom:20px;font-family:'Inter',sans-serif;">
  <span style="font-size:20px;flex-shrink:0;">🧪</span>
  <div>
    <div style="font-size:12px;font-weight:800;letter-spacing:0.04em;color:#04f5ff;text-transform:uppercase;">
      Simulating Gameweek {_sim}</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.62);margin-top:2px;line-height:1.4;">
      Off-season sandbox · GW1's fixtures are replayed as a synthetic next gameweek so every fixture &amp;
      form tool (transfers, free hit, pick team) works for the future. Toggle off in the sidebar once the real season launches.</div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )
elif _phase != "inseason":
    _pc = "#FFA500" if _phase == "offseason" else "#00FF87" if _phase == "preseason" else "#04f5ff"
    _icon = {"offseason": "🏁", "preseason": "🌱"}.get(_phase, "ℹ️")
    st.markdown(
        f"""
<div class="fplh-animate-in" style="display:flex;align-items:center;gap:12px;
     background:rgba(255,255,255,0.03);border:1px solid {_pc}55;border-left:3px solid {_pc};
     border-radius:12px;padding:12px 16px;margin-bottom:20px;font-family:'Inter',sans-serif;">
  <span style="font-size:20px;flex-shrink:0;">{_icon}</span>
  <div>
    <div style="font-size:12px;font-weight:800;letter-spacing:0.04em;color:{_pc};
         text-transform:uppercase;">{season_phase.get("title", "")}</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.62);margin-top:2px;line-height:1.4;">
      {season_phase.get("note", "")}</div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# ── Section header helper ───────────────────────────────────────────────────────
def _section_header(title: str) -> None:
    st.markdown(
        f"""<div style="margin:6px 0 12px;display:flex;align-items:center;gap:14px;">
          <div style="font-size:11px;letter-spacing:0.22em;color:rgba(255,255,255,0.45);
               text-transform:uppercase;font-weight:800;">{title}</div>
          <div style="flex:1;height:1px;background:rgba(255,255,255,0.07);"></div>
        </div>""",
        unsafe_allow_html=True,
    )


# ── Team ID input (demo default, shared across pages via session_state) ────────
_default_id = st.session_state.get("squad_team_id") or (int(FPL_TEAM_ID) if FPL_TEAM_ID else 38148)

id_col, hint_col = st.columns([1, 3])
with id_col:
    team_id = st.number_input(
        "Your FPL Team ID", min_value=1, value=int(_default_id), step=1,
        key="home_team_id", help="Find it in the FPL website URL: /entry/<ID>/",
    )
st.session_state.squad_team_id = int(team_id)
_is_demo = int(team_id) == (int(FPL_TEAM_ID) if FPL_TEAM_ID else 38148)
with hint_col:
    st.markdown(
        f"<div style='padding-top:30px;font-size:12px;color:rgba(255,255,255,0.5);'>"
        f"{'👋 Showing a <b>demo team</b> · enter your own ID above to personalise every page.' if _is_demo else 'Your team is set across every page.'}"
        f"</div>",
        unsafe_allow_html=True,
    )


# ── Command card renderer ───────────────────────────────────────────────────────
def _command_card(kicker: str, headline: str, sub: str, accent: str,
                   dot_short: Optional[str] = None) -> str:
    crest = ""
    if dot_short is not None:
        crest = (
            f'<span style="position:absolute;top:16px;right:16px;">'
            f'{team_dot(dot_short, size=14)}</span>'
        )
    return f"""
<div class="fplh-card-hover fplh-animate-in" style="
    position:relative;background:rgba(22,26,34,0.85);
    border:1px solid rgba(255,255,255,0.08);border-top:3px solid {accent};
    border-radius:14px;padding:18px 18px 14px;min-height:132px;
    font-family:'Inter',sans-serif;">
  {crest}
  <div style="font-size:10px;letter-spacing:0.16em;text-transform:uppercase;
       font-weight:800;color:{accent};margin-bottom:10px;">{kicker}</div>
  <div style="font-size:22px;font-weight:900;color:#fff;line-height:1.05;
       letter-spacing:-0.4px;margin-bottom:6px;max-width:88%;overflow:hidden;
       text-overflow:ellipsis;white-space:nowrap;">{headline}</div>
  <div style="font-size:12px;color:rgba(255,255,255,0.55);line-height:1.35;">{sub}</div>
</div>
"""


# ── Build the four answers ──────────────────────────────────────────────────────
_section_header(f"Your Gameweek {current_gw if current_gw is not None else ''} plan")

squad_df = None
if current_gw is not None:
    try:
        from components.loading import LINES_SQUAD, fpl_loader
        with fpl_loader(f"Reading team {int(team_id)}", LINES_SQUAD):
            squad_df = _load_squad(int(team_id), int(current_gw))
    except Exception:
        squad_df = None

if squad_df is None or squad_df.empty:
    st.info("Couldn't load that squad. Check the Team ID, or use **🔄 Refresh Data**. "
            "Meanwhile, explore the sidebar sections below.")
else:
    owned_ids   = set(squad_df["fpl_id"].tolist())
    owned       = players_df[players_df["fpl_id"].isin(owned_ids)].copy()
    owned_names = tuple(squad_df["web_name"].tolist())

    # 1) Captain · highest expected points in the available squad
    cap_pool = owned[owned["status"] == "a"].sort_values("ep_next", ascending=False)
    if cap_pool.empty:
        cap_pool = owned.sort_values("ep_next", ascending=False)
    cap = cap_pool.iloc[0] if not cap_pool.empty else None

    # 2) Best transfer in
    try:
        top_in = _best_transfer_in(owned_names)
    except Exception:
        top_in = None

    # 3) Chip timing · nearest upcoming Double Gameweek among owned players
    dgw_gws = sorted({
        int(g) for lst in owned.get("dgw_gameweeks", pd.Series([], dtype=object)).dropna()
        for g in (lst or []) if g and int(g) >= int(current_gw)
    })

    # 4) Risk · flagged players in the squad
    flagged = squad_df[squad_df["status"].isin(["i", "d", "s", "u"])].copy()

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        if cap is not None:
            st.markdown(_command_card(
                "Captain pick", str(cap["web_name"]),
                f"{float(cap.get('ep_next') or 0):.1f} xP · {cap.get('team_short','')}",
                "#FFD700", cap.get("team_short"),
            ), unsafe_allow_html=True)
        else:
            st.markdown(_command_card("Captain pick", "-", "No squad data", "#FFD700"),
                        unsafe_allow_html=True)
        st.page_link("views/06_captain_picker.py", label="Full captain analysis →")

    with c2:
        if top_in is not None:
            st.markdown(_command_card(
                "Best transfer in", str(top_in.get("web_name", "-")),
                f"{float(top_in.get('ep_next') or 0):.1f} xP · {top_in.get('team_short','')} · {top_in.get('position','')}",
                "#00FF87", top_in.get("team_short"),
            ), unsafe_allow_html=True)
        else:
            st.markdown(_command_card("Best transfer in", "-", "No target found", "#00FF87"),
                        unsafe_allow_html=True)
        st.page_link("views/02_transfer_suggestions.py", label="Transfer suggestions →")

    with c3:
        if dgw_gws:
            st.markdown(_command_card(
                "Chip window", f"GW{dgw_gws[0]} double",
                "Strong Bench Boost / Triple Captain timing", "#04f5ff",
            ), unsafe_allow_html=True)
        else:
            st.markdown(_command_card(
                "Chip window", "Hold chips",
                "No double gameweek in your squad yet", "#04f5ff",
            ), unsafe_allow_html=True)
        st.page_link("views/14_chip_planner.py", label="Plan your chips →")

    with c4:
        n_flag = len(flagged)
        if n_flag:
            worst = flagged.sort_values("web_name").iloc[0]
            _labels = {"i": "injured", "d": "doubtful", "s": "suspended", "u": "unavailable"}
            st.markdown(_command_card(
                "Squad risks", f"{n_flag} flagged",
                f"{worst['web_name']} · {_labels.get(str(worst['status']), 'check')}",
                "#FF4B4B", worst.get("team_short"),
            ), unsafe_allow_html=True)
        else:
            st.markdown(_command_card("Squad risks", "All fit", "No injuries or doubts", "#00FF87"),
                        unsafe_allow_html=True)
        st.page_link("views/08_injuries.py", label="Injury news →")

    # ── Gaffer's Briefing · natural-language read on the four answers above ──────
    _risks_text = None
    if len(flagged):
        _worst = flagged.sort_values("web_name").iloc[0]
        _rlabels = {"i": "injured", "d": "doubtful", "s": "suspended", "u": "unavailable"}
        _risks_text = (
            f"{len(flagged)} flagged"
            + (f", e.g. {_worst['web_name']} ({_rlabels.get(str(_worst['status']), 'check')})"
               if _worst is not None else "")
        )
    _chip_text = (
        f"GW{dgw_gws[0]} double · strong Bench Boost / Triple Captain window"
        if dgw_gws else "No double gameweek in your squad yet, hold chips"
    )
    _ctx = {
        "gw": current_gw,
        "deadline_text": deadline_text or "",
        "captain": (str(cap["web_name"]) if cap is not None else None),
        "captain_xp": (f"{float(cap.get('ep_next') or 0):.1f}" if cap is not None else None),
        "transfer_in": (str(top_in.get("web_name")) if top_in is not None else None),
        "transfer_xp": (f"{float(top_in.get('ep_next') or 0):.1f}" if top_in is not None else None),
        "chip": _chip_text,
        "risks": _risks_text,
    }
    _key = tuple(sorted(_ctx.items(), key=lambda kv: kv[0]))

    try:
        from ai.briefing import template_briefing, used_ai
        _tmpl = template_briefing(_ctx)
        _ai_avail = used_ai()
    except Exception:
        _tmpl, _ai_avail = None, False

    if _tmpl:
        # Instant deterministic briefing renders immediately · the front door never
        # blocks on the model. The AI rewrite (slow on this Mac) is opt-in and
        # cached: once generated for a situation it persists in session state.
        _ai_done = st.session_state.get("_briefing_ai_cache", {}).get(_key)
        _slot = st.empty()
        _slot.markdown(_briefing_card_html(_ai_done or _tmpl, bool(_ai_done)),
                       unsafe_allow_html=True)

        if _ai_avail and not _ai_done:
            # No st.rerun() here · Streamlit reruns on click; we update the slot in-place.
            if st.button("✨ Sharpen with AI", key="briefing_ai_btn",
                         help="Rewrite the briefing with the local model (first run is slow)."):
                with fpl_loader("The gaffer is thinking", ["Reading your gameweek…", "Checking the fixtures…", "Choosing the words…"]):
                    _got = _gaffers_briefing_ai(_key)
                if _got:
                    st.session_state.setdefault("_briefing_ai_cache", {})[_key] = _got
                    _slot.markdown(_briefing_card_html(_got, True), unsafe_allow_html=True)


st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)


# ── Live pulse strip (biggest movers this week) ─────────────────────────────────
def _pulse_tile(emoji: str, label: str, primary: str, secondary: str, accent: str) -> str:
    return f"""
<div class="fplh-card-hover fplh-animate-in" style="
    background:rgba(22,26,34,0.85);border:1px solid rgba(255,255,255,0.08);
    border-left:3px solid {accent};border-radius:12px;padding:14px 16px;
    font-family:'Inter',sans-serif;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
    <span style="font-size:16px;">{emoji}</span>
    <span style="font-size:10px;color:rgba(255,255,255,0.45);
           letter-spacing:0.15em;font-weight:700;text-transform:uppercase;">{label}</span>
  </div>
  <div style="font-size:18px;font-weight:900;color:#fff;line-height:1.1;">{primary}</div>
  <div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:2px;">{secondary}</div>
</div>
"""


_section_header("This week across the game")

_qualified = players_df[players_df["minutes"].fillna(0) >= 450]
if _qualified.empty:
    _qualified = players_df

top_form   = _qualified.nlargest(1, "form").iloc[0]
top_in     = players_df.nlargest(1, "transfers_in_event").iloc[0]
top_out    = players_df.nlargest(1, "transfers_out_event").iloc[0]
n_injured  = int((players_df["status"] == "i").sum())
n_doubtful = int((players_df["status"] == "d").sum())

pulse_cols = st.columns(4)
with pulse_cols[0]:
    st.markdown(_pulse_tile("⚡", "Best form", f"{top_form['web_name']}",
        f"{float(top_form['form']):.1f} pts/game · {top_form['team']}", "#00FF87"),
        unsafe_allow_html=True)
with pulse_cols[1]:
    st.markdown(_pulse_tile("📈", "Most transferred in", f"{top_in['web_name']}",
        f"+{int(top_in['transfers_in_event']):,} this GW", "#04f5ff"),
        unsafe_allow_html=True)
with pulse_cols[2]:
    st.markdown(_pulse_tile("📤", "Most transferred out", f"{top_out['web_name']}",
        f"-{int(top_out['transfers_out_event']):,} this GW", "#FF4B4B"),
        unsafe_allow_html=True)
with pulse_cols[3]:
    st.markdown(_pulse_tile("🚑", "Unavailable", f"{n_injured} injured",
        f"{n_doubtful} doubtful", "#FFA500"),
        unsafe_allow_html=True)
