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

from admin_api import create_admin_app, _DEFAULT_TOKEN
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
