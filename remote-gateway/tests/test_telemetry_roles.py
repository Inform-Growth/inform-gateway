"""Tests for the api_keys.role column and read helpers (get_role, is_admin)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def test_role_column_defaults_to_user(store):
    """New api_keys row gets role='user' from the column default."""
    store.add_api_key("alice@example.com", "sk-alice")
    assert store.get_role("alice@example.com") == "user"
    assert store.is_admin("alice@example.com") is False


def test_get_role_returns_none_for_unknown_user(store):
    assert store.get_role("nobody@example.com") is None
    assert store.is_admin("nobody@example.com") is False
