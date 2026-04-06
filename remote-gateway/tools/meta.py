"""
Gateway meta tools — health check and telemetry stats.
"""
from __future__ import annotations

from typing import Any


def make_health_check(server_name_fn: Any):
    """Return a health_check tool function that reads server name at call time.

    Args:
        server_name_fn: Zero-arg callable returning the server's display name.
    """

    def health_check() -> dict:
        """Check that the Gateway MCP server is running and responsive.

        Returns:
            A dict with status and server name.
        """
        return {"status": "ok", "server": server_name_fn()}

    return health_check


def make_get_tool_stats(telemetry: Any):
    """Return a get_tool_stats tool function bound to the given telemetry instance."""

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
        return telemetry.stats(tool_name or None)

    return get_tool_stats


def register(mcp: Any, server_name_fn: Any, telemetry: Any) -> None:
    """Register meta tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
        server_name_fn: Zero-arg callable returning the server's display name.
        telemetry: The Telemetry instance from telemetry.py.
    """
    mcp.tool()(make_health_check(server_name_fn))
    mcp.tool()(make_get_tool_stats(telemetry))
