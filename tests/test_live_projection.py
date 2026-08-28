"""The projector builders shared by the Draft and My Team."""
from ui import live_projection as lp


def test_fixtures_for_reads_the_supplied_map_and_pads_blanks():
    fix = {(1, 2): [("ARS", True, 2.0)], (1, 3): [("CHE", False, 4.0), ("LIV", True, 5.0)]}
    out = lp.fixtures_for(1, 2, 3, fix=fix)
    assert out[0] == {"opp": "ARS", "home": True, "fdr": 2.0}
    assert out[1]["opp"] == "CHE" and out[2]["opp"] == "LIV"
    assert lp.fixtures_for(1, 5, 2, fix=fix)[0]["blank"] is True


def test_module_stamp_changes_with_the_module():
    import analytics.gw_projection as g
    s = lp.module_stamp(g)
    assert s.startswith("analytics.gw_projection:")
