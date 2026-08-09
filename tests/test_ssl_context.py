"""Every outbound aiohttp session must carry a CA bundle.

python.org's macOS build ships no system trust store, so a bare
`aiohttp.ClientSession()` raises CERTIFICATE_VERIFY_FAILED. `_fetch_understat_async`
was fixed with certifi; `_fetch_league_results_async` beside it was not, and the
result was a warning nobody reads:

    Understat team stats fetch failed: CERTIFICATE_VERIFY_FAILED
    Composite FDR unavailable (empty team stats) - falling back to raw FDR

So the app silently ran on flat per-club fixture difficulty instead of the
venue-aware composite rating, degrading every fixture-weighted number in it.
A static scan, in the same spirit as test_na_sentinel.
"""
import ast
from pathlib import Path

import pytest

ROOTS = ["analytics", "data", "ui", "views", "components"]


def _files():
    for root in ROOTS:
        for p in Path(root).rglob("*.py"):
            if "__pycache__" not in str(p):
                yield p


def _bare_sessions(src):
    """Line numbers of `aiohttp.ClientSession()` calls with no arguments.

    Parsed, not grepped · a regex over raw text also matches the pattern where
    it appears inside a docstring explaining the rule, which is how the first
    version of this test failed on the very comment describing it.
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr == "ClientSession"
                and not node.args and not node.keywords):
            out.append(node.lineno)
    return out


@pytest.mark.parametrize("path", sorted(_files(), key=str), ids=str)
def test_no_session_without_a_ca_bundle(path):
    hits = _bare_sessions(path.read_text())
    assert not hits, (
        "%s:%s constructs aiohttp.ClientSession() with no connector, so it uses "
        "the system trust store and fails on python.org macOS builds. Pass the "
        "shared certifi connector instead." % (path, hits))
