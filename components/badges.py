"""
Player badge helpers.

Returns HTML pill/badge strings for special player attributes.
Import render_badges() and call it with a player Series/dict.
"""

import pandas as pd
from typing import Union

# Defcon monster threshold — score above this gets the badge
DEFCON_MONSTER_THRESHOLD = 0.35


def render_badges(player: Union[pd.Series, dict], size: str = "sm") -> str:
    """
    Return an HTML string of badge pills for a player's special attributes.

    Badges:
      ⚽ Pen #1   — penalties_order == 1
      2️⃣ Pen #2   — penalties_order == 2
      🎯 Corners  — corners_order <= 2
      🦶 FK       — freekicks_order <= 2
      🛡️ DEFCON   — defcon_monster_score >= threshold
      ⚠️ Mins     — avg_minutes < 60 (warning)

    Args:
        player: pd.Series or dict with player attributes
        size: "sm" (compact) or "lg" (larger padding)
    """
    pad = "1px 5px" if size == "sm" else "2px 8px"
    fs  = "10px"    if size == "sm" else "12px"

    def _badge(text: str, bg: str, color: str = "#000") -> str:
        return (
            f'<span style="background:{bg};color:{color};border-radius:4px;'
            f'padding:{pad};font-size:{fs};font-weight:700;margin-right:3px;'
            f'white-space:nowrap;">{text}</span>'
        )

    badges = []

    # Penalty taker
    pen = player.get("penalties_order")
    if pen == 1:
        badges.append(_badge("⚽ Pen #1", "#FFD700", "#000"))
    elif pen == 2:
        badges.append(_badge("⚽ Pen 2", "#C0C0C0", "#000"))

    # Corner taker
    corn = player.get("corners_order")
    try:
        if corn is not None and not pd.isna(corn) and int(corn) <= 2:
            badges.append(_badge("🎯 Corners", "#04f5ff", "#000"))
    except (ValueError, TypeError):
        pass

    # Direct free kick taker
    fk = player.get("freekicks_order")
    try:
        if fk is not None and not pd.isna(fk) and int(fk) <= 2:
            badges.append(_badge("🦶 FK", "#ff6900", "#fff"))
    except (ValueError, TypeError):
        pass

    # Defcon Monster
    monster = player.get("defcon_monster_score")
    try:
        if monster is not None and not pd.isna(monster) and float(monster) >= DEFCON_MONSTER_THRESHOLD:
            badges.append(_badge("🛡️ DEFCON", "#00FF87", "#000"))
    except (ValueError, TypeError):
        pass

    # Minutes warning
    avg_mins = player.get("avg_minutes")
    try:
        if avg_mins is not None and not pd.isna(avg_mins) and float(avg_mins) < 60:
            badges.append(_badge("⚠️ Mins", "#FF4B4B", "#fff"))
    except (ValueError, TypeError):
        pass

    return " ".join(badges)


def minutes_multiplier(avg_minutes: float, power: float = 0.5, floor: float = 0.5) -> float:
    """
    Convert average minutes per game to a [floor, 1.0] score multiplier.

    90 mins → 1.0
    87 mins → 0.98
    75 mins → 0.91
    60 mins → 0.82
    45 mins → 0.71
    30 mins → 0.58 (floored at `floor`)

    Args:
        avg_minutes: Mean minutes played per game
        power: Exponent applied (0.5 = square root — rewards high mins strongly)
        floor: Minimum multiplier (prevents 0-min players collapsing score entirely)
    """
    raw = min(float(avg_minutes), 90.0) / 90.0
    return max(floor, raw ** power)
