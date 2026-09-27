"""Cup and European minutes from FPL-Core-Insights (github.com/olbauday/FPL-Core-Insights).

What it adds that the FPL API does not: every non-Premier-League match a player
takes part in (Champions League, Europa League, Conference League, EFL Cup),
with kickoff times and minutes. That is the midweek workload behind weekend
rotation, which the engine cannot see from Premier League rows alone.

The repository has NO licence, so its data is cached locally under
data/cache/core_insights/ (gitignored) and must never be committed to the
public repo. Personal analysis only.

Output of `midweek_minutes(season)`: one row per (code, match) outside the
Premier League with the kickoff time and minutes played.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import pandas as pd
import requests

logger = logging.getLogger(__name__)

REPO_API = "https://api.github.com/repos/olbauday/FPL-Core-Insights/contents/data"
RAW = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data"
CACHE = Path(__file__).resolve().parent.parent / "cache" / "core_insights"
NON_PL = ("Champions League", "Europa League", "Conference League", "EFL Cup", "FA Cup")


def _season_dir(season: str) -> str:
    """'2025-26' -> '2025-2026'."""
    a, b = season.split("-")
    return "%s-%s" % (a, a[:2] + b[-2:] if len(b) == 2 else b)


def _list(path: str) -> List[dict]:
    r = requests.get("%s/%s" % (REPO_API, quote(path)), timeout=20,
                     headers={"Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        return []
    return r.json() if isinstance(r.json(), list) else []


def _get_csv(path: str, cache_to: Path, refresh: bool) -> Optional[pd.DataFrame]:
    if cache_to.exists() and not refresh:
        return pd.read_csv(cache_to)
    r = requests.get("%s/%s" % (RAW, quote(path)), timeout=30)
    if r.status_code != 200:
        return None
    cache_to.parent.mkdir(parents=True, exist_ok=True)
    cache_to.write_bytes(r.content)
    return pd.read_csv(io.BytesIO(r.content))


def midweek_minutes(season: str, refresh_live: bool = False) -> pd.DataFrame:
    """Every non-PL appearance in a season: code, kickoff, minutes, competition.

    Completed seasons are read from the local cache once fetched. The live
    season's latest gameweeks are re-fetched when `refresh_live` is set.
    """
    sd = _season_dir(season)
    players = _get_csv("%s/players.csv" % sd, CACHE / sd / "players.csv", refresh_live)
    if players is None:
        return pd.DataFrame()
    id_to_code = dict(zip(players["player_id"], players["player_code"]))
    jobs = []
    for comp in NON_PL:
        cdir = CACHE / sd / comp
        listing = _list("%s/By Tournament/%s" % (sd, comp)) if (refresh_live or not cdir.exists()) else \
            [{"name": p.name, "type": "dir"} for p in cdir.iterdir() if p.is_dir()]
        for gwdir in listing:
            if gwdir.get("type") != "dir":
                continue
            base = "%s/By Tournament/%s/%s" % (sd, comp, gwdir["name"])
            for f in ("matches.csv", "playermatchstats.csv"):
                jobs.append((comp, gwdir["name"], f, base + "/" + f, cdir / gwdir["name"] / f))

    def _run(job):
        comp, gw, f, path, dest = job
        return comp, gw, f, _get_csv(path, dest, refresh_live and not dest.exists())

    got = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for comp, gw, f, df in ex.map(_run, jobs):
            if df is not None:
                got[(comp, gw, f)] = df
    rows = []
    for (comp, gw, f), pms in got.items():
        if f != "playermatchstats.csv":
            continue
        m = got.get((comp, gw, "matches.csv"))
        if m is None or pms.empty:
            continue
        ko = dict(zip(m["match_id"], m["kickoff_time"]))
        for _, r in pms.iterrows():
            mins = r.get("minutes_played")
            if pd.isna(mins) or float(mins) <= 0:
                continue
            code = id_to_code.get(r["player_id"])
            if code is None:
                continue
            rows.append({"code": int(code), "kickoff": ko.get(r["match_id"]),
                         "minutes": float(mins), "competition": comp,
                         "match_id": r["match_id"]})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["kickoff"] = pd.to_datetime(out["kickoff"], utc=True, errors="coerce")
        out = out.dropna(subset=["kickoff"]).drop_duplicates(["code", "match_id"])
    logger.info("core-insights %s: %d non-PL appearances", season, len(out))
    return out


def attach_midweek(pl_rows: pd.DataFrame, extra: pd.DataFrame, days: float = 6.0) -> pd.DataFrame:
    """Add `mw_minutes` (non-PL minutes in the `days` before each PL kickoff)
    and `mw_played` (1 if any) to Premier League rows (need code, kickoff_time)."""
    out = pl_rows.copy()
    out["mw_minutes"] = 0.0
    if extra is None or extra.empty or "kickoff_time" not in out.columns:
        out["mw_played"] = 0.0
        return out
    ko = pd.to_datetime(out["kickoff_time"], utc=True, errors="coerce")
    ex = extra.sort_values("kickoff")
    by = {c: g for c, g in ex.groupby("code")}
    vals = []
    for code, t in zip(out["code"], ko):
        g = by.get(code)
        if g is None or pd.isna(t):
            vals.append(0.0)
            continue
        w = g[(g["kickoff"] < t) & (g["kickoff"] >= t - pd.Timedelta(days=days))]
        vals.append(float(w["minutes"].sum()))
    out["mw_minutes"] = vals
    out["mw_played"] = (out["mw_minutes"] > 0).astype(float)
    return out
