"""Shared ECharts chart system · one dark theme, one look, everywhere.

Apache ECharts (via streamlit-echarts, free/MIT) replaces the app's Plotly charts
with richer, more interactive, more beautiful graphs. Every chart in the app should
be built from a helper here so the whole app reads as one system (fonts, palette,
transparent grounds, tooltip style). See docs/OVERHAUL_PLAN.md Phase 3.

Python 3.8: typing.List/Dict/Optional only.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from ui.theme import COLORS

_TEXT = COLORS["text"]
_MUT = "rgba(236,241,245,0.55)"
_GRID_LINE = "rgba(255,255,255,0.06)"
_AXIS_LINE = "rgba(255,255,255,0.14)"
_FONT = "Inter, 'SF Pro Display', sans-serif"


def _rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB → rgba(r,g,b,alpha). Passes through anything already non-hex."""
    h = hex_color.strip()
    if not h.startswith("#") or len(h) != 7:
        return hex_color
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _axis(kind: str, data: Optional[List[Any]] = None) -> Dict[str, Any]:
    ax: Dict[str, Any] = {
        "type": kind,
        "axisLine": {"lineStyle": {"color": _AXIS_LINE}},
        "axisTick": {"show": False},
        "axisLabel": {"color": _MUT, "fontSize": 9, "fontFamily": _FONT},
        "splitLine": {"lineStyle": {"color": _GRID_LINE}},
    }
    if data is not None:
        ax["data"] = data
    if kind == "category":
        ax["splitLine"] = {"show": False}
        ax["axisLabel"]["interval"] = "auto"
    return ax


def _tooltip() -> Dict[str, Any]:
    return {
        "trigger": "axis",
        "backgroundColor": "rgba(11,14,19,0.94)",
        "borderColor": "rgba(255,255,255,0.12)",
        "textStyle": {"color": _TEXT, "fontFamily": _FONT, "fontSize": 12},
    }


def line_option(x: List[Any], y: List[float], name: str = "",
                color: str = COLORS["cyan"]) -> Dict[str, Any]:
    """A smooth area line · great for form / rolling trends, with an accent fill."""
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 38, "right": 14, "top": 20, "bottom": 24},
        "tooltip": _tooltip(),
        "xAxis": _axis("category", [str(v) for v in x]),
        "yAxis": _axis("value"),
        "series": [{
            "name": name, "type": "line", "data": y, "smooth": True,
            "symbol": "circle", "symbolSize": 6,
            "lineStyle": {"color": color, "width": 2.5},
            "itemStyle": {"color": color},
            "areaStyle": {"color": {
                "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                "colorStops": [
                    {"offset": 0, "color": _rgba(color, 0.35)},
                    {"offset": 1, "color": _rgba(color, 0.02)},
                ],
            }},
            "emphasis": {"focus": "series"},
        }],
    }


def grouped_bars_option(x: List[Any],
                        series: List[Tuple[str, List[float], str]]) -> Dict[str, Any]:
    """Grouped bars · e.g. xG vs Goals per gameweek. series = [(name, data, color)]."""
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 34, "right": 14, "top": 26, "bottom": 24},
        "tooltip": _tooltip(),
        "legend": {"data": [s[0] for s in series], "top": 0, "right": 0,
                   "textStyle": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT},
                   "itemWidth": 10, "itemHeight": 10},
        "xAxis": _axis("category", [str(v) for v in x]),
        "yAxis": _axis("value"),
        "series": [{
            "name": nm, "type": "bar", "data": data,
            "itemStyle": {"color": col, "borderRadius": [3, 3, 0, 0]},
            "barMaxWidth": 14, "emphasis": {"focus": "series"},
        } for (nm, data, col) in series],
    }


