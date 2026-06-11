"""
Gateway meta tools — health check and telemetry stats.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def check_google_auth() -> str:
    """Report Google credential health by exercising the refresh token.

    Returns one of:
      - "not_configured" — no GOOGLE_APPLICATION_CREDENTIALS env var
      - "ok" — authorized_user refresh token successfully exchanged
      - "configured (service_account key; not validated)" — legacy SA key present
      - "failing: <reason>" — unreadable file, rejected token, or network error
    """
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        return "not_configured"
    try:
        info = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return f"failing: credentials file unreadable ({exc})"
    if info.get("type") != "authorized_user":
        return "configured (service_account key; not validated)"
    try:
        resp = httpx.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": info.get("client_id", ""),
                "client_secret": info.get("client_secret", ""),
                "refresh_token": info.get("refresh_token", ""),
            },
            timeout=10,
        )
    except httpx.HTTPError as exc:
        return f"failing: token endpoint unreachable ({exc})"
    if resp.status_code == 200:
        return "ok"
    try:
        reason = resp.json().get("error", str(resp.status_code))
    except ValueError:
        reason = str(resp.status_code)
    return f"failing: {reason}"


def make_health_check(server_name_fn: Any) -> Callable[[], dict]:
    """Return a health_check tool function that reads server name at call time.

    Args:
        server_name_fn: Zero-arg callable returning the server's display name.
    """

    def health_check() -> dict:
        """Check that the Gateway MCP server is running and responsive.

        Also reports Google credential health when configured: 'google_auth' is
        "ok", "not_configured", or "failing: <reason>" — a failing value means
        the OAuth refresh token was revoked and needs a re-consent (run
        scripts/google_auth_setup.py and update GOOGLE_ADC_JSON).

        Returns:
            A dict with status, server name, and google_auth.
        """
        return {
            "status": "ok",
            "server": server_name_fn(),
            "google_auth": check_google_auth(),
        }

    return health_check


def make_get_tool_stats(telemetry: Any) -> Callable[[str], dict]:
    """Return a get_tool_stats tool function bound to the given telemetry instance."""

    def get_tool_stats(tool_name: str = "") -> dict:
        """Return call statistics for all gateway tools.

        Use this to monitor tool health: identify tools with high error rates
        (possible API degradation), tools that have never been called (stale
        candidates for deprecation), and overall call volume.

        Stats reset if the gateway is redeployed without a persistent database.
        For persistent history on Railway or Render, set DATABASE_URL to a
        PostgreSQL connection string (e.g., postgresql://user:pass@host/dbname).

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
        """Create an API key for a new user. Admin only (role='admin').

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
        from mcp_server import _require_admin

        _require_admin()
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
        from pathlib import Path

        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "init.md"
        if not prompt_path.exists():
            return "Error: init.md not found in prompts directory."
        return prompt_path.read_text()

    return get_operator_instructions


def make_get_session_usage(telemetry: Any) -> Callable[[int], dict]:
    """Return a get_session_usage tool function bound to the given telemetry instance."""

    def get_session_usage(limit: int = 100) -> dict:
        """Analyze tool call sequences and user-level usage breakdown.

        Use this to understand how operators are interacting with the gateway:
        the order in which tools are called (sequences) and the distribution
        of work across different users.

        Args:
            limit: Maximum number of recent calls to include in the sequence analysis.

        Returns:
            Dict with 'recent_sequences' (calls grouped by user) and 'user_breakdown'.
        """
        return telemetry.session_usage(limit)

    return get_session_usage


def register(mcp: Any, server_name_fn: Any, telemetry: Any) -> None:
    """Register meta tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
        server_name_fn: Zero-arg callable returning the server's display name.
        telemetry: The Telemetry instance from telemetry.py.
    """
    mcp.tool()(make_health_check(server_name_fn))
    mcp.tool()(make_get_tool_stats(telemetry))
    mcp.tool()(make_get_session_usage(telemetry))
    mcp.tool()(make_create_user(telemetry))
    mcp.tool()(make_get_operator_instructions())
