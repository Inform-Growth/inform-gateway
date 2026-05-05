"""Seed system skills into SQLite at gateway startup.

Reads ``remote-gateway/system_skills.json`` and upserts each entry as a
system skill (is_system=1) for the given org via
``TelemetryStore.create_system_skill``. Idempotent — safe to call on
every boot. A missing file is a clean no-op so dev environments without
a seed file still start cleanly. Malformed JSON fails loud (raises
``json.JSONDecodeError``) — a broken seed file is a config bug we want
to surface, not silently ignore.

Skill authors edit ``system_skills.json``; redeploy reconciles the file
contents into SQLite. Skills marked ``is_system=1`` cannot be edited
or deleted from the operator surface (skill_update / skill_delete).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_SEED_FILE = Path(__file__).resolve().parent.parent / "system_skills.json"


def seed_system_skills(
    telemetry: Any,
    org_id: str = "default",
    seed_file: str | None = None,
) -> int:
    """Upsert system skills from the seed JSON file.

    Args:
        telemetry: TelemetryStore instance with ``create_system_skill``.
        org_id: Org to seed into. Defaults to "default" — matches the
            fallback used by skill_manager when no user is set, so seeded
            skills are visible to every org that has not been explicitly
            scoped elsewhere.
        seed_file: Path to the JSON seed file. Defaults to
            ``remote-gateway/system_skills.json`` relative to this module.

    Returns:
        Count of skills upserted. 0 if the file is missing or its
        ``skills`` list is empty.

    Raises:
        json.JSONDecodeError: if the seed file exists but is malformed.
    """
    path = Path(seed_file) if seed_file is not None else _DEFAULT_SEED_FILE
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    skills = data.get("skills", [])
    seeded = 0
    for entry in skills:
        result = telemetry.create_system_skill(
            org_id=org_id,
            name=entry["name"],
            description=entry["description"],
            prompt_template=entry["prompt_template"],
        )
        if result is not None:
            seeded += 1
    if seeded:
        print(
            f"[system_skills] seeded {seeded} system skill(s) for org '{org_id}' from {path}",
            flush=True,
        )
    return seeded
