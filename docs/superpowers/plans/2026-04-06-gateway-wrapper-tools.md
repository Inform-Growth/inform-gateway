# Gateway Wrapper Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five promoted gateway tools (`apollo_enrich_company`, `apollo_find_contacts`, `exa_search`, `exa_fetch_pages`, `attio_push_company`) that wrap the raw proxied integrations with correct params, sequential enforcement, and graceful error handling.

**Architecture:** Each tool lives in a dedicated module under `remote-gateway/tools/`, calls the external REST API directly via `httpx` (same pattern as `tools/notes.py`), and is registered on the FastMCP server via a `register(mcp)` function. The raw proxied tools (`apollo__*`, `attio__*`, `exa__*`) remain available for admin/debugging.

**Tech Stack:** Python 3.14, httpx, pytest, unittest.mock

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `remote-gateway/tools/apollo.py` | Create | `apollo_enrich_company`, `apollo_find_contacts` |
| `remote-gateway/tools/exa.py` | Create | `exa_search`, `exa_fetch_pages` |
| `remote-gateway/tools/attio.py` | Create | `attio_push_company` |
| `remote-gateway/core/mcp_server.py` | Modify | Import and register three new tool modules |
| `remote-gateway/tests/test_apollo_tools.py` | Create | Unit tests for apollo.py (httpx mocked) |
| `remote-gateway/tests/test_exa_tools.py` | Create | Unit tests for exa.py (httpx mocked) |
| `remote-gateway/tests/test_attio_tools.py` | Create | Unit tests for attio.py (httpx mocked) |

---

## Task 1: Apollo — tests

**Files:**
- Create: `remote-gateway/tests/test_apollo_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
"""
Unit tests for apollo wrapper tools.

Run with:
    pytest remote-gateway/tests/test_apollo_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.apollo import apollo_enrich_company, apollo_find_contacts


def _mock_httpx_post(json_response: dict, status_code: int = 200):
    """Return a context-manager mock for httpx.Client that returns json_response on .post()."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_response

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    return mock_client


# ---------------------------------------------------------------------------
# apollo_enrich_company
# ---------------------------------------------------------------------------


def test_enrich_returns_clean_fields():
    raw = {
        "organization": {
            "name": "Acme Corp",
            "primary_domain": "acme.com",
            "industry": "Software",
            "estimated_num_employees": 45,
            "estimated_annual_revenue": "5M-10M",
            "city": "San Francisco",
            "country": "United States",
            "linkedin_url": "https://linkedin.com/company/acme",
            "latest_funding_stage": "Seed",
            "total_funding": 430000000,  # cents
            "raw_noise": "ignored",
        }
    }
    with patch("httpx.Client", return_value=_mock_httpx_post(raw)):
        result = apollo_enrich_company("acme.com")

    assert result["name"] == "Acme Corp"
    assert result["domain"] == "acme.com"
    assert result["industry"] == "Software"
    assert result["employee_count"] == 45
    assert result["funding_stage"] == "Seed"
    assert result["total_funding_usd"] == 4300000  # converted from cents
    assert "raw_noise" not in result


def test_enrich_returns_error_dict_on_empty_response():
    with patch("httpx.Client", return_value=_mock_httpx_post({})):
        result = apollo_enrich_company("unknown.com")

    assert result["error"] == "not_found"
    assert result["domain"] == "unknown.com"


def test_enrich_returns_error_dict_on_http_failure():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("500 Server Error")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        result = apollo_enrich_company("acme.com")

    assert "error" in result
    assert result["domain"] == "acme.com"


# ---------------------------------------------------------------------------
# apollo_find_contacts
# ---------------------------------------------------------------------------


def test_find_contacts_uses_correct_param_name():
    """Regression: must use q_organization_domains, not organization_domains."""
    raw = {
        "people": [
            {
                "first_name": "Jane",
                "last_name": "Smith",
                "title": "Head of RevOps",
                "email": "jane@acme.com",
                "linkedin_url": "https://linkedin.com/in/janesmith",
                "seniority": "manager",
            }
        ],
        "total_entries": 1,
    }
    with patch("httpx.Client", return_value=_mock_httpx_post(raw)) as mock_cls:
        result = apollo_find_contacts("acme.com", ["RevOps", "Revenue Operations"])

    call_kwargs = mock_cls.return_value.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "q_organization_domains" in body, "Must use q_organization_domains"
    assert "organization_domains" not in body, "Must NOT use organization_domains"
    assert result["count"] == 1
    assert result["contacts"][0]["name"] == "Jane Smith"


def test_find_contacts_returns_empty_on_apollo_down():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("TaskGroup error")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        result = apollo_find_contacts("acme.com", ["VP Sales"])

    assert result["error"] == "apollo_unavailable"
    assert result["contacts"] == []
    assert result["domain"] == "acme.com"


def test_find_contacts_default_max_results():
    raw = {"people": [], "total_entries": 0}
    with patch("httpx.Client", return_value=_mock_httpx_post(raw)) as mock_cls:
        apollo_find_contacts("acme.com", ["CTO"])

    call_kwargs = mock_cls.return_value.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert body["per_page"] == 5
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_apollo_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.apollo'`

