# Apollo Python Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken Apollo OAuth MCP proxy with four direct Python tools (`apollo__search_people`, `apollo__search_companies`, `apollo__enrich_person`, `apollo__enrich_organization`) plus a new `attio__upsert_record` tool, all following the `wiza.py` pattern.

**Architecture:** `tools/apollo.py` calls Apollo's REST API with `X-Api-Key` auth. Private helpers `_headers()`, `_strip_nulls()`, `_pick()`, and `_map_to_attio_values()` are shared across all four tools. `attio__upsert_record` is added to `tools/attio.py`. The broken `"apollo"` proxy entry is removed from `mcp_connections.json`.

**Tech Stack:** Python 3.11+, httpx (sync), Apollo REST API v1 (`api.apollo.io`), Attio REST API v2, pytest + monkeypatch + unittest.mock.

---

## File Map

| File | Action |
|---|---|
| `remote-gateway/tools/apollo.py` | **Create** — four tools + private helpers |
| `remote-gateway/tests/test_apollo_tools.py` | **Create** — all Apollo tool tests |
| `remote-gateway/tools/attio.py` | **Modify** — add `attio__upsert_record` |
| `remote-gateway/tests/test_attio_tools.py` | **Modify** — append upsert tests |
| `remote-gateway/core/mcp_server.py` | **Modify** — import + register `_apollo_tools` |
| `remote-gateway/mcp_connections.json` | **Modify** — remove `"apollo"` proxy entry |
| `remote-gateway/context/fields/apollo.yaml` | **Modify** — replace TODO stubs with real descriptions |
| `remote-gateway/.env.example` | **Modify** — replace OAuth vars with `APOLLO_API_KEY` |

---

## Task 1: `tools/apollo.py` skeleton — `_headers`, `_strip_nulls`, `_pick`, `_map_to_attio_values`

**Files:**
- Create: `remote-gateway/tools/apollo.py`
- Create: `remote-gateway/tests/test_apollo_tools.py`

- [ ] **Step 1: Create the test file with failing tests**

```python
# remote-gateway/tests/test_apollo_tools.py
"""Unit tests for tools/apollo.py — Apollo REST API tools."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_response(json_data: dict, status_code: int = 200, headers: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.headers = headers or {}
    m.raise_for_status = MagicMock()
    m.is_success = status_code < 300
    return m


def _mock_client(post_responses=None, get_responses=None) -> MagicMock:
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if post_responses is not None:
        mock.post.side_effect = post_responses
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------

def test_headers_raises_without_key(monkeypatch):
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    from tools.apollo import _headers
    import pytest
    with pytest.raises(ValueError, match="APOLLO_API_KEY"):
        _headers()


def test_headers_returns_api_key_header(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-apollo-key")
    from tools.apollo import _headers
    h = _headers()
    assert h["X-Api-Key"] == "test-apollo-key"
    assert h["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# _strip_nulls
# ---------------------------------------------------------------------------

def test_strip_nulls_removes_none_empty_string_and_empty_list():
    from tools.apollo import _strip_nulls
    result = _strip_nulls({
        "a": "hello", "b": None, "c": "", "d": [], "e": 0, "f": False, "g": ["x"]
    })
    assert result == {"a": "hello", "e": 0, "f": False, "g": ["x"]}


# ---------------------------------------------------------------------------
# _map_to_attio_values — person
# ---------------------------------------------------------------------------

def test_map_person_maps_name_email_title_linkedin(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": "VP of Sales",
        "linkedin_url": "https://linkedin.com/in/janedoe",
    }
    result = _map_to_attio_values(person, "person")
    assert result["name"] == [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]
    assert result["email_addresses"] == [{"email_address": "jane@acme.com"}]
    assert result["job_title"] == [{"value": "VP of Sales"}]
    assert result["linkedin"] == [{"value": "https://linkedin.com/in/janedoe"}]


def test_map_person_maps_phone_from_raw_number(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "phone_numbers": [{"raw_number": "+1-555-0100", "type": "work"}],
    }
    result = _map_to_attio_values(person, "person")
    assert result["phone_numbers"] == [{"phone_number": "+1-555-0100"}]


def test_map_person_maps_location_from_city_and_state(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "city": "San Francisco", "state": "California",
    }
    result = _map_to_attio_values(person, "person")
    assert result["primary_location"] == [{"value": "San Francisco, California"}]


def test_map_person_omits_fields_with_no_data(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {"first_name": "Jane", "last_name": "Doe", "name": "Jane Doe"}
    result = _map_to_attio_values(person, "person")
    assert "email_addresses" not in result
    assert "job_title" not in result
    assert "linkedin" not in result
    assert "phone_numbers" not in result
    assert "primary_location" not in result


def test_map_person_does_not_include_organization_name(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "organization_name": "Acme Inc",
    }
    result = _map_to_attio_values(person, "person")
    assert "company" not in result


# ---------------------------------------------------------------------------
# _map_to_attio_values — organization
# ---------------------------------------------------------------------------

def test_map_org_maps_name_domain_location(monkeypatch):
    from tools.apollo import _map_to_attio_values
    org = {
        "name": "Acme Inc", "domain": "acme.com",
        "city": "San Francisco", "state": "California",
    }
    result = _map_to_attio_values(org, "organization")
    assert result["name"] == [{"value": "Acme Inc"}]
    assert result["domains"] == [{"domain": "acme.com"}]
    assert result["primary_location"] == [{"value": "San Francisco, California"}]


def test_map_org_falls_back_to_primary_domain(monkeypatch):
    from tools.apollo import _map_to_attio_values
    org = {"name": "Acme Inc", "primary_domain": "acme.com"}
    result = _map_to_attio_values(org, "organization")
    assert result["domains"] == [{"domain": "acme.com"}]
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'tools.apollo'`

- [ ] **Step 3: Create `tools/apollo.py` with the skeleton**