def radar_option(indicators: List[Dict[str, Any]], values: List[float],
                 name: str = "", color: str = COLORS["mint"]) -> Dict[str, Any]:
    """A strengths/weaknesses radar. indicators = [{'name':..,'max':100}, ...]."""
    return {
        "backgroundColor": "transparent",
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT}},
        "radar": {
            "indicator": indicators, "radius": "66%", "center": ["50%", "54%"],
            "axisName": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT},
            "splitNumber": 4,
            "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.10)"}},
            "splitArea": {"areaStyle": {"color": ["rgba(255,255,255,0.02)",
                                                  "rgba(255,255,255,0.05)"]}},
            "axisLine": {"lineStyle": {"color": "rgba(255,255,255,0.10)"}},
        },
        "series": [{
            "type": "radar",
            "data": [{
                "value": values, "name": name,
                "symbolSize": 4,
                "areaStyle": {"color": "rgba(0,255,135,0.28)"},
                "lineStyle": {"color": color, "width": 2},
                "itemStyle": {"color": color},
            }],
        }],
    }


def radar_compare_option(indicators: List[Dict[str, Any]],
                         series: List[Tuple[str, List[float], str, float]],
                         ) -> Dict[str, Any]:
    """Radar with multiple overlaid polygons · a player vs a baseline or rival.

    series = [(name, values, color, fill_alpha)]. Later entries draw on top,
    so put the player of interest last and the baseline first.
    """
    return {
        "backgroundColor": "transparent",
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT}},
        "legend": {"bottom": 0, "textStyle": {"color": _MUT, "fontSize": 10,
                                              "fontFamily": _FONT},
                   "itemWidth": 10, "itemHeight": 10},
        "radar": {
            "indicator": indicators, "radius": "62%", "center": ["50%", "50%"],
            "axisName": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT},
            "splitNumber": 4,
            "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.10)"}},
            "splitArea": {"areaStyle": {"color": ["rgba(255,255,255,0.02)",
                                                  "rgba(255,255,255,0.05)"]}},
            "axisLine": {"lineStyle": {"color": "rgba(255,255,255,0.10)"}},
        },
        "series": [{
            "type": "radar",
            "data": [{
                "value": vals, "name": nm,
                "symbolSize": 3,
                "areaStyle": {"color": _rgba(col, alpha) if col.startswith("#") else col},
                "lineStyle": {"color": col, "width": 2},
                "itemStyle": {"color": col},
            } for (nm, vals, col, alpha) in series],
        }],
    }


def bar_option(x: List[Any], y: List[float], color: str = COLORS["mint"],
               horizontal: bool = False, name: str = "",
               colors: Optional[List[str]] = None) -> Dict[str, Any]:
    """A single-series bar chart (vertical by default; horizontal for rankings).

    `colors` gives each bar its own colour (e.g. green above average, red below);
    it wins over `color` when provided.
    """
    cat = _axis("category", [str(v) for v in x])
    val = _axis("value")
    grid = {"left": 90, "right": 18, "top": 16, "bottom": 22} if horizontal \
        else {"left": 40, "right": 14, "top": 16, "bottom": 26}
    radius = [0, 3, 3, 0] if horizontal else [3, 3, 0, 0]
    data: List[Any] = y if colors is None else [
        {"value": v, "itemStyle": {"color": colors[i % len(colors)],
                                   "borderRadius": radius}}
        for i, v in enumerate(y)
    ]
    series = {
        "name": name, "type": "bar", "data": data,
        "itemStyle": {"color": color, "borderRadius": radius},
        "barMaxWidth": 18, "emphasis": {"focus": "series"},
    }
    opt = {"backgroundColor": "transparent", "grid": grid, "tooltip": _tooltip(), "series": [series]}
    if horizontal:
        opt["xAxis"] = val
        opt["yAxis"] = cat
        opt["yAxis"]["inverse"] = True
    else:
        opt["xAxis"] = cat
        opt["yAxis"] = val
    return opt


