# Google Per-Client Internal OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the service-account credential model for Google Analytics with per-client internal OAuth apps: a credential-minting helper script, a backward-compatible Dockerfile change, token-health surfacing in `health_check`, and onboarding docs.

**Architecture:** The gateway keeps proxying `analytics-mcp` and `workspace-mcp` unchanged. What changes is the credential: an `authorized_user` ADC JSON (minted by a new local helper script from a client-owned internal OAuth app) replaces the service-account key. The Dockerfile decodes `GOOGLE_ADC_JSON` (falling back to legacy `GOOGLE_SA_JSON`) to a file for `GOOGLE_APPLICATION_CREDENTIALS`. `health_check` gains a `google_auth` field that exercises the refresh token against Google's token endpoint so dead credentials are visible.

**Tech Stack:** Python ≥3.11, pytest, httpx (already a gateway dep), `google-auth-oauthlib` via PEP 723 inline metadata (`uv run` — never added to gateway deps), stdlib `urllib` for the helper's validation call.

**Spec:** `docs/superpowers/specs/2026-06-09-google-oauth-auth-design.md`

**Conventions that apply to every task:** ruff targets py314 with rules `E,F,I,N,UP,B,SIM`, 100-char lines. Run `ruff check .` before each commit. Tests for `scripts/` live next to the script (`scripts/test_*.py`, imported as `from scripts import ...`); tests for the gateway live in `remote-gateway/tests/`. Run pytest from the repo root.

---

### Task 1: Helper script — pure credential-assembly functions

**Files:**
- Create: `scripts/google_auth_setup.py`
- Test: `scripts/test_google_auth_setup.py`

The script must be importable WITHOUT `google-auth-oauthlib` installed (pytest imports it; the OAuth lib is only resolved by `uv run` at mint time). Top-level imports are stdlib only; the OAuth import happens inside `main()` in Task 2.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scripts/test_google_auth_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.google_auth_setup'` (or ImportError).

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/google_auth_setup.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest scripts/test_google_auth_setup.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check scripts/
git add scripts/google_auth_setup.py scripts/test_google_auth_setup.py
git commit -m "feat(scripts): ADC JSON assembly for google auth helper"
```

---

### Task 2: Helper script — validation call and CLI flow

**Files:**
- Modify: `scripts/google_auth_setup.py` (append; keep Task 1 content unchanged)
- Test: `scripts/test_google_auth_setup.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `scripts/test_google_auth_setup.py`)

```python
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
        return _FakeHTTPResponse()

    monkeypatch.setattr(gas.urllib.request, "urlopen", fake_urlopen)
    ok, detail = gas.validate_token("tok-123", "client-proj-123")
    assert ok is True
    assert "accountSummaries" in captured["url"]
    assert captured["auth"] == "Bearer tok-123"
    assert captured["quota"] == "client-proj-123"


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
```

Note: `urllib.request.Request.get_header()` title-cases header names — `X-goog-user-project` is the lookup key for a header set as `x-goog-user-project`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scripts/test_google_auth_setup.py -v`
Expected: the two new tests FAIL with `AttributeError: ... has no attribute 'urllib'` (or `validate_token` missing); Task 1 tests still PASS.

- [ ] **Step 3: Implement validation + CLI** (append to `scripts/google_auth_setup.py`; also add the stdlib imports below `from __future__ import annotations`)

```python
import argparse
import json
import sys
import urllib.error
import urllib.request

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
        body = exc.fp.read().decode("utf-8", errors="replace")[:500] if exc.fp else ""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest scripts/test_google_auth_setup.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Smoke-check the CLI surface without the OAuth dependency**

Run: `python -c "from scripts import google_auth_setup; print(google_auth_setup.GA_SCOPES)"`
Expected: prints the scope list, no ImportError (proves lazy import discipline).

Run: `uv run scripts/google_auth_setup.py --help`
Expected: argparse help text (uv resolves `google-auth-oauthlib` from inline metadata). If `uv` is unavailable in the execution environment, skip this command and note it — the migration task covers the real run.

