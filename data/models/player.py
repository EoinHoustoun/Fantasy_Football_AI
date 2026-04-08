"""
Pydantic models for FPL player and fixture data.
These are the typed schemas that travel through the whole app.
"""

from pydantic import BaseModel, Field
from typing import Optional


class Player(BaseModel):
    """Core player record merged from all data sources."""

    # ── Identity ──────────────────────────────────────────────────────────────
    fpl_id: int
    name: str
    team: str
    team_id: int
    position: str           # GKP, DEF, MID, FWD

    # ── Price & Ownership ─────────────────────────────────────────────────────
    price: float            # £m e.g. 8.5
    ownership: float        # % selected by managers
    price_change: float = 0.0  # +/- change this GW

    # ── FPL Points & Form ─────────────────────────────────────────────────────
    total_points: int = 0
    form: float = 0.0       # FPL rolling form score
    points_per_game: float = 0.0
    minutes: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    bonus: int = 0
    ict_index: float = 0.0

    # ── xG Data (Understat) ───────────────────────────────────────────────────
    xg: Optional[float] = None          # Expected goals
    xa: Optional[float] = None          # Expected assists
    xg_per90: Optional[float] = None
    xa_per90: Optional[float] = None
    npxg: Optional[float] = None        # Non-penalty expected goals
    xg_gap: Optional[float] = None      # xG minus actual goals (underperformance)

    # ── Advanced Stats (FBRef) ────────────────────────────────────────────────
    progressive_carries: Optional[float] = None
    progressive_passes: Optional[float] = None
    key_passes: Optional[float] = None
    pressures: Optional[float] = None

    # ── Derived Metrics (calculated by processors) ────────────────────────────
    points_per_million: Optional[float] = None
    next_fixture_fdr: Optional[float] = None    # Average FDR next N GWs
    transfer_score: Optional[float] = None      # Composite buy/sell score
    differential_score: Optional[float] = None  # Ownership-adjusted upside


class Fixture(BaseModel):
    """A single Premier League fixture."""

    fixture_id: int
    gameweek: int
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int
    home_fdr: int           # Fixture difficulty rating (1-5) for home team
    away_fdr: int
    finished: bool = False
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