def scatter_option(points: List[Dict[str, Any]], x_name: str = "", y_name: str = "",
                   color: str = COLORS["cyan"]) -> Dict[str, Any]:
    """Scatter plot. points = [{'x':.., 'y':.., 'name':.., 'color':.., 'size':..}]."""
    data = []
    for p in points:
        item: Dict[str, Any] = {
            "value": [p.get("x", 0), p.get("y", 0)],
            "name": p.get("name", ""),
            "itemStyle": {"color": p.get("color", color), "opacity": 0.85,
                          "borderColor": "rgba(0,0,0,0.35)", "borderWidth": 0.5},
            "symbolSize": p.get("size", 11),
        }
        if p.get("tip"):
            item["tooltip"] = {"formatter": p["tip"]}
        if p.get("label"):
            item["label"] = {"show": True, "formatter": p.get("name", ""),
                             "position": "top",
                             "color": p.get("label_color", COLORS["gold"]),
                             "fontSize": 10, "fontFamily": _FONT}
        data.append(item)
    ax_x = _axis("value")
    ax_y = _axis("value")
    ax_x["name"] = x_name
    ax_y["name"] = y_name
    ax_x["nameTextStyle"] = {"color": _MUT, "fontSize": 10}
    ax_y["nameTextStyle"] = {"color": _MUT, "fontSize": 10}
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 44, "right": 18, "top": 26, "bottom": 34},
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT},
                    "formatter": "{b}"},
        "xAxis": ax_x, "yAxis": ax_y,
        "series": [{"type": "scatter", "data": data, "emphasis": {"scale": 1.4}}],
    }


def multi_line_option(series: List[Tuple[str, List[Tuple[float, float]], str]],
                      x_name: str = "", y_name: str = "") -> Dict[str, Any]:
    """Several lines on a numeric x axis. series = [(name, [(x, y), ...], color)].

    Numeric x means the lines don't need aligned categories (e.g. one line
    per GW 1-38, another with gaps).
    """
    ax_x = _axis("value")
    ax_y = _axis("value")
    ax_x["name"] = x_name
    ax_y["name"] = y_name
    ax_x["nameTextStyle"] = {"color": _MUT, "fontSize": 10}
    ax_y["nameTextStyle"] = {"color": _MUT, "fontSize": 10}
    ax_x["minInterval"] = 1
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 48, "right": 18, "top": 34, "bottom": 34},
        "tooltip": _tooltip(),
        "legend": {"top": 0, "left": 0,
                   "textStyle": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT},
                   "itemWidth": 14, "itemHeight": 8},
        "xAxis": ax_x, "yAxis": ax_y,
        "series": [{
            "name": nm, "type": "line",
            "data": [[float(x), float(y)] for (x, y) in pts],
            "symbol": "none", "smooth": False,
            "lineStyle": {"color": col, "width": 2.5},
            "itemStyle": {"color": col},
            "emphasis": {"focus": "series"},
        } for (nm, pts, col) in series],
    }


def category_lines_option(x: List[Any],
                          series: List[Tuple[str, List[float], str]]) -> Dict[str, Any]:
    """Lines on a shared category axis. series = [(name, data, color)].

    Use over multi_line_option when series are aligned to the same x labels
    (enables stacking tricks like fill-between bands).
    """
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 48, "right": 18, "top": 34, "bottom": 34},
        "tooltip": _tooltip(),
        "legend": {"top": 0, "left": 0,
                   "textStyle": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT},
                   "itemWidth": 14, "itemHeight": 8},
        "xAxis": _axis("category", [str(v) for v in x]),
        "yAxis": _axis("value"),
        "series": [{
            "name": nm, "type": "line", "data": data,
            "symbol": "none", "smooth": False,
            "lineStyle": {"color": col, "width": 2.5},
            "itemStyle": {"color": col},
            "emphasis": {"focus": "series"},
        } for (nm, data, col) in series],
    }


def band_fill_series(base: List[float], above: List[float],
                     below: List[float]) -> List[Dict[str, Any]]:
    """Fill-between bands for category_lines_option (append to option['series']).

    base = min(line1, line2) per point; above/below = positive gaps. Stacked,
    invisible lines · green tint where line1 wins, red where it trails.
    """
    def _band(data: List[float], color: str) -> Dict[str, Any]:
        return {"type": "line", "data": data, "stack": "__band__",
                "symbol": "none", "silent": True, "smooth": False,
                "lineStyle": {"opacity": 0}, "areaStyle": {"color": color},
                "tooltip": {"show": False}, "z": 0}
    return [_band(base, "rgba(0,0,0,0)"),
            _band(above, "rgba(0,255,135,0.15)"),
            _band(below, "rgba(255,75,75,0.15)")]


