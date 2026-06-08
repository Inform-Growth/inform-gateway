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

from core.field_registry import registry

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
    query: str | None = None,
    limit: int = 20,
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Search or list Attio records by name.

    Searches companies or people by name using a contains filter against the
    Attio v2 records/query endpoint. Omit query to list all records up to limit.

    Args:
        object_type: Record type to search — "companies" or "people".
        query: Text to search for in the record name field (partial match).
            Omit or pass None to list all records without filtering.
        limit: Maximum number of records to return. Defaults to 20.
        ctx: MCP Context for session state (optional).

    Returns:
        Dict with 'records' list, 'count', and 'object_type'.
        Each record has 'id.record_id' and 'values'.
    """
    import httpx

    # If Context is available, we could track 'last_searched_object'
    # if ctx and hasattr(ctx, 'set_state'):
    #     asyncio.create_task(ctx.set_state("last_searched_object", object_type))

    url = f"{_ATTIO_BASE}/objects/{object_type}/records/query"
    body: dict[str, Any] = {"limit": limit}
    if query:
        # Attio v2 uses $contains for text fields; $str_contains is rejected
        # with "Invalid operator" (issue #55).
        body["filter"] = {"name": {"$contains": query}}

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    if not resp.is_success:
        return {
            "error": f"Attio API error {resp.status_code}: {resp.text}",
            "object_type": object_type,
        }
    data = resp.json().get("data", [])
    return {"records": data, "count": len(data), "object_type": object_type}


def attio__create_record(
    object_type: str,
    values: dict[str, Any],
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Create a new record in Attio.

    Creates a company or person record with the given attribute values using
    the Attio v2 records endpoint. Field names are validated against the field
    registry before any HTTP call is made — unknown or read-only fields return
    a structured error with the list of valid writable fields and a hint.

    Call get_field_definitions("attio-people") or get_field_definitions("attio-companies")
    to see all valid field names, their write_format examples, and which are required.

    Values format for people:
        {"name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]}
        {"email_addresses": [{"email_address": "jane@acme.com"}]}
        {"job_title": [{"value": "Head of Sales"}]}
        {"linkedin": [{"value": "https://linkedin.com/in/janedoe"}]}
        {"phone_numbers": [{"phone_number": "+1-555-555-5555"}]}

    Values format for companies:
        {"name": [{"value": "Acme Inc"}], "domains": [{"domain": "acme.io"}]}

    Company reference fields require target_object alongside target_record_id:
        {"company": [{"target_object": "companies", "target_record_id": "<id>"}]}

    Args:
        object_type: Record type to create — "companies" or "people".
        values: Attribute values in Attio REST API format (see docstring examples).
        ctx: MCP Context for session state (optional).

    Returns:
        Dict with 'record_id', 'object_type', and 'data' (the created record).
        On validation failure, returns 'error', 'valid_writable_fields', and 'hint'.
    """
    import httpx

    # Pre-flight: validate field names against the registry
    integration = f"attio-{object_type}"
    field_defs = registry.get_all(integration)

    if field_defs:
        writable_fields = {k for k, v in field_defs.items() if v.get("writable", True)}
        invalid = [k for k in values if k not in writable_fields]

        if invalid:
            return {
                "error": f"Invalid or read-only field(s) for {object_type}: {invalid}",
                "valid_writable_fields": sorted(writable_fields),
                "hint": (
                    f"Call get_field_definitions('{integration}') to see correct field "
                    "names and write_format examples."
                ),
            }

    url = f"{_ATTIO_BASE}/objects/{object_type}/records"
    body: dict[str, Any] = {"data": {"values": values}}

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    record = result.get("data", {})
    record_id = record.get("id", {}).get("record_id", "")
    return {"record_id": record_id, "object_type": object_type, "data": record}


_VALID_MATCHING_ATTRIBUTES = frozenset({"email_addresses", "domains"})