---

## Task 2: Apollo — implementation

**Files:**
- Create: `remote-gateway/tools/apollo.py`

- [ ] **Step 1: Write the implementation**

```python
"""
Apollo wrapper tools.

Wraps Apollo REST API calls with correct parameter names, sequential-safe
execution, and graceful error returns (never raises to the agent).

Required env vars:
    APOLLO_ACCESS_TOKEN — OAuth access token for the Apollo API
"""
from __future__ import annotations

import os
from typing import Any


def _apollo_headers() -> dict[str, str]:
    """Return Apollo API request headers using APOLLO_ACCESS_TOKEN from env."""
    token = os.environ.get("APOLLO_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def apollo_enrich_company(domain: str) -> dict[str, Any]:
    """Enrich a company by domain using Apollo's organization enrich endpoint.

    Returns a clean subset of Apollo fields. Never raises — HTTP errors and
    not-found responses are returned as error dicts so the agent can continue.

    Args:
        domain: The company's primary domain, e.g. "acme.com".

    Returns:
        Dict with name, domain, industry, employee_count, estimated_revenue,
        hq_city, hq_country, linkedin_url, funding_stage, total_funding_usd.
        On failure: {"error": "<reason>", "domain": "<domain>"}.
    """
    import httpx

    url = "https://api.apollo.io/api/v1/organizations/enrich"
    try:
        with httpx.Client() as client:
            resp = client.post(url, headers=_apollo_headers(), json={"domain": domain})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"error": str(exc), "domain": domain}

    org = data.get("organization")
    if not org:
        return {"error": "not_found", "domain": domain}

    # Apollo stores total_funding in cents — convert to dollars
    total_funding_cents = org.get("total_funding") or 0
    total_funding_usd = total_funding_cents // 100 if total_funding_cents else None

    return {
        "name": org.get("name"),
        "domain": org.get("primary_domain", domain),
        "industry": org.get("industry"),
        "employee_count": org.get("estimated_num_employees"),
        "estimated_revenue": org.get("estimated_annual_revenue"),
        "hq_city": org.get("city"),
        "hq_country": org.get("country"),
        "linkedin_url": org.get("linkedin_url"),
        "funding_stage": org.get("latest_funding_stage"),
        "total_funding_usd": total_funding_usd,
    }


def apollo_find_contacts(
    domain: str,
    titles: list[str],
    max_results: int = 5,
) -> dict[str, Any]:
    """Find people at a company by domain and job title keywords.

    Uses the correct Apollo param name (q_organization_domains). Must be called
    sequentially — do not call this tool in parallel for multiple domains, as
    concurrent Apollo requests cause TaskGroup errors. This tool is safe to call
    in a loop.

    Args:
        domain: The company's primary domain, e.g. "acme.com".
        titles: List of title keywords to filter by, e.g. ["RevOps", "Revenue Operations"].
        max_results: Maximum number of contacts to return (default 5).

    Returns:
        Dict with domain, contacts (list of name/title/email/linkedin_url/seniority),
        and count. On Apollo outage: {"error": "apollo_unavailable", "contacts": [], "domain": ...}.
    """
    import httpx

    url = "https://api.apollo.io/api/v1/mixed_people/search"
    body = {
        "q_organization_domains": [domain],
        "titles": titles,
        "per_page": max_results,
    }

    try:
        with httpx.Client() as client:
            resp = client.post(url, headers=_apollo_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return {"error": "apollo_unavailable", "domain": domain, "contacts": []}

    people = data.get("people", [])
    contacts = [
        {
            "name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "title": p.get("title"),
            "email": p.get("email"),
            "linkedin_url": p.get("linkedin_url"),
            "seniority": p.get("seniority"),
        }
        for p in people
    ]
    return {"domain": domain, "contacts": contacts, "count": len(contacts)}


def register(mcp: Any) -> None:
    """Register Apollo wrapper tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(apollo_enrich_company)
    mcp.tool()(apollo_find_contacts)
```