def with_vertical_marks(option: Dict[str, Any],
                        marks: List[Tuple[float, str]],
                        color: str = "rgba(233,0,82,0.4)",
                        label_color: str = COLORS["magenta"],
                        series_index: int = 0) -> Dict[str, Any]:
    """Add dotted vertical event lines (e.g. chip weeks, thresholds).

    marks = [(x, label)] or [(x, label, colour)] for per-mark colours.
    """
    data = []
    for m in marks:
        item: Dict[str, Any] = {"xAxis": m[0], "label": {"formatter": m[1]}}
        if len(m) > 2:
            item["lineStyle"] = {"color": m[2]}
            item["label"]["color"] = m[2]
        data.append(item)
    option["series"][series_index]["markLine"] = {
        "silent": True, "symbol": "none",
        "lineStyle": {"type": "dotted", "color": color, "width": 1},
        "label": {"show": True, "position": "insideEndTop", "color": label_color,
                  "fontSize": 9, "fontFamily": _FONT},
        "data": data,
    }
    return option


def stacked_bars_option(categories: List[str],
                        series: List[Tuple[str, List[float], str]],
                        horizontal: bool = False,
                        title: str = "") -> Dict[str, Any]:
    """Stacked bars · e.g. score components per player. series = [(name, data, color)]."""
    cat = _axis("category", [str(v) for v in categories])
    val = _axis("value")
    if horizontal:
        cat["inverse"] = True
        val["axisLabel"] = {"show": False}
        val["splitLine"] = {"show": False}
    opt: Dict[str, Any] = {
        "backgroundColor": "transparent",
        "grid": {"left": 90 if horizontal else 40, "right": 14,
                 "top": 34 if title else 20, "bottom": 30},
        "tooltip": _tooltip(),
        "legend": {"bottom": 0, "textStyle": {"color": _MUT, "fontSize": 10,
                                              "fontFamily": _FONT},
                   "itemWidth": 10, "itemHeight": 10},
        "xAxis": val if horizontal else cat,
        "yAxis": cat if horizontal else val,
        "series": [{
            "name": nm, "type": "bar", "stack": "total", "data": data,
            "itemStyle": {"color": col},
            "barMaxWidth": 16, "emphasis": {"focus": "series"},
        } for (nm, data, col) in series],
    }
    if title:
        opt["title"] = {"text": title, "textStyle": {
            "color": _TEXT, "fontSize": 13, "fontWeight": "bold"}}
    return opt


def multi_scatter_option(series: List[Tuple[str, str, List[Dict[str, Any]]]],
                         x_name: str = "", y_name: str = "") -> Dict[str, Any]:
    """Legended scatter/bubble chart, one series per group (e.g. position).

    series = [(group_name, group_color, points)] with points =
    [{'x','y','name', 'size'?, 'tip'? (tooltip HTML), 'label'? (pin the name on chart)}].
    """
    ax_x = _axis("value")
    ax_y = _axis("value")
    ax_x["name"] = x_name
    ax_y["name"] = y_name
    ax_x["nameTextStyle"] = {"color": _MUT, "fontSize": 10}
    ax_y["nameTextStyle"] = {"color": _MUT, "fontSize": 10}
    out_series = []
    for (nm, col, points) in series:
        data = []
        for p in points:
            item: Dict[str, Any] = {
                "value": [p.get("x", 0), p.get("y", 0)],
                "name": p.get("name", ""),
                "symbolSize": p.get("size", 11),
                "itemStyle": {"color": col, "opacity": 0.85,
                              "borderColor": "rgba(0,0,0,0.35)", "borderWidth": 0.5},
            }
            if p.get("image"):
                # Player-face symbols · the point IS the player.
                item["symbol"] = f"image://{p['image']}"
                item["symbolSize"] = p.get("size", 24)
            if p.get("tip"):
                item["tooltip"] = {"formatter": p["tip"]}
            if p.get("label"):
                item["label"] = {"show": True, "formatter": p.get("name", ""),
                                 "position": "right", "color": COLORS["gold"],
                                 "fontSize": 11, "fontWeight": "bold",
                                 "fontFamily": _FONT}
            data.append(item)
        out_series.append({"name": nm, "type": "scatter", "data": data,
                           "emphasis": {"scale": 1.4}})
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 44, "right": 18, "top": 34, "bottom": 34},
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT},
                    "formatter": "{b}"},
        "legend": {"top": 0, "right": 0, "textStyle": {"color": _MUT, "fontSize": 10,
                                                       "fontFamily": _FONT},
                   "itemWidth": 10, "itemHeight": 10},
        "xAxis": ax_x, "yAxis": ax_y,
        "series": out_series,
    }


