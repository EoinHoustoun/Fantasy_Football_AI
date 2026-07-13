"""
Playbook · empirical answers to the "how should I actually play FPL"
questions, computed from the 10-season archive.

Every function returns a plain dict/DataFrame the Playbook page renders.
Questions covered:
  - best XI formation since DEFCON (is 5-4-1 real?)
  - where points-per-£ lives by position (spend on DEF or MID?)
  - CB-types vs FB-types; good-team vs bad-team defenders
  - penalty-taker uplift
  - form vs fixtures vs underlying xGI · what actually predicts next points
  - how many fixtures ahead matter (horizon)
  - how fast team value grows (template tracking)
"""

import json
import logging
from itertools import product
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import CACHE_DIR, LAST_COMPLETE_SEASON

logger = logging.getLogger(__name__)

XG_SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]

# legal FPL formations (DEF, MID, FWD)
FORMATIONS = [(d, m, f) for d, m, f in product(range(3, 6), range(2, 6), range(1, 4))
              if d + m + f == 10]


# ── 1. Formation: what XI shape actually maxes points ────────────────────────

def best_formation_per_gw(opt: pd.DataFrame) -> pd.DataFrame:
    """
    For each GW, the formation of the league-wide best legal XI
    (top scorer per slot, regardless of budget). Answers "which shape
    has the highest ceiling now DEFCON exists".
    """
    rows = []
    for gw, g in opt.groupby("gw"):
        g = g[g["points"].notna()]
        by_pos = {p: g[g["position"] == p].nlargest(6, "points")["points"].tolist()
                  for p in ("GKP", "DEF", "MID", "FWD")}
        if not by_pos["GKP"]:
            continue
        best = None
        for d, m, f in FORMATIONS:
            if len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m or len(by_pos["FWD"]) < f:
                continue
            total = (by_pos["GKP"][0] + sum(by_pos["DEF"][:d])
                     + sum(by_pos["MID"][:m]) + sum(by_pos["FWD"][:f]))
            if best is None or total > best[1]:
                best = ((d, m, f), total)
        if best:
            (d, m, f), total = best
            rows.append({"gw": int(gw), "formation": f"{d}-{m}-{f}",
                         "def": d, "mid": m, "fwd": f, "xi_points": float(total)})
    return pd.DataFrame(rows)


def formation_summary(opt: pd.DataFrame,
                      perfect_json: Optional[Dict] = None) -> Dict:
    per_gw = best_formation_per_gw(opt)
    counts = per_gw["formation"].value_counts()
    answer = {
        "best_xi_formations": counts.to_dict(),
        "avg_def": round(float(per_gw["def"].mean()), 2),
        "avg_mid": round(float(per_gw["mid"].mean()), 2),
        "avg_fwd": round(float(per_gw["fwd"].mean()), 2),
        "per_gw": per_gw,
    }
    if perfect_json is not None:
        forms = []
        for g in perfect_json["perfect"]["per_gw"]:
            pos = [perfect_json["players"][str(c)]["position"] for c in g["xi"]]
            forms.append(f"{pos.count('DEF')}-{pos.count('MID')}-{pos.count('FWD')}")
        answer["perfect_season_formations"] = pd.Series(forms).value_counts().to_dict()
    return answer


# ── 2. Position points share by season (the DEFCON shift) ────────────────────

def position_share_by_season(gw_archive: pd.DataFrame) -> pd.DataFrame:
    df = gw_archive[gw_archive["season"].isin(XG_SEASONS)]
    share = df.groupby(["season", "position"])["total_points"].sum().reset_index()
    share["pct_of_points"] = (share.groupby("season")["total_points"]
                              .transform(lambda s: 100 * s / s.sum()))
    return share[["season", "position", "pct_of_points"]]


# ── 3. Defender archetypes ────────────────────────────────────────────────────

def _load_defender_roles(season: str) -> Dict[int, str]:
    """Curated CB/FB labels (assets/defender_roles_{season}.json), editable."""
    from config import ROOT_DIR
    path = ROOT_DIR / "assets" / f"defender_roles_{season.replace('-', '_')}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {int(code): v["role"] for code, v in raw.items()
            if not code.startswith("_")}


