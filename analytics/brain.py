"""The one projection engine · per player, per gameweek, over a planning horizon.

Before this module every page read a different number: Home and My Team showed
FPL's `ep_next` (which is its 30-day form), Captain/Transfers/Buy-Sell ranked on
hand-weighted form + fixture scores, the Draft/Chip pages read a preseason board
frozen five weeks ago, and Predictions trained XGBoost on one gameweek. Three
pages named three different captains.

The brain is the component model (`analytics/component_model.py`: minutes, goals,
assists, clean sheets, bonus, DEFCON, each modelled and added up with the scoring
table) run over the next `HORIZON` gameweeks, trained on every season we hold
plus the live one. Walk-forward results live in
`scripts/benchmark_brain_horizon.py`.

Two things make a multi-week horizon honest:

1. **Features are frozen at the planning point.** `prepare()` builds each row's
   features from the rows before it, so a GW t+2 row would read GW t+1's EMPTY
   outcome as "last match" and see `mins_last = NaN`. Every player-level feature
   on a future row is overwritten with the player's value on his FIRST future
   row. Only the fixture columns (venue, both sides' ratings) vary by week.
2. **Availability is applied at read time, not baked into the cache.** The base
   projection only changes when a gameweek finishes (minutes of compute). FPL's
   `chance_of_playing_next_round` changes hourly, so it is layered on in
   `with_availability()` from the current bootstrap.

No Streamlit imports: pages, the MCP server and scripts all call this.
"""

from __future__ import annotations

import logging
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from analytics import component_model as cm

logger = logging.getLogger(__name__)

HORIZON = 8
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
BRAIN_VERSION = 1

# Columns that describe the FIXTURE, so they legitimately differ week to week.
FIXTURE_COLS = ["was_home_f", "team_att", "team_def", "opp_att", "opp_def",
                "team_matches", "league_gf", "was_home", "opponent_team"]

COMPONENTS = ["xp", "p_play", "p60", "exp_minutes", "e_goals", "e_assists",
              "e_bonus", "e_saves", "p_clean_sheet", "e_conceded", "p_defcon"]


# ── Core · fit once, score every future fixture ───────────────────────────────