def scale_sizes(values: List[float], lo: float = 8.0, hi: float = 26.0) -> List[float]:
    """Map raw magnitudes onto a sensible bubble-size range in px."""
    if not values:
        return []
    vmin, vmax = min(values), max(values)
    if vmax <= vmin:
        return [(lo + hi) / 2.0] * len(values)
    return [lo + (v - vmin) / (vmax - vmin) * (hi - lo) for v in values]


def donut_option(labels: List[str], values: List[float],
                 colors: Optional[List[str]] = None, center_label: str = "") -> Dict[str, Any]:
    """A donut chart (use over pie). colors optional; falls back to the app palette."""
    palette = colors or [COLORS["mint"], COLORS["cyan"], COLORS["magenta"],
                         COLORS["gold"], COLORS["orange"], "#a3e635"]
    data = [{"name": l, "value": v,
             "itemStyle": {"color": palette[i % len(palette)]}}
            for i, (l, v) in enumerate(zip(labels, values))]
    return {
        "backgroundColor": "transparent",
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT}},
        "legend": {"bottom": 0, "textStyle": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT},
                   "itemWidth": 10, "itemHeight": 10},
        "series": [{
            "type": "pie", "radius": ["52%", "74%"], "center": ["50%", "46%"],
            "avoidLabelOverlap": True, "label": {"show": False},
            "itemStyle": {"borderColor": COLORS["bg"], "borderWidth": 2},
            "emphasis": {"label": {"show": True, "fontSize": 14, "fontWeight": "bold",
                                   "color": _TEXT}},
            "data": data,
        }],
    }


def heatmap_option(x: List[str], y: List[str], matrix: List[List[float]],
                   vmin: Optional[float] = None, vmax: Optional[float] = None) -> Dict[str, Any]:
    """A heatmap. matrix[row][col] with rows aligned to y, cols to x."""
    data = []
    flat = []
    for ri, row in enumerate(matrix):
        for ci, v in enumerate(row):
            data.append([ci, ri, v])
            flat.append(v)
    lo = vmin if vmin is not None else (min(flat) if flat else 0)
    hi = vmax if vmax is not None else (max(flat) if flat else 1)
    # `containLabel` lets the grid size itself around the axis text instead of
    # sitting inside a guessed 70px gutter · long category names were being
    # clipped, which is worse than useless on a matrix where the row label IS
    # the identity. Rotating the column labels buys the same room horizontally.
    longest = max([len(str(v)) for v in y] + [0])
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 8, "right": 20, "top": 16, "bottom": 54,
                 "containLabel": True},
        "tooltip": {"position": "top", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT}},
        "xAxis": {"type": "category", "data": x, "splitArea": {"show": True},
                  "axisTick": {"show": False},
                  "axisLabel": {"color": _MUT, "fontSize": 9, "fontFamily": _FONT,
                                "rotate": 30 if longest > 8 else 0,
                                "interval": 0, "hideOverlap": False}},
        "yAxis": {"type": "category", "data": y, "splitArea": {"show": True},
                  "axisTick": {"show": False},
                  "axisLabel": {"color": _MUT, "fontSize": 9, "fontFamily": _FONT,
                                "interval": 0, "width": 130, "overflow": "truncate"}},
        "visualMap": {"min": lo, "max": hi, "calculable": True, "orient": "horizontal",
                      "left": "center", "bottom": 2, "itemHeight": 80,
                      "inRange": {"color": ["#123", COLORS["cyan"], COLORS["mint"]]},
                      "textStyle": {"color": _MUT, "fontSize": 9}},
        "series": [{"type": "heatmap", "data": data,
                    "label": {"show": True, "fontSize": 9, "color": "#0B0E13",
                              "fontWeight": "bold", "formatter": "{@[2]}"},
                    "emphasis": {"itemStyle": {"borderColor": "#fff", "borderWidth": 1}}}],
    }