def defender_archetypes(summary: pd.DataFrame, gw_archive: pd.DataFrame,
                        season: str = LAST_COMPLETE_SEASON) -> Dict:
    """
    Centre-backs vs full-backs/wing-backs, crossed with team defensive tier
    (clean-sheet terciles). Roles come from the curated mapping in
    assets/defender_roles_*.json (hand-labelled, user-editable); the stat
    heuristic only covers players missing from that file. Min 900 mins.
    """
    defs = summary[(summary["season"] == season)
                   & (summary["position"] == "DEF")
                   & (summary["minutes"] >= 900)].copy()
    defs["cbit_per90"] = defs["cbit_total"] / defs["minutes"] * 90
    defs["xa_per90"] = defs["xa"] / defs["minutes"] * 90

    roles = _load_defender_roles(season)
    heuristic = np.where(
        (defs["xa_per90"] >= 0.10) | (defs["assists_per90"] >= 0.12), "FB", "CB")
    defs["role"] = [roles.get(int(c), h) for c, h in zip(defs["code"], heuristic)]
    defs["archetype"] = defs["role"].map(
        {"FB": "Full-back / wing-back", "CB": "Centre-back"})
    defs["role_source"] = ["curated" if int(c) in roles else "heuristic"
                           for c in defs["code"]]

    # team defensive tier from team clean sheets (keeper rows)
    season_rows = gw_archive[gw_archive["season"] == season]
    gk = season_rows[(season_rows["position"] == "GKP") & (season_rows["minutes"] >= 60)]
    team_cs = gk.groupby("team_name")["clean_sheets"].sum().sort_values(ascending=False)
    terciles = pd.qcut(team_cs, 3, labels=["Bottom tier", "Mid tier", "Top tier"])
    defs["team_tier"] = defs["team_name"].map(dict(zip(team_cs.index, terciles)))

    grid = (defs.groupby(["archetype", "team_tier"], observed=True)
            .agg(n=("code", "size"),
                 avg_pts=("total_points", "mean"),
                 avg_ppm=("pts_per_million", "mean"),
                 avg_defcon=("defcon_points", "mean"),
                 avg_price=("start_price", "mean"))
            .round(1).reset_index())

    top = defs.nlargest(12, "pts_per_million")[
        ["web_name", "team_name", "archetype", "team_tier", "start_price",
         "total_points", "pts_per_million", "defcon_points", "cbit_per90"]].round(2)
    return {"grid": grid, "top_value": top, "n_defs": len(defs)}


# ── 4. Penalty takers ─────────────────────────────────────────────────────────

def pen_taker_uplift(summary: pd.DataFrame) -> Optional[pd.DataFrame]:
    bs_path = CACHE_DIR / "archive" / "fpl_bootstrap_2025_26_final.json"
    if not bs_path.exists():
        return None
    with open(bs_path) as f:
        bs = json.load(f)
    takers = {int(e["code"]) for e in bs["elements"]
              if e.get("penalties_order") == 1}
    cur = summary[(summary["season"] == LAST_COMPLETE_SEASON)
                  & (summary["minutes"] >= 1500)].copy()
    cur["pen_taker"] = cur["code"].isin(takers)
    out = (cur[cur["position"].isin(["DEF", "MID", "FWD"])]
           .groupby(["position", "pen_taker"])
           .agg(n=("code", "size"),
                med_pts=("total_points", "median"),
                med_ppm=("pts_per_million", "median"))
           .round(1).reset_index())
    return out


# ── 5. Form vs fixtures vs xGI · what predicts next points ───────────────────

def _opponent_ease(gw_archive: pd.DataFrame, seasons: List[str]) -> pd.DataFrame:
    """Ease = avg FPL points players score AGAINST each team (higher = softer)."""
    df = gw_archive[(gw_archive["season"].isin(seasons))
                    & (gw_archive["minutes"] > 0)]
    ease = (df.groupby(["season", "opponent_team"])["total_points"]
            .mean().reset_index().rename(columns={"total_points": "opp_ease"}))
    return ease


