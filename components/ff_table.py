"""Styled, theme-aware, clickable tables.

Streamlit's dataframe is a canvas grid. It cannot be styled with CSS, it paints
against Streamlit's configured base theme rather than ours (so it stays dark in
light mode), and its row hit testing is opaque. This module renders real HTML
instead, through a small bidirectional component, which buys three things:

  * the app's own look, following `--ff-*` variables in both themes
  * rich cells · faces, coloured chips, inline bars, fixture runs, action buttons
  * reliable clicks, reported the same way the pitch reports them

Build a table from column specs so callers stay declarative:

    cols = [
        col_face("code"), col_player("web_name", sub="team_short"),
        col_num("price", "£m", fmt="%.1f"),
        col_bar("pts", "Season", max_value=200),
        col_action("code", "swap", "+"),
    ]
    click = render(rows, cols, key="candidates")

`rows` is a list of dicts (or a DataFrame). Every spec is a plain dict, so a
page can build one inline when nothing here fits.
"""

from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ui.theme import FDR_COLORS, component_css, fill

_component = components.declare_component(
    "ff_table", path=str(Path(__file__).parent / "ff_table"))

ALIGN_NUM = "num"


def _esc(v: Any) -> str:
    return _html.escape("" if v is None else str(v))


def _num(v, default=None):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# ── Column specs ──────────────────────────────────────────────────────────────
def col_face(key: str, url_fn: Optional[Callable] = None, pinned: bool = True) -> Dict:
    """A round player headshot. `url_fn` maps the cell value to an image URL."""
    return {"kind": "face", "key": key, "label": "", "url_fn": url_fn,
            "pinned": pinned, "width": 34}


def col_player(key: str, label: str = "Player", sub: Optional[str] = None,
               pinned: bool = True, action: Optional[str] = None,
               id_key: str = "code") -> Dict:
    """Name, with an optional muted second line (club, position).

    Pass `action` to make the name itself clickable · the obvious target for
    "tell me about this player", and better than a separate icon column.
    """
    return {"kind": "player", "key": key, "label": label, "sub": sub,
            "pinned": pinned, "action": action, "id_key": id_key}


def col_text(key: str, label: str, align: str = "") -> Dict:
    return {"kind": "text", "key": key, "label": label, "align": align}


def col_num(key: str, label: str, fmt: str = "%.1f", align: str = ALIGN_NUM,
            color_fn: Optional[Callable] = None, empty: str = "") -> Dict:
    """A number. `color_fn(value)` may return a colour to tint it.

    `empty` is what to print when there is no value. A bare dot reads as a bug
    and tells the reader nothing · say WHY the cell is blank ("no forecast").
    """
    return {"kind": "num", "key": key, "label": label, "fmt": fmt,
            "align": align, "color_fn": color_fn, "empty": empty}


def col_bar(key: str, label: str, max_value: float, color: str = "mint",
            fmt: str = "%.0f") -> Dict:
    """An inline bar with the value on it · rank at a glance beats a decimal."""
    return {"kind": "bar", "key": key, "label": label, "max": max_value,
            "color": color, "fmt": fmt}


def col_chip(key: str, label: str, color_fn: Callable, align: str = "") -> Dict:
    """A solid pill carrying black text. `color_fn(value)` returns the fill."""
    return {"kind": "chip", "key": key, "label": label, "color_fn": color_fn,
            "align": align}


def col_run(key: str, label: str = "Next") -> Dict:
    """A fixture run · list of {opp, home, fdr} rendered as FDR-coloured chips."""
    return {"kind": "run", "key": key, "label": label}


def col_action(key: str, action: str, glyph: str, label: str = "",
               ghost: bool = False, disabled_key: Optional[str] = None,
               disabled_glyph: str = "") -> Dict:
    """A clickable button cell. The click posts {action, id: row[key]}.

    `disabled_key` names a truthy row field that greys the button out and stops
    it reporting. Showing an option you cannot take is more useful than hiding
    it · "too expensive" is information, an absent row is a mystery.
    """
    return {"kind": "action", "key": key, "action": action, "glyph": glyph,
            "label": label, "ghost": ghost, "disabled_key": disabled_key,
            "disabled_glyph": disabled_glyph}


def col_html(key: str, label: str, align: str = "") -> Dict:
    """Pre-rendered HTML, for anything the specs above do not cover."""
    return {"kind": "html", "key": key, "label": label, "align": align}


