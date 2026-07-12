"""
Unified player stats processor.

This is the central analytical artefact of the whole app.
It merges data from all available sources into one clean DataFrame
that every page in the UI renders from.

Sources merged here:
  1. FPL API          · always available
  2. Understat        · merged when available (xG, xA)
  3. FBRef            · merged when available (advanced stats)
  4. Fantasy Football Hub · merged when available (premium)
"""

import logging
from typing import Optional

import pandas as pd

from data.fetchers.fpl_api import (
    fetch_bootstrap,
    fetch_fixtures,
    get_players_df,
    get_fixtures_df,
    get_current_gameweek,
)
from data.processors.fixture_difficulty import (
    attach_fixture_difficulty,
    attach_season_difficulty,
    attach_composite_fixture_difficulty,
    attach_dgw_bgw,
)
from config import FIXTURE_LOOKAHEAD

logger = logging.getLogger(__name__)


def _append_simulated_gw(fixtures_df: pd.DataFrame, source_gw: int, new_gw: int) -> pd.DataFrame:
    """Clone one gameweek's fixtures under a new gameweek number, marked as
    not-yet-played. Used for the off-season sandbox: replays GW1's fixtures as a
    synthetic 'next gameweek' so fixture/FDR-based planning tools work again."""
    if fixtures_df is None or "gameweek" not in fixtures_df.columns:
        return fixtures_df
    clone = fixtures_df[fixtures_df["gameweek"] == source_gw].copy()
    if clone.empty:
        return fixtures_df
    clone["gameweek"] = new_gw
    for col, val in (("finished", False), ("home_goals", None), ("away_goals", None)):
        if col in clone.columns:
            clone[col] = val
    return pd.concat([fixtures_df, clone], ignore_index=True)