def predictiveness(gw_archive: pd.DataFrame,
                   seasons: List[str] = XG_SEASONS) -> Dict:
    """
    Spearman correlation of next-GW points (and next-4-GW points) with:
      past-4 points (form) · past-4 xGI (underlying) · next opponent ease.
    Players with minutes>0; DGWs aggregated per (player, GW).
    """
    df = gw_archive[gw_archive["season"].isin(seasons)].copy()
    agg = (df.groupby(["season", "code", "gw"])
           .agg(pts=("total_points", "sum"), xgi=("xgi", "sum"),
                minutes=("minutes", "sum"), opponent=("opponent_team", "first"),
                position=("position", "first"))
           .reset_index().sort_values(["season", "code", "gw"]))

    ease = _opponent_ease(gw_archive, seasons)
    agg = agg.merge(ease, left_on=["season", "opponent"],
                    right_on=["season", "opponent_team"], how="left")

    g = agg.groupby(["season", "code"])
    agg["form4"] = g["pts"].transform(lambda s: s.shift(1).rolling(4, min_periods=2).sum())
    agg["xgi4"] = g["xgi"].transform(lambda s: s.shift(1).rolling(4, min_periods=2).sum())
    agg["next1"] = agg["pts"]
    agg["next4"] = g["pts"].transform(
        lambda s: s.shift(-1).rolling(4, min_periods=2).sum().shift(-(4 - 1)))

    sample = agg[(agg["minutes"] > 0) & agg["form4"].notna() & agg["xgi4"].notna()]
    res = {
        "n": len(sample),
        "next_gw": {
            "form (last-4 pts)": round(float(sample["form4"].corr(sample["next1"], method="spearman")), 3),
            "underlying (last-4 xGI)": round(float(sample["xgi4"].corr(sample["next1"], method="spearman")), 3),
            "fixture ease (next opp)": round(float(sample["opp_ease"].corr(sample["next1"], method="spearman")), 3),
        },
    }
    s4 = sample[sample["next4"].notna()]
    res["next_4_gws"] = {
        "form (last-4 pts)": round(float(s4["form4"].corr(s4["next4"], method="spearman")), 3),
        "underlying (last-4 xGI)": round(float(s4["xgi4"].corr(s4["next4"], method="spearman")), 3),
    }
    return res


def fixture_horizon(gw_archive: pd.DataFrame,
                    seasons: List[str] = XG_SEASONS) -> pd.DataFrame:
    """
    For horizons h = 2..8: how well does average opponent ease over the next
    h GWs predict points over the next h GWs? Peak = how far ahead to look.
    """
    df = gw_archive[gw_archive["season"].isin(seasons)].copy()
    agg = (df.groupby(["season", "code", "gw"])
           .agg(pts=("total_points", "sum"), minutes=("minutes", "sum"),
                opponent=("opponent_team", "first"))
           .reset_index().sort_values(["season", "code", "gw"]))
    ease = _opponent_ease(gw_archive, seasons)
    agg = agg.merge(ease, left_on=["season", "opponent"],
                    right_on=["season", "opponent_team"], how="left")
    agg = agg[agg["minutes"] > 0]

    g = agg.groupby(["season", "code"])
    rows = []
    for h in range(2, 9):
        nxt_pts = g["pts"].transform(
            lambda s: s.shift(-1).rolling(h, min_periods=h).sum().shift(-(h - 1)))
        nxt_ease = g["opp_ease"].transform(
            lambda s: s.shift(-1).rolling(h, min_periods=h).mean().shift(-(h - 1)))
        mask = nxt_pts.notna() & nxt_ease.notna()
        rows.append({"horizon": h,
                     "spearman": round(float(nxt_ease[mask].corr(nxt_pts[mask],
                                                                 method="spearman")), 3),
                     "n": int(mask.sum())})
    return pd.DataFrame(rows)


# ── 5b. Minutes · the master variable ─────────────────────────────────────────

def minutes_importance(summary: pd.DataFrame) -> Dict:
    """
    Quantify how dominant minutes are: correlation with season points, and
    avg points / ppg / pts-per-£ by minutes band. The ppg column shows it's
    not just accumulation · managers start their best players, so heavy
    minutes also mark per-game quality.
    """
    df = summary[summary["season"].isin(XG_SEASONS)].copy()
    corr = float(df["minutes"].corr(df["total_points"], method="spearman"))

    bands = pd.cut(df["minutes"], bins=[0, 900, 1800, 2700, 3500],
                   labels=["<900 (rotation)", "900–1800 (squad)",
                           "1800–2700 (regular)", "2700+ (nailed)"])
    by_band = (df.assign(band=bands).dropna(subset=["band"])
               .groupby("band", observed=True)
               .agg(n=("code", "size"),
                    avg_points=("total_points", "mean"),
                    avg_ppg=("ppg", "mean"),
                    avg_ppm=("pts_per_million", "mean"))
               .round(1).reset_index())
    return {"spearman": round(corr, 3), "by_band": by_band, "n": len(df)}


