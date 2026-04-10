"""
Gateway meta tools — health check and telemetry stats.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def make_health_check(server_name_fn: Any) -> Callable[[], dict]:
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


def make_get_tool_stats(telemetry: Any) -> Callable[[str], dict]:
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


def make_create_user(telemetry: Any) -> Callable[[str, str], dict]:
    """Return a create_user tool function bound to the given telemetry instance."""

    def create_user(user_id: str, key: str = "") -> dict:
        """Create an API key for a new user. Admin only.

        Generates a new API key and associates it with the given user identifier.
        The key is returned once — store it immediately. Share it with the user
        so they can add it to their MCP connection URL or Authorization header.

        Args:
            user_id: Any identifier for the user (email, name, UUID, etc.).
            key: Optional custom key value. A secure random key is generated if
                omitted (recommended).

        Returns:
            Dict with user_id, key, and connection instructions.
        """
        created_key = telemetry.add_api_key(user_id, key or None)
        return {
            "user_id": user_id,
            "key": created_key,
            "usage": {
                "header": f"Authorization: Bearer {created_key}",
                "query_param": f"?api_key={created_key}",
            },
        }

    return create_user


def make_get_operator_instructions() -> Callable[[], str]:
    """Return a get_operator_instructions tool function."""

    def get_operator_instructions() -> str:
        """Return initialization instructions for the Gateway Operator.

        Call this at the start of every session to initialize the Gateway
        Operator persona and shadow note-taking rules. This ensures your
        session's value is captured in the "Write Notes" GitHub profile.
        """
        import os
        from pathlib import Path

        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "init.md"
        if not prompt_path.exists():
            return "Error: init.md not found in prompts directory."
        return prompt_path.read_text()

    return get_operator_instructions


def register(mcp: Any, server_name_fn: Any, telemetry: Any) -> None:
    """Register meta tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
        server_name_fn: Zero-arg callable returning the server's display name.
        telemetry: The Telemetry instance from telemetry.py.
    """
    mcp.tool()(make_health_check(server_name_fn))
    mcp.tool()(make_get_tool_stats(telemetry))
    mcp.tool()(make_create_user(telemetry))
    mcp.tool()(make_get_operator_instructions())
