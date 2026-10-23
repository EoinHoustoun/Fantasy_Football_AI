"""Does STARTING a midweek game change weekend minutes in a way the brain misses?

The club-level flag (scripts/research_congestion_minutes.py) added nothing: the
brain reads rotation from recent league minutes. This asks the sharper player
question. For every league match that follows a European or cup match by 4 days
or less, each regular is put in one group by what he did in that midweek match:

  started   in the midweek XI
  sub       came off the bench
  unused    on the bench, did not play
  absent    not in the matchday squad

Lineups come from ESPN's public match summaries, cached per season in
data/cache/espn_lineups_<season>.json. ESPN names are matched to archive
players within the same club and season (accent-folded surname, then a fuzzy
fallback); unmatched names are counted and reported.

Predictions are the brain's own walk-forward folds (data/cache/bench_brain/),
so nothing here saw the outcome. If the brain is well calibrated within each
group there is nothing to add. If a group is systematically off, a per-group
correction to P(60+) and expected minutes is fitted on two seasons and scored on
the third, judged on Brier, minutes MAE and the points ranking, worst season first.

Result (2026-10-23): the big pooled gain comes from the "absent" group, which is
mostly injury that FPL's status flags already give the live engine. Next week
only and without absentees, Brier improves by 0.001-0.007 per season, minutes
MAE gets worse in 2 of 3 and the ranking is flat. Stable direction: benched or
unused midweek plays ~7-14% more weekend minutes, started ~5% fewer. Not an
engine change; shown as a context tag only.

Run:  python scripts/research_midweek_starters.py
Writes docs/research/midweek_starters_<date>.json
"""
import difflib
import json
import sys
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.fetchers.espn_fixtures import COMPETITIONS, _months, team_code  # noqa: E402
from data.processors.archive import load_gw_archive  # noqa: E402

SEASONS = ["2023-24", "2024-25", "2025-26"]
ANCHORS = [6, 12, 18, 24, 30]
GROUPS = ["started", "sub", "unused", "absent"]
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/{what}"
HDR = {"User-Agent": "Mozilla/5.0 (compatible; FPL-Analytics/1.0)"}


def fold(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace(".", " ").replace("'", "").split())


def get(url):
    """GET with retries: one dropped connection should not lose a season's fetch."""
    for attempt in range(4):
        try:
            return requests.get(url, headers=HDR, timeout=20)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return None


def lineups(season):
    path = ROOT / "data" / "cache" / ("espn_lineups_%s.json" % season)
    if path.exists():
        return json.loads(path.read_text())
    out = []
    for league, comp in COMPETITIONS.items():
        for ym in _months(season):
            r = get(BASE.format(league=league, what="scoreboard") + "?dates=%s&limit=1000" % ym)
            if r is None or r.status_code != 200:
                continue
            for ev in r.json().get("events", []):
                teams = [c.get("team", {}).get("displayName") for c in ev["competitions"][0]["competitors"]]
                if not any(team_code(t) for t in teams):
                    continue
                s = get(BASE.format(league=league, what="summary") + "?event=%s" % ev["id"])
                time.sleep(0.15)
                if s is None or s.status_code != 200:
                    continue
                for ro in s.json().get("rosters", []):
                    code = team_code(ro.get("team", {}).get("displayName"))
                    if not code:
                        continue
                    out.append({"team": code, "date": ev["date"], "comp": comp, "event": ev["id"],
                                "players": [{"name": p.get("athlete", {}).get("displayName"),
                                             "starter": bool(p.get("starter")),
                                             "subbed_in": bool(p.get("subbedIn"))}
                                            for p in ro.get("roster", [])]})
    path.write_text(json.dumps(out))
    return out


def match_names(espn_names, roster):
    """roster: list of (code, full_name, web_name) for one club-season. Returns name -> code."""
    full = {c: fold(f) for c, f, w in roster}
    web = {c: fold(w) for c, f, w in roster}
    out = {}
    for n in espn_names:
        fn = fold(n)
        last = fn.split()[-1] if fn else ""
        hit = [c for c in full if full[c] == fn] or [c for c in web if web[c] == fn] \
            or [c for c in web if web[c] == last] or [c for c in full if last and last in full[c].split()]
        if len(hit) != 1:
            best = difflib.get_close_matches(fn, list(full.values()), n=1, cutoff=0.8)
            hit = [c for c in full if best and full[c] == best[0]]
        if len(hit) == 1:
            out[n] = hit[0]
    return out


