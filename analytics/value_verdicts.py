"""Value-verdict engine for the 2026-27 season.

The 26/27 Draft used to run on *predicted* launch prices. Now FPL has published
the *actual* prices, so we can answer the real planning questions:

  - who came in UNDER price (a bargain the model rates higher than FPL priced)
  - who is a NECESSITY (elite projected points and nailed minutes, must-have)
  - who is OVERPRICED (pedigree and a big price tag, but the value is not there)

Each player's projected points (fitted on the 2025/26 archive by
`season_projection`) is joined to their live price by the stable player `code`,
then bucketed. The headline signal is `pricing_surprise = predicted - actual`:
positive means FPL priced them below the model (bargain), negative a tax.

Players with no 2025/26 FPL history (promoted clubs, overseas signings) cannot
be projected · they are returned separately as a Scout frame, flagged, with no
invented numbers.
"""
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import VALUE_VERDICTS

_POS_BY_TYPE = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


class VERDICTS:
    """Verdict labels · stable strings the UI groups and colours on."""
    NECESSITY = "Necessity"
    VALUE = "Value"
    OVERPRICED = "Overpriced"
    FAIR = "Fair"
    SCOUT = "Scout"


def _live_price_frame(bootstrap: dict) -> pd.DataFrame:
    """code -> actual price, ownership, live position, status, from the live
    bootstrap. Price is `now_cost` in tenths of a million."""
    rows: List[Dict] = []
    for e in bootstrap.get("elements", []):
        rows.append({
            "code": int(e["code"]),
            "actual_price": round(e.get("now_cost", 0) / 10.0, 1),
            "ownership": float(e.get("selected_by_percent", 0) or 0),
            "live_position": _POS_BY_TYPE.get(e.get("element_type"), "?"),
            "status": e.get("status", "a"),
            "live_web_name": e.get("web_name", ""),
            "live_team_id": int(e.get("team", 0) or 0),
        })
    return pd.DataFrame(rows)


def _pctile(series: pd.Series, q: float) -> float:
    s = series.dropna()
    if s.empty:
        return 0.0
    return float(s.quantile(q))


def _assign_verdicts(df: pd.DataFrame, cfg: Dict) -> pd.DataFrame:
    """Bucket every projected+priced player, per-position. Adds `verdict` and a
    short human `verdict_reason`."""
    df = df.copy()
    df["verdict"] = VERDICTS.FAIR
    df["verdict_reason"] = ""

    for pos, grp in df.groupby("position"):
        pts_hi = _pctile(grp["projected_points"], cfg["necessity_pts_pctile"])
        pts_floor = _pctile(grp["projected_points"], cfg["value_pts_floor_pctile"])
        val_hi = _pctile(grp["value_score"], cfg["value_score_pctile"])
        val_med = _pctile(grp["value_score"], cfg["premium_value_pctile"])
        ped_pts = _pctile(grp["last_season_points"], cfg["pedigree_pts_pctile"])

        for idx in grp.index:
            r = df.loc[idx]
            pts = float(r["projected_points"])
            vscore = float(r["value_score"])
            surprise = float(r["pricing_surprise"])
            own = float(r.get("ownership") or 0)
            starts = float(r.get("starts_ratio") or 0)
            last_pts = float(r.get("last_season_points") or 0)
            price = float(r["actual_price"])

            # 1. Necessity · top-tier projected points AND a template must-have
            #    (widely owned, or nailed by last season's starts).
            nailed = own >= cfg["necessity_ownership"] or starts >= cfg["necessity_starts_ratio"]
            if pts >= pts_hi and nailed:
                df.at[idx, "verdict"] = VERDICTS.NECESSITY
                tag = (f"{own:.0f}% owned" if own >= cfg["necessity_ownership"]
                       else f"started {starts*100:.0f}% last year")
                df.at[idx, "verdict_reason"] = (
                    f"Top-tier {pos} projection ({pts:.0f} pts), {tag}. Template must-have.")
                continue

            # 2. Overpriced · a premium tag the value does not back up, or last
            #    season's pedigree carried into a price the projection can't earn.
            premium_weak = price >= cfg["premium_price"] and vscore <= val_med
            pedigree_tax = (last_pts >= ped_pts and price >= cfg["pedigree_min_price"]
                            and vscore <= val_med)
            if premium_weak or pedigree_tax:
                df.at[idx, "verdict"] = VERDICTS.OVERPRICED
                if premium_weak:
                    df.at[idx, "verdict_reason"] = (
                        f"£{price:.1f}m premium but only {vscore:.1f} pts/£m projected "
                        f"({pts:.0f} pts). Priced above its value.")
                else:
                    df.at[idx, "verdict_reason"] = (
                        f"{last_pts:.0f} pts in 25/26 kept the £{price:.1f}m tag, but "
                        f"the projection ({pts:.0f}) doesn't earn it. Pedigree tax.")
                continue

            # 3. Value · FPL priced below the model, or strong value at the
            #    position, provided the projection clears a floor.
            underpriced = surprise >= cfg["value_surprise_m"]
            strong_value = vscore >= val_hi
            if (underpriced or strong_value) and pts >= pts_floor:
                df.at[idx, "verdict"] = VERDICTS.VALUE
                if underpriced:
                    df.at[idx, "verdict_reason"] = (
                        f"Came in £{surprise:.1f}m under the model at £{price:.1f}m "
                        f"for {pts:.0f} projected pts. Bargain.")
                else:
                    df.at[idx, "verdict_reason"] = (
                        f"Strong value: {vscore:.1f} pts/£m at £{price:.1f}m.")
                continue

            # 4. Fair.
            df.at[idx, "verdict_reason"] = (
                f"Priced about right · {vscore:.1f} pts/£m, {pts:.0f} projected pts.")

    return df


def build_value_verdicts(
    projection_uni: pd.DataFrame,
    bootstrap: dict,
    cfg: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Annotate the archive-projected universe with ACTUAL 2026/27 prices and a
    value verdict per player.

    Returns (verdicts_df, scout_df):
      - verdicts_df: every player with both a projection and a live price, plus
        `actual_price`, `ownership`, `value_score`, `pricing_surprise`,
        `verdict`, `verdict_reason`. Sorted by projected points.
      - scout_df: live players with no 2025/26 history (promoted / new signings),
        flagged `verdict == VERDICTS.SCOUT`, with price/ownership but no
        projection. Sorted by price.
    """
    cfg = cfg or VALUE_VERDICTS
    live = _live_price_frame(bootstrap)
    team_short = {int(t["id"]): t.get("short_name") for t in bootstrap.get("teams", [])}

    proj_codes = set(projection_uni["code"].astype(int))

    # Players with both a projection and a live price.
    df = projection_uni.merge(live, on="code", how="inner").copy()
    df["value_score"] = (df["projected_points"] / df["actual_price"]).round(2)
    df["pricing_surprise"] = (df["predicted_start_price"] - df["actual_price"]).round(1)
    df = _assign_verdicts(df, cfg)
    df = df.sort_values("projected_points", ascending=False).reset_index(drop=True)

    # Live players with no history · Scout frame.
    scout = live[~live["code"].isin(proj_codes)].copy()
    scout["position"] = scout["live_position"]
    scout["web_name"] = scout["live_web_name"]
    scout["team_short"] = scout["live_team_id"].map(team_short)
    scout["verdict"] = VERDICTS.SCOUT
    scout["verdict_reason"] = "No 2025/26 FPL history · scout the depth chart before committing."
    scout = scout.sort_values("actual_price", ascending=False).reset_index(drop=True)

    return df, scout
