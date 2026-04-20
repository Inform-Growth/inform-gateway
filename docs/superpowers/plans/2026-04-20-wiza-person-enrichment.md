# Wiza Person Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `wiza__enrich_person(linkedin_url)` MCP tool that starts a Wiza Individual Reveal, polls until complete, and returns email, phone, and LinkedIn profile data in a single blocking call.

**Architecture:** A new `remote-gateway/tools/wiza.py` module following the `attio.py` pattern — sync httpx calls, a `register(mcp)` function, and a field registry YAML. Registered in `mcp_server.py` alongside the other tool modules.

**Tech Stack:** Python ≥3.11, httpx (already in use), pytest + unittest.mock

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `remote-gateway/tools/wiza.py` | `_headers()`, `_start_reveal()`, `_poll_reveal()`, `wiza__enrich_person()`, `register()` |
| Create | `remote-gateway/context/fields/wiza.yaml` | Field registry schema for wiza tool response |
| Create | `remote-gateway/tests/test_wiza_tools.py` | Full test suite |
| Modify | `remote-gateway/core/mcp_server.py` | Import wiza module and call `register(mcp)` |

---

## Task 1: Field Registry YAML

**Files:**
- Create: `remote-gateway/context/fields/wiza.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
integration: wiza
source_url: https://docs.wiza.co/overview/data-dictionary
discovered_at: "2026-04-20"
last_drift_check: "2026-04-20"

fields:
  name:
    display_name: Full Name
    description: The person's full name as found on LinkedIn.
    type: string
    notes: ""
    nullable: true
  title:
    display_name: Job Title
    description: Current job title as listed on their LinkedIn profile.
    type: string
    notes: ""
    nullable: true
  linkedin_profile_url:
    display_name: LinkedIn Profile URL
    description: Canonical LinkedIn profile URL for this person.
    type: string
    notes: ""
    nullable: true
  email:
    display_name: Work Email
    description: Primary email address found for this person.
    type: string
    notes: ""
    nullable: true
  email_status:
    display_name: Email Status
    description: "Validity of the email address: valid, catch_all, invalid, or unknown."
    type: string
    notes: Only deduct credits when status is 'valid'.
    nullable: true
  mobile_phone:
    display_name: Mobile Phone
    description: Mobile phone number in E.164 format.
    type: string
    notes: 5 credits deducted if at least one phone number is found.
    nullable: true
  company_name:
    display_name: Company Name
    description: Name of the person's current employer.
    type: string
    notes: ""
    nullable: true
  credits_used:
    display_name: Credits Used
    description: Breakdown of credits deducted for this reveal. email=2 if valid email found, phone=5 if phone found, api=1 for LinkedIn match.
    type: string
    notes: Credits are only deducted on successful data retrieval.
    nullable: false
```

- [ ] **Step 2: Commit**

```bash
git add remote-gateway/context/fields/wiza.yaml
git commit -m "feat: add wiza field registry YAML"
```

---

## Task 2: Write Failing Tests

**Files:**
- Create: `remote-gateway/tests/test_wiza_tools.py`

- [ ] **Step 1: Write the test file**

