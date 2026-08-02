"""Per-gameweek expected points · one implementation, used everywhere.

The draft page used to spread a season projection over 38 gameweeks and scale it
by fixture difficulty. That is a fixture SHAPE, not a match forecast. It cannot
tell you that a player is on 15 minutes because he came back late from a
tournament, it cannot see a rotation risk, and its average is wrong for anyone
whose scoring is lumpy (which is every premium).

Where Fantasy Football Hub's snapshot covers a gameweek, this module uses its
match-level number directly. Beyond the snapshot's window it falls back to the
old fixture-shape model, rescaled so the two never sit side by side in different
units. Every cell knows which source produced it, so the UI can be honest about
which half of the run is a forecast and which half is a shape.

Blanks score nothing. Doubles stack both fixtures. Both are handled in the
fallback; the snapshot handles them itself.
"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CHIP_TIMING

logger = logging.getLogger(__name__)

SEASON_GWS = 38

# Where a cell's number came from · surfaced so the UI can label the run.
SRC_MATCH = "match"     # Fantasy Football Hub, fixture by fixture
SRC_SHAPE = "shape"     # our season projection, spread and fixture-scaled
SRC_MANUAL = "manual"   # a hand-entered "not playing this week"


def fixture_factor(fdr: float) -> float:
    """Fixture-ease multiplier for one fixture. Shared with the Chip Planner's
    constants so the two surfaces cannot drift apart."""
    return max(CHIP_TIMING["factor_floor"],
               1.0 + (3.0 - float(fdr)) * CHIP_TIMING["fdr_slope"])


class GwProjection(object):
    """Per-(code, gameweek) expected points, with the source of each number.

    `fixtures_by_gw` is the {(team_id, gw): [(opp_short, is_home, fdr), ...]}
    map the draft page already builds.
    """

    def __init__(self, board: pd.DataFrame, fixtures_by_gw: Dict,
                 ffh_long: Optional[pd.DataFrame] = None,
                 season_col: str = "consensus_points",
                 miss_gws: Optional[Dict[int, List[int]]] = None,
                 gw_points: Optional[Dict[int, Dict[int, float]]] = None):
        self._fix = fixtures_by_gw or {}
        col = season_col if season_col in board.columns else "projected_points"
        scale = 1.0
        if "points_scale_to_match" in board.columns:
            try:
                scale = float(pd.to_numeric(
                    board["points_scale_to_match"], errors="coerce").dropna().iloc[0])
            except (IndexError, ValueError):
                scale = 1.0
        self._scale = scale if np.isfinite(scale) and scale > 0 else 1.0

        season = pd.to_numeric(board[col], errors="coerce").fillna(0.0)
        self._season = dict(zip(board["code"].astype(int), season))
        self._team = dict(zip(board["code"].astype(int),
                              pd.to_numeric(board.get("team_id"), errors="coerce")
                              .fillna(0).astype(int)))

        # Match-level cells, keyed (code, gw).
        self._match = {}
        self._mins = {}
        if ffh_long is not None and not ffh_long.empty:
            for _, r in ffh_long.iterrows():
                pts = r.get("pts")
                if pd.isna(pts):
                    continue
                self._match[(int(r["code"]), int(r["gw"]))] = float(pts)
                if not pd.isna(r.get("exp_mins")):
                    self._mins[(int(r["code"]), int(r["gw"]))] = float(r["exp_mins"])
        # Availability the models cannot see · a hand-entered "he is not playing
        # in GW1-2". Kept per gameweek rather than as a season minutes cut,
        # because missing the opening two weeks says nothing about April.
        self._miss = {int(c): set(int(g) for g in gws)
                      for c, gws in (miss_gws or {}).items()}
        # A hand-set score for one gameweek. `miss_gws` already says "he is not
        # playing"; this says "he plays, and here is what I think he returns",
        # which is the other half of the same call and the only way to overrule
        # a match model that is wrong about a specific fixture.
        self._set = {int(c): {int(g): float(v) for g, v in d.items()}
                     for c, d in (gw_points or {}).items()}
        self.window = sorted({gw for _, gw in self._match}) if self._match else []

    # ── one cell ──────────────────────────────────────────────────────────────
    def points(self, code: int, gw: int) -> float:
        if int(gw) in self._miss.get(int(code), ()):
            return 0.0
        # A hand-set score beats every model. It is the most explicit statement
        # of intent there is, so nothing downstream may quietly rescale it.
        hand = self._set.get(int(code), {}).get(int(gw))
        if hand is not None:
            return hand
        v = self._match.get((int(code), int(gw)))
        return v if v is not None else self._shape(code, gw)

    def source(self, code: int, gw: int) -> str:
        if int(gw) in self._miss.get(int(code), ()):
            return SRC_MANUAL
        if int(gw) in self._set.get(int(code), {}):
            return SRC_MANUAL
        return SRC_MATCH if (int(code), int(gw)) in self._match else SRC_SHAPE

    def expected_minutes(self, code: int, gw: int) -> Optional[float]:
        if int(gw) in self._miss.get(int(code), ()):
            return 0.0
        return self._mins.get((int(code), int(gw)))

    def misses(self, code: int, gw: int) -> bool:
        """Hand-entered unavailability for this gameweek."""
        return int(gw) in self._miss.get(int(code), ())

    def _shape(self, code: int, gw: int) -> float:
        """Season projection spread over 38 and scaled by each fixture's ease,
        lifted onto the match model's scale so both sources read alike."""
        base = self._season.get(int(code), 0.0) * self._scale / SEASON_GWS
        tid = self._team.get(int(code), 0)
        return sum(base * fixture_factor(f)
                   for _, _, f in self._fix.get((int(tid), int(gw)), []))

    # ── bulk ──────────────────────────────────────────────────────────────────
    def matrix(self, codes: List[int], gws: List[int]) -> pd.DataFrame:
        """codes x gameweeks of expected points. Index is `code`."""
        return pd.DataFrame(
            {gw: [self.points(c, gw) for c in codes] for gw in gws},
            index=pd.Index([int(c) for c in codes], name="code")).round(2)

    def run_total(self, code: int, gw_lo: int, gw_hi: int) -> float:
        return float(sum(self.points(code, g) for g in range(gw_lo, gw_hi + 1)))

    def squad_total(self, codes: List[int], gw: int) -> float:
        return float(sum(self.points(c, gw) for c in codes))

    def coverage(self, codes: List[int], gw: int) -> Tuple[int, int]:
        """(how many of these players have a real match forecast, how many asked)."""
        hit = sum(1 for c in codes if self.source(c, gw) == SRC_MATCH)
        return hit, len(codes)