- [ ] **Step 6: Lint and commit**

```bash
ruff check scripts/
git add scripts/google_auth_setup.py scripts/test_google_auth_setup.py
git commit -m "feat(scripts): google_auth_setup CLI — loopback OAuth flow with mint-time validation"
```

---

### Task 3: Dockerfile — `GOOGLE_ADC_JSON` with legacy fallback

**Files:**
- Modify: `Dockerfile:58` (the CMD line)
- Test: `remote-gateway/tests/test_dockerfile_credentials.py` (create)

- [ ] **Step 1: Write the failing test**

```python
"""Guard the Dockerfile credential-decoding contract.

The CMD must prefer GOOGLE_ADC_JSON (authorized_user ADC from the per-client
internal OAuth app) and fall back to the legacy GOOGLE_SA_JSON name so
already-deployed instances keep working. ADC autodetects the JSON type, so
both credential kinds work through the same file.
"""
from pathlib import Path

DOCKERFILE = Path(__file__).parent.parent.parent / "Dockerfile"


def test_cmd_prefers_adc_json_with_sa_fallback():
    assert "${GOOGLE_ADC_JSON:-$GOOGLE_SA_JSON}" in DOCKERFILE.read_text()


def test_cmd_exports_application_credentials_path():
    assert "GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-adc.json" in DOCKERFILE.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest remote-gateway/tests/test_dockerfile_credentials.py -v`
Expected: both FAIL (current CMD only knows `GOOGLE_SA_JSON` / `/tmp/google-sa.json`).

- [ ] **Step 3: Modify the Dockerfile CMD**

Replace line 58 of `Dockerfile`:

```dockerfile
CMD ["sh", "-c", "if [ -n \"$GOOGLE_SA_JSON\" ]; then printf '%s' \"$GOOGLE_SA_JSON\" > /tmp/google-sa.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-sa.json; fi && MCP_SERVER_PORT=${PORT:-8000} python3 remote-gateway/core/mcp_server.py"]
```

with:

```dockerfile
CMD ["sh", "-c", "GOOGLE_CREDS_JSON=\"${GOOGLE_ADC_JSON:-$GOOGLE_SA_JSON}\"; if [ -n \"$GOOGLE_CREDS_JSON\" ]; then printf '%s' \"$GOOGLE_CREDS_JSON\" > /tmp/google-adc.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-adc.json; fi && MCP_SERVER_PORT=${PORT:-8000} python3 remote-gateway/core/mcp_server.py"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest remote-gateway/tests/test_dockerfile_credentials.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Verify the shell logic stands alone**

Run: `GOOGLE_ADC_JSON='{"type":"authorized_user"}' sh -c 'GOOGLE_CREDS_JSON="${GOOGLE_ADC_JSON:-$GOOGLE_SA_JSON}"; printf "%s" "$GOOGLE_CREDS_JSON"'`
Expected output: `{"type":"authorized_user"}`

Run: `GOOGLE_SA_JSON='{"type":"service_account"}' sh -c 'GOOGLE_CREDS_JSON="${GOOGLE_ADC_JSON:-$GOOGLE_SA_JSON}"; printf "%s" "$GOOGLE_CREDS_JSON"'`
Expected output: `{"type":"service_account"}` (fallback works).

- [ ] **Step 6: Commit**

```bash
git add Dockerfile remote-gateway/tests/test_dockerfile_credentials.py
git commit -m "feat(dockerfile): GOOGLE_ADC_JSON credential env with GOOGLE_SA_JSON fallback"
```

---

### Task 4: `health_check` — `google_auth` token-health field

**Files:**
- Modify: `remote-gateway/tools/meta.py` (the header imports and `make_health_check`, currently lines 1–25)
- Test: `remote-gateway/tests/test_health_google_auth.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""health_check.google_auth — surface dead Google credentials as a visible signal.