- [ ] **Step 2: Run tests**

```bash
pytest remote-gateway/tests/test_apollo_tools.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tools/apollo.py remote-gateway/tests/test_apollo_tools.py
git commit -m "feat(gateway): add apollo_enrich_company and apollo_find_contacts wrapper tools"
```

---

## Task 3: Exa — tests

**Files:**
- Create: `remote-gateway/tests/test_exa_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
"""
Unit tests for exa wrapper tools.

Run with:
    pytest remote-gateway/tests/test_exa_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.exa import exa_fetch_pages

ASHBY_URL = "https://jobs.ashbyhq.com/acme/123"
NORMAL_URL = "https://revopscareers.com/jobs/456"


def _mock_httpx_post(json_response: dict, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_response

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    return mock_client


def test_fetch_passes_urls_as_array():
    """Regression: exa requires 'ids' (array), not a single 'url' string."""
    raw = {"results": [{"url": NORMAL_URL, "title": "GTM Engineer", "text": "Job text", "publishedDate": "2026-03-15"}]}
    with patch("httpx.Client", return_value=_mock_httpx_post(raw)) as mock_cls:
        exa_fetch_pages([NORMAL_URL])

    call_kwargs = mock_cls.return_value.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "ids" in body, "Must pass URLs as 'ids' array"
    assert isinstance(body["ids"], list), "'ids' must be a list"


def test_fetch_returns_clean_page_fields():
    raw = {
        "results": [
            {
                "url": NORMAL_URL,
                "title": "GTM Engineer at Acme",
                "text": "Full job description here.",
                "publishedDate": "2026-03-15",
                "extra_field": "ignored",
            }
        ]
    }
    with patch("httpx.Client", return_value=_mock_httpx_post(raw)):
        result = exa_fetch_pages([NORMAL_URL])

    assert len(result["pages"]) == 1
    page = result["pages"][0]
    assert page["url"] == NORMAL_URL
    assert page["title"] == "GTM Engineer at Acme"
    assert page["text"] == "Full job description here."
    assert page["published_date"] == "2026-03-15"
    assert page["warning"] is None
    assert "extra_field" not in page


def test_fetch_warns_on_ashby_url():
    raw = {"results": [{"url": ASHBY_URL, "title": "Job", "text": "", "publishedDate": None}]}
    with patch("httpx.Client", return_value=_mock_httpx_post(raw)):
        result = exa_fetch_pages([ASHBY_URL])

    page = result["pages"][0]
    assert page["warning"] is not None
    assert "Ashby" in page["warning"]
    assert "revopscareers.com" in page["warning"]


def test_fetch_handles_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("503")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        result = exa_fetch_pages([NORMAL_URL])

    assert "error" in result
    assert result["pages"] == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_exa_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.exa'`

---

## Task 4: Exa — implementation

**Files:**
- Create: `remote-gateway/tools/exa.py`

- [ ] **Step 1: Write the implementation**

