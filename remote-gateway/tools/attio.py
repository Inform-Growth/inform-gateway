"""
Direct Attio REST API tools — Python overrides for attio-mcp npm package bugs.

The attio-mcp npm package sends malformed payloads for search_records and
create_record. These Python implementations call the Attio v2 REST API
directly. The npm proxy is configured via mcp_connections.json to deny these
two tool names; these tools fill the gap.

Required env vars:
    ATTIO_API_KEY — Attio workspace API token (Bearer token)

Note: These tools do not call validated("attio", result) because no field
definitions exist yet in remote-gateway/context/fields/attio.yaml. Once
field definitions are added, wrap the return value of each function with
validated("attio", result) from mcp_server.py.
"""
from __future__ import annotations

import os
from typing import Any

_ATTIO_BASE = "https://api.attio.com/v2"


def _headers() -> dict[str, str]:
    """Return Attio API request headers using ATTIO_API_KEY from env."""
    api_key = os.environ.get("ATTIO_API_KEY")
    if not api_key:
        raise ValueError("ATTIO_API_KEY environment variable is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def attio__search_records(
    object_type: str,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Search Attio records by name.

    Searches companies or people by name using a contains filter against the
    Attio v2 records/query endpoint. Returns matching records with their IDs
    and attribute values.

    Args:
        object_type: Record type to search — "companies" or "people".
        query: Text to search for in the record name field (partial match).
        limit: Maximum number of records to return. Defaults to 20.

    Returns:
        Dict with 'records' list, 'count', and 'object_type'.
        Each record has 'id.record_id' and 'values'.
    """
    import httpx

    url = f"{_ATTIO_BASE}/objects/{object_type}/records/query"
    body: dict[str, Any] = {
        "filter": {"name": {"$str_contains": query}},
        "limit": limit,
    }

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    resp.raise_for_status()
    data = resp.json().get("data", [])
    return {"records": data, "count": len(data), "object_type": object_type}


def attio__create_record(
    object_type: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Create a new record in Attio.

    Creates a company or person record with the given attribute values using
    the Attio v2 records endpoint.

    Values format for companies:
        {"name": [{"value": "Acme Inc"}], "domains": [{"domain": "acme.io"}]}

    Values format for people — ALL THREE name subfields required:
        {"name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]}

    Company reference fields require target_object alongside target_record_id:
        {"company": [{"target_object": "companies", "target_record_id": "<id>"}]}

    Args:
        object_type: Record type to create — "companies" or "people".
        values: Attribute values in Attio REST API format (see docstring examples).

    Returns:
        Dict with 'record_id', 'object_type', and 'data' (the created record).
    """
    import httpx

    url = f"{_ATTIO_BASE}/objects/{object_type}/records"
    body: dict[str, Any] = {"data": {"values": values}}

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    record = result.get("data", {})
    record_id = record.get("id", {}).get("record_id", "")
    return {"record_id": record_id, "object_type": object_type, "data": record}


def register(mcp: Any) -> None:
    """Register Attio override tools on the FastMCP server.

    These tools replace the broken attio-mcp npm package implementations
    for search_records and create_record. The npm proxy is configured to
    deny these tool names in mcp_connections.json so only these Python
    versions are registered.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(attio__search_records)
    mcp.tool()(attio__create_record)