```python
"""
Apollo.io REST API tools — direct Python implementation.

Replaces the broken OAuth MCP proxy. Calls Apollo's REST API directly
using a simple API key header. Follows the same pattern as tools/wiza.py.

Required env vars:
    APOLLO_API_KEY — from app.apollo.io → Settings → Integrations → API Keys
"""
from __future__ import annotations

import os
from typing import Any

_APOLLO_BASE = "https://api.apollo.io/v1"

_PERSON_SEARCH_FIELDS: frozenset[str] = frozenset({
    "id", "name", "first_name", "last_name", "title",
    "email", "email_status", "linkedin_url",
    "city", "state", "country",
    "organization_name", "organization_id",
    "funding_stage", "estimated_num_employees",
})

_COMPANY_SEARCH_FIELDS: frozenset[str] = frozenset({
    "id", "name", "domain", "primary_domain",
    "industry", "city", "state", "country",
    "num_employees", "estimated_num_employees",
    "estimated_annual_revenue", "annual_revenue_printed",
    "funding_stage", "latest_funding_amount", "latest_funding_date",
})


def _headers() -> dict[str, str]:
    """Return Apollo API request headers using APOLLO_API_KEY from env."""
    api_key = os.environ.get("APOLLO_API_KEY")
    if not api_key:
        raise ValueError("APOLLO_API_KEY environment variable is not set")
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}


def _strip_nulls(d: dict) -> dict:
    """Return d with None, empty string, and empty list values removed."""
    return {k: v for k, v in d.items() if v is not None and v != "" and v != []}


def _pick(d: dict, fields: frozenset) -> dict:
    """Return d filtered to only the given fields, with nulls stripped."""
    return _strip_nulls({k: v for k, v in d.items() if k in fields})


def _map_to_attio_values(data: dict, record_type: str) -> dict:
    """Map an Apollo person or organization dict to Attio write format.

    Omits fields with no data. Does not include the organization/company
    relationship field, which requires an Attio record ID the agent must
    resolve separately.

    Args:
        data: Apollo person or organization dict.
        record_type: "person" or "organization".

    Returns:
        Dict ready to pass as `values` to attio__upsert_record.
    """
    result: dict[str, Any] = {}

    if record_type == "person":
        first = data.get("first_name") or ""
        last = data.get("last_name") or ""
        full = data.get("name") or f"{first} {last}".strip()
        if first or last or full:
            result["name"] = [{"first_name": first, "last_name": last, "full_name": full}]

        if data.get("email"):
            result["email_addresses"] = [{"email_address": data["email"]}]

        if data.get("title"):
            result["job_title"] = [{"value": data["title"]}]

        if data.get("linkedin_url"):
            result["linkedin"] = [{"value": data["linkedin_url"]}]

        phones = data.get("phone_numbers") or []
        if phones:
            raw = phones[0].get("raw_number") or phones[0].get("sanitized_number")
            if raw:
                result["phone_numbers"] = [{"phone_number": raw}]

        city = data.get("city") or ""
        state = data.get("state") or ""
        location = ", ".join(p for p in [city, state] if p)
        if location:
            result["primary_location"] = [{"value": location}]

    elif record_type == "organization":
        if data.get("name"):
            result["name"] = [{"value": data["name"]}]

        domain = data.get("domain") or data.get("primary_domain")
        if domain:
            result["domains"] = [{"domain": domain}]

        city = data.get("city") or ""
        state = data.get("state") or ""
        location = ", ".join(p for p in [city, state] if p)
        if location:
            result["primary_location"] = [{"value": location}]

    return result


def _handle_apollo_error(resp: Any, tool_name: str) -> dict | None:
    """Check for Apollo error responses. Returns error dict or None if OK."""
    if resp.status_code == 401:
        raise PermissionError("APOLLO_API_KEY is invalid or expired")
    if resp.status_code == 422:
        return {
            "error": f"{tool_name}: Apollo rejected the request parameters",
            "detail": resp.json(),
        }
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        raise RuntimeError(f"Apollo rate limit — retry after {retry_after}s")
    resp.raise_for_status()
    return None


def register(mcp: Any) -> None:
    """Register Apollo tools on the FastMCP server."""
    mcp.tool()(apollo__search_people)
    mcp.tool()(apollo__search_companies)
    mcp.tool()(apollo__enrich_person)
    mcp.tool()(apollo__enrich_organization)
```

> Note: `apollo__search_people`, `apollo__search_companies`, `apollo__enrich_person`, and `apollo__enrich_organization` are defined in Tasks 2–5. Add a stub at the bottom of the file for now so `register` doesn't fail:
>
> ```python
> def apollo__search_people(**_): raise NotImplementedError
> def apollo__search_companies(**_): raise NotImplementedError
> def apollo__enrich_person(**_): raise NotImplementedError
> def apollo__enrich_organization(**_): raise NotImplementedError
> ```

- [ ] **Step 4: Run tests**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py -v
```
Expected: all 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/apollo.py remote-gateway/tests/test_apollo_tools.py
git commit -m "feat: add apollo.py skeleton with helpers and test file"
```

---

## Task 2: `apollo__search_people`

**Files:**
- Modify: `remote-gateway/tools/apollo.py`
- Modify: `remote-gateway/tests/test_apollo_tools.py`

- [ ] **Step 1: Append failing tests**