def build_player_universe(
    bootstrap: Optional[dict] = None,
    understat_df: Optional[pd.DataFrame] = None,
    fbref_df: Optional[pd.DataFrame] = None,
    ffhub_df: Optional[pd.DataFrame] = None,
    simulate_gw: Optional[int] = None,
) -> pd.DataFrame:
    """
    Build the full player universe DataFrame used across all app pages.

    Merges FPL base data with optional enrichment sources.
    If an enrichment source is None, those columns will be absent or NaN -
    the app degrades gracefully rather than crashing.

    `simulate_gw` (off-season sandbox): when set, GW1's fixtures are cloned as
    that gameweek and used as the planning target, so upcoming-fixtures / FDR /
    DGW tools have a "next gameweek" to work against even after the season ends.

    Returns a DataFrame with one row per player.
    """
    # ── 1. FPL base data ──────────────────────────────────────────────────────
    if bootstrap is None:
        bootstrap = fetch_bootstrap()

    players_df = get_players_df(bootstrap)
    fixtures_df = get_fixtures_df(bootstrap=bootstrap)
    current_gw = get_current_gameweek(bootstrap)

    # Off-season form fallback. FPL 'form' = avg points over the last 30 days, so
    # in the summer (no recent matches) it is 0.0 for every player and all
    # form-based ranking goes flat. When form carries no signal, fall back to
    # season-long points_per_game so transfers/captain/pick-team stay meaningful.
    # Self-heals: once the new season plays a few GWs, real form returns and this
    # no longer triggers. `form_is_fallback` flags when the substitution happened.
    _form_num = pd.to_numeric(players_df.get("form"), errors="coerce").fillna(0.0)
    if float(_form_num.max() or 0.0) == 0.0 and "points_per_game" in players_df.columns:
        players_df["form"] = pd.to_numeric(players_df["points_per_game"], errors="coerce").fillna(0.0)
        players_df["form_is_fallback"] = True
        logger.info("Off-season: 'form' is all-zero → using points_per_game as the form signal")
    else:
        players_df["form_is_fallback"] = False

    if simulate_gw is not None:
        fixtures_df = _append_simulated_gw(fixtures_df, source_gw=1, new_gw=simulate_gw)
        current_gw = simulate_gw

    logger.info(f"Loaded {len(players_df)} players, GW{current_gw}"
                f"{' (simulated)' if simulate_gw is not None else ''}")

    # ── 2. Fixture difficulty ──────────────────────────────────────────────────
    players_df = attach_fixture_difficulty(players_df, fixtures_df, current_gw, FIXTURE_LOOKAHEAD)
    players_df = attach_season_difficulty(players_df, fixtures_df, current_gw)

    # ── 2b. Composite fixture difficulty (DC + xGC/xGA) ───────────────────────
    try:
        from data.fetchers.understat import fetch_understat_team_stats
        from data.fetchers.dixon_coles import fetch_dixon_coles_ratings
        _team_stats = fetch_understat_team_stats()
        if _team_stats is not None and not _team_stats.empty:
            _dc = None
            try:
                _dc = fetch_dixon_coles_ratings()
                if _dc:
                    logger.info(
                        f"DC ratings loaded ({_dc['n_matches']} matches, "
                        f"converged={_dc['converged']})"
                    )
            except Exception as _dc_err:
                logger.warning(f"DC ratings unavailable ({_dc_err}) · using Understat only")
            players_df = attach_composite_fixture_difficulty(
                players_df, fixtures_df, current_gw, _team_stats, FIXTURE_LOOKAHEAD,
                dc_ratings=_dc,
            )
            logger.info("Composite fixture difficulty attached")
        else:
            raise ValueError("empty team stats")
    except Exception as _e:
        logger.warning(f"Composite FDR unavailable ({_e}) · falling back to raw FDR")
        _fdr_col = f"avg_fdr_next_{FIXTURE_LOOKAHEAD}"
        players_df[f"composite_att_fdr_next_{FIXTURE_LOOKAHEAD}"] = players_df.get(_fdr_col, pd.Series(3.0, index=players_df.index))
        players_df[f"composite_def_fdr_next_{FIXTURE_LOOKAHEAD}"] = players_df.get(_fdr_col, pd.Series(3.0, index=players_df.index))

    # ── 2c. Double / Blank Gameweek detection ─────────────────────────────────
    players_df = attach_dgw_bgw(players_df, fixtures_df, current_gw, FIXTURE_LOOKAHEAD)
    logger.info("DGW/BGW flags attached")

    # ── 3. Understat xG data ───────────────────────────────────────────────────
    if understat_df is not None:
        players_df = _merge_understat(players_df, understat_df)
        logger.info("Understat xG data merged")
    else:
        logger.info("Understat data not available · xG columns will be empty")
        for col in ["xg", "xa", "xg_per90", "xa_per90", "npxg", "xg_gap"]:
            players_df[col] = None

    # ── 3a. FPL Opta xG backfill ───────────────────────────────────────────────
    # Understat matches by name and misses most players; FPL's own season
    # totals (expected_goals/expected_assists) cover the ENTIRE league.
    # Understat values win where present, Opta fills every gap.
    if "fpl_xg" in players_df.columns:
        for us_col, fpl_col in (("xg", "fpl_xg"), ("xa", "fpl_xa")):
            if us_col not in players_df.columns:
                players_df[us_col] = None
            players_df[us_col] = pd.to_numeric(
                players_df[us_col], errors="coerce").fillna(players_df[fpl_col])
        players_df["xg_gap"] = players_df["xg"] - players_df["goals_scored"]
        n_xg = int((pd.to_numeric(players_df["xg"], errors="coerce") > 0).sum())
        logger.info(f"xG coverage after Opta backfill: {n_xg} players")

    # ── 3b. Vaastav rolling xGI (last 4 GWs) ──────────────────────────────────
    try:
        from data.fetchers.vaastav import fetch_rolling_xgi, _norm_name
        _rolling = fetch_rolling_xgi()
        if _rolling is not None and not _rolling.empty:
            players_df = _merge_rolling_xgi(players_df, _rolling)
            logger.info("Vaastav rolling xGI merged")
        else:
            raise ValueError("empty rolling xGI data")
    except Exception as _e:
        logger.warning(f"Rolling xGI unavailable ({_e})")
        for col in ["rolling_xg", "rolling_xa", "rolling_xgi"]:
            players_df[col] = None

    # ── 3c. DEFCON stats (defensive contribution reliability) ──────────────────
    try:
        from data.fetchers.vaastav import fetch_defcon_stats
        _defcon = fetch_defcon_stats(current_gw=current_gw)
        if _defcon is not None and not _defcon.empty:
            players_df = _merge_defcon(players_df, _defcon)
            logger.info("DEFCON stats merged")
        else:
            raise ValueError("empty DEFCON data")
    except Exception as _e:
        logger.warning(f"DEFCON stats unavailable ({_e})")
        for col in ["defcon_cbit_per_game", "defcon_pct", "defcon_consistency",
                    "defcon_minutes_factor", "defcon_monster_score",
                    "defcon_threshold", "avg_minutes"]:
            players_df[col] = None

    # ── 4. FBRef advanced stats ────────────────────────────────────────────────
    if fbref_df is not None:
        players_df = _merge_fbref(players_df, fbref_df)
        logger.info("FBRef data merged")
    else:
        for col in ["progressive_carries", "progressive_passes", "key_passes", "pressures"]:
            players_df[col] = None

    # ── 5. Fantasy Football Hub ────────────────────────────────────────────────
    if ffhub_df is not None:
        players_df = _merge_ffhub(players_df, ffhub_df)
        logger.info("Fantasy Football Hub data merged")

    # ── 6. Derived metrics ─────────────────────────────────────────────────────
    players_df = _compute_derived_metrics(players_df)

    return players_df


