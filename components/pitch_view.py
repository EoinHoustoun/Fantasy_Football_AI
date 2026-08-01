"""Football pitch view component (redesigned · Overhaul Phase 2).

Renders a squad on a floodlit, stadium-depth pitch with HD FPL kits, laid out
GOALKEEPER → DEFENCE → MIDFIELD → ATTACK top-to-bottom (matching the official FPL
app). Each shirt can carry markers: captain/vice, penalty taker, DEFCON contributor,
and injury/doubt status. Built to fit one screen · the XI + bench without scrolling.

Two public entry points, unchanged signatures:
  render_pitch_view(squad_df)   · the live squad (My Team), enriched cards.
  render_squad_pitch(players)   · generic squads for the Season Lab (replay/drafts).

Kits come from components/team_identity.py (220px HD source, browser-downscaled).
Marker columns are optional · a card renders whatever it has.
"""

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from typing import List, Dict, Optional

# Bidirectional pitch host · clicks on ✕ / kits come back over the websocket
# (fluid, no page reload). See components/pitch_click/index.html.
_pitch_click = components.declare_component(
    "ff_pitch_click", path=str(Path(__file__).parent / "pitch_click"))


from components.team_identity import (
    shirt_url as _shirt_url,
    shirt_fallback_url,
    team_color,
)

# ── Stadium-depth pitch surface (shared by both renderers) ────────────────────
# Floodlight glow at top, vignette at bottom, subtle mown stripes over deep turf.
_PITCH_BG = (
    "background:"
    "radial-gradient(120% 78% at 50% -10%, rgba(255,255,255,0.16), transparent 42%),"
    "radial-gradient(90% 120% at 50% 118%, rgba(0,0,0,0.55), transparent 58%),"
    "repeating-linear-gradient(180deg, #0d3f20 0 48px, #12592e 48px 96px),"
    "#155f2c;"
    "border:1px solid rgba(255,255,255,0.14);border-radius:18px;overflow:hidden;"
    "position:relative;box-shadow:0 26px 70px rgba(0,0,0,0.5),"
    "inset 0 0 120px rgba(0,0,0,0.32);padding:14px 10px 10px;"
)

# Pitch line markings (centre circle, halfway, penalty boxes top+bottom).
_PITCH_LINES = (
    '<div style="position:absolute;inset:0;pointer-events:none;z-index:1;">'
    '<div style="position:absolute;top:50%;left:50%;width:132px;height:132px;'
    'border:2px solid rgba(255,255,255,0.22);border-radius:50%;'
    'transform:translate(-50%,-50%);"></div>'
    '<div style="position:absolute;top:50%;left:6%;right:6%;height:0;'
    'border-top:2px solid rgba(255,255,255,0.16);"></div>'
    '<div style="position:absolute;top:0;left:30%;right:30%;height:52px;'
    'border:2px solid rgba(255,255,255,0.16);border-top:0;border-radius:0 0 8px 8px;"></div>'
    '<div style="position:absolute;bottom:0;left:30%;right:30%;height:52px;'
    'border:2px solid rgba(255,255,255,0.16);border-bottom:0;border-radius:8px 8px 0 0;"></div>'
    '</div>'
)

_ROW_STYLE = ("display:flex;justify-content:space-evenly;align-items:flex-start;"
              "padding:11px 8px;position:relative;z-index:2;")

_DISPLAY = "'Archivo','SF Pro Display',sans-serif"


def _fdr_color(fdr: float) -> str:
    if fdr <= 2:
        return "#00FF87"
    if fdr <= 3:
        return "#FFD60A"
    if fdr <= 4:
        return "#FF8C42"
    return "#FF4B4B"


