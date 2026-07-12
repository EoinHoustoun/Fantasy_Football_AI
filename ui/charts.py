"""Shared ECharts chart system · one dark theme, one look, everywhere.

Apache ECharts (via streamlit-echarts, free/MIT) replaces the app's Plotly charts
with richer, more interactive, more beautiful graphs. Every chart in the app should
be built from a helper here so the whole app reads as one system (fonts, palette,
transparent grounds, tooltip style). See docs/OVERHAUL_PLAN.md Phase 3.

Python 3.8: typing.List/Dict/Optional only.
"""

from __future__ import annotations

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
    data = [{
        "value": [p.get("x", 0), p.get("y", 0)],
        "name": p.get("name", ""),
        "itemStyle": {"color": p.get("color", color), "opacity": 0.85,
                      "borderColor": "rgba(0,0,0,0.35)", "borderWidth": 0.5},
        "symbolSize": p.get("size", 11),
    } for p in points]
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
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 70, "right": 18, "top": 20, "bottom": 40},
        "tooltip": {"position": "top", "backgroundColor": "rgba(11,14,19,0.94)",
                    "borderColor": "rgba(255,255,255,0.12)",
                    "textStyle": {"color": _TEXT, "fontFamily": _FONT}},
        "xAxis": {"type": "category", "data": x, "splitArea": {"show": True},
                  "axisLabel": {"color": _MUT, "fontSize": 9, "fontFamily": _FONT}},
        "yAxis": {"type": "category", "data": y, "splitArea": {"show": True},
                  "axisLabel": {"color": _MUT, "fontSize": 9, "fontFamily": _FONT}},
        "visualMap": {"min": lo, "max": hi, "calculable": True, "orient": "horizontal",
                      "left": "center", "bottom": 4,
                      "inRange": {"color": ["#123", COLORS["cyan"], COLORS["mint"]]},
                      "textStyle": {"color": _MUT, "fontSize": 9}},
        "series": [{"type": "heatmap", "data": data,
                    "label": {"show": False},
                    "emphasis": {"itemStyle": {"borderColor": "#fff", "borderWidth": 1}}}],
    }


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


def render(option: Dict[str, Any], height: str = "260px",
           key: Optional[str] = None) -> None:
    """Render an ECharts option with the app theme. `key` must be unique per chart."""
    from streamlit_echarts import st_echarts
    st_echarts(options=option, height=height, key=key)