def color_ramp(values: List[float], low: str, high: str) -> List[str]:
    """Interpolate each value between two hex colours (a mini continuous scale)."""
    if not values:
        return []
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1.0
    lo = [int(low[i:i + 2], 16) for i in (1, 3, 5)]
    hi = [int(high[i:i + 2], 16) for i in (1, 3, 5)]
    out = []
    for v in values:
        t = (v - vmin) / span
        r, g, b = (round(l + (h - l) * t) for l, h in zip(lo, hi))
        out.append(f"rgb({r},{g},{b})")
    return out


def diverging_colors(values: List[float], low: str, mid: str, high: str,
                     midpoint: float = 0.0) -> List[str]:
    """Colour each value on a diverging scale centred on `midpoint`."""
    if not values:
        return []
    span = max(abs(v - midpoint) for v in values) or 1.0
    out = []
    for v in values:
        t = (v - midpoint) / span   # -1 .. 1
        pair = (mid, high) if t >= 0 else (mid, low)
        lo_c = [int(pair[0][i:i + 2], 16) for i in (1, 3, 5)]
        hi_c = [int(pair[1][i:i + 2], 16) for i in (1, 3, 5)]
        a = abs(t)
        r, g, b = (round(l + (h - l) * a) for l, h in zip(lo_c, hi_c))
        out.append(f"rgb({r},{g},{b})")
    return out


def with_diagonal(option: Dict[str, Any], max_val: float, name: str = "",
                  color: str = "rgba(255,255,255,0.4)") -> Dict[str, Any]:
    """Add a dashed y=x reference line to a value-axis scatter (xG vs goals)."""
    option["series"].append({
        "name": name, "type": "line", "data": [[0, 0], [max_val, max_val]],
        "symbol": "none", "silent": True, "tooltip": {"show": False},
        "lineStyle": {"type": "dashed", "color": color, "width": 1.5},
        "itemStyle": {"color": color},
        "z": 1,
    })
    return option


