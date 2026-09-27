"""Charts for transfer decisions · ECharts options, faces as symbols, animated.

Three pictures answer the three questions a transfer raises:

- `xp_duel_option`  · who scores more, week by week? Two lines, the gap shaded,
  each line ending on the player's face, the entry week marked.
- `timing_option`   · when should I make it? The move's value if made in each
  week; the tallest bar is the entry point.
- `squad_heat_option` · where are my weak weeks? Fifteen faces down the side, the
  horizon across, each cell the player's xP, outlined where the best affordable
  replacement beats him (his exit weeks).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from components.team_identity import player_photo_url
from ui import charts
from ui.theme import fill

_FONT = "Inter, 'SF Pro Display', sans-serif"


def _base(grid: Optional[Dict] = None) -> Dict:
    return {
        "backgroundColor": "transparent",
        "animationDuration": 1100, "animationEasing": "cubicOut",
        "animationDurationUpdate": 700, "animationEasingUpdate": "cubicInOut",
        "grid": grid or {"left": 44, "right": 60, "top": 34, "bottom": 34},
        "textStyle": {"fontFamily": _FONT},
        "tooltip": charts._tooltip(),
    }


def xp_duel_option(gws: List[int], out_xp: Dict[int, float], in_xp: Dict[int, float],
                   out_name: str, in_name: str, out_code: int, in_code: int,
                   out_fx: List[str], in_fx: List[str],
                   entry_gw: Optional[int] = None) -> Dict:
    red, mint, muted = fill("red"), fill("mint"), fill("muted2")
    xs = ["GW%d" % g for g in gws]
    yo = [round(out_xp.get(g, 0.0), 2) for g in gws]
    yi = [round(in_xp.get(g, 0.0), 2) for g in gws]
    top = max(yo + yi + [1.0])
    opt = _base()
    opt["legend"] = {"top": 0, "right": 8, "textStyle": {"color": muted, "fontSize": 11},
                     "data": [out_name, in_name]}
    opt["xAxis"] = charts._axis("category", xs)
    opt["xAxis"]["boundaryGap"] = False
    opt["yAxis"] = charts._axis("value")
    opt["yAxis"]["name"] = "xP"
    opt["yAxis"]["nameTextStyle"] = {"color": muted, "fontSize": 10}
    opt["yAxis"]["max"] = round(top * 1.25 + 0.5)
    # Tooltip carries the fixtures, which is what explains a dip.
    fx_js = "[" + ",".join("['%s','%s']" % (a.replace("'", ""), b.replace("'", ""))
                           for a, b in zip(out_fx, in_fx)) + "]"
    from streamlit_echarts import JsCode
    opt["tooltip"]["formatter"] = JsCode(
        "function(p){var f=" + fx_js + "[p[0].dataIndex]||['',''];"
        "var s=p[0].axisValue;for(var i=0;i<p.length;i++){"
        "if(p[i].seriesType!=='line')continue;"
        "s+='<br/>'+p[i].marker+p[i].seriesName+' <b>'+p[i].value+'</b> '+(p[i].seriesIndex==0?f[0]:f[1]);}"
        "return s;}").js_code
    line = lambda name, data, col, area: {
        "name": name, "type": "line", "smooth": 0.35, "data": data, "symbol": "circle",
        "symbolSize": 7, "lineStyle": {"width": 3, "color": col}, "itemStyle": {"color": col},
        "areaStyle": ({"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                                 "colorStops": [{"offset": 0, "color": charts._rgba(col, 0.32)},
                                                {"offset": 1, "color": charts._rgba(col, 0.0)}]}}
                      if area else None),
        "emphasis": {"focus": "series"}}
    s_out, s_in = line(out_name, yo, red, False), line(in_name, yi, mint, True)
    if entry_gw in gws:
        k = gws.index(entry_gw)
        s_in["markPoint"] = {"symbol": "pin", "symbolSize": 44,
                             "itemStyle": {"color": mint},
                             "label": {"formatter": "IN", "color": "#0B0F17",
                                       "fontWeight": "bold", "fontSize": 10},
                             "data": [{"coord": [xs[k], yi[k]]}]}
        s_in["markLine"] = {"symbol": "none", "silent": True,
                            "lineStyle": {"color": mint, "type": "dashed", "opacity": 0.5},
                            "label": {"formatter": "entry", "color": mint, "fontSize": 10,
                                      "position": "insideEndBottom"},
                            "data": [{"xAxis": xs[k]}]}
    faces = {"type": "scatter", "z": 5, "symbolSize": 34, "tooltip": {"show": False},
             "data": [{"value": [xs[-1], yo[-1]], "symbol": "image://" + player_photo_url(out_code)},
                      {"value": [xs[-1], yi[-1]], "symbol": "image://" + player_photo_url(in_code)}]}
    opt["series"] = [s_out, s_in, faces]
    return opt


def timing_option(tm: Dict) -> Dict:
    gws = tm["gws"]
    vals = [tm["gain_if_made"][g] for g in gws]
    best = tm.get("best_week")
    cols = [fill("mint") if g == best else (fill("cyan") if v > 0 else fill("red")) for g, v in zip(gws, vals)]
    opt = _base({"left": 40, "right": 16, "top": 26, "bottom": 30})
    opt["xAxis"] = charts._axis("category", ["GW%d" % g for g in gws])
    opt["yAxis"] = charts._axis("value")
    opt["tooltip"] = {**charts._tooltip(), "trigger": "item",
                      "formatter": "Move in {b}: {c} pts after the bar"}
    opt["series"] = [{"type": "bar", "barWidth": "56%",
                      "data": [{"value": v, "itemStyle": {"color": c, "borderRadius": [5, 5, 0, 0] if v >= 0 else [0, 0, 5, 5]}}
                               for v, c in zip(vals, cols)],
                      "label": {"show": True, "position": "top", "color": fill("text"),
                                "fontSize": 10, "formatter": "{c}"}}]
    return opt


def horizon_option(hz: Dict[int, float]) -> Dict:
    hs = sorted(hz)
    opt = _base({"left": 36, "right": 12, "top": 18, "bottom": 26})
    opt["xAxis"] = charts._axis("category", ["%d wk" % h for h in hs])
    opt["yAxis"] = charts._axis("value")
    opt["tooltip"] = {**charts._tooltip(), "trigger": "item", "formatter": "{b}: {c}"}
    opt["series"] = [{"type": "bar", "barWidth": "50%",
                      "data": [{"value": hz[h], "itemStyle": {
                          "color": fill("mint") if hz[h] > 0 else fill("red"),
                          "borderRadius": [5, 5, 0, 0]}} for h in hs],
                      "label": {"show": True, "position": "top", "color": fill("text"), "fontSize": 10}}]
    return opt


def squad_heat_option(rows: List[Dict], gws: List[int]) -> Dict:
    """rows: [{code, name, xp: {gw: v}, beaten: {gw: bool}}], top to bottom."""
    names = [r["name"] for r in rows][::-1]
    codes = [r["code"] for r in rows][::-1]
    data, marks = [], []
    vmax = max([v for r in rows for v in r["xp"].values()] + [1.0])
    for yi, r in enumerate(rows[::-1]):
        for xi, g in enumerate(gws):
            v = round(r["xp"].get(g, 0.0), 1)
            data.append({"value": [xi, yi, v],
                         "itemStyle": ({"borderColor": fill("red"), "borderWidth": 2}
                                       if r["beaten"].get(g) else {})})
    opt = _base({"left": 8, "right": 12, "top": 8, "bottom": 30, "containLabel": True})
    opt["tooltip"] = {**charts._tooltip(), "trigger": "item", "position": "top"}
    opt["xAxis"] = {**charts._axis("category", ["GW%d" % g for g in gws]), "position": "bottom"}
    opt["yAxis"] = charts._axis("category", names)
    opt["yAxis"]["axisLabel"] = {**opt["yAxis"]["axisLabel"], "fontSize": 11,
                                 "color": fill("text"), "width": 96, "overflow": "truncate"}
    opt["visualMap"] = {"show": False, "min": 0, "max": vmax,
                        "inRange": {"color": charts.heat_ramp()}}
    opt["series"] = [{"type": "heatmap", "data": data,
                      "label": {"show": True, "color": fill("text"), "fontSize": 10,
                                "formatter": "{@[2]}"},
                      "itemStyle": {"borderRadius": 6, "borderColor": "#0B0F17", "borderWidth": 3},
                      "emphasis": {"itemStyle": {"shadowBlur": 12, "shadowColor": charts._rgba(fill("mint"), 0.6)}},
                      "animationDuration": 900}]
    charts.with_image_labels(opt, [player_photo_url(c) for c in codes], size=24)
    return opt
