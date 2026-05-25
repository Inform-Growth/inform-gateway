"""Admin-gated MCP tools — user listing, role management, bulk permission grants.

All tools call _require_admin() before touching telemetry. The check resolves
the caller via mcp_server._resolve_user_from_request_ctx() with a ContextVar
fallback. Non-admin callers receive PermissionError; the telemetry patch in
mcp_server.py records the failure with error_type="PermissionError".
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _admin_check() -> str:
    """Lazy import to avoid a circular import with mcp_server at module load."""
    from mcp_server import _require_admin

    return _require_admin()


def make_list_users(telemetry: Any) -> Callable[[], dict]:
    def list_users() -> dict:
        """List all gateway users with their role and activity. Admin only.

        Returns:
            Dict with 'users': list of {user_id, role, created_at, call_count, last_active}.
        """
        _admin_check()
        return {"users": telemetry.list_users()}

    return list_users


def make_set_user_role(telemetry: Any) -> Callable[[str, str], dict]:
    def set_user_role(user_id: str, role: str) -> dict:
        """Set a user's role. Admin only.

        Args:
            user_id: The user whose role to update.
            role: 'user' or 'admin'. Other values are rejected.

        Returns:
            Dict with user_id and role.
        """
        _admin_check()
        telemetry.set_user_role(user_id, role)
        return {"user_id": user_id, "role": role}

    return set_user_role


def make_set_tool_permission(
    telemetry: Any,
) -> Callable[[str, list[dict]], dict]:
    def set_tool_permission(user_id: str, permissions: list[dict]) -> dict:
        """Bulk grant/revoke per-tool access for a user. Admin only.

        Args:
            user_id: The user whose tool allowlist to modify.
            permissions: List of {"tool_name": str, "enabled": bool}.
                tool_name uses the gateway-exposed name (e.g.
                "apollo__enrich_organization"). enabled=False denies.

        Returns:
            Dict with user_id and the count of upserts applied.
        """
        _admin_check()
        applied = 0
        for entry in permissions:
            telemetry.set_tool_permission(
                user_id, entry["tool_name"], bool(entry["enabled"])
            )
            applied += 1
        return {"user_id": user_id, "applied": applied}

    return set_tool_permission


def make_set_skill_permission(
    telemetry: Any,
) -> Callable[[str, list[dict]], dict]:
    def set_skill_permission(user_id: str, permissions: list[dict]) -> dict:
        """Bulk grant/revoke per-skill access for a user. Admin only.

        Args:
            user_id: The user whose skill allowlist to modify.
            permissions: List of {"skill_name": str, "enabled": bool}.

        Returns:
            Dict with user_id and the count of upserts applied.
        """
        _admin_check()
        applied = 0
        for entry in permissions:
            telemetry.set_skill_permission(
                user_id, entry["skill_name"], bool(entry["enabled"])
            )
            applied += 1
        return {"user_id": user_id, "applied": applied}

    return set_skill_permission


def register(mcp: Any, telemetry: Any) -> None:
    """Register the four admin MCP tools on the given FastMCP server instance."""
    mcp.tool()(make_list_users(telemetry))
    mcp.tool()(make_set_user_role(telemetry))
    mcp.tool()(make_set_tool_permission(telemetry))
    mcp.tool()(make_set_skill_permission(telemetry))