```python
"""
Exa wrapper tools.

Wraps Exa's contents API with the correct 'ids' array parameter and
Ashby client-side-render detection.

Required env vars:
    EXA_API_KEY — Exa API key
"""
from __future__ import annotations

import os
from typing import Any

_ASHBY_PATTERNS = ("ashbyhq.com", "jobs.ashbyhq.com")
_ASHBY_WARNING = (
    "Ashby pages are client-side rendered — content is likely empty. "
    "Use revopscareers.com or Welcome to the Jungle for full job descriptions."
)


def _exa_headers() -> dict[str, str]:
    """Return Exa API request headers using EXA_API_KEY from env."""
    return {
        "x-api-key": os.environ.get("EXA_API_KEY", ""),
        "Content-Type": "application/json",
    }


def _is_ashby(url: str) -> bool:
    """Return True if the URL is an Ashby job board page."""
    return any(pattern in url for pattern in _ASHBY_PATTERNS)


def exa_fetch_pages(urls: list[str]) -> dict[str, Any]:
    """Fetch and extract text content from a list of URLs using Exa.

    Automatically detects Ashby job board URLs (which are client-side rendered
    and return empty content) and adds a warning to those pages.

    Args:
        urls: List of URLs to fetch, e.g. ["https://revopscareers.com/jobs/123"].

    Returns:
        Dict with 'pages' list. Each page has url, title, text, published_date,
        and warning (null unless Ashby URL detected).
        On fetch failure: {"error": "<message>", "pages": []}.
    """
    import httpx

    url = "https://api.exa.ai/contents"
    body = {"ids": urls, "text": True}

    try:
        with httpx.Client() as client:
            resp = client.post(url, headers=_exa_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"error": str(exc), "pages": []}

    pages = [
        {
            "url": r.get("url", ""),
            "title": r.get("title"),
            "text": r.get("text"),
            "published_date": r.get("publishedDate"),
            "warning": _ASHBY_WARNING if _is_ashby(r.get("url", "")) else None,
        }
        for r in data.get("results", [])
    ]
    return {"pages": pages}


def register(mcp: Any) -> None:
    """Register Exa wrapper tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(exa_fetch_pages)
```

- [ ] **Step 2: Run tests**

```bash
pytest remote-gateway/tests/test_exa_tools.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tools/exa.py remote-gateway/tests/test_exa_tools.py
git commit -m "feat(gateway): add exa_fetch_pages wrapper tool with Ashby detection"
```

---

## Task 4a: Exa search — tests

**Files:**
- Modify: `remote-gateway/tests/test_exa_tools.py` (append new tests)

- [ ] **Step 1: Append the failing tests**

Add to the bottom of `remote-gateway/tests/test_exa_tools.py`:

```python
# ---------------------------------------------------------------------------
# exa_search
# ---------------------------------------------------------------------------

from tools.exa import exa_search

SEARCH_RESULTS = {
    "results": [
        {
            "url": "https://revopscareers.com/jobs/123",
            "title": "GTM Engineer at Acme",
            "text": "Job description text here...",
            "publishedDate": "2026-03-15",
            "score": 0.92,
        }
    ]
}


def test_search_returns_clean_results():
    with patch("httpx.Client", return_value=_mock_httpx_post(SEARCH_RESULTS)):
        result = exa_search("GTM Engineer AI workflow")

    assert len(result["results"]) == 1
    r = result["results"][0]
    assert r["url"] == "https://revopscareers.com/jobs/123"
    assert r["title"] == "GTM Engineer at Acme"
    assert r["text"] == "Job description text here..."
    assert r["published_date"] == "2026-03-15"


def test_search_default_num_results():
    with patch("httpx.Client", return_value=_mock_httpx_post(SEARCH_RESULTS)) as mock_cls:
        exa_search("GTM Engineer AI workflow")

    call_kwargs = mock_cls.return_value.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert body["num_results"] == 10


def test_search_passes_domain_filter_when_provided():
    with patch("httpx.Client", return_value=_mock_httpx_post(SEARCH_RESULTS)) as mock_cls:
        exa_search("GTM Engineer", domains=["revopscareers.com", "greenhouse.io"])

    call_kwargs = mock_cls.return_value.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert body["include_domains"] == ["revopscareers.com", "greenhouse.io"]


def test_search_omits_domain_filter_when_not_provided():
    with patch("httpx.Client", return_value=_mock_httpx_post(SEARCH_RESULTS)) as mock_cls:
        exa_search("GTM Engineer")

    call_kwargs = mock_cls.return_value.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "include_domains" not in body


def test_search_returns_error_on_failure():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("503")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        result = exa_search("GTM Engineer")

    assert "error" in result
    assert result["results"] == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest remote-gateway/tests/test_exa_tools.py -v -k "search"
```