def upcoming_long(players_df: pd.DataFrame, fixtures_df: pd.DataFrame,
                  season: str, gws: List[int]) -> pd.DataFrame:
    frames = [cm.upcoming_rows(players_df, fixtures_df, season, g) for g in gws]
    frames = [f for f in frames if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def freeze_future_features(frame: pd.DataFrame, is_future: pd.Series,
                           features: List[str]) -> pd.DataFrame:
    """Overwrite player-level features on future rows with the first future row's.

    See the module docstring, point 1.
    """
    frame = frame.copy()
    fut = frame[is_future].sort_values(["code", "season_ord", "gw", "fixture"])
    player_cols = [c for c in features if c not in FIXTURE_COLS]
    first = fut.groupby("code", sort=False)[player_cols].transform("first")
    frame.loc[first.index, player_cols] = first.values
    return frame


def project(history: pd.DataFrame, upcoming: pd.DataFrame,
            min_career_games: int = 3,
            tree_params: Optional[Dict] = None) -> pd.DataFrame:
    """Fit on every played row, score every upcoming row, sum doubles.

    Returns one row per (code, gw) with the model components and `fixtures`
    (0 rows = blank, 2 = double).
    """
    if upcoming is None or upcoming.empty:
        return pd.DataFrame(columns=["code", "gw"] + COMPONENTS)
    combined = pd.concat([history, upcoming], ignore_index=True, sort=False)
    frame = cm.prepare(combined)
    is_future = frame["minutes"].isna() & frame["total_points"].isna()
    model = cm.ComponentPointsModel(tree_params)
    frame = freeze_future_features(frame, is_future, model.features)

    train = frame[~is_future]
    train = train[train["career_games"] >= min_career_games]
    test = frame[is_future].copy()
    model.fit(train)
    comps = model.predict(test)
    per_fx = pd.concat([test[["code", "gw", "career_games"]].reset_index(drop=True),
                        comps.reset_index(drop=True)], axis=1)
    per_fx["thin_history"] = per_fx["career_games"] < min_career_games

    agg = {c: "sum" for c in ("xp", "exp_minutes", "e_goals", "e_assists",
                              "e_bonus", "e_saves", "e_conceded")}
    agg.update({c: "max" for c in ("p_play", "p60", "p_clean_sheet", "p_defcon",
                                   "thin_history")})
    out = per_fx.groupby(["code", "gw"], as_index=False).agg(agg)
    out["fixtures"] = per_fx.groupby(["code", "gw"]).size().values
    return out


# ── Live build + disk cache ───────────────────────────────────────────────────

def _cache_path(season: str, first_gw: int, last_finished: int) -> Path:
    return CACHE_DIR / ("brain_v%d_%s_gw%d_fin%d.pkl"
                        % (BRAIN_VERSION, season, first_gw, last_finished))


def _last_finished(bootstrap: dict) -> int:
    done = [int(e["id"]) for e in bootstrap.get("events", [])
            if e.get("finished") and e.get("data_checked", True)]
    return max(done) if done else 0


def _next_gw(bootstrap: dict) -> int:
    nxt = [int(e["id"]) for e in bootstrap.get("events", []) if e.get("is_next")]
    return nxt[0] if nxt else _last_finished(bootstrap) + 1


def build(players_df: pd.DataFrame, fixtures_df: pd.DataFrame,
          first_gw: int, horizon: int = HORIZON,
          season: Optional[str] = None) -> pd.DataFrame:
    """Uncached live projection for first_gw .. first_gw+horizon-1."""
    season = season or cm.active_season()
    history = cm.build_history(season)
    if history is None or history.empty:
        raise RuntimeError("brain: no history (build the archive first)")
    last = int(pd.to_numeric(history.loc[history["season"] == season, "gw"],
                             errors="coerce").max() or 0)
    if last and last >= first_gw:
        # Never train on the rows we are about to predict.
        history = history[~((history["season"] == season) & (history["gw"] >= first_gw))]
    gws = [g for g in range(int(first_gw), int(first_gw) + int(horizon)) if g <= 38]
    up = upcoming_long(players_df, fixtures_df, season, gws)
    long = project(history, up)
    long["season"] = season
    return long


_LOCK = threading.Lock()


def load(bootstrap: dict, players_df: pd.DataFrame, fixtures_df: pd.DataFrame,
         horizon: int = HORIZON, allow_compute: bool = True) -> Optional[pd.DataFrame]:
    """The cached base projection for the next `horizon` gameweeks.

    Keyed by (season, next gameweek, last finished gameweek), so it rebuilds
    exactly when a gameweek finishes. Returns None if nothing is cached and
    `allow_compute` is False (the page shows a loader and the warm thread fills it).
    """
    season = cm.active_season()
    first, fin = _next_gw(bootstrap), _last_finished(bootstrap)
    path = _cache_path(season, first, fin)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)["long"]
        except Exception:  # noqa: BLE001 · a torn file is rebuilt below
            logger.warning("brain cache unreadable, rebuilding: %s", path)
    if not allow_compute:
        return None
    with _LOCK:
        if path.exists():
            with open(path, "rb") as f:
                return pickle.load(f)["long"]
        t0 = time.time()
        long = build(players_df, fixtures_df, first, horizon, season)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump({"long": long, "built_at": time.time(),
                         "first_gw": first, "last_finished": fin,
                         "horizon": horizon}, f)
        os.replace(tmp, path)
        logger.info("brain built GW%d+%d in %.0fs", first, horizon, time.time() - t0)
        return long


def warm_async(bootstrap: dict, players_df: pd.DataFrame,
               fixtures_df: pd.DataFrame) -> None:
    """Build the cache in a daemon thread if it is missing. Never raises."""
    season = cm.active_season()
    path = _cache_path(season, _next_gw(bootstrap), _last_finished(bootstrap))
    if path.exists() or _LOCK.locked():
        return

    def _run():
        try:
            load(bootstrap, players_df, fixtures_df)
        except Exception:  # noqa: BLE001
            logger.exception("brain warm failed")

    threading.Thread(target=_run, daemon=True, name="brain-warm").start()


# ── Availability ──────────────────────────────────────────────────────────────

def availability_factor(status: str, chance: Optional[float], weeks_ahead: int) -> float:
    """Multiplier on a player's projection `weeks_ahead` gameweeks after the next.

    FPL's `chance_of_playing_next_round` speaks only to the next gameweek. Beyond
    it the doubt fades: half-way back a week later, mostly back after two. A
    player who has left the league ('u') is zero for good; a suspension ('s')
    costs the next gameweek only.
    """
    status = (status or "a").lower()
    if status == "u":
        return 0.0
    if chance is None or (isinstance(chance, float) and np.isnan(chance)):
        chance = 100.0 if status == "a" else (0.0 if status in ("i", "s", "n") else 50.0)
    c = max(0.0, min(1.0, float(chance) / 100.0))
    if status == "s":
        return c if weeks_ahead == 0 else 1.0
    if weeks_ahead == 0:
        return c
    if weeks_ahead == 1:
        return c + (1.0 - c) * 0.5
    return c + (1.0 - c) * 0.85


