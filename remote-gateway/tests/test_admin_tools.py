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
