"""Background checks for a transfer, before the app recommends it.

A projection says "B scores more than A over six weeks". A manager needs more
than that before spending a transfer:

- **Timing.** Is now the week, or does the gain only arrive later (so bank the
  transfer and move then)? `timing()` prices the move made in each week of the
  horizon, which gives the ENTRY point for the incoming player and the EXIT point
  for the outgoing one.
- **Robustness.** Does the move win over one, three, six AND eight weeks, or
  only on one window? A move that wins only on the longest window rests on the
  least reliable forecasts.
- **Why do we own him?** The outgoing player may have been bought for a reason
  the next six weeks do not show: fixtures that turn after the horizon, penalties,
  a DEFCON floor, underlying numbers better than his points (a cold spell, not a
  decline).
- **Is the new man real?** Points well above his xG and xA (running hot), a
  minutes pattern that is not nailed, injury news, a price about to move.

Evidence the flags lean on (docs/WORKFLOW.md, 22 Sep persistence test): xGI/90
predicts later points at r=0.53, points at only 0.26, luck (G+A minus xGI) at
-0.01, and DEFCON per 90 at 0.71. So luck is noise, underlying rate is signal.

No Streamlit imports.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12, "GKP": 999}
HORIZONS = (1, 3, 6, 8)


# ── Per-player profile from this season's match rows ─────────────────────────

def profile(code: int, season_rows: pd.DataFrame, players: pd.DataFrame) -> Dict:
    """Minutes pattern, underlying rate, luck, set pieces and DEFCON for one player."""
    r = season_rows[season_rows["code"] == code].sort_values("gw")
    p = players[players["code"] == code]
    p = p.iloc[0] if not p.empty else pd.Series(dtype=object)
    pos = str(p.get("position") or (r["position"].iloc[0] if not r.empty else ""))
    mins = r["minutes"].fillna(0)
    played = r[mins > 0]
    n = int(len(r))
    tot_min = float(mins.sum())
    g, a = float(r["goals_scored"].fillna(0).sum()), float(r["assists"].fillna(0).sum())
    xg, xa = float(r["xg"].fillna(0).sum()), float(r["xa"].fillna(0).sum())
    per90 = (90.0 / tot_min) if tot_min > 0 else 0.0
    dc = r["defensive_contribution"].fillna(0) if "defensive_contribution" in r else pd.Series(dtype=float)
    thr = DEFCON_THRESHOLD.get(pos, 999)
    starts = r["starts"].fillna((r["minutes"] >= 60).astype(float)) if "starts" in r else (mins >= 60)
    return {
        "code": int(code), "name": p.get("web_name"), "position": pos,
        "team": p.get("team_short"), "price": float(p.get("price") or 0),
        "gws": n, "starts": int(starts.sum()), "minutes": int(tot_min),
        "mins_list": [int(x) for x in mins.tolist()],
        "mins_per_start": round(float(mins[starts > 0].mean()), 1) if (starts > 0).any() else 0.0,
        "goals": int(g), "assists": int(a),
        "xgi": round(xg + xa, 2), "xgi90": round((xg + xa) * per90, 2),
        "ga90": round((g + a) * per90, 2),
        "luck": round((g + a) - (xg + xa), 2),
        "points": int(r["total_points"].fillna(0).sum()),
        "pts_per_start": round(float(r.loc[starts > 0, "total_points"].mean()), 2) if (starts > 0).any() else 0.0,
        "defcon_rate": (round(float((dc[mins >= 60] >= thr).mean()), 2)
                        if thr < 999 and (mins >= 60).any() else None),
        "penalties": (None if pd.isna(p.get("penalties_order")) else int(p.get("penalties_order")))
        if "penalties_order" in p.index else None,
        "status": p.get("status"), "news": p.get("news") or "",
        "chance": p.get("chance_of_playing_next_round"),
        "net_transfers": int((p.get("transfers_in_event") or 0) - (p.get("transfers_out_event") or 0)),
        "ownership": p.get("ownership"),
        "played_all": bool(n > 0 and (mins >= 60).all()),
    }


def fixture_ease(team_id: int, fixtures: pd.DataFrame, gws: List[int]) -> Optional[float]:
    """Mean FPL difficulty over the given gameweeks (lower = easier)."""
    f = fixtures[fixtures["gameweek"].isin(gws)]
    vals = ([float(x) for x in f.loc[f["home_team_id"] == team_id, "home_fdr"]]
            + [float(x) for x in f.loc[f["away_team_id"] == team_id, "away_fdr"]])
    return round(float(np.mean(vals)), 2) if vals else None


# ── Timing: entry and exit points ─────────────────────────────────────────────

def timing(out_xp: Dict[int, float], in_xp: Dict[int, float], friction: float = 2.0) -> Dict:
    """Value of making the move in each week of the horizon.

    Making it in week k means you keep the outgoing player before k and have the
    incoming one from k on. `gain_if_made[k]` is that total difference minus the
    friction a move must clear. The best k is the ENTRY point; the first week the
    incoming player outscores the outgoing one is where the outgoing player's
    EXIT point starts.
    """
    gws = sorted(set(out_xp) | set(in_xp))
    diff = {g: float(in_xp.get(g, 0.0)) - float(out_xp.get(g, 0.0)) for g in gws}
    made = {k: round(sum(diff[g] for g in gws if g >= k) - friction, 2) for g0, k in enumerate(gws)}
    best = max(made, key=made.get) if made else None
    first_ahead = next((g for g in gws if diff[g] > 0), None)
    return {"gws": gws, "diff": {g: round(v, 2) for g, v in diff.items()},
            "gain_if_made": made, "best_week": best,
            "best_gain": made.get(best) if best else None,
            "now_gain": made.get(gws[0]) if gws else None,
            "wait_value": (round(made[best] - made[gws[0]], 2) if best and gws else 0.0),
            "first_week_ahead": first_ahead}


def horizon_gains(out_xp: Dict[int, float], in_xp: Dict[int, float]) -> Dict[int, float]:
    gws = sorted(set(out_xp) | set(in_xp))
    return {h: round(sum(in_xp.get(g, 0) - out_xp.get(g, 0) for g in gws[:h]), 2)
            for h in HORIZONS if h <= len(gws)}


# ── The audit ─────────────────────────────────────────────────────────────────

def audit(out_p: Dict, in_p: Dict, tm: Dict, hz: Dict[int, float],
          out_ease_after: Optional[float], in_ease_after: Optional[float],
          team_gain: Optional[float] = None, friction: float = 2.0) -> Dict:
    """Flags on both players and a verdict: make it now, wait until GW k, or skip."""
    flags: List[Dict] = []

    def flag(side, level, text):
        flags.append({"side": side, "level": level, "text": text})

    # Why do we own the outgoing player?
    if out_p["luck"] <= -2.0 and out_p["xgi90"] >= 0.35:
        flag("out", "warn", "%s is running cold: %d G+A from %.1f xGI. Underlying rate %.2f xGI/90 "
             "is the part that persists (r=0.53); a cold spell alone is not a reason to sell."
             % (out_p["name"], out_p["goals"] + out_p["assists"], out_p["xgi"], out_p["xgi90"]))
    if out_p.get("penalties") == 1:
        flag("out", "warn", "%s is first-choice on penalties." % out_p["name"])
    if out_p.get("defcon_rate") is not None and out_p["defcon_rate"] >= 0.5:
        flag("out", "warn", "%s clears the DEFCON bar in %d%% of his starts (DEFCON per 90 persists "
             "at r=0.71)." % (out_p["name"], round(100 * out_p["defcon_rate"])))
    if out_ease_after is not None and in_ease_after is not None and out_ease_after + 0.4 < in_ease_after:
        flag("out", "warn", "%s's fixtures after the window are easier (difficulty %.1f vs %.1f): "
             "you may want him back." % (out_p["name"], out_ease_after, in_ease_after))
    if out_p["status"] not in (None, "a"):
        flag("out", "good", "%s is flagged (%s): selling now avoids a blank."
             % (out_p["name"], out_p["news"] or out_p["status"]))
    if out_p["net_transfers"] < -100_000:
        flag("out", "info", "%s is being sold heavily (%s net): price likely to drop."
             % (out_p["name"], f'{out_p["net_transfers"]:,}'))

    # Is the incoming player real?
    if in_p["luck"] >= 2.0:
        flag("in", "warn", "%s is running hot: %d G+A from %.1f xGI. Luck does not persist "
             "(r=-0.01); the engine discounts most of it, not all, and the price may not."
             % (in_p["name"], in_p["goals"] + in_p["assists"], in_p["xgi"]))
    if in_p["gws"] >= 3 and in_p["starts"] < in_p["gws"] - 1:
        flag("in", "warn", "%s has started %d of %d: minutes %s."
             % (in_p["name"], in_p["starts"], in_p["gws"], ", ".join(map(str, in_p["mins_list"]))))
    if in_p["status"] not in (None, "a"):
        flag("in", "bad", "%s is flagged: %s." % (in_p["name"], in_p["news"] or in_p["status"]))
    if in_p.get("penalties") == 1:
        flag("in", "good", "%s is first-choice on penalties." % in_p["name"])
    if in_p.get("defcon_rate") is not None and in_p["defcon_rate"] >= 0.5:
        flag("in", "good", "%s clears the DEFCON bar in %d%% of his starts."
             % (in_p["name"], round(100 * in_p["defcon_rate"])))
    if in_p["net_transfers"] > 150_000:
        flag("in", "info", "%s is being bought heavily (+%s net): a price rise is likely, buy before "
             "the deadline if you are making the move." % (in_p["name"], f'{in_p["net_transfers"]:,}'))

    # Robustness across horizons
    signs = [v > 0 for v in hz.values()]
    if signs and not all(signs):
        short = [h for h, v in hz.items() if v <= 0]
        flag("move", "warn", "The move loses over %s week%s: its gain rests on the later, "
             "less certain weeks." % (", ".join(map(str, short)), "" if len(short) == 1 else "s"))

    # Verdict
    gain = team_gain if team_gain is not None else tm.get("now_gain", 0) + friction
    bad = any(f["level"] == "bad" for f in flags)
    warns = sum(1 for f in flags if f["level"] == "warn")
    if bad or gain < 0.5:
        verdict, tone = "Skip", "red"
        why = "It does not clear the bar" if not bad else "The incoming player is flagged"
    elif tm.get("best_week") and tm["best_week"] != tm["gws"][0] and tm.get("wait_value", 0) >= 1.0:
        verdict, tone = "Wait until GW%d" % tm["best_week"], "gold"
        why = "Making it in GW%d is worth %.1f more than now; bank the transfer" % (
            tm["best_week"], tm["wait_value"])
    elif gain >= friction and warns <= 1:
        verdict, tone = "Make it", "mint"
        why = "Clears the %.0f-point bar and survives the background checks" % friction
    elif gain >= friction:
        verdict, tone = "Make it, eyes open", "gold"
        why = "Clears the bar, but read the %d warnings first" % warns
    else:
        verdict, tone = "Marginal", "gold"
        why = "Positive, but under the %.0f-point bar a move needs" % friction
    return {"verdict": verdict, "tone": tone, "why": why, "flags": flags}
