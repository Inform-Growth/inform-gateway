"""
Org profile manager tools — read and patch organization profile.

Profile fields are free-form (stored as JSON). Common fields: display_name,
tone, icp, vocab_rules. The admin UI's Profile tab writes here too.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register profile_get and profile_update on mcp.

    Args:
        mcp: FastMCP instance.
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    @mcp.tool()
    def profile_get() -> dict:
        """Return the current organization profile.

        Bypasses the init gate.
        """
        org_id = _org_id()
        return {"org_id": org_id, "profile": telemetry.get_org_profile(org_id)}

    @mcp.tool()
    def profile_update(fields: dict) -> dict:
        """Patch organization profile fields (merged into existing values).

        Args:
            fields: Dict of fields to set. Common keys:
                display_name (str), tone (str), icp (str),
                vocab_rules (str), notes (str).

        Bypasses the init gate.
        """
        org_id = _org_id()
        updated = telemetry.update_org_profile(org_id, fields)
        return {"org_id": org_id, "profile": updated}