def minutes_intensity(summary: pd.DataFrame) -> Dict:
    """
    The clean test: among REGULARS (20+ appearances, so games-played can't
    confound it), does a full-90 player beat one subbed early?

    Answer: per-90 efficiency is flat (slightly higher for early-subbed
    attackers · their returns cluster while they're on), but points PER
    MATCH climb steadily with minutes-per-game: extra minutes are extra
    exposure (returns can land any minute, 60' threshold, CS eligibility,
    DEFCON accumulation).
    """
    df = summary[summary["season"].isin(XG_SEASONS)].copy()
    df = df[df["games_played"] >= 20].copy()
    df["mins_per_game"] = df["minutes"] / df["games_played"]
    df["pts_per_appearance"] = df["total_points"] / df["games_played"]
    df["band"] = pd.cut(df["mins_per_game"], bins=[0, 65, 75, 85, 91],
                        labels=["<65 (subbed early)", "65–75", "75–85",
                                "85+ (full 90)"])
    overall = (df.groupby("band", observed=True)
               .agg(n=("code", "size"),
                    pts_per_match=("pts_per_appearance", "mean"),
                    pts_per_90=("pp90", "mean"),
                    ppm=("pts_per_million", "mean"))
               .round(2).reset_index())
    by_pos = (df[df["position"].isin(["DEF", "MID", "FWD"])]
              .groupby(["position", "band"], observed=True)
              .agg(n=("code", "size"),
                   pts_per_match=("pts_per_appearance", "mean"))
              .round(2).reset_index())
    return {"overall": overall, "by_pos": by_pos, "n": len(df)}


# ── 6. Team value growth ──────────────────────────────────────────────────────

def team_value_growth(gw_archive: pd.DataFrame,
                      season: str = LAST_COMPLETE_SEASON) -> Dict:
    """
    Track the price of the 15 most-owned players at GW1 across the season -
    a proxy for how a sharp template team's value grows. £/month estimate.
    """
    df = gw_archive[gw_archive["season"] == season]
    agg = (df.groupby(["code", "gw"])
           .agg(price=("price", "last"), selected=("selected", "last"))
           .reset_index())
    gw1 = agg[agg["gw"] == 1].nlargest(15, "selected")
    codes = gw1["code"].tolist()
    traj = (agg[agg["code"].isin(codes)]
            .groupby("gw")["price"].sum().reset_index())
    traj["growth"] = traj["price"] - traj["price"].iloc[0]
    total_growth = float(traj["growth"].iloc[-1])
    return {
        "trajectory": traj,
        "total_growth": round(total_growth, 1),
        "per_month": round(total_growth / 9.0, 2),   # Aug–May ≈ 9 months
        "note": ("Tracks GW1's 15 most-owned players held all season. Sell "
                 "price rises £0.1 for every £0.2 of price rise, so realised "
                 "budget gain is roughly half the raw growth."),
    }


# ── Q10-Q12 · 2026-27 squad-build doctrine (added 2026-07) ─────────────────────

def premium_captaincy(gw_archive: pd.DataFrame, summary: pd.DataFrame,
                      season: str = "2025-26") -> Dict:
    """Is the premium captain worth it? Set-and-forget vs rotation vs
    reallocating the price difference into the rest of the XI."""
    import itertools

    g = gw_archive[gw_archive["season"] == season]
    s = summary[(summary["season"] == season) & (summary["minutes"] >= 2000)]
    prem = s[s["start_price"] >= 8.0].nlargest(8, "total_points")
    codes = prem["code"].tolist()
    name = dict(zip(prem["code"], prem["web_name"]))
    price = dict(zip(prem["code"], prem["start_price"]))

    pg = (g[g["code"].isin(codes)].groupby(["code", "gw"])["total_points"].sum()
          .unstack(fill_value=0).reindex(columns=range(1, 39), fill_value=0))
    saf = pg.sum(axis=1).sort_values(ascending=False)

    home = (g[g["code"].isin(codes)].groupby(["code", "gw"])["was_home"].max()
            .unstack(fill_value=False))

    def _home_rot(a, b):
        tot = 0.0
        for w in range(1, 39):
            ha = bool(home[w].get(a, False)) if w in home.columns else False
            hb = bool(home[w].get(b, False)) if w in home.columns else False
            pick = a if (ha and not hb) else (
                b if (hb and not ha) else (a if saf[a] >= saf[b] else b))
            tot += float(pg.loc[pick, w])
        return tot

    pairs = []
    for a, b in itertools.combinations(codes, 2):
        perfect = float(pg.loc[[a, b]].max(axis=0).sum())
        pairs.append({"pair": f"{name[a]} + {name[b]}", "perfect": round(perfect),
                      "home_rule": round(_home_rot(a, b)),
                      "combined_price": round(price[a] + price[b], 1)})
    pairs.sort(key=lambda x: -x["perfect"])

    # What does the freed budget buy? Season points by attacker price band.
    att = summary[(summary["season"] == season) & (summary["minutes"] >= 900)
                  & (summary["position"].isin(["MID", "FWD"]))]
    bands = pd.cut(att["start_price"], [4.0, 5.5, 7.0, 8.5, 10.0, 15.5])
    curve = att.groupby(bands, observed=True)["total_points"].agg(["mean", "count"])
    curve.index = [f"£{i.left:g}–{i.right:g}m" for i in curve.index]

    top = [{"name": name[c], "extra": int(v), "price": price[c]}
           for c, v in saf.items()]
    return {"saf": top, "pairs": pairs[:5], "budget_curve": curve.round(1)}