def _fixture_label(row: pd.Series, fixture_gw: Optional[int] = None) -> str:
    fixtures = row.get("upcoming_fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        return '<span style="color:rgba(255,255,255,0.4);">-</span>'
    nxt = None
    if fixture_gw is not None:
        for f in fixtures:
            if int(f.get("gw", -1) or -1) == int(fixture_gw):
                nxt = f
                break
        if nxt is None:
            return ('<span style="background:#444;color:#ccc;border-radius:4px;'
                    'padding:2px 6px;font-size:11px;font-weight:800;">BLANK</span>')
    else:
        nxt = fixtures[0]
    opp   = str(nxt.get("opp_short") or nxt.get("opponent", "?"))[:3].upper()
    home  = bool(nxt.get("home", False))
    fdr   = float(nxt.get("fdr", 3) or 3)
    side  = "H" if home else "A"
    color = _fdr_color(fdr)
    return (
        f'<span style="background:{color};color:#000;border-radius:4px;'
        f'padding:2px 6px;font-size:11px;font-weight:800;letter-spacing:0.3px;">'
        f'{opp} ({side})</span>'
    )


def _marker(pos: str, bg: str, glyph: str, color: str = "#000",
            pulse: bool = False) -> str:
    """A small corner badge on a kit. `pos` = css for placement (e.g. 'top:-8px;right:-8px')."""
    anim = "class=\"fplh-captain-pulse\" " if pulse else ""
    return (
        f'<div {anim}style="position:absolute;{pos};width:18px;height:18px;'
        f'border-radius:50%;display:grid;place-items:center;background:{bg};color:{color};'
        f'font-size:10px;font-weight:900;border:2px solid #0B0E13;'
        f'box-shadow:0 2px 4px rgba(0,0,0,0.4);">{glyph}</div>'
    )


def _num(val, default: float = 0.0) -> Optional[float]:
    try:
        if val is None or pd.isna(val):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _kit_markers(row) -> str:
    """Captain/vice (top-right), penalty (bottom-right), DEFCON (bottom-left),
    injury/doubt status (top-left). Each renders only when its data is present."""
    out = []
    # Captain / vice · top-right
    if bool(row.get("is_captain", False)):
        out.append(_marker("top:-8px;right:-8px", "#FFD700", "C", "#000", pulse=True))
    elif bool(row.get("is_vice_captain", False)):
        out.append(_marker("top:-8px;right:-8px", "#C9CDD6", "V", "#000"))
    # Penalty taker · bottom-right
    pen = _num(row.get("penalties_order"))
    if pen == 1:
        out.append(_marker("bottom:16px;right:-8px", "#FFB000", "P", "#000"))
    elif pen == 2:
        out.append(_marker("bottom:16px;right:-8px", "#C9CDD6", "P", "#000"))
    # DEFCON contributor · bottom-left
    defc = _num(row.get("defcon_monster_score"))
    if defc is not None and defc >= 0.35:
        out.append(_marker("bottom:16px;left:-8px", "#00FF87", "D", "#043"))
    # Status · top-left
    status = str(row.get("status", "a"))
    scol = {"i": "#FF4B4B", "d": "#FFA500", "s": "#333", "u": "#FF4B4B"}.get(status)
    if scol:
        out.append(_marker("top:-8px;left:-8px", scol, "", "#fff"))
    return "".join(out)


def _shirt_img(code: int, is_gkp: bool, width: int = 60) -> str:
    url = _shirt_url(code, is_gkp)
    fb  = shirt_fallback_url(is_gkp)
    return (
        f'<img src="{url}" width="{width}" onerror="this.src=\'{fb}\'" '
        f'style="display:block;filter:drop-shadow(0 5px 7px rgba(0,0,0,0.55));" />'
    )


def _nameplate(name: str, tcol: str, size: int = 12) -> str:
    cap = 12 if size >= 12 else 10
    label = (name[:cap - 1] + "…") if len(name) > cap else name
    return (
        f'<div style="color:#fff;padding:1px 4px;text-shadow:0 1px 3px rgba(0,0,0,0.8);'
        f'border-radius:4px;font-size:{size}px;font-weight:800;margin-top:5px;'
        f'white-space:nowrap;max-width:{"92" if size >= 12 else "72"}px;'
        f'overflow:hidden;text-overflow:ellipsis;'
        f'text-align:center;border-bottom:2px solid {tcol};">{label}</div>'
    )


def _axe_badge(fpl_id: int, gw: Optional[int] = None) -> str:
    """The always-visible transfer-out ✕ above a kit (planner mode).

    A data-attribute click target · the pitch_click component reports it over
    the websocket, so tapping is instant (no reload).
    """
    return (
        f'<span data-ffaction="axe" data-ffid="{fpl_id}" style="position:absolute;'
        f'top:-14px;left:50%;transform:translateX(-50%);width:20px;height:20px;'
        f'border-radius:50%;display:grid;place-items:center;background:#FF4B4B;'
        f'color:#fff;font-size:12px;font-weight:900;text-decoration:none;'
        f'border:2px solid #0B0E13;box-shadow:0 2px 6px rgba(0,0,0,0.5);'
        f'z-index:5;line-height:1;">×</span>'
    )


def _card(row: pd.Series, is_bench: bool = False,
          interactive: bool = False, fixture_gw: Optional[int] = None,
          detail_only: bool = False) -> str:
    code   = int(row.get("team_code", 1) or 1)
    is_gkp = str(row.get("position", "")) == "GKP"
    name   = str(row.get("web_name", "?"))
    fpl_id = int(row.get("fpl_id", 0) or 0)
    xp     = _num(row.get("ep_next")) or 0.0
    tcol   = team_color(row.get("team_short"))
    opacity = "0.62" if is_bench else "1"
    is_new = bool(row.get("_is_new", False))
    is_axed = bool(row.get("_is_axed", False))
    if is_axed:
        opacity = "0.38"

    shirt = _shirt_img(code, is_gkp)
    if (interactive or detail_only) and fpl_id:
        # Whole kit is a click target → opens the player's stats popup.
        shirt = (f'<span data-ffaction="detail" data-ffid="{fpl_id}">{shirt}</span>')
    axe = _axe_badge(fpl_id, fixture_gw) if interactive and fpl_id else ""
    ring = ("box-shadow:0 0 0 2px #00FF87,0 0 18px rgba(0,255,135,0.5);"
            "border-radius:8px;" if is_new else "")
    if is_axed:
        ring = ("outline:2px dashed #FF4B4B;outline-offset:2px;"
                "border-radius:8px;")

    return (
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'width:96px;opacity:{opacity};">'
        f'<div style="position:relative;display:inline-block;padding:2px;{ring}">'
        f'{axe}{shirt}{_kit_markers(row)}'
        f'</div>'
        f'{_nameplate(name, tcol)}'
        f'<div style="margin-top:4px;">{_fixture_label(row, fixture_gw)}</div>'
        f'<div style="color:#00FF87;font-size:13px;font-weight:800;margin-top:3px;'
        f'font-family:{_DISPLAY};">'
        f'{xp:.1f} <span style="color:rgba(255,255,255,0.5);font-weight:500;font-size:10px;">xP</span>'
        f'</div>'
        f'</div>'
    )


def _position_row(players: List[pd.Series], interactive: bool = False,
                  fixture_gw: Optional[int] = None,
                  detail_only: bool = False) -> str:
    return (f'<div style="{_ROW_STYLE}border-bottom:1px solid rgba(255,255,255,0.14);">'
            + "".join(_card(p, interactive=interactive, fixture_gw=fixture_gw,
                            detail_only=detail_only)
                      for p in players) + '</div>')


def _formation_bar(formation: str, title_right: str = "",
                   total: Optional[float] = None, total_label: str = "XI",
                   bench_total: Optional[float] = None) -> str:
    """Squad header · label, projected total, formation.

    The total lives here rather than in a tile below the pitch, because it is
    the number you want while you are looking at the team.
    """
    # This bar sits ABOVE the pitch, on the page background rather than on
    # grass, so it cannot use the white the cards use · in light mode that was
    # white-on-white and the squad total simply vanished. Theme variables reach
    # here because the component is handed theme.component_css().
    left = (f'<div style="color:var(--ff-muted);font-size:13px;font-weight:600;">'
            f'{title_right}</div>') if title_right else '<div></div>'
    mid = ""
    if total is not None:
        bench = (f'<span style="font-size:11px;font-weight:600;'
                 f'color:var(--ff-muted);margin-left:8px;">'
                 f'bench {bench_total:.1f}</span>' if bench_total is not None else "")
        mid = (f'<div style="display:flex;align-items:baseline;gap:7px;">'
               f'<span style="font-size:10px;font-weight:800;letter-spacing:0.16em;'
               f'text-transform:uppercase;color:var(--ff-muted);">'
               f'{total_label}</span>'
               f'<span style="font-family:{_DISPLAY};font-size:22px;font-weight:900;'
               f'color:var(--ff-mint);line-height:1;">{total:.1f}</span>{bench}</div>')
    return (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'gap:12px;flex-wrap:wrap;margin-bottom:8px;">{left}{mid}'
        f'<div style="font-family:{_DISPLAY};color:var(--ff-text);font-size:13px;'
        f'font-weight:800;letter-spacing:0.02em;">Formation '
        f'<span style="color:var(--ff-mint);">{formation}</span></div>'
        f'</div>'
    )


def _bench_strip(cards_html: str, compact: bool = False) -> str:
    pad = "7px 6px 9px" if compact else "12px 8px 14px"
    return (
        '<div style="border-top:2px dashed rgba(255,255,255,0.3);'
        f'padding:{pad};background:rgba(0,0,0,0.22);position:relative;z-index:2;">'
        '<div style="color:rgba(255,255,255,0.85);font-size:10px;letter-spacing:0.4em;'
        'text-align:center;margin-bottom:6px;font-weight:800;'
        'text-shadow:0 1px 2px rgba(0,0,0,0.4);">BENCH</div>'
        '<div style="display:flex;justify-content:center;gap:8px;">'
        + cards_html + '</div></div>'
    )


def _legend(interactive: bool = False) -> str:
    def chip(bg, g, txt, color="#000"):
        return (f'<span style="display:inline-flex;align-items:center;gap:5px;">'
                f'<span style="display:inline-grid;place-items:center;width:15px;height:15px;'
                f'border-radius:50%;background:{bg};color:{color};font-size:9px;font-weight:900;">{g}</span>'
                f'{txt}</span>')
    planner = (chip("#FF4B4B", "×", "Transfer out", "#fff")
               + '<span>Tap a kit for the player\'s stats</span>') if interactive else ""
    return (
        '<div style="display:flex;gap:16px;flex-wrap:wrap;justify-content:center;'
        'margin-top:10px;font-size:11px;color:rgba(255,255,255,0.5);">'
        + chip("#FFD700", "C", "Captain") + chip("#FFB000", "P", "Penalty")
        + chip("#00FF87", "D", "DEFCON", "#043")
        + chip("#FF4B4B", "", "Injury/doubt", "#fff")
        + planner
        + ('<span>xP = projected points for the viewed gameweek · '
           'fixture = OPP(H/A), FDR colour</span>' if interactive else
           '<span>xP = projected points, next gameweek · '
           'fixture = OPP(H/A), FDR colour</span>')
        + '</div>'
    )


def render_pitch_view(squad_df: pd.DataFrame, interactive: bool = False,
                      fixture_gw: Optional[int] = None,
                      title_right: str = "",
                      detail_only: bool = False,
                      key: str = "ff_pitch_planner"):
    """Render the live squad on the stadium pitch (GK→DEF→MID→FWD, top to bottom).

    Required columns: web_name, position, team_code, is_captain, is_vice_captain,
                      on_bench, squad_position, status.
    Optional (enrich the card): ep_next, upcoming_fixtures, team_short,
                      penalties_order, defcon_monster_score, _is_new (mint ring).

    `interactive` (planner mode): every kit gets a permanent ✕ transfer badge
    and the kit itself opens the player's stats popup. Rendered through the
    pitch_click component, whose return value is the last click
    ({action: "axe"|"detail", id, nonce}) · returned to the caller.
    `fixture_gw`: show each player's fixture FOR that gameweek (future planning)
    instead of their next fixture.
    """
    xi    = squad_df[~squad_df["on_bench"]].sort_values("squad_position")
    bench = squad_df[squad_df["on_bench"]].sort_values("squad_position")

    by_pos = {p: [r for _, r in xi.iterrows() if r["position"] == p]
              for p in ("GKP", "DEF", "MID", "FWD")}
    formation = f"{len(by_pos['DEF'])}-{len(by_pos['MID'])}-{len(by_pos['FWD'])}"
    bench_cards = "".join(
        _card(r, is_bench=True, interactive=interactive, fixture_gw=fixture_gw,
              detail_only=detail_only)
        for _, r in bench.iterrows())

    html = (
        '<div style="font-family:sans-serif;max-width:900px;margin:0 auto;">'
        + _formation_bar(formation, title_right)
        + f'<div style="{_PITCH_BG}">' + _PITCH_LINES
        + '<div style="position:relative;z-index:2;">'
        + _position_row(by_pos["GKP"], interactive, fixture_gw, detail_only)
        + _position_row(by_pos["DEF"], interactive, fixture_gw, detail_only)
        + _position_row(by_pos["MID"], interactive, fixture_gw, detail_only)
        + _position_row(by_pos["FWD"], interactive, fixture_gw, detail_only)
        + '</div>'
        + _bench_strip(bench_cards)
        + '</div>'
        + _legend(interactive)
        + '</div>'
    )
    if interactive or detail_only:
        from ui.theme import component_css
        return _pitch_click(html=component_css() + html, key=key, default=None)
    st.markdown(html, unsafe_allow_html=True)
    return None


# ── Generic pitch for Season Lab squads (perfect season, drafts) ───────────────
def _run_strip(fixtures: Optional[List[Dict]], big: bool = False) -> str:
    """The next few fixtures as FDR-coloured chips · the run at a glance.

    Three chips is the sweet spot: enough to read a run, few enough to stay
    inside a 96px card. Each chip is opponent + venue, coloured by difficulty.
    """
    if not fixtures:
        return ""
    _fs = 9.5 if big else 8
    _pad = "2px 5px" if big else "1px 3px"
    chips = []
    for f in fixtures[:3]:
        opp = str(f.get("opp") or "?")[:3].upper()
        if opp == "BLANK" or f.get("blank"):
            chips.append('<span style="background:rgba(255,255,255,0.12);color:'
                         'rgba(255,255,255,0.55);border-radius:3px;padding:1px 3px;'
                         'font-size:8px;font-weight:900;">BLK</span>')
            continue
        col = _fdr_color(float(f.get("fdr", 3) or 3))
        side = "" if f.get("home") else "·a"
        chips.append(f'<span style="background:{col};color:#04140C;border-radius:4px;'
                     f'padding:{_pad};font-size:{_fs}px;font-weight:900;'
                     f'letter-spacing:-0.2px;">{opp}{side}</span>')
    return (f'<div style="display:flex;gap:3px;margin-top:{5 if big else 4}px;'
            f'justify-content:center;">' + "".join(chips) + '</div>')


def _action_badge(action: str, fpl_id: int, glyph: str, bg: str,
                  placement: str, color: str = "#fff") -> str:
    """A kit action chip.

    A flat circle with a bare glyph read as a stray dot on a busy pitch. A
    rounded square with a lighter top edge, a real shadow and a hover state reads
    as a control, which is what it is.
    """
    return (
        f'<span class="ff-kit-act" data-ffaction="{action}" data-ffid="{fpl_id}" '
        f'style="position:absolute;{placement};width:17px;height:17px;'
        f'border-radius:6px;display:grid;place-items:center;'
        f'background:linear-gradient(160deg,{bg} 0%,{bg} 55%,rgba(0,0,0,0.22) 100%);'
        f'color:{color};font-size:10px;font-weight:800;line-height:1;'
        f'border:1.5px solid rgba(255,255,255,0.30);'
        f'box-shadow:0 3px 9px rgba(0,0,0,0.45),inset 0 1px 0 rgba(255,255,255,0.28);'
        f'z-index:5;">{glyph}</span>')


def _corner_button(action: str, fpl_id: int, glyph: str, bg: str,
                   placement: str) -> str:
    """A control pinned to a CORNER OF THE CARD, never over the shirt.

    On the jersey these read as part of the player and were easy to hit by
    accident. In the corner of a card they read as what they are: the card's
    controls.
    """
    return (
        f'<span class="ff-kit-act" data-ffaction="{action}" data-ffid="{fpl_id}" '
        f'style="position:absolute;{placement};width:17px;height:17px;'
        f'border-radius:6px;display:grid;place-items:center;z-index:6;'
        f'background:{bg};color:#fff;font-size:11px;font-weight:800;line-height:1;'
        f'border:1px solid rgba(255,255,255,0.35);'
        f'box-shadow:0 2px 6px rgba(0,0,0,0.45);">{glyph}</span>')


def _simple_card(row: Dict, stat_label: str = "pts", is_bench: bool = False,
                 interactive: bool = False, compact: bool = False) -> str:
    """One player as a card on the pitch.

    The card is the object, not the kit. It carries its own dark ground so it
    reads clearly against grass, its controls live in its corners rather than on
    the shirt, and the two numbers that decide a pick · the upcoming run and the
    projection · get the space they deserve. Wide enough to fit all that, tight
    enough that a whole row still sits together.
    """
    W, SHIRT = (100, 36) if compact else (120, 52)
    FS_NAME = 11 if compact else 12.5
    FS_STAT = 17 if compact else 20
    FS_PRICE = 10 if compact else 11

    code = int(row.get("team_code", 1) or 1)
    is_gkp = str(row.get("position", "")) == "GKP"
    name = str(row.get("web_name", "?"))
    tcol = team_color(row.get("team_short"))
    is_axed = bool(row.get("is_axed", False))
    opacity = "0.4" if is_axed else ("0.66" if is_bench else "1")

    # Kit markers that belong ON the shirt: the armband, the penalty flag, and
    # the minutes warning. The transfer controls do not · they go in the card's
    # corners, where they never sit over a player.
    markers = ""
    if bool(row.get("is_captain", False)):
        markers = _marker("top:-7px;right:-7px", "#FFD700", "C", "#000", pulse=True)
    if _num(row.get("penalties_order")) == 1:
        markers += ('<span title="Takes the penalties" style="position:absolute;'
                    'bottom:-4px;right:-6px;width:15px;height:15px;border-radius:5px;'
                    'display:grid;place-items:center;background:#FFB000;color:#000;'
                    'font-size:9px;font-weight:900;line-height:1;'
                    'border:1.5px solid rgba(0,0,0,0.4);">P</span>')
    mins = _num(row.get("exp_mins"))
    if mins is not None and mins < 45:
        markers += ('<span title="Barely any minutes expected" style="position:absolute;'
                    'bottom:-4px;left:-6px;width:15px;height:15px;border-radius:5px;'
                    'display:grid;place-items:center;background:#FF4B4B;color:#fff;'
                    'font-size:9px;font-weight:900;line-height:1;'
                    'border:1.5px solid rgba(0,0,0,0.4);">!</span>')

    _shirt = _shirt_img(code, is_gkp, width=SHIRT)
    _pid = row.get("fpl_id")
    corners = ""
    if interactive and _pid:
        _shirt = f'<span data-ffaction="detail" data-ffid="{int(_pid)}">{_shirt}</span>'
        if row.get("allow_axe"):
            corners += _corner_button(
                "unaxe" if is_axed else "axe", int(_pid), "↺" if is_axed else "×",
                "#6b7280" if is_axed else "#FF4B4B", "top:4px;left:4px")
        if row.get("allow_bench"):
            corners += _corner_button(
                "bench", int(_pid), "↑" if is_bench else "↓", "#04C7DE",
                "top:4px;right:4px")

    # Swap state, in priority order: the player being subbed, then anyone who
    # can legally come on for him.
    if row.get("is_sub_source"):
        edge = ("border-color:#04F5FF;box-shadow:0 0 0 2px rgba(4,245,255,0.45),"
                "0 6px 16px rgba(0,0,0,0.4);")
    elif row.get("swap_ok"):
        edge = ("border-color:#00FF87;box-shadow:0 0 0 2px rgba(0,255,135,0.4),"
                "0 6px 16px rgba(0,0,0,0.4);"
                "animation:fplh-swap-ready 1.1s ease-in-out infinite;")
    elif is_axed:
        edge = "border-color:#FF4B4B;border-style:dashed;"
    else:
        edge = ""

    price = _num(row.get("price"))
    stat = _num(row.get("stat"))
    dp = int(row.get("stat_dp", 0))

    # The run gets real estate · it is half the reason you are looking.
    fixtures = row.get("fixtures")
    fixture_html = _run_strip(fixtures, big=True) if fixtures else ""
    if not fixture_html and row.get("fixture_label"):
        fixture_html = (f'<div style="color:#fff;font-size:10px;font-weight:800;'
                        f'margin-top:5px;background:rgba(0,0,0,0.4);'
                        f'border-radius:4px;padding:2px 6px;">{row["fixture_label"]}</div>')

    # Price on the left, projection on the right and large · the projection is
    # the number you are comparing, so it should be the loudest thing here.
    foot = ""
    if price is not None or stat is not None:
        left = (f'<span style="font-size:{FS_PRICE}px;font-weight:700;'
                f'color:rgba(255,255,255,0.72);">£{price:.1f}</span>'
                if price is not None else "<span></span>")
        right = (f'<span class="ff-pitch-stat" style="font-size:{FS_STAT}px;'
                 f'font-weight:900;color:#00FF87;font-family:{_DISPLAY};'
                 f'line-height:1;">{stat:.{dp}f}</span>'
                 if stat is not None else "")
        foot = (f'<div style="display:flex;align-items:baseline;'
                f'justify-content:space-between;width:100%;margin-top:4px;'
                f'padding:0 2px;">{left}{right}</div>')

    return (
        f'<div style="position:relative;display:flex;flex-direction:column;'
        f'align-items:center;width:{W}px;opacity:{opacity};'
        f'background:linear-gradient(180deg,rgba(23,32,52,0.90) 0%,'
        f'rgba(14,20,34,0.94) 100%);'
        f'border:1.5px solid rgba(255,255,255,0.22);{edge}'
        f'border-radius:12px;padding:{"17px 6px 6px" if compact else "19px 8px 8px"};'
        f'box-shadow:0 6px 18px rgba(0,0,0,0.42),'
        f'inset 0 1px 0 rgba(255,255,255,0.16);">'
        f'{corners}'
        f'<div style="position:relative;display:inline-block;">{_shirt}{markers}</div>'
        f'<div style="color:#fff;font-size:{FS_NAME}px;font-weight:800;margin-top:4px;'
        f'white-space:nowrap;max-width:{W - 12}px;overflow:hidden;'
        f'text-overflow:ellipsis;text-align:center;padding-bottom:2px;'
        f'border-bottom:2px solid {tcol};">{name}</div>'
        f'{fixture_html}{foot}</div>'
    )


def render_squad_pitch(players: List[Dict], stat_label: str = "pts",
                       title_right: str = "",
                       interactive: bool = False,
                       compact: bool = False,
                       show_total: bool = True,
                       xi_total_override: Optional[float] = None,
                       total_label: str = "XI",
                       key: str = "ff_pitch_replay"):
    """Generic pitch for Season Lab squads (GK→DEF→MID→FWD, top to bottom).

    Each player dict: web_name, position (GKP/DEF/MID/FWD), team_code, on_bench.
    Optional: is_captain, stat (number under name), price, team_short,
    fixture_label, fixtures (list of {opp, home, fdr}), exp_mins, allow_axe,
    allow_bench, is_axed.

    `compact` shrinks every dimension so the fifteen plus the bench fit a laptop
    screen without scrolling.
    """
    xi = [p for p in players if not p.get("on_bench")]
    bench = [p for p in players if p.get("on_bench")]

    by_pos = {pos: [p for p in xi if p.get("position") == pos]
              for pos in ("GKP", "DEF", "MID", "FWD")}
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: -(p.get("stat") or 0))
    bench_order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    bench = sorted(bench, key=lambda p: (bench_order.get(p.get("position"), 4),
                                         -(p.get("stat") or 0)))
    formation = f"{len(by_pos['DEF'])}-{len(by_pos['MID'])}-{len(by_pos['FWD'])}"
    # The caller may already have a truer total than the sum of the cards ·
    # the XI tile doubles the captain, and two different numbers both labelled
    # "XI GW1" on the same screen is worse than either being slightly off.
    xi_total = (xi_total_override if xi_total_override is not None
                else (sum((p.get("stat") or 0) for p in xi) if show_total else None))
    if not show_total:
        xi_total = None
    bench_total = sum((p.get("stat") or 0) for p in bench) if show_total else None

    pad = "3px 5px" if compact else "7px 7px"
    # Five defenders of fixed-width card do not fit 560px of content column, and
    # a clipped card hides the very numbers the card exists to show. Wrapping
    # costs a little height and keeps every player readable.
    row_style = ("display:flex;justify-content:center;align-items:flex-start;"
                 "flex-wrap:wrap;"
                 f"gap:{6 if compact else 9}px;padding:{pad};"
                 "position:relative;z-index:2;")

    def _row(ps):
        return (f'<div style="{row_style}">'
                + "".join(_simple_card(p, stat_label, interactive=interactive,
                                       compact=compact)
                          for p in ps) + '</div>')

    bench_cards = "".join(_simple_card(p, stat_label, is_bench=True,
                                       interactive=interactive, compact=compact)
                          for p in bench)

    pitch_bg = _PITCH_BG.replace("padding:14px 10px 10px;", "padding:8px 6px 6px;") \
        if compact else _PITCH_BG
    html = (
        f'<div style="font-family:sans-serif;max-width:{900 if compact else 1040}px;'
        f'margin:0 auto;">'
        + _formation_bar(formation, title_right, xi_total,
                         f"{total_label} {stat_label}", bench_total)
        + f'<div style="{pitch_bg}">' + _PITCH_LINES
        + '<div style="position:relative;z-index:2;">'
        + _row(by_pos["GKP"]) + _row(by_pos["DEF"])
        + _row(by_pos["MID"]) + _row(by_pos["FWD"])
        + '</div>'
        + _bench_strip(bench_cards, compact)
        + '</div></div>'
    )
    if interactive:
        # The iframe does not inherit the host's custom properties, so hand the
        # palette over explicitly or the chrome around the pitch ignores the theme.
        from ui.theme import component_css
        return _pitch_click(html=component_css() + html, key=key, default=None)
    st.markdown(html, unsafe_allow_html=True)
    return None
