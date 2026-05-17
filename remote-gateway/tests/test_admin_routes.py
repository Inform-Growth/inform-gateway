"""
Tests for the admin route layout introduced for the React SPA migration.

Verifies:
  * SPA catch-all returns 503 when admin-ui/dist is not present
  * Unauthorized requests get 403

Run with:
    pytest remote-gateway/tests/test_admin_routes.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import admin_api  # noqa: E402
from admin_api import _DEFAULT_TOKEN, create_admin_app  # noqa: E402
from telemetry import TelemetryStore  # noqa: E402

TOKEN = _DEFAULT_TOKEN


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


@pytest.fixture()
def client(store):
    app = create_admin_app(store)
    return TestClient(app, raise_server_exceptions=True)


def test_spa_fallback_returns_503_when_dist_missing(tmp_path, store):
    """When admin-ui/dist/index.html does not exist, SPA catch-all returns 503."""
    # Point DIST at an empty directory so index.html is absent.
    with patch.object(admin_api, "DIST", tmp_path / "no-dist"):
        app = create_admin_app(store)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get(f"/dashboard?token={TOKEN}")
    assert resp.status_code == 503
    assert "admin-ui not built" in resp.text


def test_unauthorized_returns_403(client):
    """SPA catch-all without token must return 403."""
    resp = client.get("/dashboard")
    assert resp.status_code == 403
    assert "403" in resp.text or "Forbidden" in resp.text