```python
# Append to remote-gateway/tests/test_apollo_tools.py

from unittest.mock import patch

# ---------------------------------------------------------------------------
# apollo__search_people
# ---------------------------------------------------------------------------

def test_search_people_posts_to_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people()
    url = mock_client.post.call_args.args[0]
    assert "mixed_people/search" in url


def test_search_people_sends_api_key_header(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "my-secret-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people()
    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers["X-Api-Key"] == "my-secret-key"


def test_search_people_includes_filters_in_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people(
            person_titles=["VP of Sales"],
            person_seniorities=["vp"],
            funding_stage=["series_b"],
            per_page=10,
        )
    body = mock_client.post.call_args.kwargs["json"]
    assert body["person_titles"] == ["VP of Sales"]
    assert body["person_seniorities"] == ["vp"]
    assert body["funding_stage"] == ["series_b"]
    assert body["per_page"] == 10


def test_search_people_omits_none_filters_from_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people()
    body = mock_client.post.call_args.kwargs["json"]
    assert "person_titles" not in body
    assert "funding_stage" not in body


def test_search_people_strips_nulls_from_results(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    raw_person = {
        "id": "p1", "name": "Jane Doe", "first_name": "Jane", "last_name": "Doe",
        "title": None, "email": "jane@acme.com", "linkedin_url": None,
        "city": "SF", "state": "CA", "country": "US",
        "organization_name": "Acme", "organization_id": "o1",
        "funding_stage": None, "estimated_num_employees": 200,
    }
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [raw_person], "pagination": {"total_entries": 1}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people()
    person = result["people"][0]
    assert "title" not in person
    assert "linkedin_url" not in person
    assert "funding_stage" not in person
    assert person["email"] == "jane@acme.com"


def test_search_people_returns_pagination_and_agent_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [{"id": "p1", "name": "Jane"}],
        "pagination": {"total_entries": 500}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people(page=1, per_page=25)
    assert result["pagination"]["total"] == 500
    assert result["pagination"]["has_more"] is True
    assert "500" in result["pagination"]["summary"]
    assert "agent_hint" in result


def test_search_people_raises_permission_error_on_401(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "bad-key")
    from tools.apollo import apollo__search_people
    import pytest
    mock_client = _mock_client(post_responses=[_mock_response({}, status_code=401)])
    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(PermissionError, match="APOLLO_API_KEY"):
            apollo__search_people()


def test_search_people_returns_error_dict_on_422(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[
        _mock_response({"error": "invalid seniority"}, status_code=422)
    ])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people(person_seniorities=["bogus"])
    assert "error" in result
    assert "detail" in result


def test_search_people_raises_runtime_error_on_429(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    import pytest
    resp = _mock_response({}, status_code=429, headers={"Retry-After": "30"})
    mock_client = _mock_client(post_responses=[resp])
    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="30"):
            apollo__search_people()
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py::test_search_people_posts_to_correct_url -v
```
Expected: `NotImplementedError`

- [ ] **Step 3: Replace the `apollo__search_people` stub with the real implementation**

Remove the stub and add this function before `register()` in `tools/apollo.py`:

```python
def apollo__search_people(
    person_titles: list[str] | None = None,
    person_seniorities: list[str] | None = None,
    person_locations: list[str] | None = None,
    q_keywords: str | None = None,
    q_organization_name: str | None = None,
    organization_domains: list[str] | None = None,
    organization_num_employees_ranges: list[str] | None = None,
    organization_industry_tag_ids: list[str] | None = None,
    organization_keywords: list[str] | None = None,
    funding_stage: list[str] | None = None,
    organization_latest_funding_amount_min: int | None = None,
    organization_latest_funding_amount_max: int | None = None,
    contact_email_status: list[str] | None = None,
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """Search Apollo for people matching demographic filters.

    All filter parameters are optional and combined with AND logic.
    Returns trimmed results with only populated fields. Nulls are stripped
    from each person record so agents only see meaningful data.

    person_seniorities valid values: "owner", "founder", "c_suite", "partner",
        "vp", "head", "director", "manager", "senior", "entry", "intern"
    organization_num_employees_ranges format: ["1,10", "11,50", "51,200",
        "201,500", "501,1000", "1001,5000", "5001,10000", "10001,"]
    funding_stage valid values: "seed", "series_a", "series_b", "series_c",
        "series_d", "series_e_plus", "ipo"
    contact_email_status valid values: "verified", "guessed", "unavailable",
        "bounced", "pending_manual_fulfillment"

    Args:
        person_titles: Job title keywords (e.g. ["VP of Sales"]).
        person_seniorities: Seniority levels.
        person_locations: Location strings (e.g. ["San Francisco, California, United States"]).
        q_keywords: Free-text keyword search across all fields.
        q_organization_name: Company name substring.
        organization_domains: Company domains (e.g. ["acme.com"]).
        organization_num_employees_ranges: Employee count ranges.
        organization_industry_tag_ids: Apollo industry IDs.
        organization_keywords: Keywords in company description.
        funding_stage: Company funding stages.
        organization_latest_funding_amount_min: Min latest funding amount (USD).
        organization_latest_funding_amount_max: Max latest funding amount (USD).
        contact_email_status: Email verification statuses to include.
        page: Page number (1-indexed).
        per_page: Results per page (max 100).

    Returns:
        Dict with 'people' list, 'pagination' summary, and 'agent_hint'.
    """
    import httpx

    body: dict[str, Any] = {"page": page, "per_page": per_page}
    if person_titles:
        body["person_titles"] = person_titles
    if person_seniorities:
        body["person_seniorities"] = person_seniorities
    if person_locations:
        body["person_locations"] = person_locations
    if q_keywords:
        body["q_keywords"] = q_keywords
    if q_organization_name:
        body["q_organization_name"] = q_organization_name
    if organization_domains:
        body["organization_domains"] = organization_domains
    if organization_num_employees_ranges:
        body["organization_num_employees_ranges"] = organization_num_employees_ranges
    if organization_industry_tag_ids:
        body["organization_industry_tag_ids"] = organization_industry_tag_ids
    if organization_keywords:
        body["organization_keywords"] = organization_keywords
    if funding_stage:
        body["funding_stage"] = funding_stage
    if organization_latest_funding_amount_min is not None:
        body["organization_latest_funding_amount_min"] = organization_latest_funding_amount_min
    if organization_latest_funding_amount_max is not None:
        body["organization_latest_funding_amount_max"] = organization_latest_funding_amount_max
    if contact_email_status:
        body["contact_email_status"] = contact_email_status

    with httpx.Client() as client:
        resp = client.post(
            f"{_APOLLO_BASE}/mixed_people/search",
            headers=_headers(),
            json=body,
        )

    err = _handle_apollo_error(resp, "apollo__search_people")
    if err:
        return err

    data = resp.json()
    people = [_pick(p, _PERSON_SEARCH_FIELDS) for p in data.get("people", [])]

    pagination_data = data.get("pagination", {})
    total = pagination_data.get("total_entries", 0)
    has_more = total > page * per_page
    pagination = {
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": has_more,
        "summary": (
            f"Showing {len(people)} of {total:,} matches"
            + (" — refine filters or increment page to continue." if has_more else ".")
        ),
    }

    return {
        "people": people,
        "pagination": pagination,
        "agent_hint": (
            "Review results above. To enrich a person and get Attio-ready values, "
            "call apollo__enrich_person with their id. To search again with refined "
            "filters, call apollo__search_people with updated parameters."
        ),
    }
```