def with_image_labels(option: Dict[str, Any], images: List[str],
                      size: int = 24) -> Dict[str, Any]:
    """Put player faces (or kits) on a bar chart's category axis labels.

    `images[i]` pairs with category i (data order · works with inverse axes).
    Empty URLs fall back to the plain text label.
    """
    from streamlit_echarts import JsCode
    axis = option["yAxis"] if option.get("yAxis", {}).get("type") == "category" \
        else option.get("xAxis", {})
    rich = {f"img{i}": {"backgroundColor": {"image": u},
                        "height": size, "width": size, "borderRadius": size // 2}
            for i, u in enumerate(images) if u}
    keys = "[" + ",".join(f"'{('img'+str(i)) if u else ''}'"
                          for i, u in enumerate(images)) + "]"
    axis["axisLabel"] = {**axis.get("axisLabel", {}),
        "formatter": JsCode(
            "function(v,i){var k=" + keys + "[i];"
            "return (k? '{'+k+'|} ' : '') + v;}").js_code,
        "rich": rich, "margin": 10}
    return option


def with_mark_line(option: Dict[str, Any], value: float, label: str = "",
                   color: str = "rgba(255,255,255,0.35)",
                   series_index: int = 0) -> Dict[str, Any]:
    """Add a dashed horizontal reference line (e.g. a season average) to a series.

    Mutates and returns `option` so it chains: render(with_mark_line(opt, avg)).
    """
    option["series"][series_index]["markLine"] = {
        "silent": True, "symbol": "none",
        "lineStyle": {"type": "dashed", "color": color, "width": 1.2},
        "label": {"show": bool(label), "formatter": label, "position": "insideEndTop",
                  "color": "rgba(255,255,255,0.7)", "fontSize": 10, "fontFamily": _FONT},
        "data": [{"yAxis": value}],
    }
    return option


def fixture_run_option(gws: List[int], points: List[float], opponents: List[str],
                       fdr: List[float], minutes: Optional[List[float]] = None,
                       fdr_colors: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """The opening run · one bar a gameweek, coloured by fixture difficulty.

    Colouring by difficulty rather than by data source is the whole point: the
    reader sees WHY a week is high or low without a legend, because the bar is
    green when the fixture is kind and red when it is not. The opponent goes on
    the axis under the gameweek, so no tooltip is needed to read the run.

    An optional minutes line rides on a second axis · a tall bar on thin minutes
    is the trap this chart exists to expose.
    """
    cols = fdr_colors or {1: "#00E37A", 2: "#00E37A", 3: "#FFD60A",
                          4: "#FF8C42", 5: "#FF4B4B"}
    labels = [f"GW{g}\n{o or 'blank'}" for g, o in zip(gws, opponents)]
    ax_x = _axis("category", labels)
    ax_x["axisLabel"]["fontSize"] = 9
    ax_x["axisLabel"]["lineHeight"] = 13
    ax_x["axisLabel"]["interval"] = 0
    ax_y = _axis("value")
    ax_y["splitLine"]["lineStyle"]["type"] = "dashed"

    series: List[Dict[str, Any]] = [{
        "type": "bar", "name": "Expected points", "barWidth": "58%",
        "data": [{"value": round(float(p), 2),
                  "itemStyle": {"color": cols.get(int(round(float(f))), "#FFD60A"),
                                "borderRadius": [5, 5, 0, 0], "opacity": 0.92}}
                 for p, f in zip(points, fdr)],
        "label": {"show": True, "position": "top", "fontSize": 10,
                  "fontWeight": "bold", "color": _MUT, "formatter": "{c}"},
    }]
    axes = [ax_y]
    if minutes is not None:
        axes.append({**_axis("value"), "max": 90, "splitLine": {"show": False},
                     "axisLabel": {"color": _MUT, "fontSize": 9,
                                   "formatter": "{value}'"}})
        series.append({
            "type": "line", "name": "Expected minutes", "yAxisIndex": 1,
            "data": [None if m is None else round(float(m), 0) for m in minutes],
            "smooth": False, "symbol": "circle", "symbolSize": 6,
            "lineStyle": {"color": COLORS["cyan"], "width": 2, "type": "dashed"},
            "itemStyle": {"color": COLORS["cyan"]},
        })
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 40, "right": 44 if minutes is not None else 16,
                 "top": 34, "bottom": 42},
        "tooltip": _tooltip(),
        # Only the minutes line goes in the legend. The bars are individually
        # coloured by difficulty, so a single swatch for them would be a lie (and
        # ECharts picks its own blue for it, which clashes with everything).
        "legend": {"top": 0, "left": 0, "itemWidth": 14, "itemHeight": 8,
                   "data": ["Expected minutes"] if minutes is not None else [],
                   "textStyle": {"color": _MUT, "fontSize": 10, "fontFamily": _FONT}},
        "xAxis": ax_x, "yAxis": axes, "series": series,
    }


