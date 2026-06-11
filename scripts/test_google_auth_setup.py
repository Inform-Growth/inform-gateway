"""Tests for scripts/google_auth_setup.py.

Covers the pure helpers (ADC JSON assembly, token validation HTTP handling).
The interactive OAuth flow in main() is exercised manually at migration time.
"""
from __future__ import annotations

from scripts import google_auth_setup as gas


def test_build_adc_json_shape():
    adc = gas.build_adc_json(
        client_id="cid.apps.googleusercontent.com",
        client_secret="csec",
        refresh_token="rtok",
        quota_project_id="client-proj-123",
    )
    assert adc == {
        "type": "authorized_user",
        "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "csec",
        "refresh_token": "rtok",
        "quota_project_id": "client-proj-123",
    }


def test_default_scopes_are_ga_readonly_only():
    # The ADC credential is consumed only by analytics-mcp today; workspace-mcp
    # runs its own consent flow. Broader scopes here would widen blast radius.
    assert gas.GA_SCOPES == ["https://www.googleapis.com/auth/analytics.readonly"]


class _FakeHTTPResponse:
    status = 200

    def read(self) -> bytes:
        return b'{"accountSummaries": []}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_validate_token_success(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["quota"] = req.get_header("X-goog-user-project")
        captured["timeout"] = timeout
        return _FakeHTTPResponse()

    monkeypatch.setattr(gas.urllib.request, "urlopen", fake_urlopen)
    ok, detail = gas.validate_token("tok-123", "client-proj-123")
    assert ok is True
    assert "accountSummaries" in captured["url"]
    assert captured["auth"] == "Bearer tok-123"
    assert captured["quota"] == "client-proj-123"
    assert captured["timeout"] == 30


def test_validate_token_failure_includes_body(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", hdrs=None,
            fp=io.BytesIO(b'{"error": {"status": "PERMISSION_DENIED"}}'),
        )

    monkeypatch.setattr(gas.urllib.request, "urlopen", fake_urlopen)
    ok, detail = gas.validate_token("tok-123", "client-proj-123")
    assert ok is False
    assert "403" in detail
    assert "PERMISSION_DENIED" in detail


def test_validate_token_network_error(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=0):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(gas.urllib.request, "urlopen", fake_urlopen)
    ok, detail = gas.validate_token("tok-123", "client-proj-123")
    assert ok is False
    assert "network error" in detail
    assert "Name or service not known" in detail
