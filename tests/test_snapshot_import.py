"""Importing a snapshot must fail loudly, or not at all.

Every snapshot bug this repo has had was silent. Rate My Team writes "GK" where
the code expected "G", so all 55 keepers dropped out of a join and the overall
match rate still read 89% because the outfield players carried it. A file that
installs cleanly and quietly breaks a join is the failure mode; refusing to
install is the feature.
"""
import pandas as pd
import pytest

from data import snapshot_import as SI


def _ffh(n=5):
    return pd.DataFrame({
        "name": ["P%d" % i for i in range(n)],
        "team": ["Arsenal"] * n, "pos": ["MID"] * n,
        "price": [5.0] * n, "own": [1.0] * n, "pps": [3.0] * n, "pred": [10.0] * n,
        "gw1_pts": [4.0] * n, "gw1_opp": ["BOU(H)"] * n, "gw1_min": [90] * n,
        "gw2_pts": [4.0] * n, "gw2_opp": ["CRY(A)"] * n, "gw2_min": [90] * n,
        "gw3_pts": [4.0] * n, "gw3_opp": ["COV(H)"] * n, "gw3_min": [90] * n,
        "gw4_pts": [4.0] * n, "gw4_opp": ["MUN(A)"] * n, "gw4_min": [90] * n,
    })


# ── identifying which snapshot a file is ─────────────────────────────────────

def test_it_recognises_the_hub_export():
    assert SI.identify(_ffh()) == "ffh"


def test_it_recognises_the_scout_per_gameweek_table():
    df = pd.DataFrame(columns=["name", "team", "pos", "gw1", "gw2", "gw3", "gw4",
                               "gw5", "gw6", "total", "price", "value"])
    assert SI.identify(df) == "scout_rmt_gw"


def test_it_recognises_the_scout_season_table():
    df = pd.DataFrame(columns=["name", "team", "pos", "season_total", "price"])
    assert SI.identify(df) == "scout_rmt_season"


def test_it_recognises_the_scout_stats_table():
    df = pd.DataFrame(columns=["name", "team", "pos", "price", "mins", "g", "a",
                               "cs", "bonus", "dc", "yc", "pts", "value"])
    assert SI.identify(df) == "scout_stats"


def test_an_unrecognised_file_is_not_guessed_at():
    assert SI.identify(pd.DataFrame({"foo": [1], "bar": [2]})) is None


# ── validation · the point of the whole thing ────────────────────────────────

def test_a_good_file_validates():
    # reference=None · a unit test must not depend on whichever snapshot happens
    # to be installed on this machine.
    ok, problems = SI.validate(_ffh(300), "ffh", reference=None)
    assert ok, problems


def test_a_missing_required_column_is_refused():
    bad = _ffh(300).drop(columns=["gw1_min"])
    ok, problems = SI.validate(bad, "ffh", reference=None)
    assert not ok
    assert any("gw1_min" in p for p in problems)


def test_a_suspiciously_small_file_is_refused():
    # A truncated export · half the table copied, or a filter left on.
    ok, problems = SI.validate(_ffh(12), "ffh", reference=None)
    assert not ok
    assert any("rows" in p.lower() for p in problems)


def test_an_all_empty_numeric_column_is_refused():
    bad = _ffh(300)
    bad["gw1_pts"] = None
    ok, problems = SI.validate(bad, "ffh", reference=None)
    assert not ok
    assert any("gw1_pts" in p for p in problems)


# The position vocabulary is LEARNED from the file that currently works, not
# hardcoded. A first attempt guessed {"GK","MID",...} and refused the real Hub
# export, which spells them "Goalkeeper" and "Midfielder"; Scout's two tables
# use "GK"/"M"/"D"/"F" and "GK"/"MID"/"DEF"/"FWD". Three vocabularies, none of
# them guessable. What matters is a CHANGE from what the joins already handle.

def test_positions_matching_the_current_file_are_fine():
    ref = _ffh(300)
    ref.loc[:, "pos"] = "Midfielder"
    new = _ffh(300)
    new.loc[:, "pos"] = "Midfielder"
    ok, problems = SI.validate(new, "ffh", reference=ref)
    assert ok, problems


def test_a_new_position_spelling_is_refused():
    """The exact bug: Rate My Team started writing GK where the join expected G,
    and all 55 keepers silently vanished."""
    ref = _ffh(300)
    ref.loc[:, "pos"] = "Goalkeeper"
    new = _ffh(300)
    new.loc[:, "pos"] = "GK"
    ok, problems = SI.validate(new, "ffh", reference=ref)
    assert not ok
    assert any("pos" in p.lower() for p in problems)


def test_with_no_reference_any_position_is_allowed():
    # A first-ever import has nothing to compare against, and refusing it would
    # make the tool unusable exactly when it is most needed.
    ok, problems = SI.validate(_ffh(300), "ffh", reference=None)
    assert ok, problems


def test_a_normal_rate_of_shared_surnames_is_fine():
    # The real files run 2.5-3% duplicates · different players, same surname.
    df = _ffh(300)
    df.loc[:9, "name"] = "Silva"
    ok, problems = SI.validate(df, "ffh", reference=None)
    assert ok, problems


def test_a_doubled_export_is_refused():
    df = _ffh(300)
    df.loc[:, "name"] = "Same Guy"
    ok, problems = SI.validate(df, "ffh", reference=None)
    assert not ok
    assert any("duplicate" in p.lower() for p in problems)


# ── installing ───────────────────────────────────────────────────────────────

def test_install_writes_the_file_and_backs_up_the_old_one(tmp_path, monkeypatch):
    monkeypatch.setattr(SI, "CACHE", tmp_path)
    monkeypatch.setattr(SI, "BACKUPS", tmp_path / "_snapshot_backups")
    target = tmp_path / SI.SPECS["ffh"].filename
    target.write_text("old,file\n1,2\n")
    SI.install(_ffh(300), "ffh")
    assert len(pd.read_csv(target)) == 300
    backups = list((tmp_path / "_snapshot_backups").glob("*.csv"))
    assert backups, "the previous snapshot was overwritten with no backup"


def test_install_refuses_a_file_that_failed_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(SI, "CACHE", tmp_path)
    monkeypatch.setattr(SI, "BACKUPS", tmp_path / "_snapshot_backups")
    with pytest.raises(ValueError):
        SI.install(_ffh(3), "ffh")


def test_backups_never_land_in_the_tracked_archive(tmp_path, monkeypatch):
    # data/cache/archive is deliberately un-ignored and committed. A backup of
    # paid Scout data dropped in there would publish it to a PUBLIC repo.
    monkeypatch.setattr(SI, "CACHE", tmp_path)
    assert "archive" not in str(SI.BACKUPS).split("/")[-1]


# ── numbers that arrive as strings ───────────────────────────────────────────
# Scout's per-gameweek export writes price as "15.5m". The parser downstream
# already copes; an earlier version of this check called the column
# "entirely non-numeric" and refused the real, working file.

def test_a_price_written_with_a_unit_still_counts_as_numeric():
    df = _ffh(300)
    df["price"] = ["%.1fm" % 5.0] * 300
    ok, problems = SI.validate(df, "ffh", reference=None)
    assert ok, problems


def test_a_genuinely_empty_column_is_still_refused():
    df = _ffh(300)
    df["price"] = [""] * 300
    ok, problems = SI.validate(df, "ffh", reference=None)
    assert not ok
    assert any("price" in p for p in problems)