A revoked refresh token should be a 2-minute re-consent (re-run
scripts/google_auth_setup.py, update one Railway var), not a mystery outage.
"""
from __future__ import annotations

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
    result = health()
    assert result["status"] == "ok"
    assert result["server"] == "test-gateway"
    assert result["google_auth"] == "not_configured"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_health_google_auth.py -v`
Expected: FAIL with `AttributeError: module 'tools.meta' has no attribute 'check_google_auth'`.

- [ ] **Step 3: Implement in `remote-gateway/tools/meta.py`**

Replace the module header and `make_health_check` (lines 1–25) with:

```python
"""
Gateway meta tools — health check and telemetry stats.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def check_google_auth() -> str:
    """Report Google credential health by exercising the refresh token.

    Returns one of:
      - "not_configured" — no GOOGLE_APPLICATION_CREDENTIALS env var
      - "ok" — authorized_user refresh token successfully exchanged
      - "configured (service_account key; not validated)" — legacy SA key present
      - "failing: <reason>" — unreadable file, rejected token, or network error
    """
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        return "not_configured"
    try:
        info = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return f"failing: credentials file unreadable ({exc})"
    if info.get("type") != "authorized_user":
        return "configured (service_account key; not validated)"
    try:
        resp = httpx.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": info.get("client_id", ""),
                "client_secret": info.get("client_secret", ""),
                "refresh_token": info.get("refresh_token", ""),
            },
            timeout=10,
        )
    except httpx.HTTPError as exc:
        return f"failing: token endpoint unreachable ({exc})"
    if resp.status_code == 200:
        return "ok"
    try:
        reason = resp.json().get("error", str(resp.status_code))
    except ValueError:
        reason = str(resp.status_code)
    return f"failing: {reason}"


def make_health_check(server_name_fn: Any) -> Callable[[], dict]:
    """Return a health_check tool function that reads server name at call time.

    Args:
        server_name_fn: Zero-arg callable returning the server's display name.
    """

    def health_check() -> dict:
        """Check that the Gateway MCP server is running and responsive.

        Also reports Google credential health when configured: 'google_auth' is
        "ok", "not_configured", or "failing: <reason>" — a failing value means
        the OAuth refresh token was revoked and needs a re-consent (run
        scripts/google_auth_setup.py and update GOOGLE_ADC_JSON).

        Returns:
            A dict with status, server name, and google_auth.
        """
        return {
            "status": "ok",
            "server": server_name_fn(),
            "google_auth": check_google_auth(),
        }

    return health_check
```

Everything below `make_get_tool_stats` in the file stays unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_health_google_auth.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Run the adjacent suites to catch regressions**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v` (imports `tools.meta`)
Expected: PASS (no signature changes).

- [ ] **Step 6: Lint and commit**

```bash
ruff check remote-gateway/tools/meta.py remote-gateway/tests/test_health_google_auth.py
git add remote-gateway/tools/meta.py remote-gateway/tests/test_health_google_auth.py
git commit -m "feat(meta): health_check reports google_auth token health"
```

---

### Task 5: `mcp_connections.json` — update the google-analytics comment

**Files:**
- Modify: `remote-gateway/mcp_connections.json:72` (the `_comment` key of the `google-analytics` entry)

No new test: the existing `remote-gateway/tests/test_google_analytics_config.py` pins everything load-bearing (transport, command, env interpolation, tool allowlist); the comment is documentation.

- [ ] **Step 1: Edit the comment**

Replace the `_comment` value of the `google-analytics` entry:

```json
"_comment": "Read-only GA4 data via official analytics-mcp. Auth: authorized_user ADC JSON minted from the client's internal OAuth app (scripts/google_auth_setup.py) — tokens carry the consenting user's own GA access, no service-account grants. Property ID is passed as a parameter on each tool call — document your property ID in the org profile so agents know which to use.",
```

- [ ] **Step 2: Verify config tests still pass**