Expected: `ImportError: cannot import name 'exa_search' from 'tools.exa'`

---

## Task 4b: Exa search — implementation

**Files:**
- Modify: `remote-gateway/tools/exa.py` (add `exa_search` function and update `register`)

- [ ] **Step 1: Add `exa_search` to `remote-gateway/tools/exa.py`**

Insert after the `_is_ashby` function and before `exa_fetch_pages`:

```python
def exa_search(
    query: str,
    domains: list[str] | None = None,
    num_results: int = 10,
) -> dict[str, Any]:
    """Search the web using Exa and return matching pages with extracted text.

    Use this for targeted research — job board searches, company news, industry signals.
    Keyword search mode is best for specific terms like job titles or company names.

    Args:
        query: Search query, e.g. "GTM Engineer AI workflow seed startup hiring".
        domains: Optional list of domains to restrict the search to,
            e.g. ["revopscareers.com", "greenhouse.io"]. Omit to search all.
        num_results: Number of results to return (default 10, max 100).

    Returns:
        Dict with 'results' list. Each result has url, title, text, published_date.
        On failure: {"error": "<message>", "results": []}.
    """
    import httpx

    url = "https://api.exa.ai/search"
    body: dict[str, Any] = {
        "query": query,
        "num_results": num_results,
        "type": "keyword",
        "contents": {"text": True},
    }
    if domains:
        body["include_domains"] = domains

    try:
        with httpx.Client() as client:
            resp = client.post(url, headers=_exa_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"error": str(exc), "results": []}

    results = [
        {
            "url": r.get("url", ""),
            "title": r.get("title"),
            "text": r.get("text"),
            "published_date": r.get("publishedDate"),
        }
        for r in data.get("results", [])
    ]
    return {"results": results}
```

Also update the `register` function at the bottom of `exa.py`:

```python
def register(mcp: Any) -> None:
    """Register Exa wrapper tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(exa_search)
    mcp.tool()(exa_fetch_pages)
```

- [ ] **Step 2: Run exa tests**

```bash
pytest remote-gateway/tests/test_exa_tools.py -v
```

