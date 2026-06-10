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
