"""Every 2026-27 Premier League club must have a real colour tuple so shirts
and dots never fall back to the default green."""
import re

import config

# The 20 short_names in the live 2026-27 bootstrap (verified against the API).
CLUBS_2026_27 = {
    "ARS", "AVL", "BHA", "BOU", "BRE", "CHE", "COV", "CRY", "EVE", "FUL",
    "HUL", "IPS", "LEE", "LIV", "MCI", "MUN", "NEW", "NFO", "SUN", "TOT",
}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_every_2026_27_club_has_a_colour_tuple():
    missing = [c for c in CLUBS_2026_27 if c not in config.TEAM_COLORS]
    assert not missing, f"clubs missing from TEAM_COLORS: {missing}"


def test_colour_tuples_are_valid_hex_pairs():
    for club in CLUBS_2026_27:
        primary, secondary = config.TEAM_COLORS[club]
        assert HEX.match(primary), f"{club} primary not hex: {primary}"
        assert HEX.match(secondary), f"{club} secondary not hex: {secondary}"