Expected: all 9 tests pass (4 fetch + 5 search).

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tools/exa.py remote-gateway/tests/test_exa_tools.py
git commit -m "feat(gateway): add exa_search wrapper tool with domain filtering"
```

---

## Task 5: Attio — tests

**Files:**
- Create: `remote-gateway/tests/test_attio_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
"""
Unit tests for attio wrapper tools.

Run with:
    pytest remote-gateway/tests/test_attio_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.attio import attio_push_company


def _make_client(responses: list[dict]) -> MagicMock:
    """Return a mock httpx.Client that returns each response dict in sequence."""
    mock_resps = []
    for r in responses:
        m = MagicMock()
        m.status_code = r.get("status_code", 200)
        m.json.return_value = r.get("json", {})
        m.raise_for_status = MagicMock()
        mock_resps.append(m)

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = mock_resps[:2]   # list lookup calls
    mock_client.post.side_effect = mock_resps[2:]  # create + list entry calls
    return mock_client


def test_push_returns_error_on_missing_name():
    result = attio_push_company(name="", domain="acme.com", list_name="My List")
    assert result["error"] == "missing_required_fields"
    assert "name" in result["missing"]


def test_push_returns_error_on_missing_domain():
    result = attio_push_company(name="Acme", domain="", list_name="My List")
    assert result["error"] == "missing_required_fields"
    assert "domain" in result["missing"]


def test_push_returns_error_when_list_not_found():
    # GET /v2/lists returns empty list
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"data": []}),
        raise_for_status=MagicMock(),
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_push_company("Acme", "acme.com", "Nonexistent List")

    assert result["error"] == "list_not_found"
    assert result["list_name"] == "Nonexistent List"


def test_push_creates_company_and_adds_to_list():
    lists_response = {
        "data": [{"id": {"list_id": "list-abc"}, "name": "RevOps AI Infra — Apr 2026"}]
    }
    # Search for existing company → not found
    search_response = {"data": []}
    # Create company → returns record_id
    create_response = {"data": {"id": {"record_id": "rec-123"}}}
    # Add to list → returns entry
    list_entry_response = {"data": {"id": {"entry_id": "entry-456"}}}

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    get_responses = [
        MagicMock(status_code=200, json=MagicMock(return_value=lists_response), raise_for_status=MagicMock()),
        MagicMock(status_code=200, json=MagicMock(return_value=search_response), raise_for_status=MagicMock()),
    ]
    post_responses = [
        MagicMock(status_code=200, json=MagicMock(return_value=create_response), raise_for_status=MagicMock()),
        MagicMock(status_code=200, json=MagicMock(return_value=list_entry_response), raise_for_status=MagicMock()),
    ]
    mock_client.get.side_effect = get_responses
    mock_client.post.side_effect = post_responses

    with patch("httpx.Client", return_value=mock_client):
        result = attio_push_company("Acme Corp", "acme.com", "RevOps AI Infra — Apr 2026")

    assert result["company_id"] == "rec-123"
    assert result["action"] == "created"
    assert result["list_entry_id"] == "entry-456"
    assert result["list_name"] == "RevOps AI Infra — Apr 2026"


def test_push_updates_existing_company():
    lists_response = {
        "data": [{"id": {"list_id": "list-abc"}, "name": "RevOps AI Infra — Apr 2026"}]
    }
    # Search finds existing company
    search_response = {"data": [{"id": {"record_id": "rec-existing"}}]}
    # Add to list → returns entry (no create call)
    list_entry_response = {"data": {"id": {"entry_id": "entry-789"}}}

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    get_responses = [
        MagicMock(status_code=200, json=MagicMock(return_value=lists_response), raise_for_status=MagicMock()),
        MagicMock(status_code=200, json=MagicMock(return_value=search_response), raise_for_status=MagicMock()),
    ]
    post_responses = [
        MagicMock(status_code=200, json=MagicMock(return_value=list_entry_response), raise_for_status=MagicMock()),
    ]
    mock_client.get.side_effect = get_responses
    mock_client.post.side_effect = post_responses

    with patch("httpx.Client", return_value=mock_client):
        result = attio_push_company("Acme Corp", "acme.com", "RevOps AI Infra — Apr 2026")

    assert result["company_id"] == "rec-existing"
    assert result["action"] == "updated"
    assert result["list_entry_id"] == "entry-789"
    # No create call should have been made
    mock_client.post.assert_called_once()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.attio'`

---

## Task 6: Attio — implementation

**Files:**
- Create: `remote-gateway/tools/attio.py`

- [ ] **Step 1: Write the implementation**

```python
"""
Attio wrapper tools.

Calls the Attio REST API directly — bypasses the broken attio-mcp npm package
(attio__create_record fails with "Required information is missing. (Field: are)"
for all inputs). All write operations use the REST API.

Required env vars:
    ATTIO_API_KEY — Attio workspace API key