# ── Cell rendering ────────────────────────────────────────────────────────────
def _cell(spec: Dict, row: Dict) -> str:
    kind = spec["kind"]
    v = row.get(spec["key"])

    if kind == "face":
        url = spec["url_fn"](v) if spec.get("url_fn") else v
        if not url:
            return '<div class="face"></div>'
        return (f'<img class="face" src="{_esc(url)}" loading="lazy" '
                f'onerror="this.style.visibility=\'hidden\'"/>')

    if kind == "player":
        sub = row.get(spec["sub"]) if spec.get("sub") else None
        sub_html = f'<div class="sub">{_esc(sub)}</div>' if sub else ""
        name = f'<div class="nm">{_esc(v)}</div>'
        if spec.get("action"):
            rid = int(_num(row.get(spec.get("id_key", "code")), 0) or 0)
            name = (f'<div class="nm link" data-ffaction="{_esc(spec["action"])}" '
                    f'data-ffid="{rid}">{_esc(v)}</div>')
        return f'{name}{sub_html}'

    if kind == "num":
        f = _num(v)
        if f is None:
            lab = spec.get("empty") or ""
            if lab:
                return (f'<span class="sub" style="font-style:italic;'
                        f'white-space:nowrap;">{_esc(lab)}</span>')
            return '<span class="sub">·</span>'
        txt = spec["fmt"] % f
        c = spec["color_fn"](f) if spec.get("color_fn") else None
        return f'<span style="color:{c};font-weight:700;">{txt}</span>' if c else txt

    if kind == "bar":
        f = _num(v, 0.0) or 0.0
        pct = max(0.0, min(1.0, f / float(spec["max"] or 1))) * 100
        c = fill(spec["color"])
        return (f'<div class="bar"><i style="width:{pct:.0f}%;background:{c};'
                f'opacity:0.42;"></i><b>{spec["fmt"] % f}</b></div>')

    if kind == "chip":
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return '<span class="sub">·</span>'
        return (f'<span class="chip" style="background:{spec["color_fn"](v)};">'
                f'{_esc(v)}</span>')

    if kind == "run":
        if not isinstance(v, list) or not v:
            return '<span class="sub">·</span>'
        out = []
        for fx in v[:5]:
            if fx.get("blank"):
                out.append('<span class="chip" style="background:rgba(128,128,128,0.5);'
                           'color:#fff;">BLK</span>')
                continue
            c = FDR_COLORS.get(int(round(float(fx.get("fdr", 3) or 3))), "#FFD60A")
            side = "" if fx.get("home") else "·a"
            out.append(f'<span class="chip" style="background:{c};">'
                       f'{_esc(str(fx.get("opp", "?"))[:3])}{side}</span>')
        return '<span style="display:inline-flex;gap:3px;">' + "".join(out) + "</span>"

    if kind == "action":
        dk = spec.get("disabled_key")
        if dk and row.get(dk):
            return (f'<span class="act off" title="Not available">'
                    f'{_esc(spec.get("disabled_glyph") or spec["glyph"])}</span>')
        cls = "act ghost" if spec.get("ghost") else "act"
        return (f'<span class="{cls}" data-ffaction="{_esc(spec["action"])}" '
                f'data-ffid="{int(_num(v, 0) or 0)}">{spec["glyph"]}</span>')

    if kind == "html":
        return "" if v is None else str(v)

    return _esc(v)


def build_html(rows: List[Dict], cols: List[Dict], max_height: int = 420,
               row_action: Optional[str] = None, row_key: str = "code",
               highlight: Optional[set] = None, empty: str = "Nothing to show.") -> str:
    """The table markup. Split out from `render` so it can be unit tested."""
    if not rows:
        return f'<div class="wrap"><div class="empty">{_esc(empty)}</div></div>'

    # Pinned columns need a left offset, which depends on the widths of the
    # pinned columns before them, so compute the running offset up front.
    offsets, run = {}, 0
    for i, c in enumerate(cols):
        if c.get("pinned"):
            offsets[i] = run
            run += int(c.get("width", 120))

    def _cls(i: int, c: Dict) -> str:
        bits = []
        if c.get("align") == ALIGN_NUM or c["kind"] in ("num", "bar"):
            bits.append("num")
        if c.get("pinned"):
            bits.append("pin1" if offsets[i] == 0 else "pin2")
        return (' class="%s"' % " ".join(bits)) if bits else ""

    def _style(i: int, c: Dict) -> str:
        if not c.get("pinned"):
            return ""
        return ' style="left:%dpx;"' % offsets[i]

    head = "".join(
        f'<th{_cls(i, c)}{_style(i, c)}>{_esc(c.get("label", ""))}</th>'
        for i, c in enumerate(cols))

    body = []
    hl = highlight or set()
    for r in rows:
        rid = _num(r.get(row_key), 0) or 0
        # A row the caller has marked unavailable is dimmed rather than dropped.
        dim = " unaffordable" if r.get("_unavailable") else ""
        attrs = ""
        if row_action and not r.get("_unavailable"):
            attrs = (f' class="clickable{" hl" if int(rid) in hl else ""}{dim}"'
                     f' data-ffaction="{_esc(row_action)}" data-ffid="{int(rid)}"')
        elif int(rid) in hl or dim:
            attrs = f' class="{"hl" if int(rid) in hl else ""}{dim}"'
        tds = "".join(
            f'<td{_cls(i, c)}{_style(i, c)}>{_cell(c, r)}</td>'
            for i, c in enumerate(cols))
        body.append(f"<tr{attrs}>{tds}</tr>")

    return (f'<div class="wrap" style="max-height:{int(max_height)}px;">'
            f'<table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def render(rows: Union[List[Dict], pd.DataFrame], cols: List[Dict],
           key: str, max_height: int = 420, row_action: Optional[str] = None,
           row_key: str = "code", highlight: Optional[set] = None,
           empty: str = "Nothing to show."):
    """Render the table and return the last click, or None.

    The component replays its last value on every rerun, so callers MUST dedupe
    on the returned `nonce` exactly as they do for the pitch.
    """
    if isinstance(rows, pd.DataFrame):
        rows = rows.to_dict("records")
    html = build_html(rows, cols, max_height, row_action, row_key, highlight, empty)
    return _component(html=html, theme_css=component_css(), key=key, default=None)
