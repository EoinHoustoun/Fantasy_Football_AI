"""The cold-start fold · can any of this pick a squad before a ball is kicked?

`benchmark_points_models.py` starts every fold at GW10, so it says nothing about
the case the 26/27 Draft actually faces: no minutes, no form, no in-season
anything, and a squad to pick for the opening weeks.

This test removes the current season entirely. For each test season the training
set is every PRIOR season in full, and the target is GW1-6 of the test season.

Arms:
  * **component model** · trained on prior seasons only, scoring each opening
    fixture. All of its player features come from the previous season's tail,
    which is exactly the information a manager has in August.
  * **season projector** · `analytics/season_projection.py`, the model that
    actually feeds the Value Board and the Draft today, fitted on pairs strictly
    before the test season. Points spread evenly over 38.
  * **season projector x fixture ease** · the same number scaled by opening
    fixture difficulty, which is what the Draft's shape fallback does. The
    archive has no FDR column, so difficulty is reconstructed by ranking each
    opponent's end-of-last-season defensive rating into five buckets and putting
    it through the app's own `1 + (3 - fdr) x 0.15`.
  * **baseline: last season's points**, the thing every projector has to beat.

The incumbent `analytics/points_model.py` cannot be an arm here. Its features are
within-season rolling windows and it drops any player with fewer than three
played gameweeks in the current season, so at GW1-3 it has no rows at all. That
is not a handicap imposed by this harness, it is the property that makes
`model_store._warm` skip it in preseason.

Two questions get separate answers, because they are different decisions:
  1. per fixture · how well is a single opening gameweek ranked
  2. per player over GW1-6 · which is what picking a draft actually asks

    python3 scripts/benchmark_gw1_fold.py
    python3 scripts/benchmark_gw1_fold.py --through 6      # opening window size
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics.component_model import (ComponentPointsModel,  # noqa: E402
                                       PRESEASON_FEATURES, prepare)
from analytics.season_projection import (fit_projection_params,  # noqa: E402
                                         project_season)
from config import CACHE_DIR  # noqa: E402

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gw1-fold")
logging.getLogger("analytics").setLevel(logging.ERROR)

ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "cache" / "archive" / "gw_archive.parquet"
SUMMARY = Path(__file__).resolve().parents[1] / "data" / "cache" / "archive" / "season_summary.parquet"
OUT_JSON = Path(CACHE_DIR) / "benchmark_gw1_fold.json"

SEASON_GWS = 38
STARTER_MINUTES = 60.0
XI = 11

ARMS = [("pred_preseason", "component model (season features only)"),
        ("pred_frozen", "component model (frozen at GW1)"),
        ("pred_component", "component model (updating)"),
        ("pred_projector_fdr", "season projector x fixture ease"),
        ("pred_projector", "season projector (flat)"),
        ("pred_last_season", "baseline: last season's points")]

# Features that describe the two clubs in a fixture rather than the player.
# Frozen separately, because a draft knows who the opponent is in GW5 but not
# how that opponent will be playing by then.
TEAM_FEATS = ["team_att", "team_def", "opp_att", "opp_def", "team_matches",
              "league_gf"]
FIXTURE_FEATS = ["was_home_f"]


def pseudo_fdr(opp_def: pd.Series) -> pd.Series:
    """Reconstruct a 1-5 difficulty from the opponent's defensive rating.

    The archive carries no FDR column. Ranking opponents by how much they were
    conceding at the end of the previous season into five equal buckets is the
    closest honest stand-in, and it is applied to the projector arm only · the
    component model gets the raw ratings as features and does not need it.
    """
    r = opp_def.rank(pct=True)
    return pd.cut(r, [0, .2, .4, .6, .8, 1.0], labels=[5, 4, 3, 2, 1],
                  include_lowest=True).astype(float)


def _freeze(test: pd.DataFrame, gw_df: pd.DataFrame, season: str) -> pd.DataFrame:
    """Rebuild the window's feature rows as they looked before a ball was kicked.

    Player features come from that player's earliest row of the season. Team and
    opponent ratings come from each club's first fixture of the season, so a side
    that starts well does not retroactively improve its own GW6 projection. Only
    `was_home` and which opponent it is vary across the window · the two things a
    draft genuinely knows in advance.
    """
    from analytics.component_model import PLAYER_FEATURES, build_team_form

    # Everything except the opponent and home/away is carried from the player's
    # own first row. That freezes his own club's ratings too, and it does so
    # without going through `team_id`, which the archive fills from the
    # end-of-season lookup and therefore misfiles for a winter transfer.
    carried = [f for f in PLAYER_FEATURES
               if f not in FIXTURE_FEATS + ["opp_att", "opp_def"]]

    first = (test.sort_values("gw").groupby("code", as_index=False).first()
             .set_index("code"))
    out = test.copy()
    for f in carried:
        out[f] = out["code"].map(first[f])

    # The opponent changes every week, so its rating is looked up per row · at
    # the value that club carried into ITS first fixture of the season.
    sides = build_team_form(gw_df)
    sides = sides[sides["season"] == season]
    pre = (sides.sort_values("gw").groupby("team_id", as_index=False).first()
           .set_index("team_id"))
    out["opp_att"] = out["opponent_team"].map(pre["team_att"])
    out["opp_def"] = out["opponent_team"].map(pre["team_def"])
    return out


def _metrics(y: np.ndarray, p: np.ndarray) -> Dict[str, float]:
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0, None)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    if len(y) < 10:
        return {}
    denom = ((y - y.mean()) ** 2).sum()
    sp = pd.Series(p).corr(pd.Series(y), method="spearman")
    return {"rmse": float(np.sqrt(((p - y) ** 2).mean())),
            "mae": float(np.abs(p - y).mean()),
            "r2": float(1 - ((p - y) ** 2).sum() / denom) if denom > 0 else float("nan"),
            "spearman": float(sp) if pd.notna(sp) else float("nan"),
            "n": int(len(y))}


def run(through: int = 6, seasons: Optional[List[str]] = None) -> Dict:
    gw = pd.read_parquet(ARCHIVE)
    summary = pd.read_parquet(SUMMARY)
    all_seasons = sorted(gw["season"].unique())
    test_seasons = seasons or all_seasons[2:]   # need a pair to fit the projector

    logger.warning("preparing features…")
    frame = prepare(gw)

    per_fixture, per_player = [], []
    for season in test_seasons:
        prev = all_seasons[all_seasons.index(season) - 1]

        train = frame[frame["season"] < season]
        train = train[train["career_games"] >= 3]
        test = frame[(frame["season"] == season) & (frame["gw"] <= through)].copy()
        if len(train) < 5000 or len(test) < 500:
            continue

        # Arm 1 · component model, features updating through the window. A GW5
        # row's form window legitimately contains GW1-4, which is right for
        # "what should I captain in GW5" and WRONG for "who should I draft in
        # August". Kept as a reference point, not as the draft answer.
        model = ComponentPointsModel().fit(train)
        test["pred_component"] = model.predict(test)["xp"].values

        # Arm 2 · the same model with every feature frozen at the pre-season
        # state. Player form comes from each player's first row of the season,
        # team ratings from each club's first fixture, and only the opponent
        # identity and home/away change from gameweek to gameweek. This is the
        # information a draft actually has.
        frozen = _freeze(test, gw, season)
        test["pred_frozen"] = model.predict(frozen)["xp"].values

        # Arm 3 · the same architecture with the form window REMOVED and only
        # whole-prior-season carryover left. If the event decomposition is sound
        # and it was the three-match window that did not survive the summer,
        # this is the arm that shows it.
        pre_model = ComponentPointsModel(features=PRESEASON_FEATURES).fit(train)
        test["pred_preseason"] = pre_model.predict(frozen)["xp"].values

        # Arms 2 and 3 · the season projector that feeds the Draft today.
        params = fit_projection_params(summary, through=prev)
        proj = project_season(summary, prev, params).set_index("code")["projected_points"]
        per_gw = test["code"].map(proj) / SEASON_GWS
        test["pred_projector"] = per_gw
        # A promoted opponent has no prior rating. Average difficulty is the
        # honest stand-in; dropping the row instead would quietly delete every
        # fixture against a promoted side from all four arms.
        fdr = pseudo_fdr(test["opp_def"]).fillna(3.0)
        test["pred_projector_fdr"] = per_gw * (1.0 + (3.0 - fdr) * 0.15).clip(0.5, 1.5)

        # Arm 4 · last season's points, spread the same way.
        last = summary[summary["season"] == prev].set_index("code")["total_points"]
        test["pred_last_season"] = test["code"].map(last) / SEASON_GWS

        cols = [c for c, _ in ARMS]
        test = test.dropna(subset=cols)
        per_fixture.append(test[["season", "gw", "code", "total_points",
                                 "ewm_minutes"] + cols])

        # The draft question · one row per player over the whole opening window.
        agg = (test.groupby(["season", "code"], as_index=False)
               .agg(dict([("total_points", "sum"), ("ewm_minutes", "max")]
                         + [(c, "sum") for c in cols])))
        per_player.append(agg)
        logger.warning("%s · trained on %d rows, scored %d fixtures / %d players",
                       season, len(train), len(test), len(agg))

    if not per_fixture:
        raise SystemExit("no folds ran")
    return _summarise(pd.concat(per_fixture, ignore_index=True),
                      pd.concat(per_player, ignore_index=True), through)


def _summarise(fx: pd.DataFrame, pl: pd.DataFrame, through: int) -> Dict:
    out: Dict = {"through_gw": through, "fixtures": int(len(fx)),
                 "players": int(len(pl)), "per_fixture": {}, "gw1_only": {},
                 "per_player": {}, "per_player_starters": {}, "per_season": {},
                 "draft": {}}

    starters_fx = fx[fx["ewm_minutes"] >= STARTER_MINUTES]
    gw1 = starters_fx[starters_fx["gw"] == 1]
    for col, label in ARMS:
        out["gw1_only"][label] = _metrics(gw1["total_points"], gw1[col])
    starters_pl = pl[pl["ewm_minutes"] >= STARTER_MINUTES]

    for col, label in ARMS:
        out["per_fixture"][label] = _metrics(starters_fx["total_points"],
                                             starters_fx[col])
        out["per_player"][label] = _metrics(pl["total_points"], pl[col])
        out["per_player_starters"][label] = _metrics(starters_pl["total_points"],
                                                     starters_pl[col])

    for season, block in starters_pl.groupby("season"):
        out["per_season"][season] = {
            label: _metrics(block["total_points"], block[col])
            for col, label in ARMS}

    # The draft decision itself: rank by predicted opening-window points, take
    # eleven, see what they actually returned.
    for col, label in ARMS:
        got, best = [], []
        for _, block in pl.groupby("season"):
            if len(block) < XI:
                continue
            got.append(block.nlargest(XI, col)["total_points"].sum())
            best.append(block.nlargest(XI, "total_points")["total_points"].sum())
        if got:
            caps = [g / b for g, b in zip(got, best)]
            out["draft"][label] = {
                "xi_points_mean": float(np.mean(got)),
                "ceiling_mean": float(np.mean(best)),
                "capture_mean": float(np.mean(caps)),
                "capture_worst": float(np.min(caps))}
    return out


def report(res: Dict) -> str:
    L: List[str] = []
    L.append("Cold-start fold · no in-season data, scoring GW1-%d"
             % res["through_gw"])
    L.append("%d opening fixtures, %d player-seasons, %d test seasons"
             % (res["fixtures"], res["players"], len(res["per_season"])))
    L.append("")

    def table(title: str, block: Dict):
        L.append(title)
        L.append("  %-34s %8s %8s %8s %9s %7s"
                 % ("", "RMSE", "MAE", "R2", "Spearman", "n"))
        for _, label in ARMS:
            m = block.get(label)
            if not m:
                continue
            L.append("  %-34s %8.3f %8.3f %+8.3f %9.3f %7d"
                     % (label, m["rmse"], m["mae"], m["r2"], m["spearman"], m["n"]))
        L.append("")

    table("GAMEWEEK 1 ONLY, likely starters · the purest cold start",
          res["gw1_only"])
    table("PER FIXTURE across GW1-%d, likely starters" % res["through_gw"],
          res["per_fixture"])
    table("PER PLAYER over the window · the draft question, whole pool",
          res["per_player"])
    table("PER PLAYER over the window · likely starters only",
          res["per_player_starters"])

    L.append("DRAFT DECISION · rank by predicted window points, take eleven")
    L.append("  %-34s %10s %10s %10s %10s"
             % ("", "pts", "ceiling", "capture", "worst szn"))
    for _, label in ARMS:
        d = res["draft"].get(label)
        if not d:
            continue
        L.append("  %-34s %10.1f %10.1f %9.1f%% %9.1f%%"
                 % (label, d["xi_points_mean"], d["ceiling_mean"],
                    100 * d["capture_mean"], 100 * d["capture_worst"]))
    L.append("")

    L.append("PER SEASON · Spearman over the window, likely starters")
    short = {"component model (season features only)": "preseason",
             "component model (frozen at GW1)": "frozen",
             "component model (updating)": "updating",
             "season projector x fixture ease": "proj+fdr",
             "season projector (flat)": "projector",
             "baseline: last season's points": "last szn"}
    header = "  %-10s" % "season"
    for _, lab in ARMS:
        header += " %11s" % short.get(lab, lab[:11])
    L.append(header)
    for season in sorted(res["per_season"]):
        line = "  %-10s" % season
        for _, lab in ARMS:
            m = res["per_season"][season].get(lab)
            line += " %11s" % ("%.3f" % m["spearman"] if m else "-")
        L.append(line)
    L.append("")
    for _, lab in ARMS:
        vals = [res["per_season"][s][lab]["spearman"] for s in res["per_season"]
                if res["per_season"][s].get(lab)]
        if vals:
            L.append("  %-34s mean %.3f   worst %.3f (%s)"
                     % (lab, np.mean(vals), np.min(vals),
                        sorted(res["per_season"])[int(np.argmin(vals))]))
    L.append("")
    L.append("The incumbent points model is absent by construction · its rolling")
    L.append("features need three played gameweeks of the season being predicted.")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", type=int, default=6)
    ap.add_argument("--seasons", nargs="*", default=None)
    args = ap.parse_args()

    res = run(args.through, args.seasons)
    print("\n" + report(res) + "\n")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, default=float)
    print("full results · %s" % OUT_JSON)


if __name__ == "__main__":
    main()
