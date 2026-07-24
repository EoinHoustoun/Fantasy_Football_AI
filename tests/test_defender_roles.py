"""The new-season roles file must load, and a missing season must degrade to an
empty dict rather than crash."""
from analytics.playbook import _load_defender_roles


def test_2026_27_roles_file_loads_non_empty():
    roles = _load_defender_roles("2026-27")
    assert isinstance(roles, dict)
    assert len(roles) > 0, "expected seeded provisional roles"


def test_missing_season_returns_empty_dict():
    roles = _load_defender_roles("1999-00")
    assert roles == {}