```python
"""
Unit tests for tools/wiza.py — Wiza Individual Reveal person enrichment.

Run with:
    pytest remote-gateway/tests/test_wiza_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx response."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.text = str(json_data)
    m.is_success = status_code < 400

    def raise_for_status():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")

    m.raise_for_status = raise_for_status
    return m


def _mock_client(post_responses=None, get_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if post_responses is not None:
        mock.post.side_effect = post_responses
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# Canonical start and finished responses for reuse across tests
_START_RESPONSE = {"data": {"id": "rev-abc-123", "status": "queued", "is_complete": False}}

_FINISHED_RESPONSE = {
    "data": {
        "id": "rev-abc-123",
        "status": "finished",
        "is_complete": True,
        "name": "Jane Smith",
        "title": "VP of Engineering",
        "linkedin_profile_url": "https://www.linkedin.com/in/janesmith",
        "email": "jane@example.com",
        "email_status": "valid",
        "mobile_phone": "+14155551234",
        "company": "Acme Corp",
        "credits": {
            "email_credits": 2,
            "phone_credits": 5,
            "api_credits": {"total": 1, "email_credits": 0, "phone_credits": 0, "scrape_credits": 1},
        },
    }
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_enrich_person_returns_all_fields(monkeypatch):
    """wiza__enrich_person returns name, title, email, phone, linkedin, company, credits."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        result = wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert result["name"] == "Jane Smith"
    assert result["title"] == "VP of Engineering"
    assert result["email"] == "jane@example.com"
    assert result["email_status"] == "valid"
    assert result["mobile_phone"] == "+14155551234"
    assert result["linkedin_profile_url"] == "https://www.linkedin.com/in/janesmith"
    assert result["company_name"] == "Acme Corp"
    assert result["credits_used"]["email"] == 2
    assert result["credits_used"]["phone"] == 5
    assert result["credits_used"]["api"] == 1


def test_enrich_person_posts_correct_payload(monkeypatch):
    """wiza__enrich_person POSTs enrichment_level=full and the linkedin URL."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "individual_reveals" in posted_url
    assert posted_body["individual_reveal"]["profile_url"] == "https://www.linkedin.com/in/janesmith"
    assert posted_body["individual_reveal"]["enrichment_level"] == "full"


def test_enrich_person_sends_bearer_token(monkeypatch):
    """wiza__enrich_person sends WIZA_API_KEY as Bearer token on both POST and GET."""
    monkeypatch.setenv("WIZA_API_KEY", "my-secret-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    post_headers = mock_client.post.call_args.kwargs["headers"]
    get_headers = mock_client.get.call_args.kwargs["headers"]

    assert post_headers["Authorization"] == "Bearer my-secret-key"
    assert get_headers["Authorization"] == "Bearer my-secret-key"


def test_enrich_person_polls_correct_url(monkeypatch):
    """wiza__enrich_person GETs /individual_reveals/{id} using the ID from the POST response."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    polled_url = mock_client.get.call_args.args[0]
    assert "individual_reveals/rev-abc-123" in polled_url


def test_enrich_person_retries_while_resolving(monkeypatch):
    """wiza__enrich_person keeps polling through 'resolving' status until 'finished'."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    resolving = {"data": {"id": "rev-abc-123", "status": "resolving", "is_complete": False}}

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[
            _mock_response(resolving),
            _mock_response(resolving),
            _mock_response(_FINISHED_RESPONSE),
        ],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        result = wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert result["name"] == "Jane Smith"
    assert mock_client.get.call_count == 3


def test_enrich_person_omits_absent_fields(monkeypatch):
    """wiza__enrich_person omits fields not present in the Wiza response."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    sparse_finished = {
        "data": {
            "id": "rev-abc-123",
            "status": "finished",
            "is_complete": True,
            "name": "Jane Smith",
            "email": "jane@example.com",
            "email_status": "valid",
            # no title, mobile_phone, company, linkedin_profile_url
            "credits": {"email_credits": 2, "phone_credits": 0, "api_credits": None},
        }
    }

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(sparse_finished)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        result = wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert "title" not in result
    assert "mobile_phone" not in result
    assert "company_name" not in result
    assert "linkedin_profile_url" not in result
    assert result["name"] == "Jane Smith"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_enrich_person_raises_value_error_when_no_api_key(monkeypatch):
    """wiza__enrich_person raises ValueError if WIZA_API_KEY is not set."""
    monkeypatch.delenv("WIZA_API_KEY", raising=False)

    from tools.wiza import wiza__enrich_person
    with pytest.raises(ValueError, match="WIZA_API_KEY"):
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_permission_error_on_401(monkeypatch):
    """wiza__enrich_person raises PermissionError on 401 from Wiza."""
    monkeypatch.setenv("WIZA_API_KEY", "bad-key")

    mock_client = _mock_client(
        post_responses=[_mock_response({}, status_code=401)],
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(PermissionError, match="WIZA_API_KEY"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_runtime_error_on_400(monkeypatch):
    """wiza__enrich_person raises RuntimeError on 400 from Wiza."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response({"error": "invalid input"}, status_code=400)],
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(RuntimeError, match="bad request"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_runtime_error_on_429(monkeypatch):
    """wiza__enrich_person raises RuntimeError on 429 queue full from Wiza."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response({}, status_code=429)],
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(RuntimeError, match="queue full"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_runtime_error_on_failed_reveal(monkeypatch):
    """wiza__enrich_person raises RuntimeError when reveal status is 'failed'."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    failed = {"data": {"id": "rev-abc-123", "status": "failed", "is_complete": True}}

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(failed)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(RuntimeError, match="failed"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_timeout_error_after_max_polls(monkeypatch):
    """wiza__enrich_person raises TimeoutError if still queued after 10 polls."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    still_queued = {"data": {"id": "rev-abc-123", "status": "queued", "is_complete": False}}

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(still_queued)] * 10,
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(TimeoutError, match="rev-abc-123"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert mock_client.get.call_count == 10
```

