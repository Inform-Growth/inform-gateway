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


def apollo__search_companies(**_): raise NotImplementedError


def apollo__enrich_person(**_): raise NotImplementedError


def apollo__enrich_organization(**_): raise NotImplementedError


def register(mcp: Any) -> None:
    """Register Apollo tools on the FastMCP server."""
    mcp.tool()(apollo__search_people)
    mcp.tool()(apollo__search_companies)
    mcp.tool()(apollo__enrich_person)
    mcp.tool()(apollo__enrich_organization)