- [ ] **Step 4: Run tests**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py -k "search_people" -v
```
Expected: all 9 search_people tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/apollo.py remote-gateway/tests/test_apollo_tools.py
git commit -m "feat: add apollo__search_people with rich demographic filters"
```

---

## Task 3: `apollo__search_companies`

**Files:**
- Modify: `remote-gateway/tools/apollo.py`
- Modify: `remote-gateway/tests/test_apollo_tools.py`

- [ ] **Step 1: Append failing tests**

```python
# Append to remote-gateway/tests/test_apollo_tools.py

# ---------------------------------------------------------------------------
# apollo__search_companies
# ---------------------------------------------------------------------------

def test_search_companies_posts_to_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_companies()
    url = mock_client.post.call_args.args[0]
    assert "mixed_companies/search" in url


def test_search_companies_includes_filters_in_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_companies(
            q_organization_name="Acme",
            organization_num_employees_ranges=["51,200"],
            funding_stage=["series_a"],
            organization_latest_funding_amount_min=1000000,
        )
    body = mock_client.post.call_args.kwargs["json"]
    assert body["q_organization_name"] == "Acme"
    assert body["organization_num_employees_ranges"] == ["51,200"]
    assert body["funding_stage"] == ["series_a"]
    assert body["organization_latest_funding_amount_min"] == 1000000


def test_search_companies_strips_nulls_from_results(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    raw_org = {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
        "industry": None, "city": "SF", "state": "CA",
        "num_employees": 200, "estimated_annual_revenue": None,
        "funding_stage": "series_b", "latest_funding_amount": 25000000,
        "latest_funding_date": None,
    }
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [raw_org], "pagination": {"total_entries": 1}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_companies()
    org = result["companies"][0]
    assert "industry" not in org
    assert "estimated_annual_revenue" not in org
    assert "latest_funding_date" not in org
    assert org["name"] == "Acme Inc"


def test_search_companies_returns_pagination_and_agent_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [], "pagination": {"total_entries": 250}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_companies(page=1, per_page=25)
    assert result["pagination"]["total"] == 250
    assert result["pagination"]["has_more"] is True
    assert "agent_hint" in result
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py::test_search_companies_posts_to_correct_url -v
```
Expected: `NotImplementedError`

- [ ] **Step 3: Replace the `apollo__search_companies` stub**

```python
def apollo__search_companies(
    q_keywords: str | None = None,
    q_organization_name: str | None = None,
    organization_locations: list[str] | None = None,
    organization_num_employees_ranges: list[str] | None = None,
    organization_revenue_ranges: list[str] | None = None,
    organization_industry_tag_ids: list[str] | None = None,
    organization_keywords: list[str] | None = None,
    funding_stage: list[str] | None = None,
    organization_latest_funding_amount_min: int | None = None,
    organization_latest_funding_amount_max: int | None = None,
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """Search Apollo for companies matching demographic filters.

    organization_num_employees_ranges format: ["1,10", "51,200", "1001,5000", "10001,"]
    organization_revenue_ranges format: ["1000000,10000000"] (USD)
    funding_stage valid values: "seed", "series_a", "series_b", "series_c",
        "series_d", "series_e_plus", "ipo"

    Args:
        q_keywords: Free-text search across all fields.
        q_organization_name: Company name substring.
        organization_locations: Location strings (e.g. ["United States"]).
        organization_num_employees_ranges: Employee count ranges.
        organization_revenue_ranges: Annual revenue ranges in USD.
        organization_industry_tag_ids: Apollo industry IDs.
        organization_keywords: Keywords in company description.
        funding_stage: Funding stage filter.
        organization_latest_funding_amount_min: Min latest funding amount (USD).
        organization_latest_funding_amount_max: Max latest funding amount (USD).
        page: Page number (1-indexed).
        per_page: Results per page (max 100).

    Returns:
        Dict with 'companies' list, 'pagination' summary, and 'agent_hint'.
    """
    import httpx

    body: dict[str, Any] = {"page": page, "per_page": per_page}
    if q_keywords:
        body["q_keywords"] = q_keywords
    if q_organization_name:
        body["q_organization_name"] = q_organization_name
    if organization_locations:
        body["organization_locations"] = organization_locations
    if organization_num_employees_ranges:
        body["organization_num_employees_ranges"] = organization_num_employees_ranges
    if organization_revenue_ranges:
        body["organization_revenue_ranges"] = organization_revenue_ranges
    if organization_industry_tag_ids:
        body["organization_industry_tag_ids"] = organization_industry_tag_ids
    if organization_keywords:
        body["organization_keywords"] = organization_keywords
    if funding_stage:
        body["funding_stage"] = funding_stage
    if organization_latest_funding_amount_min is not None:
        body["organization_latest_funding_amount_min"] = organization_latest_funding_amount_min
    if organization_latest_funding_amount_max is not None:
        body["organization_latest_funding_amount_max"] = organization_latest_funding_amount_max

    with httpx.Client() as client:
        resp = client.post(
            f"{_APOLLO_BASE}/mixed_companies/search",
            headers=_headers(),
            json=body,
        )

    err = _handle_apollo_error(resp, "apollo__search_companies")
    if err:
        return err

    data = resp.json()
    companies = [_pick(c, _COMPANY_SEARCH_FIELDS) for c in data.get("organizations", [])]

    pagination_data = data.get("pagination", {})
    total = pagination_data.get("total_entries", 0)
    has_more = total > page * per_page
    pagination = {
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": has_more,
        "summary": (
            f"Showing {len(companies)} of {total:,} matches"
            + (" — refine filters or increment page to continue." if has_more else ".")
        ),
    }

    return {
        "companies": companies,
        "pagination": pagination,
        "agent_hint": (
            "Review results above. To enrich a company and get Attio-ready values, "
            "call apollo__enrich_organization with its domain. To search again with "
            "refined filters, call apollo__search_companies with updated parameters."
        ),
    }
```