- [ ] **Step 2: Run tests to confirm they all fail (module not found)**

```bash
cd remote-gateway && python -m pytest tests/test_wiza_tools.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'tools.wiza'`

- [ ] **Step 3: Commit failing tests**

```bash
git add remote-gateway/tests/test_wiza_tools.py
git commit -m "test: add failing tests for wiza__enrich_person"
```

---

## Task 3: Implement `wiza.py`

**Files:**
- Create: `remote-gateway/tools/wiza.py`

- [ ] **Step 1: Write the implementation**

```python
"""
Wiza Individual Reveal tool — person enrichment via LinkedIn URL.

Starts a Wiza reveal, polls until complete, and returns email, phone,
and LinkedIn profile data in a single blocking call.

Required env vars:
    WIZA_API_KEY — Wiza API key (Bearer token)
"""
from __future__ import annotations

import os
import time
from typing import Any

_WIZA_BASE = "https://wiza.co/api"
_POLL_INTERVAL_S = 3.0
_MAX_POLL_ATTEMPTS = 10


def _headers() -> dict[str, str]:
    """Return Wiza API request headers using WIZA_API_KEY from env."""
    api_key = os.environ.get("WIZA_API_KEY")
    if not api_key:
        raise ValueError("WIZA_API_KEY environment variable is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _start_reveal(linkedin_url: str) -> str:
    """POST to start a Wiza Individual Reveal. Returns the reveal ID.

    Args:
        linkedin_url: LinkedIn profile URL to enrich.

    Returns:
        Reveal ID string from the Wiza response.

    Raises:
        RuntimeError: On 400 bad request.
        PermissionError: On 401 invalid API key.
        RuntimeError: On 429 queue full.
    """
    import httpx

    with httpx.Client() as client:
        resp = client.post(
            f"{_WIZA_BASE}/individual_reveals",
            headers=_headers(),
            json={
                "individual_reveal": {
                    "profile_url": linkedin_url,
                    "enrichment_level": "full",
                }
            },
        )

    if resp.status_code == 400:
        raise RuntimeError(f"Wiza bad request: {resp.text}")
    if resp.status_code == 401:
        raise PermissionError("WIZA_API_KEY is invalid or disabled")
    if resp.status_code == 429:
        raise RuntimeError("Wiza queue full — try again later")
    resp.raise_for_status()

    return resp.json()["data"]["id"]


def _poll_reveal(reveal_id: str) -> dict[str, Any]:
    """Poll GET /individual_reveals/{id} until finished or failed.

    Polls every 3 seconds up to 10 attempts (30s total).

    Args:
        reveal_id: Reveal ID returned by _start_reveal.

    Returns:
        The finished reveal data dict.

    Raises:
        RuntimeError: If the reveal status is 'failed'.
        TimeoutError: If the reveal does not complete within 30s.
    """
    import httpx

    for _ in range(_MAX_POLL_ATTEMPTS):
        with httpx.Client() as client:
            resp = client.get(
                f"{_WIZA_BASE}/individual_reveals/{reveal_id}",
                headers=_headers(),
            )
        resp.raise_for_status()

        payload = resp.json().get("data", {})
        status = payload.get("status")

        if status == "finished":
            return payload
        if status == "failed":
            raise RuntimeError(f"Wiza reveal {reveal_id} failed")

        time.sleep(_POLL_INTERVAL_S)

    raise TimeoutError(
        f"Wiza reveal {reveal_id} did not complete within "
        f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_S:.0f}s"
    )


def wiza__enrich_person(linkedin_url: str) -> dict[str, Any]:
    """Enrich a person by LinkedIn URL using Wiza.

    Starts a Wiza Individual Reveal for the given LinkedIn profile URL,
    polls until enrichment is complete (up to 30s), and returns the person's
    email, mobile phone, and LinkedIn profile data.

    Uses enrichment_level 'full'. Credits are only deducted when data is found:
    2 credits for a valid email, 5 for a phone number, 1 for a LinkedIn match.

    Args:
        linkedin_url: The person's LinkedIn profile URL
            (e.g. https://www.linkedin.com/in/username).

    Returns:
        Dict with any of: name, title, linkedin_profile_url, email,
        email_status, mobile_phone, company_name, credits_used.
        Fields absent from the Wiza response are omitted.

    Raises:
        ValueError: If WIZA_API_KEY is not set.
        PermissionError: If the API key is invalid or disabled.
        RuntimeError: On 400/429 from Wiza, or if the reveal fails.
        TimeoutError: If enrichment does not complete within 30s.
    """
    reveal_id = _start_reveal(linkedin_url)
    payload = _poll_reveal(reveal_id)

    result: dict[str, Any] = {}

    for field in ("name", "title", "linkedin_profile_url", "email", "email_status", "mobile_phone"):
        val = payload.get(field)
        if val is not None:
            result[field] = val

    company = payload.get("company")
    if company:
        result["company_name"] = company

    credits_raw = payload.get("credits") or {}
    api_credits_raw = credits_raw.get("api_credits") or {}
    result["credits_used"] = {
        "email": credits_raw.get("email_credits", 0),
        "phone": credits_raw.get("phone_credits", 0),
        "api": api_credits_raw.get("total", 0) if isinstance(api_credits_raw, dict) else 0,
    }

    return result


def register(mcp: Any) -> None:
    """Register Wiza tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(wiza__enrich_person)
```

