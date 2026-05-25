"""Tests for the admin-gated MCP tools and the _require_admin chokepoint."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import mcp_server as server  # noqa: E402


def test_require_admin_allows_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        assert server._require_admin() == "alice@example.com"
    finally:
        server._current_user.reset(token)


def test_require_admin_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError, match="admin role required"):
            server._require_admin()
    finally:
        server._current_user.reset(token)


def test_require_admin_blocks_unauthenticated(monkeypatch, store):
    monkeypatch.setattr(server, "_telemetry", store)
    token = server._current_user.set(None)
    try:
        with pytest.raises(PermissionError, match="admin role required"):
            server._require_admin()
    finally:
        server._current_user.reset(token)


from tools.admin import (  # noqa: E402, I001
    make_list_users,
    make_set_user_role,
    make_set_tool_permission,
    make_set_skill_permission,
)


# ---- list_users ----

def test_list_users_returns_users_with_role(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_list_users(store)()
    finally:
        server._current_user.reset(token)
    user_ids = {u["user_id"] for u in result["users"]}
    assert user_ids == {"alice@example.com", "bob@example.com"}
    roles = {u["user_id"]: u["role"] for u in result["users"]}
    assert roles == {"alice@example.com": "admin", "bob@example.com": "user"}


def test_list_users_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_list_users(store)()
    finally:
        server._current_user.reset(token)


# ---- set_user_role ----

def test_set_user_role_promotes(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_user_role(store)("bob@example.com", "admin")
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "role": "admin"}
    assert store.is_admin("bob@example.com") is True


def test_set_user_role_rejects_invalid_role(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        with pytest.raises(ValueError):
            make_set_user_role(store)("alice@example.com", "superadmin")
    finally:
        server._current_user.reset(token)


def test_set_user_role_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_set_user_role(store)("bob@example.com", "admin")
    finally:
        server._current_user.reset(token)


# ---- set_tool_permission ----

def test_set_tool_permission_bulk_applies_all(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_tool_permission(store)(
            "bob@example.com",
            [
                {"tool_name": "apollo__enrich_person", "enabled": True},
                {"tool_name": "buffer__create_post", "enabled": False},
                {"tool_name": "exa__web_search_exa", "enabled": True},
            ],
        )
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "applied": 3}
    perms = {
        row["tool_name"]: row["enabled"]
        for row in store.get_tool_permissions("bob@example.com")
    }
    assert perms == {
        "apollo__enrich_person": 1,
        "buffer__create_post": 0,
        "exa__web_search_exa": 1,
    }


def test_set_tool_permission_empty_list_returns_zero(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_tool_permission(store)("bob@example.com", [])
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "applied": 0}


def test_set_tool_permission_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_set_tool_permission(store)(
                "bob@example.com",
                [{"tool_name": "anything", "enabled": True}],
            )
    finally:
        server._current_user.reset(token)


# ---- set_skill_permission ----

def test_set_skill_permission_bulk_applies_all(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_skill_permission(store)(
            "bob@example.com",
            [
                {"skill_name": "role_signal_scout", "enabled": True},
                {"skill_name": "schedule_linkedin_post", "enabled": False},
            ],
        )
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "applied": 2}
    perms = {
        row["skill_name"]: row["enabled"]
        for row in store.get_skill_permissions("bob@example.com")
    }
    assert perms == {"role_signal_scout": 1, "schedule_linkedin_post": 0}


def test_set_skill_permission_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_set_skill_permission(store)(
                "bob@example.com",
                [{"skill_name": "anything", "enabled": True}],
            )
    finally:
        server._current_user.reset(token)


from tools.meta import make_create_user  # noqa: E402


def test_create_user_requires_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")  # non-admin
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_create_user(store)("ghost@example.com", "")
    finally:
        server._current_user.reset(token)


def test_create_user_allows_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_create_user(store)("new_user", "")
    finally:
        server._current_user.reset(token)
    assert result["user_id"] == "new_user"
    assert result["key"].startswith("sk-")
