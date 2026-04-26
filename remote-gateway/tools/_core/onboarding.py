"""
Gateway onboarding tools.

Setup flow — always bypasses the init gate. Guides an agent through
org profile creation and marks the gateway as initialized.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any


def _slugify(name: str) -> str:
    """Convert a display name to a lowercase hyphenated slug, e.g. 'Camber Core' → 'camber-core'."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


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
        if initialized:
            next_step = "Already initialized. Use profile_get to view current settings."
            questions = []
        else:
            next_step = (
                "AGENT INSTRUCTION: Ask the user the questions in 'questions_to_ask' "
                "conversationally (not as a numbered list). Collect all answers, then call "
                "setup_save_profile with the gathered fields, and finally call setup_complete."
            )
            questions = [
                "What is your organization's name?",
                "Who are your ideal customers? (industry, company size, job title)",
                "What tone should the AI use in communications? (e.g. professional, friendly, direct)",
                "Any words or phrases the AI should always avoid or always prefer?",
            ]
        return {
            "org_id": org_id,
            "initialized": initialized,
            "profile": profile,
            "next_step": next_step,
            "questions_to_ask": questions,
        }

    @mcp.tool()
    def setup_save_profile(fields: dict) -> dict:
        """Save organization profile fields (merged into existing profile).

        Args:
            fields: Dict of profile fields to set. Map user answers to these keys:
                display_name (str): Organization name — also sets the org_id slug.
                tone (str): Communication style, e.g. "professional and direct".
                icp (str): Ideal customer profile, e.g. "RevOps leaders at mid-market SaaS".
                vocab_rules (str): Words/phrases to avoid or prefer, e.g. "avoid: leverage, synergies".

        Bypasses the init gate.
        """
        user_id = current_user_var.get()
        if user_id and "display_name" in fields:
            new_org_id = _slugify(fields["display_name"])
            telemetry.set_user_org_id(user_id, new_org_id)
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
