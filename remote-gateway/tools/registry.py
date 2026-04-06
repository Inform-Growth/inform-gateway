"""
Field registry tools — lookup, drift detection, and discovery.

These tools expose the gateway's field registry to connected agents,
allowing them to look up field definitions, detect schema drift, and
generate definitions for new integrations.
"""
from __future__ import annotations

from typing import Any


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


def make_list_field_integrations(registry: Any):
    """Return a list_field_integrations tool function bound to the given registry."""

    def list_field_integrations() -> dict:
        """List all integrations that have field definitions in the registry.

        Returns:
            Dict with 'integrations' key containing a sorted list of slugs.
        """
        return {"integrations": registry.list_integrations()}

    return list_field_integrations


def make_lookup_field(registry: Any):
    """Return a lookup_field tool function bound to the given registry."""

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

    return lookup_field


def make_get_field_definitions(registry: Any):
    """Return a get_field_definitions tool function bound to the given registry."""

    def get_field_definitions(integration: str) -> dict:
        """Return all field definitions for an integration.

        Args:
            integration: Integration slug (e.g., "stripe", "hubspot").

        Returns:
            Dict with 'integration' and 'fields' keys, or empty fields if unknown.
        """
        return {"integration": integration, "fields": registry.get_all(integration)}

    return get_field_definitions


def make_check_field_drift(registry: Any):
    """Return a check_field_drift tool function bound to the given registry."""

    def check_field_drift(integration: str, fresh_sample: dict[str, Any]) -> dict:
        """Compare a current API/MCP response against the stored field definitions.

        Run this periodically or when you suspect an integration has changed its
        schema. Returns a diff of new, removed, and unchanged fields.

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

    return check_field_drift


def make_discover_fields(registry: Any):
    """Return a discover_fields tool function bound to the given registry."""

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
                continue

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

    return discover_fields


def register(mcp: Any, registry: Any) -> None:
    """Register all field registry tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
        registry: The FieldRegistry instance from field_registry.py.
    """
    mcp.tool()(make_list_field_integrations(registry))
    mcp.tool()(make_lookup_field(registry))
    mcp.tool()(make_get_field_definitions(registry))
    mcp.tool()(make_check_field_drift(registry))
    mcp.tool()(make_discover_fields(registry))