- [ ] **Step 4: Run tests**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py -k "search_companies" -v
```
Expected: all 4 search_companies tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/apollo.py remote-gateway/tests/test_apollo_tools.py
git commit -m "feat: add apollo__search_companies"
```

---

## Task 4: `apollo__enrich_person`

**Files:**
- Modify: `remote-gateway/tools/apollo.py`
- Modify: `remote-gateway/tests/test_apollo_tools.py`

- [ ] **Step 1: Append failing tests**

```python
# Append to remote-gateway/tests/test_apollo_tools.py
import pytest

# ---------------------------------------------------------------------------
# apollo__enrich_person
# ---------------------------------------------------------------------------

def test_enrich_person_raises_without_identifier(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    with pytest.raises(ValueError, match="id, email, linkedin_url"):
        apollo__enrich_person()


def test_enrich_person_posts_to_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    mock_client = _mock_client(post_responses=[_mock_response({"person": {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": "VP of Sales",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_person(email="jane@acme.com")
    url = mock_client.post.call_args.args[0]
    assert "people/match" in url


def test_enrich_person_posts_identifier_in_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    mock_client = _mock_client(post_responses=[_mock_response({"person": {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_person(id="p1", reveal_phone_number=True)
    body = mock_client.post.call_args.kwargs["json"]
    assert body["id"] == "p1"
    assert body["reveal_phone_number"] is True


def test_enrich_person_returns_person_attio_values_and_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    apollo_person = {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": "VP of Sales",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "phone_numbers": [{"raw_number": "+1-555-0100", "type": "work"}],
        "city": "San Francisco", "state": "California",
        "employment_history": None,
    }
    mock_client = _mock_client(post_responses=[_mock_response({"person": apollo_person})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_person(email="jane@acme.com")
    assert "person" in result
    assert "attio_values" in result
    assert "agent_hint" in result
    # attio_values should be pre-mapped
    av = result["attio_values"]
    assert av["email_addresses"] == [{"email_address": "jane@acme.com"}]
    assert av["job_title"] == [{"value": "VP of Sales"}]
    assert av["phone_numbers"] == [{"phone_number": "+1-555-0100"}]


def test_enrich_person_strips_nulls_from_person(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    apollo_person = {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": None, "linkedin_url": None,
        "employment_history": None,
    }
    mock_client = _mock_client(post_responses=[_mock_response({"person": apollo_person})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_person(email="jane@acme.com")
    assert "title" not in result["person"]
    assert "linkedin_url" not in result["person"]
    assert "employment_history" not in result["person"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py::test_enrich_person_raises_without_identifier -v
```
Expected: `NotImplementedError`

- [ ] **Step 3: Replace the `apollo__enrich_person` stub**

```python
def apollo__enrich_person(
    id: str | None = None,
    email: str | None = None,
    linkedin_url: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    organization_name: str | None = None,
    domain: str | None = None,
    reveal_personal_emails: bool = False,
    reveal_phone_number: bool = False,
) -> dict:
    """Enrich a person's contact data from Apollo.

    At least one of id, email, or linkedin_url must be provided.
    Returns full Apollo person data (nulls stripped) plus a pre-mapped
    attio_values dict ready to pass directly to attio__upsert_record.

    Args:
        id: Apollo person ID (from apollo__search_people results).
        email: Person's work email address.
        linkedin_url: Person's LinkedIn profile URL.
        first_name: First name (improves match accuracy).
        last_name: Last name (improves match accuracy).
        organization_name: Company name (improves match accuracy).
        domain: Company domain (improves match accuracy).
        reveal_personal_emails: Also return personal email addresses (uses credits).
        reveal_phone_number: Also return phone number (uses credits).

    Returns:
        Dict with 'person' (raw Apollo data, nulls stripped),
        'attio_values' (pre-mapped for attio__upsert_record),
        and 'agent_hint'.
    """
    import httpx

    if not any([id, email, linkedin_url]):
        raise ValueError("Provide at least one of: id, email, linkedin_url")

    body: dict[str, Any] = {
        "reveal_personal_emails": reveal_personal_emails,
        "reveal_phone_number": reveal_phone_number,
    }
    if id:
        body["id"] = id
    if email:
        body["email"] = email
    if linkedin_url:
        body["linkedin_url"] = linkedin_url
    if first_name:
        body["first_name"] = first_name
    if last_name:
        body["last_name"] = last_name
    if organization_name:
        body["organization_name"] = organization_name
    if domain:
        body["domain"] = domain

    with httpx.Client() as client:
        resp = client.post(
            f"{_APOLLO_BASE}/people/match",
            headers=_headers(),
            json=body,
        )

    err = _handle_apollo_error(resp, "apollo__enrich_person")
    if err:
        return err

    person = _strip_nulls(resp.json().get("person") or {})
    attio_values = _map_to_attio_values(person, "person")

    return {
        "person": person,
        "attio_values": attio_values,
        "agent_hint": (
            "attio_values is pre-mapped for attio__upsert_record. "
            "Call attio__upsert_record(object_type='people', values=attio_values, "
            "matching_attribute='email_addresses') to write to Attio."
        ),
    }
```

