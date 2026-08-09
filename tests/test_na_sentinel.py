"""`replace(0, pd.NA)` on a float column is a time bomb, not a bug you can see.

Replacing a NUMERIC value with `pd.NA` promotes the whole Series to `object`,
and every `astype(float)` downstream then dies on `NAType`. The catch is that
the promotion only happens when the sentinel is actually PRESENT · while no
player has a season total of exactly 0 the replace is a no-op, the dtype stays
float64, and nothing is wrong. The day a refreshed snapshot first contains a 0,
the page breaks with a traceback pointing at `astype`, several frames away from
the line that caused it.

That is the whole reason this is a STATIC check. It has now happened twice from
the same two-word mistake · once in `value_board.solve_draft`, and again in the
Draft page's `_window_board`, where a Scout refresh that widened coverage to
players projected for zero points took the page down.

`float("nan")` does the same job and keeps the column float64. Use it.

Replacing a STRING sentinel (`replace("", pd.NA)`) is fine and is not flagged ·
that column is object dtype already, so there is nothing to promote.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

SCAN_DIRS = ("analytics", "ui", "views", "data", "components")


def _is_pd_na(node) -> bool:
    """Matches `pd.NA` / `pandas.NA`."""
    return (isinstance(node, ast.Attribute) and node.attr == "NA"
            and isinstance(node.value, ast.Name)
            and node.value.id in ("pd", "pandas"))


def _is_numeric_literal(node) -> bool:
    """Matches 0, 0.0, -1 · the sentinels that live in a numeric column."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(
            node.value, bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_numeric_literal(node.operand)
    return False


def _sources():
    for d in SCAN_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _offences(path):
    """Every `.replace(<number>, pd.NA)` in one file, as "line: source"."""
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:  # not ours to police
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "replace"):
            continue
        if len(node.args) < 2:
            continue
        if _is_numeric_literal(node.args[0]) and _is_pd_na(node.args[1]):
            out.append("%s:%d" % (path.relative_to(ROOT), node.lineno))
    return out


def test_no_numeric_value_is_replaced_with_pd_na():
    found = [hit for path in _sources() for hit in _offences(path)]
    assert not found, (
        "replace(<number>, pd.NA) promotes a float column to object and breaks "
        "astype(float) the first time the sentinel appears in the data. Use "
        "float('nan') instead. Offending lines: " + ", ".join(found))


# ── the behaviour the rule is protecting, pinned ─────────────────────────────

def test_pd_na_promotes_a_float_column_but_nan_does_not():
    pd = pytest.importorskip("pandas")
    with_zero = pd.Series([1.0, 0.0, 2.0])
    assert with_zero.replace(0, pd.NA).dtype == object
    assert with_zero.replace(0, float("nan")).dtype == "float64"


def test_dividing_by_the_promoted_column_cannot_be_cast_back():
    pd = pytest.importorskip("pandas")
    run = pd.Series([5.0, 4.0, 6.0])
    season = pd.Series([100.0, 0.0, 50.0]).replace(0, pd.NA)
    with pytest.raises(TypeError):
        (run / season).astype(float)
    # The supported spelling survives the same round trip.
    ok = pd.Series([100.0, 0.0, 50.0]).replace(0, float("nan"))
    assert (run / ok).astype(float).fillna(0.0).tolist() == [0.05, 0.0, 0.12]
