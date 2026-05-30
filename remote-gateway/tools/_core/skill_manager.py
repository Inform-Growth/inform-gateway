"""
Skill manager tools — CRUD and execution for dynamic prompt-based skills.

Skills are prompt templates with {variable} placeholders. run_skill renders
the template and returns a string; Claude executes the resulting prompt using
whatever tools are available. Skills don't need to know about tool availability.
"""
from __future__ import annotations

import contextvars
import hashlib
from collections.abc import Callable
from typing import Any


def _skill_embed_source(name: str, description: str) -> str:
    return f"{name}\n{description}"


def _skill_embed_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def register(
    mcp: Any,
    telemetry: Any,
    current_user_var: contextvars.ContextVar,
    embed_fn: Callable[[str], list[float] | None] | None = None,
) -> None:
    """Register skill CRUD tools and run_skill on mcp.

    Args:
        mcp: FastMCP instance.
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    def _try_embed(org_id: str, name: str, description: str) -> None:
        """Compute and store a skill embedding; silently no-ops on any failure."""
        if embed_fn is None:
            return
        try:
            source = _skill_embed_source(name, description)
            new_hash = _skill_embed_hash(source)
            if new_hash == telemetry.get_skill_embed_hash(org_id, name):
                return  # hash-gate: skip if description unchanged
            vec = embed_fn(source)
            if vec is not None:
                telemetry.store_skill_embedding(org_id, name, vec, new_hash)
        except Exception:
            pass  # fail open — never let embedding block skill writes

    @mcp.tool()
    def skill_list(
        prefix: str | None = None,
        name_only: bool = False,
    ) -> list[dict]:
        """Return active, permitted skills for the calling user.

        Use filters to avoid token-limit issues on large skill catalogs — the
        full catalog can exceed 77K characters. Combine ``prefix`` and
        ``name_only`` to get a minimal index under 2K characters.

        Bypasses the init gate — available even before setup. Skills disabled for
        the user (or globally via '*') are filtered out.

        Args:
            prefix: Return only skills whose name starts with this string
                (e.g. ``"role_"`` for role skills, ``"brief_"`` for briefs).
            name_only: If True, return only the ``name`` field and omit
                ``description``, ``prompt_template``, and other metadata.
                Reduces payload by ~95% on a typical catalog.
        """
        user_id = current_user_var.get()
        skills = telemetry.list_skills(_org_id())
        if user_id is not None:
            visible = telemetry.filter_visible_skills(user_id, [s["name"] for s in skills])
            skills = [s for s in skills if s["name"] in visible]
        if prefix is not None:
            skills = [s for s in skills if s["name"].startswith(prefix)]
        if name_only:
            skills = [{"name": s["name"]} for s in skills]
        return skills

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
        result = telemetry.create_skill(
            org_id, name, description, prompt_template, created_by=user_id
        )
        _try_embed(org_id, name, description)
        return result

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
        org_id = _org_id()
        result = telemetry.update_skill(org_id, name, **fields)
        if result is None:
            raise ValueError(f"Skill '{name}' not found or is a system skill.")
        if description is not None:
            _try_embed(org_id, name, description)
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
        user_id = current_user_var.get()
        if user_id is not None and not telemetry.is_skill_enabled(user_id, name):
            raise PermissionError(
                f"Skill '{name}' is disabled for your account. "
                "Contact a gateway administrator to request access."
            )
        skill = telemetry.get_skill(_org_id(), name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found.")
        template: str = skill["prompt_template"]
        if variables:
            template = template.format(**variables)
        return template
