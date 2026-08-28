"""Is the gap real? · current squad vs the squad after this week's moves.

Pure helpers only. `_gap_sim` (the cached call into `head_to_head.simulate_drafts`)
lives in `views/00_my_team.py` next to the board it closes over.
"""
from typing import Dict, List

import pandas as pd

from analytics.head_to_head import significance


def gap_entries(board: pd.DataFrame, codes_now: List[int], codes_after: List[int], gw: int) -> List[Dict]:
    def _sq(codes):
        return board[board["code"].isin(codes)].set_index("code").reindex(codes).reset_index()
    return [{"name": "Current squad", "phases": [(int(gw), _sq(codes_now))], "bench_boost_gw": None},
            {"name": "After these moves", "phases": [(int(gw), _sq(codes_after))], "bench_boost_gw": None}]


def gap_verdict(sim: Dict) -> Dict:
    d = {x["name"]: x for x in sim.get("drafts", [])}
    return significance(d["After these moves"], d["Current squad"])
