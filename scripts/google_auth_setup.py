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

import argparse
import json
import sys
import urllib.error
import urllib.request

GA_SCOPES: list[str] = ["https://www.googleapis.com/auth/analytics.readonly"]


def build_adc_json(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    quota_project_id: str,
) -> dict[str, str]:
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


_VALIDATE_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=1"


def validate_token(access_token: str, quota_project_id: str) -> tuple[bool, str]:
    """One cheap GA Admin API call so a bad consent fails at mint time, not deploy time."""
    req = urllib.request.Request(
        _VALIDATE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": quota_project_id,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        body = exc.fp.read().decode("utf-8", errors="replace")[:500]
        return False, f"HTTP {exc.code}: {body}"
    except urllib.error.URLError as exc:
        return False, f"network error: {exc.reason}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--client-secrets", required=True,
        help="Path to the OAuth client JSON downloaded from the client's GCP console",
    )
    parser.add_argument(
        "--quota-project", required=True,
        help="Client GCP project id where the GA APIs are enabled",
    )
    parser.add_argument(
        "--extra-scopes", nargs="*", default=[],
        help="Additional OAuth scopes beyond GA readonly (future integrations)",
    )
    args = parser.parse_args(argv)

    # Lazy import: resolved by `uv run` from the inline metadata; the module
    # stays importable under pytest without this dependency installed.
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = GA_SCOPES + list(args.extra_scopes)
    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, scopes=scopes)
    creds = flow.run_local_server(port=0)

    if not creds.refresh_token:
        print(
            "Consent returned no refresh token — cannot mint a durable credential. "
            "Remove the app's prior grant at https://myaccount.google.com/permissions "
            "and re-run to force a fresh consent.",
            file=sys.stderr,
        )
        return 1

    ok, detail = validate_token(creds.token, args.quota_project)
    if not ok:
        print(f"Credential validation FAILED — not printing env vars.\n{detail}", file=sys.stderr)
        print(
            "Check: APIs enabled in the quota project? Consent screen Internal? "
            "Consenting user has GA access?",
            file=sys.stderr,
        )
        return 1

    adc = build_adc_json(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        refresh_token=creds.refresh_token,
        quota_project_id=args.quota_project,
    )
    print(f"Credential validated against the GA Admin API ({detail}).\n")
    print("Set this Railway env var (replaces GOOGLE_SA_JSON):\n")
    print("GOOGLE_ADC_JSON:")
    print(json.dumps(adc))
    print(
        "\nworkspace-mcp keeps using GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET "
        "from the same OAuth app (unchanged mechanism)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
