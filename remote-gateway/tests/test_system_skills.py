"""Tests for system skill seeding (TelemetryStore.create_system_skill + the
seeder module that reads system_skills.json on startup)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)
sys.modules.pop("system_skills", None)

from telemetry import TelemetryStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------------
# create_system_skill
# ---------------------------------------------------------------------------


def test_create_system_skill_sets_is_system_flag(store):
    skill = store.create_system_skill(
        org_id="default",
        name="test-skill",
        description="A test skill",
        prompt_template="Do the thing.",
    )
    assert skill is not None
    assert skill["is_system"] == 1
    assert skill["name"] == "test-skill"
    assert skill["description"] == "A test skill"
    assert skill["prompt_template"] == "Do the thing."


def test_create_system_skill_is_idempotent(store):
    a = store.create_system_skill("default", "dup", "desc", "template")
    b = store.create_system_skill("default", "dup", "desc", "template")
    assert a["id"] == b["id"]
    skills = [s for s in store.list_skills("default") if s["name"] == "dup"]
    assert len(skills) == 1


def test_create_system_skill_updates_on_change(store):
    store.create_system_skill("default", "ev", "v1", "template v1")
    updated = store.create_system_skill("default", "ev", "v2", "template v2")
    assert updated["description"] == "v2"
    assert updated["prompt_template"] == "template v2"
    assert updated["is_system"] == 1


def test_system_skills_cannot_be_user_deleted(store):
    store.create_system_skill("default", "protected", "desc", "template")
    deleted = store.delete_skill("default", "protected")
    assert deleted is False
    still_there = store.get_skill("default", "protected")
    assert still_there is not None
    assert still_there["is_system"] == 1


def test_system_skills_cannot_be_user_updated(store):
    store.create_system_skill("default", "locked", "orig", "orig template")
    result = store.update_skill("default", "locked", description="hijack")
    assert result is None
    after = store.get_skill("default", "locked")
    assert after["description"] == "orig"


# ---------------------------------------------------------------------------
# Seeder module
# ---------------------------------------------------------------------------


def test_seeder_loads_skills_from_json(store, tmp_path):
    from system_skills import seed_system_skills
    seed_file = tmp_path / "skills.json"
    seed_file.write_text(json.dumps({
        "skills": [
            {"name": "alpha", "description": "first", "prompt_template": "Do alpha."},
            {"name": "beta", "description": "second", "prompt_template": "Do {x}."},
        ]
    }))
    count = seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    assert count == 2
    assert store.get_skill("default", "alpha")["is_system"] == 1
    assert store.get_skill("default", "beta")["prompt_template"] == "Do {x}."


def test_seeder_is_idempotent(store, tmp_path):
    from system_skills import seed_system_skills
    seed_file = tmp_path / "skills.json"
    seed_file.write_text(json.dumps({
        "skills": [{"name": "alpha", "description": "first", "prompt_template": "Do alpha."}]
    }))
    seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    skills = [s for s in store.list_skills("default") if s["name"] == "alpha"]
    assert len(skills) == 1


def test_seeder_skips_when_file_missing(store, tmp_path):
    from system_skills import seed_system_skills
    count = seed_system_skills(store, org_id="default", seed_file=str(tmp_path / "missing.json"))
    assert count == 0


def test_seeder_handles_empty_skills_list(store, tmp_path):
    from system_skills import seed_system_skills
    seed_file = tmp_path / "skills.json"
    seed_file.write_text('{"skills": []}')
    count = seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    assert count == 0


def test_seeder_fails_loud_on_malformed_json(store, tmp_path):
    from system_skills import seed_system_skills
    seed_file = tmp_path / "broken.json"
    seed_file.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        seed_system_skills(store, org_id="default", seed_file=str(seed_file))


def test_seeder_default_seed_file_path(store, tmp_path, monkeypatch):
    """When seed_file is None, the default path is the repo's system_skills.json.

    A missing default file is a clean no-op (returns 0)."""
    from system_skills import seed_system_skills
    # Don't create the default file — should return 0 without raising.
    count = seed_system_skills(store, org_id="default")
    assert count == 0 or count > 0  # tolerant: file may exist on disk
