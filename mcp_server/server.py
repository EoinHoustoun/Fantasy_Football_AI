"""FPL Analytics MCP server · lets Claude use the app's own engine.

Every tool calls `analytics/service.py`, the same functions the Streamlit pages
call, so Claude and the app cannot disagree about a projection or a plan.

Runs in its own Python 3.11 venv (`.venv-mcp`, the `mcp` SDK needs 3.10+) with
the numerical libraries pinned to the app's versions, so the brain's disk cache
is shared with the app.

Register (once):
    claude mcp add --scope user fpl -- \\
        "<repo>/.venv-mcp/bin/python" "<repo>/mcp_server/server.py"
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # the app's caches and .env are resolved relative to the repo

# MCP speaks JSON-RPC over stdout. Anything else printed there corrupts the
# stream, so every log goes to stderr.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

from mcp.server.fastmcp import FastMCP  # noqa: E402

class _Lazy(object):
    """Import the engine on first use. pandas + xgboost take seconds to import,
    and Claude gives a server 30 s to answer its handshake."""

    def __getattr__(self, name):
        from analytics import service
        return getattr(service, name)


S = _Lazy()

mcp = FastMCP(
    "fpl",
    instructions=(
        "Eoin's Fantasy Premier League analytics engine (the same one his FPL "
        "Analytics app runs). Projections are per player per gameweek expected "
        "points (xP) from a component model (minutes, goals, assists, clean "
        "sheets, bonus, DEFCON) scaled by current injury news. Start with "
        "`status`, then `my_team`. For transfers call `optimise_transfers` and "
        "compare `best` against `hold`: a plan that gains under ~2 pts a move "
        "is noise. Use `player` to explain WHY a number is what it is before "
        "recommending it. `save_plan_to_app` writes drafts into the My Team "
        "planner; the user still presses Save. Never claim a player's minutes "
        "fade without checking his recent minutes in `player`."
    ),
)


@mcp.tool()
def status() -> dict:
    """Season clock: next gameweek, deadline, last finished GW, and whether projections are ready."""
    gwi = S.gameweek_info()
    ready = S.projections(allow_compute=False) is not None
    return {**gwi, "projections_ready": ready, "team_id": S.default_team_id(),
            "app": "http://localhost:8510"}


@mcp.tool()
def my_team(team_id: Optional[int] = None) -> dict:
    """The manager's squad with prices, selling prices, injury news, bank, free
    transfers (replayed from history), chips remaining this half, and GW points."""
    return S.team(team_id)


@mcp.tool()
def projections(position: Optional[str] = None, max_price: Optional[float] = None,
                horizon: int = 6, top_n: int = 20, sort: str = "xp_window") -> dict:
    """Top players by projected points over the next `horizon` gameweeks.

    position: GKP|DEF|MID|FWD. sort: xp_window (total), xp_next (next GW), value (xP per £m).
    Each row has xp_by_gw, fixtures, expected minutes and injury status.
    """
    return S.top_players(position, max_price, horizon, top_n, sort)


@mcp.tool()
def player(names: List[str], horizon: int = 6) -> dict:
    """Detail for one or more players: xP per gameweek, next-GW components
    (p60, expected minutes, goals, assists, clean sheet, DEFCON), fixtures and
    season stats. Disambiguate duplicates as 'Palmer (CHE)'."""
    return S.player_detail(names, horizon)


@mcp.tool()
def captaincy(gw: Optional[int] = None, top_n: int = 5) -> dict:
    """Captain options from the manager's squad for a gameweek, ranked by xP."""
    return S.captaincy(None, gw, top_n)


@mcp.tool()
def optimise_transfers(horizon: int = 6, free_transfers: Optional[int] = None,
                       friction: float = 2.0, decay: float = 0.9, ft_value: float = 1.5,
                       lock: Optional[List[str]] = None, ban: Optional[List[str]] = None,
                       alternatives: int = 2) -> dict:
    """Multi-week transfer plan (MILP): who to sell/buy each week, captain, hits,
    free-transfer banking and budget with real selling prices.

    Returns `best`, the `hold` baseline (no transfers), `gain_vs_hold`, and
    `alternatives` that differ in THIS week's moves. friction = points a move must
    clear to be worth making; decay = weight per week further out; lock/ban take names.
    Takes ~30-60 s.
    """
    r = S.optimise(None, horizon, free_transfers,
                   {"friction": friction, "decay": decay, "ft_value": ft_value},
                   lock, ban, alternatives)
    r.pop("_raw", None)
    return r


