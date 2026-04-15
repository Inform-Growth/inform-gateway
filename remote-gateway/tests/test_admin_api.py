"""
Tests for the admin API routes in admin_api.py.

Uses Starlette's TestClient for HTTP-level testing with a real
in-memory TelemetryStore.

Run with:
    pytest remote-gateway/tests/test_admin_api.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from admin_api import _DEFAULT_TOKEN, create_admin_app
from telemetry import TelemetryStore

TOKEN = _DEFAULT_TOKEN


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


@pytest.fixture()
def client(store):
    app = create_admin_app(store)
    return TestClient(app, raise_server_exceptions=True), store


# ---------------------------------------------------------------------------
# Token enforcement
# ---------------------------------------------------------------------------

def test_dashboard_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/")
    assert resp.status_code == 403


def test_api_stats_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/api/stats")
    assert resp.status_code == 403


def test_dashboard_allowed_with_token(client):
    c, _ = client
    dash_path = Path(__file__).parent.parent / "core" / "admin_dashboard.html"
    if not dash_path.exists():
        pytest.skip("admin_dashboard.html not yet created")
    resp = c.get(f"/?token={TOKEN}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_returns_tools_key(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/stats?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert "tools" in body
    assert "summary" in body


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def test_list_users_empty(client):
    c, _ = client
    resp = c.get(f"/api/users?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_user_returns_key(client):
    c, _ = client
    resp = c.post(f"/api/users?token={TOKEN}", json={"user_id": "alice@example.com"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == "alice@example.com"
    assert body["key"].startswith("sk-")


def test_create_user_missing_user_id(client):
    c, _ = client
    resp = c.post(f"/api/users?token={TOKEN}", json={})
    assert resp.status_code == 400


def test_delete_user_success(client):
    c, store = client
    store.add_api_key("alice@example.com", "sk-alice")
    resp = c.delete(f"/api/users/alice@example.com?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


def test_delete_user_not_found(client):
    c, _ = client
    resp = c.delete(f"/api/users/nobody@example.com?token={TOKEN}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def test_get_permissions_empty(client):
    c, _ = client
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.json()["permissions"] == []


def test_set_and_get_permission(client):
    c, _ = client
    resp = c.put(
        f"/api/permissions/alice@example.com/health_check?token={TOKEN}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert perms["health_check"] is False


def test_set_permission_missing_enabled(client):
    c, _ = client
    resp = c.put(
        f"/api/permissions/alice@example.com/health_check?token={TOKEN}",
        json={},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Permissions — merged with tool list
# ---------------------------------------------------------------------------

class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = ""


@pytest.fixture()
def client_with_tools(store):
    async def _list_tools():
        return [_FakeTool("health_check"), _FakeTool("get_tool_stats"), _FakeTool("write_note")]

    app = create_admin_app(store, list_tools_fn=_list_tools)
    return TestClient(app, raise_server_exceptions=True), store


def test_permissions_shows_all_tools_when_no_explicit_rows(client_with_tools):
    """All tools appear with enabled=True when no explicit permissions exist."""
    c, _ = client_with_tools
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    assert resp.status_code == 200
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert set(perms.keys()) == {"health_check", "get_tool_stats", "write_note"}
    assert all(v is True for v in perms.values())


def test_permissions_merges_explicit_row_with_tool_list(client_with_tools):
    """An explicit disabled row overrides the default enabled=True."""
    c, store = client_with_tools
    store.set_tool_permission("alice@example.com", "health_check", False)
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert perms["health_check"] is False
    assert perms["get_tool_stats"] is True


def test_permissions_falls_back_to_explicit_rows_when_no_list_fn(client):
    """Without list_tools_fn, only explicit rows are returned (existing behavior)."""
    c, store = client
    store.set_tool_permission("alice@example.com", "write_note", False)
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert list(perms.keys()) == ["write_note"]


# ---------------------------------------------------------------------------
# Sessions / Sankey
# ---------------------------------------------------------------------------

def test_sessions_returns_sankey_key(client):
    c, store = client
    store.record("tool_a", 10, True, user_id="alice")
    store.record("tool_b", 10, True, user_id="alice")
    resp = c.get(f"/api/sessions?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert "sankey" in body
    assert "nodes" in body["sankey"]
    assert "links" in body["sankey"]


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def test_logs_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/api/logs")
    assert resp.status_code == 403


def test_logs_returns_list(client):
    c, store = client
    store.record("health_check", 10, True, user_id="alice", input_body='{"x": 1}')
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["tool_name"] == "health_check"
    assert "input_body" in body[0]
    assert "input_size" in body[0]


def test_logs_filters_by_tool(client):
    c, store = client
    store.record("tool_a", 10, True)
    store.record("tool_b", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}&tool=tool_a")
    assert resp.status_code == 200
    assert all(row["tool_name"] == "tool_a" for row in resp.json())


def test_logs_filters_errors_only(client):
    c, store = client
    store.record("health_check", 10, True)
    store.record("health_check", 10, False, error_type="ValueError")
    resp = c.get(f"/api/logs?token={TOKEN}&success=false")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["success"] is False


def test_logs_includes_error_message(client):
    c, store = client
    store.record(
        "attio__create_note", 50, False,
        error_type="Exception",
        error_message="Missing required parameter: resource_type",
    )
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["error_message"] == "Missing required parameter: resource_type"


def test_logs_error_message_none_on_success(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["error_message"] is None


def test_logs_invalid_limit_uses_default(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}&limit=abc&offset=xyz")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_logs_filters_by_user(client):
    c, store = client
    store.record("health_check", 10, True, user_id="alice")
    store.record("health_check", 10, True, user_id="bob")
    resp = c.get(f"/api/logs?token={TOKEN}&user=alice")
    assert resp.status_code == 200
    rows = resp.json()
    assert all(row["user_id"] == "alice" for row in rows)


def test_logs_negative_limit_clamped(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}&limit=-1")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def test_timeline_empty(client):
    c, _ = client
    resp = c.get(f"/api/timeline?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"users": [], "days": []}


def test_timeline_returns_per_user_breakdown(client):
    c, store = client
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    store.record("health_check", 10, True, user_id="alice@example.com")
    resp = c.get(f"/api/timeline?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["users"]) == ["alice@example.com", "bob@example.com"]
    assert len(body["days"]) == 1
    day = body["days"][0]
    assert day["alice@example.com"] == 2
    assert day["bob@example.com"] == 1


def test_timeline_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/api/timeline")
    assert resp.status_code == 403