def build():
    arc = load_gw_archive()
    rows, unmatched, total = [], 0, 0
    for s in SEASONS:
        lu = lineups(s)
        a = arc[arc["season"] == s].copy()
        a["team"] = a["team_name"].map(team_code)
        a["kick"] = pd.to_datetime(a["kickoff_time"], utc=True)
        roster = {t: list(g.drop_duplicates("code")[["code", "player_name", "web_name"]].itertuples(index=False, name=None))
                  for t, g in a.groupby("team")}
        status = {}                                   # (team, event) -> {code: group}
        mids = []                                     # (team, date, event)
        for m in lu:
            mp = match_names([p["name"] for p in m["players"]], roster.get(m["team"], []))
            total += len(m["players"])
            unmatched += sum(1 for p in m["players"] if p["name"] not in mp)
            status[(m["team"], m["event"])] = {mp[p["name"]]: ("started" if p["starter"] else "sub" if p["subbed_in"] else "unused")
                                               for p in m["players"] if p["name"] in mp}
            mids.append((m["team"], pd.Timestamp(m["date"]), m["event"]))
        mid = pd.DataFrame(mids, columns=["team", "date", "event"])
        per = a.groupby(["code", "gw"]).agg(minutes=("minutes", "sum"), points=("total_points", "sum"),
                                            n=("fixture", "nunique"), team=("team", "first"), kick=("kick", "first")).reset_index()
        grp = []
        for r in per.itertuples():
            m = mid[(mid["team"] == r.team) & (mid["date"] < r.kick) & (mid["date"] >= r.kick - timedelta(days=4))]
            if m.empty:
                grp.append(None)
            else:
                st = status.get((r.team, m["event"].iloc[-1]), {})
                grp.append(st.get(r.code, "absent") if st else None)
        per["group"] = grp
        for t in ANCHORS:
            # Our own walk-forward cache, written by scripts/benchmark_brain_horizon.py.
            pr = pd.read_pickle(ROOT / "data" / "cache" / "bench_brain" / ("%s_gw%d.pkl" % (s, t)))
            before = per[(per["gw"] < t) & (per["gw"] >= t - 4)]
            reg = set(before[before["minutes"] >= 60].groupby("code")["gw"].nunique().loc[lambda x: x >= 2].index)
            d = pr.merge(per, on=["code", "gw"], how="inner")
            d = d[d["code"].isin(reg) & (d["n"] == 1) & (d["fixtures"] == 1) & d["group"].notna()]
            rows.append(d.assign(season=s, anchor=t, ahead=d["gw"] - t))
    return pd.concat(rows, ignore_index=True), unmatched, total


def metrics(d, mins, p60, xp):
    rho = np.nanmean([spearmanr(g[xp], g["points"]).correlation for _, g in d.groupby(["anchor", "gw"]) if len(g) > 10])
    return {"mins_mae": round(float((d[mins] - d["minutes"]).abs().mean()), 3),
            "p60_brier": round(float(((d[p60] - d["hit"]) ** 2).mean()), 4),
            "xp_spearman": round(float(rho), 4)}


def main():
    d, unmatched, total = build()
    d["hit"] = (d["minutes"] >= 60).astype(float)
    out = {"rows": int(len(d)), "espn_names": total, "unmatched_names": unmatched, "by_group": {}, "by_group_next_week": {}}
    for key, sub in (("by_group", d), ("by_group_next_week", d[d["ahead"] == 0])):
        for g in GROUPS:
            x = sub[sub["group"] == g]
            if len(x):
                out[key][g] = {"n": int(len(x)), "pred_p60": round(float(x["p60"].mean()), 3), "actual_p60": round(float(x["hit"].mean()), 3),
                               "pred_mins": round(float(x["exp_minutes"].mean()), 1), "actual_mins": round(float(x["minutes"].mean()), 1)}
    loso = {}
    for test in SEASONS:
        tr, te = d[d["season"] != test], d[d["season"] == test].copy()
        bias = float(tr["hit"].mean() - tr["p60"].mean())
        gap = {g: float(tr.loc[tr["group"] == g, "hit"].mean() - tr.loc[tr["group"] == g, "p60"].mean()) - bias
               for g in GROUPS if (tr["group"] == g).any()}
        base_r = float(tr["minutes"].sum() / tr["exp_minutes"].sum())
        mult = {g: float(tr.loc[tr["group"] == g, "minutes"].sum() / tr.loc[tr["group"] == g, "exp_minutes"].sum()) / base_r
                for g in gap}
        k = te["group"].map(mult).fillna(1.0)
        te["p60_adj"] = (te["p60"] + te["group"].map(gap).fillna(0.0)).clip(0, 1)
        te["mins_adj"] = te["exp_minutes"] * k
        te["xp_adj"] = te["xp"] * k
        loso[test] = {"p60_shift": {g: round(v, 3) for g, v in gap.items()}, "mins_mult": {g: round(v, 3) for g, v in mult.items()},
                      "n": int(len(te)), "incumbent": metrics(te, "exp_minutes", "p60", "xp"),
                      "adjusted": metrics(te, "mins_adj", "p60_adj", "xp_adj")}
    out["leave_one_season_out"] = loso
    print(json.dumps(out, indent=1))
    path = ROOT / "docs" / "research" / ("midweek_starters_%s.json" % date.today().isoformat())
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