@mcp.tool()
def compare_players(names: List[str], horizon: int = 6) -> dict:
    """Side-by-side projections for 2-4 players over the horizon, with the per-GW edge."""
    d = S.player_detail(names, horizon)
    rows = d["players"]
    if len(rows) >= 2:
        a, b = rows[0], rows[1]
        d["edge_first_over_second"] = {
            "window": round(a["xp_window"] - b["xp_window"], 2),
            "by_gw": {g: round(a["xp_by_gw"].get(g, 0) - b["xp_by_gw"].get(g, 0), 2)
                      for g in d["gws"]},
            "price_diff": round(a["price"] - b["price"], 1)}
    return d


@mcp.tool()
def chip_squad(chip: str, gw: Optional[int] = None, weeks: int = 6) -> dict:
    """Best fifteen for a chip, on the engine, within the real selling budget.

    chip: "freehit" (one gameweek, the squad reverts) or "wildcard" (a window of
    `weeks`). Returns the squad, XI, captain, points vs the current team over the
    same weeks (`gain`), and whether the solve is proven optimal.
    """
    return S.chip_squad(chip, gw, weeks)


@mcp.tool()
def check_move(sell: str, buy: str, horizon: int = 8) -> dict:
    """Background check ONE transfer before recommending it.

    Returns a verdict (Make it / Wait until GWk / Marginal / Skip) with the reason,
    the team-level gain over six weeks, the value of making it in each week
    (entry point), gains over 1/3/6/8 weeks (robustness), and flags on both
    players: running hot or cold (luck vs xGI), minutes pattern, penalties,
    DEFCON hit rate, injury news, price pressure, fixtures after the window, and
    who the new player really displaces when the sale is a benchwarmer.
    ALWAYS call this before telling the user to make a transfer.
    """
    codes = S.find_players([sell, buy])
    if len(codes) != 2:
        return {"error": "could not identify both players; use 'Name (CLUB)'"}
    d = S.move_dossier(codes[0], codes[1], None, horizon)
    for k in ("out", "in"):
        d[k].pop("mins_list", None)
    return d


@mcp.tool()
def exit_points(horizon: int = 8) -> dict:
    """For each player in the squad, the weeks an affordable same-position
    replacement outscores him by a point or more (his exit weeks)."""
    return S.squad_exit_map(None, horizon)


@mcp.tool()
def fixtures(horizon: int = 6) -> dict:
    """Engine fixture ticker: every club's expected goals and clean-sheet chance per
    gameweek over the horizon, sorted by attacking total. Use it to pick which
    clubs to invest in and when their run starts or ends."""
    return S.fixture_ticker(horizon)


@mcp.tool()
def rivals(league_id: int, top_n: int = 20, horizon: int = 6) -> dict:
    """A mini-league on the engine: each rival's current squad projected like the
    user's (best XI + captain per week), plus THREATS (players many rivals own and
    the user does not) and SWORDS (the user's players few rivals own). Use it for
    rank-aware transfer and captain advice. League ids come from my_team."""
    return S.league_rivals(league_id, None, top_n, horizon)


@mcp.tool()
def save_plan_to_app(week_moves: List[dict]) -> dict:
    """Write a plan into the My Team planner as drafts (user presses Save in the app).

    week_moves: [{"gw": 6, "out": ["Rogers"], "in": ["Mbeumo"], "captain": "Haaland", "chip": null}]
    """
    return S.save_plan_to_app(week_moves)


def _warm():
    try:
        S.projections(allow_compute=True)
    except Exception:  # noqa: BLE001
        logging.exception("projection warm-up failed")


if __name__ == "__main__":
    # Warm after the handshake has had time to complete.
    _t = threading.Timer(5.0, _warm)
    _t.daemon = True
    _t.start()
    mcp.run()