def attio__update_record(
    object_type: str,
    record_id: str,
    values: dict[str, Any],
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Patch attribute values on an existing Attio record.

    Replaces the attio-mcp npm package's update_record, which wrapped Attio
    errors in opaque 400s and used inconsistent resource_type pluralization
    (see issue #54). This version PATCHes /v2/objects/{object_type}/records/
    {record_id} directly and surfaces the underlying Attio error body verbatim.

    Args:
        object_type: Record type — "people" or "companies" (always plural).
        record_id: Attio record UUID to update.
        values: Attribute values in Attio REST write format (same shape as
            attio__upsert_record). Only the fields you pass are updated;
            omitted fields are left untouched.
        ctx: MCP Context for session state (optional).

    Returns:
        Dict with 'record_id', 'object_type', and 'data' (the updated record).
        On Attio rejection, returns {'error': '<status> <full response body>',
        'object_type': ...} — the full body is surfaced so the agent can see
        which field was invalid.
    """
    import httpx

    integration = f"attio-{object_type}"
    field_defs = registry.get_all(integration)
    if field_defs:
        writable_fields = {k for k, v in field_defs.items() if v.get("writable", True)}
        invalid = [k for k in values if k not in writable_fields]
        if invalid:
            return {
                "error": f"Invalid or read-only field(s) for {object_type}: {invalid}",
                "valid_writable_fields": sorted(writable_fields),
                "hint": (
                    f"Call get_field_definitions('{integration}') to see correct field "
                    "names and write_format examples."
                ),
            }

    url = f"{_ATTIO_BASE}/objects/{object_type}/records/{record_id}"
    body: dict[str, Any] = {"data": {"values": values}}

    with httpx.Client() as client:
        resp = client.patch(url, headers=_headers(), json=body)

    if not resp.is_success:
        return {
            "error": f"Attio API error {resp.status_code}: {resp.text}",
            "object_type": object_type,
            "record_id": record_id,
        }

    record = resp.json().get("data", {})
    return {
        "record_id": record.get("id", {}).get("record_id", record_id),
        "object_type": object_type,
        "data": record,
    }


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


def attio__create_task(
    content: str,
    assignee_id: str | None = None,
    deadline_at: str | None = None,
    linked_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a task in Attio.

    Creates a task using the Attio v2 tasks endpoint (POST /v2/tasks). Tasks
    are a first-class resource — distinct from object records — so this tool
    replaces the broken attio__batch_records workaround for task creation.

    Args:
        content: Task description (required).
        assignee_id: Workspace member UUID to assign the task to.
        deadline_at: ISO 8601 deadline (e.g. "2026-06-08T23:59:59.000Z").
        linked_records: List of record references, each a dict with
            "target_object" (e.g. "companies") and "target_record_id" (UUID).

    Returns:
        Dict with 'task_id', 'content', and 'data' (full Attio task object).
        On failure, returns {'error': 'Attio API error {status}: {body}'}.
    """
    import httpx

    payload: dict[str, Any] = {
        "content": content,
        "format": "plaintext",
        "is_completed": False,
        "assignees": (
            [{"referenced_actor_type": "workspace-member", "referenced_actor_id": assignee_id}]
            if assignee_id is not None
            else []
        ),
    }
    if deadline_at is not None:
        payload["deadline_at"] = deadline_at
    if linked_records is not None:
        payload["linked_records"] = linked_records

    url = f"{_ATTIO_BASE}/tasks"
    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json={"data": payload})

    if not resp.is_success:
        return {"error": f"Attio API error {resp.status_code}: {resp.text}"}

    task = resp.json().get("data", {})
    return {
        "task_id": task.get("id", {}).get("task_id", ""),
        "content": task.get("content", content),
        "data": task,
    }


def attio__list_tasks(
    assignee_id: str | None = None,
    is_completed: bool | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List tasks from Attio, with optional filtering.

    Fetches tasks using the Attio v2 tasks endpoint (GET /v2/tasks). Filter
    by assignee or completion status to narrow results.

    Args:
        assignee_id: Workspace member UUID — return only tasks assigned to
            this member. Omit to return tasks for all assignees.
        is_completed: True to return only completed tasks, False for only
            incomplete tasks. Omit to return both.
        limit: Maximum number of tasks to return. Defaults to 20.

    Returns:
        Dict with 'tasks' (list of Attio task objects) and 'count'.
    """
    import httpx

    params: dict[str, Any] = {"limit": limit}
    if assignee_id is not None:
        params["filter[assignees]"] = assignee_id
    if is_completed is not None:
        params["filter[is_completed]"] = is_completed

    url = f"{_ATTIO_BASE}/tasks"
    with httpx.Client() as client:
        resp = client.get(url, headers=_headers(), params=params)

    if not resp.is_success:
        return {"error": f"Attio API error {resp.status_code}: {resp.text}"}

    data = resp.json().get("data", [])
    return {"tasks": data, "count": len(data)}


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
    mcp.tool()(attio__update_record)
    mcp.tool()(attio__upsert_record)
    mcp.tool()(attio__create_task)
    mcp.tool()(attio__list_tasks)
