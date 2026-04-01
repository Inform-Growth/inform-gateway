"""
Agent Gateway — Central MCP Server

Hosts promoted, QA-approved tools as official MCP endpoints.
All tools are read-only by default unless explicitly granted write permission.

On startup, also proxies upstream MCP servers defined in mcp_connections.json,
re-exposing their tools under the naming convention ``<integration>__<tool_name>``.
Employees connect only to this gateway — no vendor credentials on their machines.

Run with:
    python remote-gateway/core/mcp_server.py
    # or via mcp CLI:
    mcp run remote-gateway/core/mcp_server.py
"""

from __future__ import annotations

import asyncio
import functools
import os
import time as _time
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from field_registry import registry
from mcp_proxy import mount_all_proxies
from telemetry import telemetry as _telemetry


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Start upstream MCP proxy connections on startup; clean up on shutdown."""
    proxy_tasks = await mount_all_proxies(server)
    yield
    for task in proxy_tasks:
        task.cancel()
    if proxy_tasks:
        await asyncio.gather(*proxy_tasks, return_exceptions=True)


mcp = FastMCP(
    os.environ.get("MCP_SERVER_NAME", "inform-gateway"),
    lifespan=lifespan,
    host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
)


# ---------------------------------------------------------------------------
# Telemetry — patches mcp.tool() so every registered tool is tracked.
# Applies automatically to built-in and promoted tools; no per-tool changes
# needed. Uses functools.wraps so FastMCP sees the original function signature.
# ---------------------------------------------------------------------------

_orig_mcp_tool = mcp.tool


def _tracked_mcp_tool(*args: Any, **kwargs: Any) -> Any:
    """Replacement for mcp.tool() that injects timing and error recording."""
    fastmcp_decorator = _orig_mcp_tool(*args, **kwargs)

    def wrapper(fn: Any) -> Any:
        @functools.wraps(fn)
        def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            try:
                result = fn(*fn_args, **fn_kwargs)
                _telemetry.record(fn.__name__, int((_time.monotonic() - t0) * 1000), True)
                return result
            except Exception as exc:
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__
                )
                raise

        return fastmcp_decorator(tracked)

    return wrapper


mcp.tool = _tracked_mcp_tool


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------


def validated(integration: str, response: dict[str, Any]) -> dict[str, Any]:
    """Validate a tool response against the field registry and return it.

    Attaches a '_field_validation' key only when drift is detected, so
    callers can surface unknowns without blocking the response. In clean
    state the response passes through unchanged.

    Args:
        integration: Integration slug (e.g., "stripe").
        response: The raw dict returned by a promoted tool.

    Returns:
        The original response, with '_field_validation' appended if drift found.
    """
    result = registry.validate_response(integration, response)
    if not result.valid:
        response["_field_validation"] = result.summary()
    return response


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


@mcp.tool()
def health_check() -> dict:
    """Check that the Gateway MCP server is running and responsive.

    Returns:
        A dict with status and server name.
    """
    return {
        "status": "ok",
        "server": mcp.name,
    }


@mcp.tool()
def get_tool_stats(tool_name: str = "") -> dict:
    """Return call statistics for all gateway tools.

    Use this to monitor tool health: identify tools with high error rates
    (possible API degradation), tools that have never been called (stale
    candidates for deprecation), and overall call volume.

    Stats reset if the gateway is redeployed without a persistent volume.
    For persistent history on Railway or Render, set TELEMETRY_DB_PATH to a
    path on a mounted volume (e.g., /data/telemetry.db).

    Args:
        tool_name: Filter to a specific tool by name, or leave empty for all.

    Returns:
        Dict with 'tools' list and 'summary'. Each tool entry includes
        call_count, error_count, error_rate, last_called, avg_duration_ms,
        and max_duration_ms. summary.high_error_rate lists tools with
        ≥5% error rate over ≥10 calls.
    """
    return _telemetry.stats(tool_name or None)


# ---------------------------------------------------------------------------
# Field Registry tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_field_integrations() -> dict:
    """List all integrations that have field definitions in the registry.

    Returns:
        Dict with 'integrations' key containing a sorted list of slugs.
    """
    return {"integrations": registry.list_integrations()}


@mcp.tool()
def lookup_field(integration: str, field_name: str) -> dict:
    """Return the business context definition for a specific field.

    Use this when a tool returns a field whose meaning is unclear. The
    registry maps technical field names to business definitions, types,
    and any calculation notes.

    Args:
        integration: Integration slug (e.g., "stripe", "hubspot").
        field_name: Exact field key as returned by the integration.

    Returns:
        Field definition dict, or a 'not_found' status if undefined.
    """
    definition = registry.lookup(integration, field_name)
    if definition is None:
        return {
            "status": "not_found",
            "integration": integration,
            "field": field_name,
            "message": (
                f"'{field_name}' is not in the registry for '{integration}'. "
                "Run discover_fields() to generate definitions for new integrations."
            ),
        }
    return {"integration": integration, "field": field_name, "definition": definition}


@mcp.tool()
def get_field_definitions(integration: str) -> dict:
    """Return all field definitions for an integration.

    Args:
        integration: Integration slug (e.g., "stripe", "hubspot").

    Returns:
        Dict with 'integration' and 'fields' keys, or empty fields if unknown.
    """
    return {
        "integration": integration,
        "fields": registry.get_all(integration),
    }


@mcp.tool()
def check_field_drift(integration: str, fresh_sample: dict[str, Any]) -> dict:
    """Compare a current API/MCP response against the stored field definitions.

    Run this periodically or when you suspect an integration has changed its
    schema. Returns a diff of new, removed, and unchanged fields. If drift is
    detected, the YAML file in remote-gateway/context/fields/ should be
    reviewed and updated via discover_fields().

    Args:
        integration: Integration slug (e.g., "stripe").
        fresh_sample: A current response dict from the integration to compare.

    Returns:
        Drift report with new_fields, removed_fields, unchanged_fields, and
        has_drift flag.
    """
    result = registry.check_drift(integration, fresh_sample)
    return {
        "integration": integration,
        "has_drift": result.has_drift,
        "new_fields": result.new_fields,
        "removed_fields": result.removed_fields,
        "unchanged_fields": result.unchanged_fields,
        "summary": result.summary(),
    }


@mcp.tool()
def discover_fields(integration: str, sample_response: dict[str, Any]) -> dict:
    """Generate field definitions for a new integration from a sample response.

    Call this when adding a new MCP or API integration. Pass in a real
    response sample; the tool creates a YAML entry for each field, using
    field names and values to infer types. Business descriptions are left
    as placeholders — an admin or AI agent should enrich them after discovery.

    Existing field definitions are never overwritten; only new fields are added.

    Args:
        integration: Integration slug for the new source (e.g., "hubspot").
        sample_response: A representative response dict from the integration.

    Returns:
        Dict with the fields that were discovered and written to the registry.
    """
    discovered: dict[str, Any] = {}

    for key, value in sample_response.items():
        if registry.lookup(integration, key) is not None:
            continue  # already defined, skip

        inferred_type = _infer_type(key, value)
        discovered[key] = {
            "display_name": key.replace("_", " ").title(),
            "description": f"TODO: Add business description for '{key}'.",
            "type": inferred_type,
            "notes": "",
            "nullable": value is None,
        }

    if discovered:
        registry.upsert(integration, {"integration": integration, "fields": discovered})

    return {
        "integration": integration,
        "discovered_count": len(discovered),
        "fields": list(discovered.keys()),
        "message": (
            f"Discovered {len(discovered)} new field(s) for '{integration}'. "
            "Update 'description' and 'notes' in "
            f"remote-gateway/context/fields/{integration}.yaml."
        )
        if discovered
        else f"No new fields found — '{integration}' registry is up to date.",
    }


# ---------------------------------------------------------------------------
# Promoted tools go below this line.
#
# Migration pattern:
#   1. Copy the function from local-workspace/tools/<script>.py
#   2. Decorate with @mcp.tool()
#   3. Wrap the return value with validated("<integration>", result) so the
#      field registry automatically checks the response on every call.
#   4. Ensure all credentials use os.environ (never hardcode)
#   5. Verify the docstring is clear — it becomes the MCP tool description
#
# Example:
#
#   @mcp.tool()
#   def get_churn_metrics(period: str = "30d") -> dict:
#       """Fetch customer churn metrics from Stripe for a given period.
#
#       Args:
#           period: Time window for churn calculation (e.g., "7d", "30d", "90d").
#
#       Returns:
#           Dict with churn_rate, churned_customers, and total_customers.
#       """
#       result = {...}  # fetch from Stripe
#       return validated("stripe", result)
#
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_type(key: str, value: Any) -> str:
    """Infer a semantic field type from key name and value."""
    if value is None:
        return "unknown"

    key_lower = key.lower()

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        if any(k in key_lower for k in ("amount", "price", "revenue", "mrr", "arr", "value")):
            return "currency_usd"
        if any(k in key_lower for k in ("rate", "percent", "ratio", "pct")):
            return "percentage"
        return "number"
    if isinstance(value, str):
        if any(k in key_lower for k in ("_at", "_date", "timestamp", "created", "updated")):
            return "timestamp"
        if any(k in key_lower for k in ("_id", "uuid", "key")):
            return "id"
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"

    return "unknown"


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        mcp.run(transport="sse")
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