Run: `pytest remote-gateway/tests/test_google_analytics_config.py -v`
Expected: 7 PASS.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/mcp_connections.json
git commit -m "docs(connections): describe OAuth ADC credential model on google-analytics entry"
```

---

### Task 6: Documentation — onboarding runbook and env-var tables

**Files:**
- Create: `docs/google-auth-onboarding.md`
- Modify: `remote-gateway/CLAUDE.md` (env var table — the `GOOGLE_SA_JSON` and `GOOGLE_APPLICATION_CREDENTIALS` rows)
- Modify: `CLAUDE.md` (root — the two `GOOGLE_SA_JSON` mentions in the docs commit trail are historical; only update if the root file references the env var, see step 2)

- [ ] **Step 1: Write `docs/google-auth-onboarding.md`**

```markdown
# Google Auth Onboarding (Per-Client Internal OAuth)

One internal OAuth app per client deployment is the single Google credential
story for the gateway (GA4 today; Workspace via the same app; Search Console /
Ads / BigQuery later). Design: `docs/superpowers/specs/2026-06-09-google-oauth-auth-design.md`.

Each MCP deployment serves exactly one Workspace org. The credential carries
the consenting user's own access — nobody is ever added to GA Admin, and no
Google verification is needed (the app is Internal to the client's org).

## One-time client setup (~20 min, drive it on the onboarding call)

1. **GCP project** — new or existing, inside the client's Google org.
   The client needs a free Google Cloud account tied to their Workspace.
2. **Enable APIs** (replace `<project>`):
   ```bash
   gcloud services enable analyticsdata.googleapis.com analyticsadmin.googleapis.com \
       gmail.googleapis.com calendar-json.googleapis.com drive.googleapis.com \
       docs.googleapis.com --project=<project>
   ```
3. **OAuth consent screen** — APIs & Services → OAuth consent screen → User type:
   **Internal**. (This is what removes verification, token expiry caps, and
   third-party app blocking.)
4. **OAuth client** — APIs & Services → Credentials → Create credentials →
   OAuth client ID → **Desktop app**. Download the JSON.

## Mint the deployment credential

On any machine with a browser, as the user whose Google access the gateway
should have (typically the operator):

```bash
uv run scripts/google_auth_setup.py \
    --client-secrets client_secret_<...>.json \
    --quota-project <project>
```

The script runs the consent flow, validates the credential against the GA
Admin API (fails loudly at mint time if an API is disabled or access is
missing), and prints:

- `GOOGLE_ADC_JSON` — set in Railway. The container writes it to
  `/tmp/google-adc.json` and exports `GOOGLE_APPLICATION_CREDENTIALS`.
- A reminder that `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`
  (workspace-mcp) come from the same OAuth app.

Then: document the client's GA4 property ID in the org profile
(`profile_update`) so agents know which property to pass on report calls.

## Verifying / monitoring

- `health_check` returns `google_auth: ok | not_configured | failing: <reason>`.
  It exercises the refresh token on every call.
- `failing: invalid_grant` means the token was revoked (password change on
  Gmail-scoped credentials, admin revocation, or ~6 months unused). Fix:
  re-run the mint step and update the one Railway var. No redeploy needed
  beyond Railway's automatic restart on env change.

## Legacy

Deployments still on a service-account key (`GOOGLE_SA_JSON`) keep working —
the Dockerfile falls back to that env var and ADC autodetects the JSON type.
Migrate them to `GOOGLE_ADC_JSON` opportunistically.
```

- [ ] **Step 2: Update env-var docs**

In `remote-gateway/CLAUDE.md`, replace the two rows:

```markdown
| `GOOGLE_SA_JSON` | GA | Raw service account JSON key content. Set this in Railway; the startup script writes it to `/tmp/google-sa.json` and exports `GOOGLE_APPLICATION_CREDENTIALS`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | GA (auto) | Set automatically by the startup script to `/tmp/google-sa.json` when `GOOGLE_SA_JSON` is present. Can also be set directly to a mounted file path. |
```

with:

```markdown
| `GOOGLE_ADC_JSON` | GA | authorized_user ADC JSON minted by `scripts/google_auth_setup.py` from the client's internal OAuth app. The startup script writes it to `/tmp/google-adc.json` and exports `GOOGLE_APPLICATION_CREDENTIALS`. See `docs/google-auth-onboarding.md`. |
| `GOOGLE_SA_JSON` | GA (legacy) | Legacy service-account key content. Still honored as a fallback when `GOOGLE_ADC_JSON` is unset; migrate to `GOOGLE_ADC_JSON`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | GA (auto) | Set automatically by the startup script to `/tmp/google-adc.json` when either env var above is present. Can also be set directly to a mounted file path. |
```

Check the root `CLAUDE.md` with `grep -n "GOOGLE_SA_JSON" CLAUDE.md` — if it has its own mention, apply the same GOOGLE_ADC_JSON-first framing there.

- [ ] **Step 3: Commit**

```bash
git add docs/google-auth-onboarding.md remote-gateway/CLAUDE.md CLAUDE.md
git commit -m "docs: google auth onboarding runbook and GOOGLE_ADC_JSON env docs"
```

---

### Task 7: Full-suite gate

- [ ] **Step 1: Run everything**

Run: `ruff check . && pytest`
Expected: clean lint; full suite PASS (Postgres-backed tests require local PostgreSQL via pytest-postgresql — if unavailable, run `pytest scripts/ remote-gateway/tests/test_google_analytics_config.py remote-gateway/tests/test_dockerfile_credentials.py remote-gateway/tests/test_health_google_auth.py` and note the constraint).

- [ ] **Step 2: Commit anything outstanding; do not push until migration validates**

---

### Task 8: Migration — dogfood deployment (operator + agent, not code)

These are operational steps; the code tasks above must be deployed to Railway first.

- [ ] **Step 1 (operator):** Confirm the existing workspace OAuth app's consent screen is **Internal** (GCP console of the project that owns `GOOGLE_OAUTH_CLIENT_ID`), and that `analyticsdata.googleapis.com` + `analyticsadmin.googleapis.com` are enabled in that project (this becomes `--quota-project`).
- [ ] **Step 2 (operator):** Download that OAuth client's JSON (or create a Desktop-type client in the same project) and run:
  `uv run scripts/google_auth_setup.py --client-secrets <file> --quota-project <project>`
- [ ] **Step 3 (operator):** In Railway: set `GOOGLE_ADC_JSON` to the printed JSON; delete `GOOGLE_SA_JSON`. Wait for redeploy.
- [ ] **Step 4 (agent, via gateway):** Smoke-test all seven `google-analytics__*` tools against property `443879695` — `get_account_summaries` should now list real accounts (the operator's access), `run_report` should return rows. Check `health_check` shows `google_auth: ok`.
- [ ] **Step 5 (agent, via gateway):** `profile_update` — add `ga4_property_id: 443879695` to the org profile.
- [ ] **Step 6 (operator/agent):** Cleanup: delete the `inform-gateway-ga4-reader` service account in `gen-lang-client-0075541127` (`gcloud iam service-accounts delete`), delete the key file `gen-lang-client-0075541127-c9661f3b6464.json` from the repo root, and close the loop on the open gateway task (`complete_task`).
- [ ] **Step 7 (agent):** Per the friction-to-test discipline, the regression tests added in Tasks 3–4 are the answer to "which test would have caught this": mint-time validation + `google_auth` health surfacing catch dead/misconfigured credentials before agents hit opaque 403s.

---

### Template sync note

The Dockerfile change, `scripts/google_auth_setup.py`, `tools/meta.py`, and `docs/google-auth-onboarding.md` are core files that must flow to the template via the normal distribute path (run from the template branch, not main — see the template-vs-dogfood split). `mcp_connections.json` stays consumer-owned. This is a follow-up after the dogfood migration validates, not part of this plan's tasks.