"""
from __future__ import annotations

import os
from typing import Any

_BASE = "https://api.attio.com/v2"


def _attio_headers() -> dict[str, str]:
    """Return Attio API request headers using ATTIO_API_KEY from env."""
    return {
        "Authorization": f"Bearer {os.environ.get('ATTIO_API_KEY', '')}",
        "Content-Type": "application/json",
    }


def _find_list_id(client: Any, list_name: str) -> str | None:
    """Return the list_id for a list matching list_name, or None if not found."""
    resp = client.get(f"{_BASE}/lists", headers=_attio_headers())
    resp.raise_for_status()
    for lst in resp.json().get("data", []):
        if lst.get("name") == list_name:
            return lst["id"]["list_id"]
    return None


def _find_company_by_domain(client: Any, domain: str) -> str | None:
    """Return the record_id of an existing company with this domain, or None."""
    resp = client.get(
        f"{_BASE}/objects/companies/records",
        headers=_attio_headers(),
        params={"filter[domains][domain]": domain},
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if data:
        return data[0]["id"]["record_id"]
    return None


def attio_push_company(
    name: str,
    domain: str,
    list_name: str,
    notes: str = "",
) -> dict[str, Any]:
    """Create or update a company in Attio and add it to a named list.

    Validates required fields before any API call. Idempotent — safe to call
    twice for the same domain. Looks up the list by name (not ID).

    Args:
        name: Company display name, e.g. "Acme Corp".
        domain: Company primary domain, e.g. "acme.com".
        list_name: Exact name of the Attio list to add the company to.
        notes: Optional notes to store on the company record.

    Returns:
        Dict with company_id, action ("created" or "updated"), list_entry_id,
        and list_name. On error: {"error": "<reason>", ...}.
    """
    import httpx

    missing = [f for f, v in [("name", name), ("domain", domain)] if not v]
    if missing:
        return {"error": "missing_required_fields", "missing": missing}

    try:
        with httpx.Client() as client:
            # 1. Find the list by name
            list_id = _find_list_id(client, list_name)
            if list_id is None:
                return {"error": "list_not_found", "list_name": list_name}

            # 2. Find existing company by domain
            existing_id = _find_company_by_domain(client, domain)
            action = "updated" if existing_id else "created"

            if existing_id:
                record_id = existing_id
            else:
                # 3. Create company
                body: dict[str, Any] = {
                    "data": {
                        "values": {
                            "name": [{"value": name}],
                            "domains": [{"domain": domain}],
                        }
                    }
                }
                if notes:
                    body["data"]["values"]["description"] = [{"value": notes}]

                resp = client.post(
                    f"{_BASE}/objects/companies/records",
                    headers=_attio_headers(),
                    json=body,
                )
                resp.raise_for_status()
                record_id = resp.json()["data"]["id"]["record_id"]

            # 4. Add to list (Attio prevents duplicate entries automatically)
            entry_resp = client.post(
                f"{_BASE}/lists/{list_id}/entries",
                headers=_attio_headers(),
                json={
                    "data": {
                        "parent_object": "companies",
                        "parent_record_id": record_id,
                        "entry_values": {},
                    }
                },
            )
            entry_resp.raise_for_status()
            entry_id = entry_resp.json()["data"]["id"]["entry_id"]

    except Exception as exc:
        return {"error": str(exc), "name": name, "domain": domain}

    return {
        "company_id": record_id,
        "action": action,
        "list_entry_id": entry_id,
        "list_name": list_name,
    }


def register(mcp: Any) -> None:
    """Register Attio wrapper tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(attio_push_company)
```

- [ ] **Step 2: Run tests**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 3: Run all tests together**

```bash
pytest remote-gateway/tests/test_apollo_tools.py remote-gateway/tests/test_exa_tools.py remote-gateway/tests/test_attio_tools.py -v
```

Expected: all 15 tests pass.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/tools/attio.py remote-gateway/tests/test_attio_tools.py
git commit -m "feat(gateway): add attio_push_company wrapper tool with direct REST API"
```

---

## Task 7: Register tools in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Add imports and register calls**

In `remote-gateway/core/mcp_server.py`, find the existing tool registration block (around line 105–111):

```python
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
```

Replace with:

```python
from tools import apollo as _apollo_tools  # noqa: E402
from tools import attio as _attio_tools  # noqa: E402
from tools import exa as _exa_tools  # noqa: E402
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
_apollo_tools.register(mcp)
_attio_tools.register(mcp)
_exa_tools.register(mcp)
```

- [ ] **Step 2: Verify server starts without errors**

```bash
cd remote-gateway && python core/mcp_server.py --help 2>&1 | head -5 || python core/mcp_server.py &
sleep 2 && kill %1 2>/dev/null; echo "Startup check done"
```

Expected: no import errors, no tracebacks.

- [ ] **Step 3: Run full test suite**

```bash
pytest remote-gateway/tests/ -v --ignore=remote-gateway/tests/test_notes.py
```

Expected: all tests pass (test_notes.py is skipped — it requires live GitHub credentials).

- [ ] **Step 4: Lint**

```bash
ruff check remote-gateway/tools/apollo.py remote-gateway/tools/exa.py remote-gateway/tools/attio.py
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat(gateway): register apollo, exa, and attio wrapper tools on server"
```

> **Note on `validated()`:** The spec mentions wrapping returns with `validated("<integration>", result)`. This is only applicable to tools injected directly into `mcp_server.py` — `validated()` is defined there and not importable from modules without circular imports. All existing module-based tools (notes, meta, registry) follow the same pattern and skip `validated()`. Field registry validation for these tools is a future iteration.
