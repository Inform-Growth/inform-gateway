"""Tests for the api_keys.role column and read helpers (get_role, is_admin)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def test_role_column_defaults_to_user(store):
    """New api_keys row gets role='user' from the column default."""
    store.add_api_key("alice@example.com", "sk-alice")
    assert store.get_role("alice@example.com") == "user"
    assert store.is_admin("alice@example.com") is False


def test_get_role_returns_none_for_unknown_user(store):
    assert store.get_role("nobody@example.com") is None
    assert store.is_admin("nobody@example.com") is False


def test_set_user_role_roundtrip(store):
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    assert store.get_role("alice@example.com") == "admin"
    assert store.is_admin("alice@example.com") is True
    store.set_user_role("alice@example.com", "user")
    assert store.is_admin("alice@example.com") is False


def test_set_user_role_rejects_invalid_role(store):
    store.add_api_key("alice@example.com", "sk-alice")
    with pytest.raises(ValueError):
        store.set_user_role("alice@example.com", "superadmin")


def test_set_user_role_updates_all_keys_for_user(store):
    """Multi-key invariant: set_user_role moves every row for a user_id."""
    store.add_api_key("alice@example.com", "sk-alice-1")
    store.add_api_key("alice@example.com", "sk-alice-2")
    store.set_user_role("alice@example.com", "admin")
    with store._cursor() as cur:
        cur.execute(
            "SELECT role FROM api_keys WHERE user_id = %s ORDER BY key",
            ("alice@example.com",),
        )
        roles = [r["role"] for r in cur.fetchall()]
    assert roles == ["admin", "admin"]


def test_set_user_role_unknown_user_is_noop(store):
    """No api_keys row -> no error, no effect."""
    store.set_user_role("nobody@example.com", "admin")
    assert store.get_role("nobody@example.com") is None


def test_add_api_key_inherits_admin_role(store):
    """Second key for an existing admin user stays admin."""
    store.add_api_key("alice@example.com", "sk-alice-1")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("alice@example.com", "sk-alice-2")
    with store._cursor() as cur:
        cur.execute(
            "SELECT role FROM api_keys WHERE key = %s", ("sk-alice-2",)
        )
        row = cur.fetchone()
    assert row["role"] == "admin"


def test_add_api_key_defaults_new_user_to_user_role(store):
    store.add_api_key("bob@example.com", "sk-bob")
    assert store.get_role("bob@example.com") == "user"


def test_bootstrap_admin_roles_promotes_known_users(store):
    """bootstrap_admin_roles promotes existing users to admin."""
    store.add_api_key("alice@example.com", "sk-alice")
    store.add_api_key("bob@example.com", "sk-bob")
    result = store.bootstrap_admin_roles(["alice@example.com", "bob@example.com"])
    assert sorted(result["promoted"]) == ["alice@example.com", "bob@example.com"]
    assert result["skipped_unknown"] == []
    assert store.is_admin("alice@example.com") is True
    assert store.is_admin("bob@example.com") is True


def test_bootstrap_admin_roles_skips_unknown_users(store):
    """bootstrap_admin_roles skips users with no api_keys row."""
    result = store.bootstrap_admin_roles(["nobody@example.com"])
    assert result["promoted"] == []
    assert result["skipped_unknown"] == ["nobody@example.com"]


def test_bootstrap_admin_roles_never_demotes(store):
    """An admin not listed in the bootstrap call stays admin."""
    store.add_api_key("alice@example.com", "sk-alice")
    store.add_api_key("bob@example.com", "sk-bob")
    store.set_user_role("alice@example.com", "admin")
    store.bootstrap_admin_roles(["bob@example.com"])
    assert store.is_admin("alice@example.com") is True
    assert store.is_admin("bob@example.com") is True


def test_bootstrap_admin_roles_returns_admin_in_promoted_on_rerun(store):
    """Re-running bootstrap on an already-admin user still reports them as promoted
    (the spec semantics: 'promoted' = users we ran UPDATE on, regardless of net change)."""
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    result = store.bootstrap_admin_roles(["alice@example.com"])
    assert result["promoted"] == ["alice@example.com"]
    assert result["skipped_unknown"] == []
    assert store.is_admin("alice@example.com") is True


def test_bootstrap_admin_roles_empty_list_is_noop(store):
    """bootstrap_admin_roles with empty list is a no-op."""
    result = store.bootstrap_admin_roles([])
    assert result["promoted"] == []
    assert result["skipped_unknown"] == []


def test_list_users_includes_role(store):
    store.add_api_key("alice@example.com", "sk-alice")
    store.add_api_key("bob@example.com", "sk-bob")
    store.set_user_role("alice@example.com", "admin")
    users = {u["user_id"]: u for u in store.list_users()}
    assert users["alice@example.com"]["role"] == "admin"
    assert users["bob@example.com"]["role"] == "user"