def build(board: pd.DataFrame, fixtures_by_gw: Dict) -> GwProjection:
    """Construct from the board, pulling the FFH snapshot when one is saved."""
    long = None
    try:
        from data.fetchers.ffhub import load_snapshot, per_gw_by_code
        snap = load_snapshot()
        if snap is not None:
            long = per_gw_by_code(snap, board)
    except Exception as exc:
        logger.warning("per-gameweek match forecasts unavailable: %s", exc)

    miss, early, hand = {}, {}, {}
    try:
        from analytics.projection_overrides import load_overrides
        for code, adj in load_overrides().items():
            gws = adj.get("miss_gws")
            if gws:
                miss[int(code)] = [int(g) for g in gws]
            if adj.get("early_nailedness") is not None:
                early[int(code)] = float(adj["early_nailedness"])
            pts = adj.get("gw_points")
            if pts:
                hand[int(code)] = {int(g): float(v) for g, v in pts.items()}
        if miss:
            logger.info("per-gameweek unavailability for %d players", len(miss))
        if hand:
            logger.info("hand-set gameweek scores for %d players", len(hand))
    except Exception as exc:
        logger.warning("miss_gws overrides skipped: %s", exc)

    # A hand minutes call has to reach the PER-GAMEWEEK numbers, not just the
    # season gate. The match model had Foden at 70 minutes in GW1 then 20, 20,
    # 20 · a substitute · so any objective scored over an opening window read
    # him as a sub however emphatically the overrides file said otherwise.
    #
    # Points are scaled by the minutes ratio. That is an approximation: two of
    # a player's points are an appearance bonus that does not scale, so this
    # slightly over-rewards a big uplift. It is far closer than ignoring the
    # call entirely, and it is capped so a 10-minute cameo cannot be multiplied
    # into a haul.
    if early and long is not None and not long.empty:
        long = _apply_early_minutes(long, early)

    # The Hub is optimistic about players it has no Premier League record for,
    # and the bias survives into its PER-GAMEWEEK cells. Measured against our
    # own fixture shape it runs 23% hotter on them (median ratio 0.90 against
    # 0.73 for established players). The season blend already refuses their
    # vote; without this the same optimism walked straight into any objective
    # scored over a window · a Coventry forward away at Arsenal read 3.3.
    # The same call has to reach the match cells. A player who may not be in
    # the league cannot be projected 15.5 points over three gameweeks just
    # because the Hub has not heard he is leaving.
    if long is not None and not long.empty and "availability_mult" in board.columns:
        av = {int(c): float(m) for c, m in
              zip(board["code"], board["availability_mult"].fillna(1.0)) if m != 1.0}
        if av:
            hit = long["code"].astype(int).isin(av)
            long = long.copy()
            long.loc[hit, "pts"] = (
                pd.to_numeric(long.loc[hit, "pts"], errors="coerce")
                * long.loc[hit, "code"].astype(int).map(av)).round(2)
            logger.info("availability multiplier applied to %d match cells",
                        int(hit.sum()))

    if long is not None and not long.empty and "consensus_echoed_scout" in board.columns:
        no_record = set(board.loc[board["consensus_echoed_scout"].fillna(False).astype(bool),
                                  "code"].astype(int))
        if no_record:
            long = _damp_no_record(long, no_record)

    return GwProjection(board, fixtures_by_gw, long, miss_gws=miss,
                        gw_points=hand)