- [ ] **Step 4: Run tests**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py -k "enrich_person" -v
```
Expected: all 5 enrich_person tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/apollo.py remote-gateway/tests/test_apollo_tools.py
git commit -m "feat: add apollo__enrich_person with pre-mapped attio_values"
```

---

## Task 5: `apollo__enrich_organization`

**Files:**
- Modify: `remote-gateway/tools/apollo.py`
- Modify: `remote-gateway/tests/test_apollo_tools.py`

- [ ] **Step 1: Append failing tests**

```python
# Append to remote-gateway/tests/test_apollo_tools.py

# ---------------------------------------------------------------------------
# apollo__enrich_organization
# ---------------------------------------------------------------------------

def test_enrich_organization_gets_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    mock_client = _mock_client(get_responses=[_mock_response({"organization": {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_organization(domain="acme.com")
    url = mock_client.get.call_args.args[0]
    assert "organizations/enrich" in url


def test_enrich_organization_passes_domain_as_param(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    mock_client = _mock_client(get_responses=[_mock_response({"organization": {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_organization(domain="acme.com")
    params = mock_client.get.call_args.kwargs.get("params", {})
    assert params.get("domain") == "acme.com"


def test_enrich_organization_returns_org_attio_values_and_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    apollo_org = {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
        "industry": "Software", "city": "San Francisco", "state": "California",
        "num_employees": 250, "funding_stage": "series_b",
        "latest_funding_amount": 25000000, "annual_revenue": None,
    }
    mock_client = _mock_client(get_responses=[_mock_response({"organization": apollo_org})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_organization(domain="acme.com")
    assert "organization" in result
    assert "attio_values" in result
    assert "agent_hint" in result
    av = result["attio_values"]
    assert av["name"] == [{"value": "Acme Inc"}]
    assert av["domains"] == [{"domain": "acme.com"}]
    assert av["primary_location"] == [{"value": "San Francisco, California"}]


def test_enrich_organization_strips_nulls(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    apollo_org = {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
        "annual_revenue": None, "latest_funding_date": None,
    }
    mock_client = _mock_client(get_responses=[_mock_response({"organization": apollo_org})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_organization(domain="acme.com")
    assert "annual_revenue" not in result["organization"]
    assert "latest_funding_date" not in result["organization"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py::test_enrich_organization_gets_correct_url -v
```
Expected: `NotImplementedError`

- [ ] **Step 3: Replace the `apollo__enrich_organization` stub**

```python
def apollo__enrich_organization(domain: str) -> dict:
    """Enrich a company's data from Apollo by domain.

    Returns full Apollo organization data (nulls stripped) plus a pre-mapped
    attio_values dict ready to pass directly to attio__upsert_record.

    Args:
        domain: Company website domain (e.g. "acme.com"). Required.

    Returns:
        Dict with 'organization' (raw Apollo data, nulls stripped),
        'attio_values' (pre-mapped for attio__upsert_record),
        and 'agent_hint'.
    """
    import httpx

    with httpx.Client() as client:
        resp = client.get(
            f"{_APOLLO_BASE}/organizations/enrich",
            headers=_headers(),
            params={"domain": domain},
        )

    err = _handle_apollo_error(resp, "apollo__enrich_organization")
    if err:
        return err

    org = _strip_nulls(resp.json().get("organization") or {})
    attio_values = _map_to_attio_values(org, "organization")

    return {
        "organization": org,
        "attio_values": attio_values,
        "agent_hint": (
            "attio_values is pre-mapped for attio__upsert_record. "
            "Call attio__upsert_record(object_type='companies', values=attio_values, "
            "matching_attribute='domains') to write to Attio."
        ),
    }
```

- [ ] **Step 4: Run the full Apollo test suite**

```bash
cd remote-gateway && pytest tests/test_apollo_tools.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/apollo.py remote-gateway/tests/test_apollo_tools.py
git commit -m "feat: add apollo__enrich_organization with pre-mapped attio_values"
```

---

## Task 6: `attio__upsert_record`

**Files:**
- Modify: `remote-gateway/tools/attio.py`
- Modify: `remote-gateway/tests/test_attio_tools.py`

- [ ] **Step 1: Append failing tests to `test_attio_tools.py`**

