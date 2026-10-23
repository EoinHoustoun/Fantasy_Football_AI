"""Fixture congestion per club and gameweek: midweek games, rest days.

FPL's fixture list only holds Premier League matches. A Thursday in the Europa
League or a League Cup tie changes who starts on Sunday, and who started in
midweek is a strong hint about the weekend XI. This joins the league calendar
to the European and domestic-cup calendar from `data.fetchers.espn_fixtures`
and answers, for every club's league match:

- `rest_days`   days since the club's previous match in ANY competition
- `mw_before`   a non-league match in the 4 days before (the rotation risk)
- `mw_after`    a non-league match in the 4 days after (managers rest players for it)
- `comp_before` / `comp_after`   which competition, for the label

`live_context()` serves the current season; `archive_context()` the past ones for
research (`scripts/research_congestion_minutes.py`).

No Streamlit imports.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

from data.fetchers.espn_fixtures import fetch_season, team_code

WINDOW = timedelta(days=4)
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"


def _cups(season: str) -> pd.DataFrame:
    rows = fetch_season(season)
    df = pd.DataFrame(rows, columns=["team", "date", "comp", "opponent", "home", "status"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def context(league: pd.DataFrame, cups: pd.DataFrame) -> pd.DataFrame:
    """`league`: team, gw, kickoff (UTC). Returns it with the congestion columns."""
    out = league.copy()
    out["kickoff"] = pd.to_datetime(out["kickoff"], utc=True)
    parts = [out[["team", "kickoff"]].rename(columns={"kickoff": "date"}).assign(comp="PL")]
    if not cups.empty:
        parts.append(cups[["team", "date", "comp"]])
    every = pd.concat(parts, ignore_index=True).sort_values(["team", "date"])
    rest, before, after, cb, ca = [], [], [], [], []
    by_team = {t: g for t, g in every.groupby("team")}
    for _, r in out.iterrows():
        g = by_team.get(r["team"])
        k = r["kickoff"]
        if g is None or pd.isna(k):
            rest.append(None); before.append(False); after.append(False); cb.append(""); ca.append("")
            continue
        prev = g[g["date"] < k - timedelta(hours=6)]
        rest.append(round((k - prev["date"].iloc[-1]).total_seconds() / 86400, 1) if len(prev) else None)
        nl = g[g["comp"] != "PL"]
        b = nl[(nl["date"] < k) & (nl["date"] >= k - WINDOW)]
        a = nl[(nl["date"] > k) & (nl["date"] <= k + WINDOW)]
        before.append(bool(len(b))); after.append(bool(len(a)))
        cb.append(b["comp"].iloc[-1] if len(b) else ""); ca.append(a["comp"].iloc[0] if len(a) else "")
    out["rest_days"], out["mw_before"], out["mw_after"] = rest, before, after
    out["comp_before"], out["comp_after"] = cb, ca
    return out


def live_context(season: str, gws: Optional[List[int]] = None) -> pd.DataFrame:
    """Congestion for the live season from FPL's raw fixtures (they carry kickoff times)."""
    boot = json.loads((CACHE / "fpl_bootstrap.json").read_text())
    fx = json.loads((CACHE / "fpl_fixtures.json").read_text())
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    rows = []
    for f in fx:
        if f.get("event") is None or (gws and int(f["event"]) not in gws):
            continue
        for side, other in (("team_h", "team_a"), ("team_a", "team_h")):
            rows.append({"team": short[f[side]], "opp": short[f[other]], "gw": int(f["event"]),
                         "home": side == "team_h", "kickoff": f.get("kickoff_time")})
    return context(pd.DataFrame(rows), _cups(season))


def archive_context(rows: pd.DataFrame, season: str) -> pd.DataFrame:
    """Congestion for a finished season from archive rows (team_name, gw, kickoff_time)."""
    lg = (rows[rows["season"] == season][["team_name", "gw", "kickoff_time", "fixture"]]
          .drop_duplicates(["team_name", "fixture"]))
    lg = lg.assign(team=lg["team_name"].map(team_code), kickoff=lg["kickoff_time"])
    lg = lg.dropna(subset=["team"])
    return context(lg[["team", "gw", "fixture", "kickoff"]], _cups(season))