- [ ] **Step 2: Run the tests**

```bash
cd remote-gateway && python -m pytest tests/test_wiza_tools.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tools/wiza.py
git commit -m "feat: add wiza__enrich_person tool with polling"
```

---

## Task 4: Register in `mcp_server.py`

**Files:**
- Modify: `remote-gateway/core/mcp_server.py:533-543`

- [ ] **Step 1: Add import and registration**

In `mcp_server.py`, the imports block at line 533 looks like:

```python
from tools import attio as _attio_tools  # noqa: E402
from tools import email_tools as _email_tools  # noqa: E402
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
_attio_tools.register(mcp)  # must register after telemetry patch is applied
_email_tools.register(mcp)
```

Add the wiza import and registration:

```python
from tools import attio as _attio_tools  # noqa: E402
from tools import email_tools as _email_tools  # noqa: E402
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402
from tools import wiza as _wiza_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
_attio_tools.register(mcp)  # must register after telemetry patch is applied
_email_tools.register(mcp)
_wiza_tools.register(mcp)
```

- [ ] **Step 2: Run the full test suite to check for regressions**

```bash
cd remote-gateway && python -m pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 3: Smoke-test the import**

```bash
cd remote-gateway && python -c "from tools.wiza import wiza__enrich_person; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat: register wiza__enrich_person on the MCP server"
```

---

## Self-Review

**Spec coverage:**
- [x] `wiza__enrich_person(linkedin_url)` — Task 3
- [x] `enrichment_level: "full"` hardcoded — Task 3 `_start_reveal`
- [x] Polling: 3s interval, 10 attempts, 30s total — Task 3 `_poll_reveal`
- [x] Auth via `WIZA_API_KEY` env var — Task 3 `_headers()`
- [x] 400 → RuntimeError — Task 3 + tested in Task 2
- [x] 401 → PermissionError — Task 3 + tested in Task 2
- [x] 429 → RuntimeError("queue full") — Task 3 + tested in Task 2
- [x] reveal `"failed"` → RuntimeError — Task 3 + tested in Task 2
- [x] Timeout after 10 polls → TimeoutError with reveal ID — Task 3 + tested in Task 2
- [x] Absent fields omitted — Task 3 + tested in Task 2
- [x] Field registry YAML — Task 1
- [x] Registration in `mcp_server.py` — Task 4

**Placeholder scan:** No TBDs, no "similar to Task N" references, all code blocks are complete.

**Type consistency:** `wiza__enrich_person` returns `dict[str, Any]` throughout. `_start_reveal` returns `str`. `_poll_reveal` returns `dict[str, Any]`. `register(mcp: Any)` matches `attio.py` pattern exactly.