def bench_doctrine(summary: pd.DataFrame, season: str = "2025-26") -> Dict:
    """Strong bench or cheap bench? Autosub demand vs the XI opportunity cost."""
    s = summary[(summary["season"] == season) & (summary["minutes"] >= 900)]
    reg = s[s["starts_total"] >= 25]
    missed_per_starter = float((38 - reg["games_played"]).clip(lower=0).mean())
    autosub_events = missed_per_starter * 10          # 10 outfield XI slots

    bands = pd.cut(s["start_price"], [3.9, 4.5, 5.0, 5.5, 6.5])
    ppg = s.groupby(bands, observed=True).apply(
        lambda d: float((d["total_points"] / d["games_played"].clip(lower=1)).mean()))
    ppg.index = [f"£{i.left:g}–{i.right:g}m" for i in ppg.index]

    # Tiers: 3 outfield bench slots at a band each · autosub pts vs XI cost.
    tiers = []
    labels = list(ppg.index)
    for ti, lbl in enumerate(labels[:3]):
        sub_ppg = float(ppg.iloc[ti])
        autosub_pts = autosub_events * sub_ppg
        extra_cost = ti * 3 * 0.5      # each band step ≈ +£0.5m per slot × 3
        tiers.append({"tier": f"3 subs at {lbl}", "autosub_pts": round(autosub_pts),
                      "extra_cost": round(extra_cost, 1)})
    return {"missed_per_starter": round(missed_per_starter, 1),
            "autosub_events": round(autosub_events),
            "bench_ppg": ppg.round(2), "tiers": tiers}


def defcon_mix(summary: pd.DataFrame, season: str = "2025-26",
               def_budget: float = 26.0) -> Dict:
    """How many DEFCON defenders? Sweep squad mixes under a fixed budget,
    scoring realistic usage (3 start weekly, the 4th plays half the weeks)."""
    d = summary[(summary["season"] == season) & (summary["minutes"] >= 900)
                & (summary["position"] == "DEF")]
    groups = {
        "monster": d[d["defcon_points"] >= 20],
        "premium": d[d["start_price"] >= 5.8],
        "fodder":  d[d["start_price"] <= 4.5],
    }
    stats = {k: {"price": round(float(v["start_price"].mean()), 1),
                 "pts": round(float(v["total_points"].mean())),
                 "n": int(len(v))} for k, v in groups.items()}

    mixes = []
    for k in range(0, 6):
        slots = 5 - k
        budget = def_budget - k * stats["monster"]["price"]
        n_prem = 0
        while (n_prem < slots
               and budget - stats["premium"]["price"]
               >= (slots - n_prem - 1) * stats["fodder"]["price"]):
            n_prem += 1
            budget -= stats["premium"]["price"]
        n_fod = slots - n_prem
        pool = ([stats["monster"]["pts"]] * k + [stats["premium"]["pts"]] * n_prem
                + [stats["fodder"]["pts"]] * n_fod)
        pool.sort(reverse=True)
        usage = sum(pool[:3]) + (pool[3] * 0.5 if len(pool) > 3 else 0)
        mixes.append({"mix": f"{k} DEFCON · {n_prem} premium · {n_fod} fodder",
                      "k": k, "usable_pts": round(usage),
                      "spend": round(k * stats["monster"]["price"]
                                     + n_prem * stats["premium"]["price"]
                                     + n_fod * stats["fodder"]["price"], 1)})
    return {"stats": stats, "mixes": mixes}
