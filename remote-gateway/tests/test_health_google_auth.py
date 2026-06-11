"""health_check.google_auth — surface dead Google credentials as a visible signal.

A revoked refresh token should be a 2-minute re-consent (re-run
scripts/google_auth_setup.py, update one Railway var), not a mystery outage.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import meta  # noqa: E402


def _write_adc(tmp_path, type_="authorized_user"):
    p = tmp_path / "adc.json"
    p.write_text(json.dumps({
        "type": type_,
        "client_id": "cid",
        "client_secret": "csec",
        "refresh_token": "rtok",
        "quota_project_id": "proj",
    }))
    return p


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    assert meta.check_google_auth() == "not_configured"


def test_ok_when_refresh_succeeds(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(_write_adc(tmp_path)))
    monkeypatch.setattr(
        meta.httpx, "post",
        lambda url, data, timeout: _FakeResponse(200, {"access_token": "t"}),
    )
    assert meta.check_google_auth() == "ok"


def test_failing_when_refresh_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(_write_adc(tmp_path)))
    monkeypatch.setattr(
        meta.httpx, "post",
        lambda url, data, timeout: _FakeResponse(400, {"error": "invalid_grant"}),
    )
    assert meta.check_google_auth() == "failing: invalid_grant"


def test_service_account_reported_but_not_validated(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "GOOGLE_APPLICATION_CREDENTIALS", str(_write_adc(tmp_path, type_="service_account"))
    )
    assert meta.check_google_auth() == "configured (service_account key; not validated)"


def test_failing_when_file_unreadable(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "missing.json"))
    assert meta.check_google_auth().startswith("failing: credentials file unreadable")


def test_health_check_includes_google_auth(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    health = meta.make_health_check(lambda: "test-gateway")
    result = asyncio.run(health())
    assert result["status"] == "ok"
    assert result["server"] == "test-gateway"
    assert result["google_auth"] == "not_configured"


def test_failing_when_file_is_not_a_json_object(monkeypatch, tmp_path):
    p = tmp_path / "adc.json"
    p.write_text(json.dumps(["not", "a", "dict"]))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(p))
    assert meta.check_google_auth() == "failing: credentials file malformed (not a JSON object)"


def test_failing_when_token_endpoint_unreachable(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(_write_adc(tmp_path)))

    def raise_connect_error(url, data, timeout):
        raise meta.httpx.ConnectError("dns failure")

    monkeypatch.setattr(meta.httpx, "post", raise_connect_error)
    assert meta.check_google_auth().startswith("failing: token endpoint unreachable")


def test_failing_with_non_json_error_body(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(_write_adc(tmp_path)))

    class _NonJSONResponse:
        status_code = 503

        def json(self) -> dict:
            raise ValueError("not json")

    monkeypatch.setattr(meta.httpx, "post", lambda url, data, timeout: _NonJSONResponse())
    assert meta.check_google_auth() == "failing: 503"
