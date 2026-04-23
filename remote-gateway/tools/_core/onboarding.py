"""
Gateway onboarding tools.

Setup flow — always bypasses the init gate. Guides an agent through
org profile creation and marks the gateway as initialized.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register setup_start, setup_save_profile, and setup_complete on mcp.

    Args:
        mcp: FastMCP instance (or stub with .tool() decorator).
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    @mcp.tool()
    def setup_start() -> dict:
        """Check gateway initialization status and return onboarding guidance.

        Call this first. Returns current profile state and next steps.
        Bypasses the init gate — safe to call on an unconfigured gateway.
        """
        org_id = _org_id()
        profile = telemetry.get_org_profile(org_id)
        initialized = telemetry.is_initialized(org_id)
        next_step = (
            "Already initialized. Use profile_get to view current settings."
            if initialized
            else "Call setup_save_profile with your org details, then setup_complete to go live."
        )
        return {
            "org_id": org_id,
            "initialized": initialized,
            "profile": profile,
            "next_step": next_step,
        }

    @mcp.tool()
    def setup_save_profile(fields: dict) -> dict:
        """Save organization profile fields (merged into existing profile).

        Args:
            fields: Dict of profile fields to set. Common fields:
                display_name, tone, icp, vocab_rules.

        Bypasses the init gate.
        """
        org_id = _org_id()
        updated = telemetry.update_org_profile(org_id, fields)
        return {
            "org_id": org_id,
            "saved_fields": list(fields.keys()),
            "current_profile": updated,
        }

    @mcp.tool()
    def setup_complete() -> dict:
        """Mark the organization as initialized and activate the gateway.

        Call after setup_save_profile. After this, the init gate is lifted
        and all tools become available.

        Bypasses the init gate.
        """
        org_id = _org_id()
        telemetry.set_initialized(org_id)
        return {
            "org_id": org_id,
            "initialized": True,
            "message": "Gateway is now active. All tools are available.",
        }
