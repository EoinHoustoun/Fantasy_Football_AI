"""The numbers behind the player card, kept out of the view that draws them.

Clean-sheet and team-goal probabilities come from our own Dixon-Coles fit rather
than a paid ticker. Percentile ranks answer "is 6.7 DEFCON per 90 good?", which
a bare number cannot.
"""
import math

import pandas as pd
import pytest

from analytics import player_card as PC

# attack/defence on the log scale · positive attack = dangerous,
# positive defence = leaky.
RATINGS = {
    "attacks": {"Arsenal": 0.40, "Burnley": -0.35, "Everton": 0.0},
    "defenses": {"Arsenal": -0.40, "Burnley": 0.30, "Everton": 0.0},
    "home_adv": 0.25,
    "rho": -0.08,
}


# ── expected goals ───────────────────────────────────────────────────────────

def test_home_advantage_lifts_the_home_side():
    home = PC.match_shape(RATINGS, "Everton", "Everton", is_home=True)
    away = PC.match_shape(RATINGS, "Everton", "Everton", is_home=False)
    assert home["exp_goals_for"] > away["exp_goals_for"]


def test_a_strong_attack_outscores_a_weak_one_against_the_same_defence():
    strong = PC.match_shape(RATINGS, "Arsenal", "Everton", is_home=True)
    weak = PC.match_shape(RATINGS, "Burnley", "Everton", is_home=True)
    assert strong["exp_goals_for"] > weak["exp_goals_for"]


def test_a_leaky_opponent_concedes_more():
    vs_leaky = PC.match_shape(RATINGS, "Arsenal", "Burnley", is_home=True)
    vs_tight = PC.match_shape(RATINGS, "Arsenal", "Arsenal", is_home=True)
    assert vs_leaky["exp_goals_for"] > vs_tight["exp_goals_for"]


# ── clean sheets ─────────────────────────────────────────────────────────────

def test_clean_sheet_is_poisson_zero_of_goals_against():
    m = PC.match_shape(RATINGS, "Arsenal", "Burnley", is_home=True)
    assert m["p_clean_sheet"] == pytest.approx(math.exp(-m["exp_goals_against"]), abs=1e-9)


def test_clean_sheet_is_a_probability():
    for home in (True, False):
        for a, b in (("Arsenal", "Burnley"), ("Burnley", "Arsenal")):
            p = PC.match_shape(RATINGS, a, b, is_home=home)["p_clean_sheet"]
            assert 0.0 <= p <= 1.0


def test_a_good_defence_keeps_more_clean_sheets_than_a_bad_one():
    good = PC.match_shape(RATINGS, "Arsenal", "Everton", is_home=True)["p_clean_sheet"]
    bad = PC.match_shape(RATINGS, "Burnley", "Everton", is_home=True)["p_clean_sheet"]
    assert good > bad


def test_missing_team_returns_nothing_rather_than_guessing():
    assert PC.match_shape(RATINGS, "Atlantis", "Arsenal", is_home=True) is None


def test_no_ratings_at_all_returns_nothing():
    assert PC.match_shape(None, "Arsenal", "Burnley", is_home=True) is None


# ── percentile ranks · "is this number any good?" ────────────────────────────

S = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])


def test_the_best_value_ranks_at_the_top():
    assert PC.percentile(S, 10.0) == 100


def test_the_worst_value_ranks_at_the_bottom():
    assert PC.percentile(S, 1.0) == 10


def test_the_middle_ranks_in_the_middle():
    assert 40 <= PC.percentile(S, 5.0) <= 60


def test_a_missing_value_has_no_rank():
    assert PC.percentile(S, None) is None
    assert PC.percentile(S, float("nan")) is None


def test_an_empty_population_has_no_rank():
    assert PC.percentile(pd.Series([], dtype=float), 5.0) is None


# ── the name bridge · Dixon-Coles fits on football-data.co.uk names ──────────
# The fit calls them "Manchester United" and "Brighton & Hove Albion"; the board
# calls them "Man Utd" and "Brighton". Joining these by raw string is exactly
# the failure that has already cost this repo two bugs, so it is pinned.

DC_TEAMS = ['Arsenal', 'Aston Villa', 'Bournemouth', 'Brentford',
            'Brighton & Hove Albion', 'Burnley', 'Chelsea', 'Crystal Palace',
            'Everton', 'Fulham', 'Ipswich Town', 'Leeds', 'Leicester City',
            'Liverpool', 'Luton Town', 'Manchester City', 'Manchester United',
            'Newcastle United', 'Nottingham Forest', 'Sheffield United',
            'Southampton', 'Sunderland', 'Tottenham Hotspur',
            'West Ham United', 'Wolverhampton Wanderers']


@pytest.mark.parametrize("board_name,expected", [
    ("Man Utd", "Manchester United"),
    ("Man City", "Manchester City"),
    ("Spurs", "Tottenham Hotspur"),
    ("Brighton", "Brighton & Hove Albion"),
    ("Newcastle", "Newcastle United"),
    ("Nott'm Forest", "Nottingham Forest"),
    ("Wolves", "Wolverhampton Wanderers"),
    ("West Ham", "West Ham United"),
    ("Arsenal", "Arsenal"),
    ("Liverpool", "Liverpool"),
    ("Leeds", "Leeds"),
    ("Sunderland", "Sunderland"),
])
def test_board_names_resolve_to_the_fit(board_name, expected):
    assert PC.resolve_team(board_name, DC_TEAMS) == expected


def test_a_promoted_club_with_no_history_resolves_to_nothing():
    # Coventry and Hull have never been in this fit. A wrong match here would
    # silently price a fixture off another club's strength.
    assert PC.resolve_team("Coventry", DC_TEAMS) is None
    assert PC.resolve_team("Hull", DC_TEAMS) is None


def test_it_does_not_confuse_the_two_manchesters():
    assert PC.resolve_team("Man City", DC_TEAMS) != "Manchester United"


def test_it_does_not_confuse_united_clubs():
    # Four clubs end in "United" · a token match on that word alone would pick
    # whichever sorted first.
    assert PC.resolve_team("Newcastle", DC_TEAMS) == "Newcastle United"
    assert PC.resolve_team("Sheffield Utd", DC_TEAMS) == "Sheffield United"


# ── the column whitelist · this repo has lost data to it twice ───────────────

def test_the_last_season_frame_carries_what_the_card_shows():
    """`_last_season_stats` prunes columns. Anything the card ranks or displays
    has to survive that prune, or it silently renders as a dash."""
    import re
    from pathlib import Path
    src = Path("views/18_draft_2026_27.py").read_text()
    block = re.search(r"keep = \[(.*?)\]", src, re.S).group(1)
    for col in ("pts_per_million", "position", "minutes", "total_points",
                "starts_total", "xgi"):
        assert '"%s"' % col in block, (
            "%s is used by the player card but pruned from _last_season_stats" % col)
