import pandas as pd
from ui import team_gap as G


def test_gap_entries_shape():
    board = pd.DataFrame({"code": [1, 2, 3], "position": ["MID"] * 3, "web_name": list("abc")})
    ents = G.gap_entries(board, [1, 2], [1, 3], gw=4)
    assert [e["name"] for e in ents] == ["Current squad", "After these moves"]
    assert ents[0]["phases"][0][0] == 4 and list(ents[1]["phases"][0][1]["code"]) == [1, 3]
    assert ents[0]["bench_boost_gw"] is None


def test_gap_verdict_reads_pairwise_probability():
    sim = {"drafts": [{"name": "Current squad", "total_mean": 50.0, "beats": {"After these moves": 0.3}},
                      {"name": "After these moves", "total_mean": 54.0, "beats": {"Current squad": 0.7}}]}
    v = G.gap_verdict(sim)
    assert v["call"] == "lean" and v["gap"] == 4.0
