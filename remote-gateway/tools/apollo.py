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


def apollo__search_people(**_): raise NotImplementedError
def apollo__search_companies(**_): raise NotImplementedError
def apollo__enrich_person(**_): raise NotImplementedError
def apollo__enrich_organization(**_): raise NotImplementedError


def register(mcp: Any) -> None:
    """Register Apollo tools on the FastMCP server."""
    mcp.tool()(apollo__search_people)
    mcp.tool()(apollo__search_companies)
    mcp.tool()(apollo__enrich_person)
    mcp.tool()(apollo__enrich_organization)
