"""Price-change radar · who is likely to rise or fall tonight.

FPL moves a player's price when net transfers cross a (secret) threshold that
scales with how many managers own him. We approximate the pressure as

    pressure = net_transfers_this_gw / sqrt(estimated_owner_count)

then rank by |pressure|. This is a heuristic, not the real algorithm · it is
honest about that in the UI, but the ordering (who moves FIRST) is what a
manager actually needs: buy risers before the rise, sell fallers before the
fall banks only half.

Off-season the market sleeps (net transfers ≈ 0) and the radar reports that
rather than inventing noise.

Pure logic · no Streamlit. Python 3.8 typing.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

TOTAL_MANAGERS = 11_000_000       # ~constant in recent seasons
MIN_ABS_BALANCE = 5_000           # below this the market is just noise


def price_watch(players_df: pd.DataFrame, top_n: int = 10
                ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(risers, fallers) · each a df ranked by pressure with a 0-100 score.

    Empty frames when the market is quiet (off-season / early week).
    """
    cols = ["fpl_id", "web_name", "team", "team_short", "position", "price",
            "ownership", "transfer_balance"]
    have = [c for c in cols if c in players_df.columns]
    if "transfer_balance" not in have:
        return pd.DataFrame(), pd.DataFrame()

    df = players_df[have].copy()
    df["transfer_balance"] = pd.to_numeric(df["transfer_balance"],
                                           errors="coerce").fillna(0)
    df = df[df["transfer_balance"].abs() >= MIN_ABS_BALANCE]
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    owners = (pd.to_numeric(df.get("ownership"), errors="coerce").fillna(0.1)
              / 100.0 * TOTAL_MANAGERS).clip(lower=1_000)
    df["pressure_raw"] = df["transfer_balance"] / np.sqrt(owners)
    peak = float(df["pressure_raw"].abs().max()) or 1.0
    df["pressure"] = (df["pressure_raw"].abs() / peak * 100).round(0)

    risers = (df[df["pressure_raw"] > 0]
              .sort_values("pressure_raw", ascending=False).head(top_n))
    fallers = (df[df["pressure_raw"] < 0]
               .sort_values("pressure_raw").head(top_n))
    return risers.reset_index(drop=True), fallers.reset_index(drop=True)


def price_flags(players_df: pd.DataFrame, top_n: int = 25
                ) -> Dict[int, str]:
    """{fpl_id: "rise"|"fall"} for the strongest movers · cheap lookup for
    badges on transfer candidate cards."""
    risers, fallers = price_watch(players_df, top_n=top_n)
    flags: Dict[int, str] = {}
    for _, r in risers.iterrows():
        flags[int(r["fpl_id"])] = "rise"
    for _, r in fallers.iterrows():
        flags[int(r["fpl_id"])] = "fall"
    return flags