def with_availability(long: pd.DataFrame, players_df: pd.DataFrame) -> pd.DataFrame:
    """Scale xp and minutes by current injury/suspension news, and join identity."""
    if long is None or long.empty:
        return long
    cols = [c for c in ("code", "fpl_id", "web_name", "team", "team_short",
                        "team_code", "team_id", "position", "price", "ownership",
                        "status", "news", "chance_of_playing_next_round",
                        "form", "total_points", "ep_next")
            if c in players_df.columns]
    ids = players_df[cols].drop_duplicates("code")
    out = long.merge(ids, on="code", how="inner")
    first = int(out["gw"].min())
    f = [availability_factor(s, c, int(g) - first) for s, c, g in
         zip(out.get("status", "a"), out.get("chance_of_playing_next_round"), out["gw"])]
    out["avail"] = np.round(f, 3)
    out["xp_raw"] = out["xp"]
    for c in ("xp", "exp_minutes", "e_goals", "e_assists", "e_bonus", "e_saves"):
        if c in out.columns:
            out[c] = out[c] * out["avail"]
    out["xp"] = out["xp"].round(2)
    return out


# ── Convenient views the pages and the MCP server share ──────────────────────

def wide(long: pd.DataFrame, value: str = "xp") -> pd.DataFrame:
    """code x gw table of one component, blanks as 0."""
    return (long.pivot_table(index="code", columns="gw", values=value,
                             aggfunc="sum").fillna(0.0))


def summary(long: pd.DataFrame, gws: Optional[List[int]] = None) -> pd.DataFrame:
    """One row per player: next-GW xp, horizon total, mean minutes, per-GW list."""
    if long is None or long.empty:
        return pd.DataFrame()
    sel = long if gws is None else long[long["gw"].isin(gws)]
    first = int(sel["gw"].min())
    nxt = sel[sel["gw"] == first].set_index("code")["xp"]
    ident = [c for c in ("web_name", "team_short", "team_code", "team_id", "position",
                         "price", "ownership", "status", "news", "fpl_id",
                         "chance_of_playing_next_round", "form", "ep_next")
             if c in sel.columns]
    g = sel.groupby("code")
    out = g[ident].first()
    out["xp_next"] = nxt.reindex(out.index).fillna(0.0)
    out["xp_total"] = g["xp"].sum()
    out["xmins"] = g["exp_minutes"].mean()
    out["p60"] = g["p60"].mean()
    out["n_gws"] = g["gw"].nunique()
    out["xp_per_m"] = out["xp_total"] / out["price"].replace(0, np.nan)
    return out.reset_index().sort_values("xp_total", ascending=False)


POINT_PARTS = [("pts_appear", "Appearance"), ("pts_goals", "Goals"),
               ("pts_assists", "Assists"), ("pts_cs", "Clean sheet"),
               ("pts_bonus", "Bonus"), ("pts_dc", "DEFCON")]


def point_parts(rows: pd.DataFrame) -> pd.DataFrame:
    """Split each row's xp into where it comes from, for charts and explanations.

    Approximate for doubles (probabilities are the per-fixture max) and it leaves
    out the small negatives (cards, goals conceded), so the parts are rescaled to
    sum to the row's xp. The SHAPE is the point: a Haaland is goals, a Gabriel is
    clean sheet plus DEFCON.
    """
    from config import FPL_ASSIST_PTS, FPL_CS_PTS, FPL_GOAL_PTS
    out = rows.copy()
    pos = out["position"].astype(str).str.upper()
    nfx = out.get("fixtures", pd.Series(1, index=out.index)).clip(lower=1)
    out["pts_appear"] = (out["p_play"] + out["p60"]) * nfx
    out["pts_goals"] = out["e_goals"] * pos.map(FPL_GOAL_PTS).fillna(4)
    out["pts_assists"] = out["e_assists"] * FPL_ASSIST_PTS
    out["pts_cs"] = out["p_clean_sheet"] * out["p60"] * pos.map(FPL_CS_PTS).fillna(0) * nfx
    out["pts_bonus"] = out["e_bonus"]
    out["pts_dc"] = 2.0 * out["p_defcon"] * out["p60"] * nfx
    cols = [c for c, _ in POINT_PARTS]
    tot = out[cols].sum(axis=1).replace(0, np.nan)
    scale = (out["xp"] / tot).fillna(0.0)
    for c in cols:
        out[c] = (out[c] * scale).round(3)
    return out


# ── Why there is no blend with FPL's own xP ───────────────────────────────────
# Tried and rejected 2026-09-27. The archive's FPL `xp` column (vaastav) looked
# like the best next-week predictor in the walk-forward (Spearman 0.62 vs the
# brain's 0.44), and a 30/50 blend scored best over 3 and 6 weeks. It is LEAKED:
# among regulars it correlates 0.61 with the SAME gameweek's points but only
# 0.30 with the next one's, and 62% of its zeros are players who then played 0
# minutes. It was captured after team news / kickoff. The live `ep_next` a
# manager sees before the deadline is FPL's 30-day form (Groß 11.2 = form 11.2),
# and a 4-gameweek form mean ranks the next 3 weeks at 0.27 against the brain's
# 0.48. Do not reintroduce a blend on the archived column.
