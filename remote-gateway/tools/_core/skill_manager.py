"""
Skill manager tools — CRUD and execution for dynamic prompt-based skills.

Skills are prompt templates with {variable} placeholders. run_skill renders
the template and returns a string; Claude executes the resulting prompt using
whatever tools are available. Skills don't need to know about tool availability.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register skill CRUD tools and run_skill on mcp.

    Args:
        mcp: FastMCP instance.
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    @mcp.tool()
    def skill_list() -> list[dict]:
        """Return all active skills for this organization.

        Bypasses the init gate — available even before setup.
        """
        return telemetry.list_skills(_org_id())

    @mcp.tool()
    def skill_create(name: str, description: str, prompt_template: str) -> dict:
        """Create a new skill with a prompt template.

        Args:
            name: Unique skill name (no spaces, snake_case recommended).
            description: What this skill does — shown in skill_list.
            prompt_template: Prompt string. Use {variable} for placeholders
                filled at runtime by run_skill.

        Bypasses the init gate.
        """
        user_id = current_user_var.get()
        org_id = _org_id()
        return telemetry.create_skill(org_id, name, description, prompt_template, created_by=user_id)

    @mcp.tool()
    def skill_update(
        name: str,
        description: str | None = None,
        prompt_template: str | None = None,
    ) -> dict:
        """Update an existing skill's description or prompt template.

        Args:
            name: Skill to update.
            description: New description, or omit to leave unchanged.
            prompt_template: New template, or omit to leave unchanged.

        Bypasses the init gate.
        """
        fields: dict = {}
        if description is not None:
            fields["description"] = description
        if prompt_template is not None:
            fields["prompt_template"] = prompt_template
        result = telemetry.update_skill(_org_id(), name, **fields)
        if result is None:
            raise ValueError(f"Skill '{name}' not found or is a system skill.")
        return result

    @mcp.tool()
    def skill_delete(name: str) -> dict:
        """Soft-delete a skill (sets is_active=0). System skills cannot be deleted.

        Args:
            name: Skill to delete.
        """
        if not telemetry.delete_skill(_org_id(), name):
            raise ValueError(f"Skill '{name}' not found or is a system skill.")
        return {"deleted": name}

    @mcp.tool()
    def run_skill(name: str, variables: dict | None = None) -> str:
        """Render a skill's prompt template with variables and return the prompt.

        The returned string is a prompt for you (Claude) to act on. Execute it
        using whatever gateway tools are available.

        Args:
            name: Skill name to render.
            variables: Dict of {placeholder: value} pairs to fill into the template.
        """
        skill = telemetry.get_skill(_org_id(), name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found.")
        template: str = skill["prompt_template"]
        if variables:
            template = template.format(**variables)
        return template