def model_spread_option(labels: List[str], values: List[float],
                        blend: float, colors: List[str],
                        notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Where each model lands, on one line, with the blend marked.

    Three separate bars make you compare heights; one axis with three points
    makes the SPREAD the thing you see, which is the question being asked.

    **Tooltips are pre-formatted in Python, not templated.** `{@[0]}` is
    dataset syntax: it resolves for a `label` formatter but NOT for a `tooltip`
    one on a series with inline `data`, so hovering a point printed a literal
    "@" at the reader. Per-item `tooltip.formatter` strings need no templating
    at all and cannot drift out of sync with the value on the axis.

    `notes` optionally annotates a model that is shown but does not vote.
    """
    notes = list(notes or []) + [""] * len(labels)
    lo, hi = min(values + [blend]), max(values + [blend])
    pad = max((hi - lo) * 0.18, 4)
    ax_x = {**_axis("value"), "min": round(lo - pad), "max": round(hi + pad)}
    ax_y = {**_axis("category", [""]), "axisLine": {"show": False},
            "splitLine": {"show": False}}
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 12, "right": 24, "top": 44, "bottom": 30, "containLabel": True},
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT}},
        "xAxis": ax_x, "yAxis": ax_y,
        "series": [
            # The connecting rule, so the gap between models is a visible length.
            {"type": "line", "data": [[min(values), 0], [max(values), 0]],
             "symbol": "none", "silent": True, "z": 1,
             "lineStyle": {"color": "rgba(255,255,255,0.18)", "width": 6}},
            {"type": "scatter", "symbolSize": 17, "z": 3,
             "data": [{"value": [round(v, 1), 0], "name": n,
                       "itemStyle": {"color": c, "borderColor": "rgba(0,0,0,0.35)",
                                     "borderWidth": 1},
                       "tooltip": {"formatter": "%s: %.0f pts%s" % (n, v, note)}}
                      for n, v, c, note in zip(labels, values, colors, notes)],
             "label": {"show": True, "position": "top", "fontSize": 10,
                       "fontWeight": "bold", "color": _MUT,
                       "formatter": "{b}"}},
            {"type": "scatter", "symbol": "diamond", "symbolSize": 15, "z": 4,
             "data": [{"value": [round(blend, 1), 0], "name": "Blend",
                       "itemStyle": {"color": "#FFFFFF"},
                       "tooltip": {"formatter": "Blend: %.0f pts" % blend}}],
             "label": {"show": True, "position": "bottom", "fontSize": 10,
                       "color": _MUT, "formatter": "blend %.0f" % blend}},
        ],
    }



def _light_swap() -> Dict[str, str]:
    """{dark literal: light literal}, derived from the two palettes.

    Built rather than hand-written. An earlier version referenced a
    `_LIGHT_SWAP` constant that was never defined anywhere, so every chart in
    the app raised NameError the moment the light palette was active · quietly,
    because Streamlit catches it into a red box and the rest of the page still
    renders. Deriving it from DARK and LIGHT means a new token can never be
    missing from the map.
    """
    from ui.theme import DARK, LIGHT
    out = {}
    for k, dark in DARK.items():
        light = LIGHT.get(k)
        if light and isinstance(dark, str) and dark != light:
            out[dark] = light
            out[dark.upper()] = light
            out[dark.lower()] = light
    return out


def _retheme(node: Any) -> Any:
    """Recursively swap dark-palette literals for their light equivalents."""
    if isinstance(node, str):
        return _light_swap().get(node, node)
    if isinstance(node, dict):
        return {k: _retheme(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_retheme(v) for v in node]
    return node


def _json_safe(o):
    """Replace NaN and infinity with None, recursively.

    `json.dumps` writes bare NaN, which is not valid JSON, and the browser dies
    on the whole option with "Unexpected token 'N'" · taking the entire card
    with it. One NaN from an empty median is enough. ECharts treats null as a
    gap, which is the honest rendering of a missing value anyway.
    """
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    # numpy scalars arrive here from pandas and are not caught by isinstance
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            v = o.item()
            return _json_safe(v) if isinstance(v, float) else v
        except (ValueError, AttributeError):
            return o
    return o


def render(option: Dict[str, Any], height: str = "260px",
           key: Optional[str] = None) -> None:
    """Render an ECharts option with the app theme. `key` must be unique per chart.

    The height is PINNED in CSS as well as passed to the component, because a
    custom component measures itself on mount and Streamlit then fixes its
    iframe at whatever it reported. Inside a tab that is not the open one,
    Streamlit has already set `display:none`, so the component measures zero and
    the iframe is pinned at zero forever · the chart draws perfectly well inside
    it and is simply invisible, on the tab and after you switch to it. It cost
    the "Minutes are the master variable" scatter its entire existence.
    """
    import streamlit as st
    from streamlit_echarts import st_echarts
    from ui.theme import is_light
    if is_light():
        option = _retheme(option)
        # The key has to change with the palette or Streamlit reuses the mounted
        # chart and the old colours stay on screen.
        key = (key + "_lt") if key else None

    if not key:
        st_echarts(options=_json_safe(option), height=height, key=key)
        return

    # A keyed container gives us a `st-key-…` class to hang the rule on, so the
    # height applies to THIS chart rather than to every iframe on the page.
    box_key = "ffchart_%s" % key
    with st.container(key=box_key):
        st_echarts(options=_json_safe(option), height=height, key=key)
    st.markdown(
        "<style>.st-key-%s iframe{height:%s !important;min-height:%s !important;}"
        "</style>" % (box_key, height, height), unsafe_allow_html=True)