# Our shape / the Hub's, for players with no Premier League record. Measured,
# not chosen · see the comment above.
NO_RECORD_DAMPING = 0.81


def _damp_no_record(long: pd.DataFrame, codes: set) -> pd.DataFrame:
    """Pull the Hub's match points back for players it cannot really see.

    Minutes are left alone · those are a statement about selection, which the
    Hub is good at even for a player it has no history for. Only the POINTS,
    which need a scoring rate nobody has observed in this league, are damped.
    """
    out = long.copy()
    hit = out["code"].astype(int).isin(codes)
    if not hit.any():
        return out
    out.loc[hit, "pts"] = (pd.to_numeric(out.loc[hit, "pts"], errors="coerce")
                           * NO_RECORD_DAMPING).round(2)
    logger.info("damped %d match cells for %d players with no PL record",
                int(hit.sum()), len(codes))
    return out


# A hand call can lift a player's minutes by at most this multiple. Beyond it
# we are no longer adjusting a forecast, we are inventing one.
EARLY_MINUTES_CAP = 3.0


def _apply_early_minutes(long: pd.DataFrame, early: Dict[int, float]) -> pd.DataFrame:
    """Rescale match forecasts where a human has overruled the expected minutes."""
    out = long.copy()
    want = out["code"].astype(int).map(early) * 90.0
    have = pd.to_numeric(out.get("exp_mins"), errors="coerce")

    usable = want.notna() & have.notna() & (have > 0) & (want > have)
    if not usable.any():
        return out

    ratio = (want / have).clip(upper=EARLY_MINUTES_CAP)
    out.loc[usable, "pts"] = (pd.to_numeric(out.loc[usable, "pts"], errors="coerce")
                              * ratio[usable]).round(2)
    out.loc[usable, "exp_mins"] = want[usable].round(0)
    logger.info("early-minutes override rescaled %d match cells", int(usable.sum()))
    return out


def best_xi(squad: pd.DataFrame, proj: GwProjection, gw: int) -> set:
    """The eleven to start THIS gameweek · exactly 1 GKP, and at least 3 DEF,
    2 MID, 1 FWD, then the best of whoever is left.

    The squad MILP maximises a season, but in any single week the worst four
    differ: a blank or a hard away trip should bench a player who is otherwise a
    starter. Returns the set of `code`s in the XI.
    """
    scored = {int(r["code"]): proj.points(int(r["code"]), gw)
              for _, r in squad.iterrows()}
    by_pos = {}
    for _, r in squad.iterrows():
        by_pos.setdefault(str(r["position"]), []).append(int(r["code"]))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda c: -scored.get(c, 0.0))

    xi = set(by_pos.get("GKP", [])[:1])
    for pos, lo in (("DEF", 3), ("MID", 2), ("FWD", 1)):
        xi.update(by_pos.get(pos, [])[:lo])

    pos_of = {int(r["code"]): str(r["position"]) for _, r in squad.iterrows()}
    rest = [c for c in scored if c not in xi and pos_of.get(c) != "GKP"]
    rest.sort(key=lambda c: -scored.get(c, 0.0))
    for c in rest[:11 - len(xi)]:
        xi.add(c)
    return xi


