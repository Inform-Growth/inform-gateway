"""Mint Google OAuth credentials for a gateway deployment.

Runs the installed-app (loopback) OAuth flow against a client-owned INTERNAL
OAuth app, validates the credential against the GA Admin API, and prints the
GOOGLE_ADC_JSON env var value for Railway.

Run with uv so dependencies resolve from the inline metadata below (nothing
is added to the gateway's own dependencies):

    uv run scripts/google_auth_setup.py \
        --client-secrets client_secret.json \
        --quota-project <client-gcp-project-id>

Prerequisites (per client, one time — see docs/google-auth-onboarding.md):
  1. GCP project in the client's Google org
  2. APIs enabled: analyticsdata, analyticsadmin (+ Workspace APIs as needed)
  3. OAuth consent screen set to INTERNAL
  4. OAuth client (Desktop type) created; its JSON downloaded
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-auth-oauthlib>=1.2"]
# ///
from __future__ import annotations

GA_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def build_adc_json(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    quota_project_id: str,
) -> dict:
    """Assemble an authorized_user ADC JSON.

    ADC autodetects the credential type from the "type" key, so this file is a
    drop-in replacement for a service-account key at GOOGLE_APPLICATION_CREDENTIALS.
    quota_project_id is required for the GA APIs with authorized_user credentials;
    it must be a project where those APIs are enabled and the consenting user has
    serviceusage.services.use (any project owner/editor in the client org does).
    """
    return {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "quota_project_id": quota_project_id,
    }