def _merge_understat(players_df: pd.DataFrame, understat_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge Understat xG data onto players_df.

    Understat identifies players by name + team. We fuzzy-match on web_name
    to handle abbreviations. The merge adds xg, xa, npxg columns.
    """
    xg_cols = ["xg", "xa", "npxg", "xg_per90", "xa_per90"]
    available_cols = [c for c in xg_cols if c in understat_df.columns]

    if "name_key" not in understat_df.columns:
        understat_df = understat_df.copy()
        understat_df["name_key"] = understat_df["player_name"].str.lower().str.strip()

    players_df = players_df.copy()
    players_df["name_key"] = players_df["web_name"].str.lower().str.strip()

    merge_cols = ["name_key"] + available_cols
    merged = players_df.merge(
        understat_df[merge_cols].drop_duplicates("name_key"),
        on="name_key",
        how="left",
    )
    merged.drop(columns=["name_key"], inplace=True)

    # xG gap: positive means player has scored LESS than expected (underperforming)
    if "xg" in merged.columns and "goals_scored" in merged.columns:
        merged["xg_gap"] = (merged["xg"] - merged["goals_scored"]).round(2)

    return merged


def _merge_fbref(players_df: pd.DataFrame, fbref_df: pd.DataFrame) -> pd.DataFrame:
    """Merge FBRef advanced stats onto players_df."""
    fbref_cols = [c for c in ["progressive_carries", "progressive_passes", "key_passes", "pressures"]
                  if c in fbref_df.columns]
    if not fbref_cols:
        return players_df

    if "name_key" not in fbref_df.columns:
        fbref_df = fbref_df.copy()
        fbref_df["name_key"] = fbref_df["player_name"].str.lower().str.strip()

    players_df = players_df.copy()
    players_df["name_key"] = players_df["web_name"].str.lower().str.strip()

    merged = players_df.merge(
        fbref_df[["name_key"] + fbref_cols].drop_duplicates("name_key"),
        on="name_key",
        how="left",
    )
    merged.drop(columns=["name_key"], inplace=True)
    return merged


def _merge_ffhub(players_df: pd.DataFrame, ffhub_df: pd.DataFrame) -> pd.DataFrame:
    """Merge Fantasy Football Hub premium stats onto players_df."""
    # FFHub columns TBD once we see their data structure
    return players_df


def _merge_defcon(players_df: pd.DataFrame, defcon: pd.DataFrame) -> pd.DataFrame:
    """
    Merge DEFCON reliability stats into player universe using 2-pass name matching.
    """
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFD", str(s))
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.lower().strip()

    defcon_cols = ["defcon_cbit_per_game", "defcon_pct", "defcon_consistency",
                   "defcon_minutes_factor", "defcon_monster_score",
                   "defcon_threshold", "defcon_games", "avg_minutes"]
    available = [c for c in defcon_cols if c in defcon.columns]

    df = players_df.copy()
    df["_name_norm"] = df["web_name"].apply(_norm)

    # Pass 1: web_name match
    r1 = df.merge(
        defcon[["name_norm"] + available],
        left_on="_name_norm", right_on="name_norm", how="inner",
    )
    matched_ids = set(r1["fpl_id"].tolist())

    # Pass 2: last-name fallback
    unmatched = df[~df["fpl_id"].isin(matched_ids)].copy()
    unmatched["_last"] = unmatched["_name_norm"].apply(lambda x: x.split()[-1])
    last_available = [c for c in ["last_norm"] + available if c in defcon.columns]
    r2_all = unmatched.merge(defcon[last_available], left_on="_last", right_on="last_norm", how="inner")
    r2 = r2_all.sort_values("defcon_monster_score", ascending=False).drop_duplicates("fpl_id")

    merge_cols = ["fpl_id"] + available
    all_defcon = pd.concat([
        r1[[c for c in merge_cols if c in r1.columns]],
        r2[[c for c in merge_cols if c in r2.columns]],
    ]).drop_duplicates("fpl_id")

    result = df.merge(all_defcon[[c for c in merge_cols if c in all_defcon.columns]],
                      on="fpl_id", how="left")
    result.drop(columns=["_name_norm"], inplace=True, errors="ignore")
    return result


def _merge_rolling_xgi(players_df: pd.DataFrame, rolling: pd.DataFrame) -> pd.DataFrame:
    """
    Merge vaastav rolling xGI onto players using 2-pass name matching.

    Pass 1: normalised full name (web_name)
    Pass 2: last name only with deduplication by highest xGI
    """
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFD", str(s))
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.lower().strip()

    xgi_cols = ["name_norm", "rolling_xg", "rolling_xa", "rolling_xgi"]
    available = [c for c in xgi_cols if c in rolling.columns]

    df = players_df.copy()
    df["_name_norm"] = df["web_name"].apply(_norm)

    # Pass 1: web_name match
    r1 = df.merge(
        rolling[available],
        left_on="_name_norm", right_on="name_norm", how="inner",
    )
    matched_ids = set(r1["fpl_id"].tolist())

    # Pass 2: last-name fallback for unmatched players
    unmatched = df[~df["fpl_id"].isin(matched_ids)].copy()
    unmatched["_last"] = unmatched["_name_norm"].apply(lambda x: x.split()[-1])

    last_cols = ["last_norm", "rolling_xg", "rolling_xa", "rolling_xgi"]
    last_available = [c for c in last_cols if c in rolling.columns]

    r2_all = unmatched.merge(
        rolling[last_available],
        left_on="_last", right_on="last_norm", how="inner",
    )
    r2 = (
        r2_all.sort_values("rolling_xgi", ascending=False)
              .drop_duplicates("fpl_id")
    )

    merge_cols = ["fpl_id", "rolling_xg", "rolling_xa", "rolling_xgi"]
    merge_available = [c for c in merge_cols if c in r1.columns]

    all_xgi = pd.concat([
        r1[merge_available],
        r2[[c for c in merge_available if c in r2.columns]],
    ]).drop_duplicates("fpl_id")

    result = df.merge(
        all_xgi[merge_available],
        on="fpl_id", how="left",
    )
    result.drop(columns=["_name_norm"], inplace=True, errors="ignore")
    return result


def _compute_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute derived columns that depend on the merged data being complete."""
    df = df.copy()

    # Points per million (recalculate after merge in case price changed)
    df["points_per_million"] = (df["total_points"] / df["price"]).round(2)

    # Transfer balance (net transfers this GW · positive = being bought)
    df["transfer_balance"] = df["transfers_in_event"] - df["transfers_out_event"]

    return df