```python
# Append to remote-gateway/tests/test_attio_tools.py

from tools.attio import attio__upsert_record

# ---------------------------------------------------------------------------
# attio__upsert_record
# ---------------------------------------------------------------------------

def test_upsert_record_raises_for_invalid_matching_attribute(monkeypatch):
    """upsert_record raises ValueError for unsupported matching_attribute."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    import pytest
    with pytest.raises(ValueError, match="matching_attribute"):
        attio__upsert_record("people", {}, matching_attribute="bogus_field")


def test_upsert_record_posts_with_matching_attribute(monkeypatch):
    """upsert_record includes matching_attribute in the POST body."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    mock_client = _mock_client(
        post_responses=[_mock_response(
            {"data": {"id": {"record_id": "rec-upserted"}, "values": {}}},
            status_code=200,
        )]
    )
    values = {"email_addresses": [{"email_address": "jane@acme.com"}]}
    with patch("httpx.Client", return_value=mock_client):
        attio__upsert_record("people", values, matching_attribute="email_addresses")
    posted_body = mock_client.post.call_args.kwargs["json"]
    assert posted_body["matching_attribute"] == "email_addresses"
    assert posted_body["data"]["values"] == values


def test_upsert_record_returns_upserted_true_on_200(monkeypatch):
    """upsert_record returns upserted=True when Attio returns 200 (existing record updated)."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    mock_client = _mock_client(
        post_responses=[_mock_response(
            {"data": {"id": {"record_id": "rec-existing"}, "values": {}}},
            status_code=200,
        )]
    )
    with patch("httpx.Client", return_value=mock_client):
        result = attio__upsert_record(
            "people",
            {"email_addresses": [{"email_address": "jane@acme.com"}]},
            matching_attribute="email_addresses",
        )
    assert result["upserted"] is True
    assert result["record_id"] == "rec-existing"


def test_upsert_record_returns_upserted_false_on_201(monkeypatch):
    """upsert_record returns upserted=False when Attio returns 201 (new record created)."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    mock_client = _mock_client(
        post_responses=[_mock_response(
            {"data": {"id": {"record_id": "rec-new"}, "values": {}}},
            status_code=201,
        )]
    )
    with patch("httpx.Client", return_value=mock_client):
        result = attio__upsert_record(
            "companies",
            {"domains": [{"domain": "acme.com"}]},
            matching_attribute="domains",
        )
    assert result["upserted"] is False
    assert result["record_id"] == "rec-new"


def test_upsert_record_returns_error_on_attio_failure(monkeypatch):
    """upsert_record returns error dict on non-2xx Attio response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    resp = _mock_response({"message": "bad request"}, status_code=400)
    resp.is_success = False
    resp.text = '{"message": "bad request"}'
    mock_client = _mock_client(post_responses=[resp])
    with patch("httpx.Client", return_value=mock_client):
        result = attio__upsert_record(
            "people",
            {"email_addresses": [{"email_address": "x@y.com"}]},
            matching_attribute="email_addresses",
        )
    assert "error" in result
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_attio_tools.py::test_upsert_record_raises_for_invalid_matching_attribute -v
```
Expected: `ImportError` or `AttributeError`

- [ ] **Step 3: Add `attio__upsert_record` to `tools/attio.py`**

Add this function after `attio__create_record` and before `register()`:

```python
_VALID_MATCHING_ATTRIBUTES = frozenset({"email_addresses", "domains"})


def attio__upsert_record(
    object_type: str,
    values: dict[str, Any],
    matching_attribute: str,
) -> dict[str, Any]:
    """Create or update an Attio record, matching on a unique attribute.

    Uses Attio's native upsert: if a record with the given matching_attribute
    value already exists, it is updated; otherwise a new record is created.

    matching_attribute must be one of:
        "email_addresses" — for object_type "people" (matches on email)
        "domains"         — for object_type "companies" (matches on domain)

    Values format is identical to attio__create_record. Examples:
        people:    {"email_addresses": [{"email_address": "jane@acme.com"}],
                    "name": [{"first_name": "Jane", "last_name": "Doe",
                               "full_name": "Jane Doe"}]}
        companies: {"domains": [{"domain": "acme.com"}],
                    "name": [{"value": "Acme Inc"}]}

    Args:
        object_type: Record type — "people" or "companies".
        values: Attribute values in Attio REST API write format.
        matching_attribute: Attribute to match on for upsert logic.

    Returns:
        Dict with 'record_id', 'object_type', 'upserted' (True if existing
        record was updated, False if a new record was created), and 'data'.
    """
    import httpx

    if matching_attribute not in _VALID_MATCHING_ATTRIBUTES:
        raise ValueError(
            f"Invalid matching_attribute '{matching_attribute}'. "
            f"Must be one of: {sorted(_VALID_MATCHING_ATTRIBUTES)}"
        )

    url = f"{_ATTIO_BASE}/objects/{object_type}/records"
    body: dict[str, Any] = {
        "data": {"values": values},
        "matching_attribute": matching_attribute,
    }

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    if not resp.is_success:
        return {
            "error": f"Attio API error {resp.status_code}: {resp.text}",
            "object_type": object_type,
        }

    record = resp.json().get("data", {})
    record_id = record.get("id", {}).get("record_id", "")
    return {
        "record_id": record_id,
        "object_type": object_type,
        "upserted": resp.status_code == 200,
        "data": record,
    }
```

- [ ] **Step 4: Register `attio__upsert_record` in the `register()` function in `tools/attio.py`**

```python
def register(mcp: Any) -> None:
    """Register Attio override tools on the FastMCP server."""
    mcp.tool()(attio__search_records)
    mcp.tool()(attio__create_record)
    mcp.tool()(attio__upsert_record)
```

- [ ] **Step 5: Run all Attio tests**

```bash
cd remote-gateway && pytest tests/test_attio_tools.py -v
```
Expected: all tests pass (including the new upsert tests).

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/attio.py remote-gateway/tests/test_attio_tools.py
git commit -m "feat: add attio__upsert_record with email/domain matching"
```

---

## Task 7: Wire up, clean up, update config

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Modify: `remote-gateway/mcp_connections.json`
- Modify: `remote-gateway/context/fields/apollo.yaml`
- Modify: `remote-gateway/.env.example`

- [ ] **Step 1: Register Apollo tools in `mcp_server.py`**

In `remote-gateway/core/mcp_server.py`, add the import alongside the other tool imports (after line `from tools import wiza as _wiza_tools`):

```python
from tools import apollo as _apollo_tools  # noqa: E402
```

Add the registration call alongside the others (after `_wiza_tools.register(mcp)`):

```python
_apollo_tools.register(mcp)
```

- [ ] **Step 2: Remove the broken Apollo proxy entry from `mcp_connections.json`**

Open `remote-gateway/mcp_connections.json`. Remove the entire `"apollo"` block:

```json
"apollo": {
  "transport": "http",
  "url": "https://mcp.apollo.io/mcp",
  "rate_limit": { "rpm": 10, "concurrency": 1 },
  "auth": {
    "type": "oauth",
    "access_token": "${APOLLO_ACCESS_TOKEN}",
    "token_url": "https://mcp.apollo.io/api/v1/oauth/token",
    "client_id": "${APOLLO_CLIENT_ID}",
    "refresh_token": "${APOLLO_REFRESH_TOKEN}"
  }
},
```

The resulting `"connections"` object should contain only `"exa"`, `"attio"`, `"github"`, and `"gmail"`.

- [ ] **Step 3: Update `context/fields/apollo.yaml`** — replace TODO stubs with real descriptions

Replace the entire file content:

```yaml
integration: apollo
fields:
  id:
    display_name: Apollo Person ID
    description: Unique Apollo identifier for this person record.
    type: string
    notes: Use this id with apollo__enrich_person to get full contact data.
    nullable: false
  first_name:
    display_name: First Name
    description: Person's first name.
    type: string
    notes: ''
    nullable: true
  last_name:
    display_name: Last Name
    description: Person's last name.
    type: string
    notes: ''
    nullable: true
  name:
    display_name: Full Name
    description: Person's full name (first + last).
    type: string
    notes: ''
    nullable: true
  title:
    display_name: Job Title
    description: Person's current job title at their organization.
    type: string
    notes: ''
    nullable: true
  organization_name:
    display_name: Company Name
    description: Name of the company this person currently works at.
    type: string
    notes: Use organization_id to look up the company record in Apollo.
    nullable: true
  organization_id:
    display_name: Apollo Organization ID
    description: Apollo's unique identifier for the person's current employer.
    type: string
    notes: Use with apollo__enrich_organization (via domain lookup) for full company data.
    nullable: true
  email:
    display_name: Work Email
    description: Person's primary work email address.
    type: string
    notes: ''
    nullable: true
  email_status:
    display_name: Email Status
    description: Verification status of the work email address.
    type: string
    notes: "Values: verified, guessed, unavailable, bounced, pending_manual_fulfillment"
    nullable: true
  linkedin_url:
    display_name: LinkedIn URL
    description: Full URL to the person's LinkedIn profile.
    type: string
    notes: ''
    nullable: true
  city:
    display_name: City
    description: City where this person is located.
    type: string
    notes: ''
    nullable: true
  state:
    display_name: State / Region
    description: State or region where this person is located.
    type: string
    notes: ''
    nullable: true
  country:
    display_name: Country
    description: Country where this person is located.
    type: string
    notes: ''
    nullable: true
  funding_stage:
    display_name: Company Funding Stage
    description: Current funding stage of the person's employer.
    type: string
    notes: "Values: seed, series_a, series_b, series_c, series_d, series_e_plus, ipo"
    nullable: true
  estimated_num_employees:
    display_name: Company Employee Count
    description: Estimated number of employees at the person's current employer.
    type: integer
    notes: ''
    nullable: true
  created_at:
    display_name: Created At
    description: Timestamp when this Apollo record was created.
    type: timestamp
    notes: ''
    nullable: true
  updated_at:
    display_name: Updated At
    description: Timestamp when this Apollo record was last updated.
    type: timestamp
    notes: ''
    nullable: true
  existence_level:
    display_name: Existence Level
    description: Apollo's confidence level that this person record is current and accurate.
    type: string
    notes: ''
    nullable: true
```

- [ ] **Step 4: Update `.env.example`** — replace OAuth vars with `APOLLO_API_KEY`

Find the Apollo block in `remote-gateway/.env.example`:

```
# Apollo.io (proxied via gateway)
# Connect via Claude Code first: add https://mcp.apollo.io/mcp as a remote MCP, complete OAuth,
# then extract from keychain: security find-generic-password -s "Claude Code-credentials" -w
# APOLLO_ACCESS_TOKEN=eyJ...
# APOLLO_REFRESH_TOKEN=...
# APOLLO_CLIENT_ID=...
```

Replace it with:

```
# Apollo.io (direct REST API — no OAuth required)
# Get from: app.apollo.io → Settings → Integrations → API Keys
# APOLLO_API_KEY=your_api_key_here
```

- [ ] **Step 5: Run the full test suite**

```bash
cd remote-gateway && pytest --tb=short -q
```
Expected: all tests pass, no regressions.

- [ ] **Step 6: Start the gateway and verify Apollo tools appear and proxy error is gone**

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

Expected startup output — `[proxy] 'apollo'` line should be **absent**. Apollo tools should appear in `tools/list` as `apollo__search_people`, `apollo__search_companies`, `apollo__enrich_person`, `apollo__enrich_organization`.

- [ ] **Step 7: Commit all**

```bash
git add remote-gateway/core/mcp_server.py \
        remote-gateway/mcp_connections.json \
        remote-gateway/context/fields/apollo.yaml \
        remote-gateway/.env.example
git commit -m "feat: wire Apollo tools, remove broken proxy, update field registry and env docs"
```

---

## Self-Review

**Spec coverage:**
- ✅ `apollo__search_people` with all demographic filters including funding
- ✅ `apollo__search_companies` with all filters
- ✅ `apollo__enrich_person` with identifier validation
- ✅ `apollo__enrich_organization` by domain
- ✅ `_map_to_attio_values` for both person and organization
- ✅ Null stripping on all responses
- ✅ Pre-mapped `attio_values` on enrich responses
- ✅ `agent_hint` on all responses
- ✅ Pagination summary on search responses
- ✅ `attio__upsert_record` with `matching_attribute`
- ✅ `upserted` boolean (200 = updated, 201 = created)
- ✅ All error cases: 401 PermissionError, 422 dict, 429 RuntimeError, missing key ValueError
- ✅ Apollo proxy entry removed from `mcp_connections.json`
- ✅ `apollo.yaml` TODO stubs replaced
- ✅ `.env.example` updated
- ✅ `mcp_server.py` import and registration
