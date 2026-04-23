from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)
from telemetry import TelemetryStore

@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")

def test_get_org_id_falls_back_to_user_id(store):
    store.add_api_key("alice@example.com", "sk-test")
    assert store.get_org_id("alice@example.com") == "alice@example.com"

def test_get_org_id_returns_explicit_org(store):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    assert store.get_org_id("alice@example.com") == "acme"

def test_is_initialized_false_by_default(store):
    assert store.is_initialized("acme") is False

def test_is_initialized_true_after_set(store):
    store.set_initialized("acme")
    assert store.is_initialized("acme") is True

def test_get_org_profile_empty_for_unknown(store):
    assert store.get_org_profile("acme") == {}

def test_update_org_profile_creates_and_patches(store):
    store.update_org_profile("acme", {"tone": "professional", "icp": "SaaS"})
    profile = store.get_org_profile("acme")
    assert profile["tone"] == "professional"
    assert profile["icp"] == "SaaS"

def test_update_org_profile_merges_not_replaces(store):
    store.update_org_profile("acme", {"tone": "professional"})
    store.update_org_profile("acme", {"icp": "SaaS"})
    profile = store.get_org_profile("acme")
    assert profile["tone"] == "professional"
    assert profile["icp"] == "SaaS"

import secrets as _secrets

def test_create_skill_and_list(store):
    store.create_skill("acme", "daily_briefing", "Run morning summary", "Summarize {topic}")
    skills = store.list_skills("acme")
    assert len(skills) == 1
    assert skills[0]["name"] == "daily_briefing"
    assert skills[0]["prompt_template"] == "Summarize {topic}"

def test_list_skills_excludes_inactive(store):
    store.create_skill("acme", "to_delete", "...", "...")
    store.delete_skill("acme", "to_delete")
    assert store.list_skills("acme") == []

def test_delete_skill_blocked_for_system_skills(store):
    conn = store._connect()
    sid = _secrets.token_hex(8)
    now = __import__("time").time()
    conn.execute(
        "INSERT INTO skills (id, org_id, name, description, prompt_template, is_system, created_at, updated_at) "
        "VALUES (?, 'acme', 'protected', 'system skill', 'template', 1, ?, ?)",
        (sid, now, now),
    )
    conn.commit()
    assert store.delete_skill("acme", "protected") is False
    assert len(store.list_skills("acme")) == 1

def test_get_skill_returns_none_for_unknown(store):
    assert store.get_skill("acme", "nonexistent") is None

def test_update_skill_changes_template(store):
    store.create_skill("acme", "my_skill", "desc", "old template")
    result = store.update_skill("acme", "my_skill", prompt_template="new template")
    assert result is not None
    assert result["prompt_template"] == "new template"

def test_get_tool_hint_none_for_unknown(store):
    assert store.get_tool_hint("acme", "health_check") is None

def test_upsert_and_get_tool_hint(store):
    store.upsert_tool_hint("acme", "apollo__people_match",
                           interpretation_hint="Returns person records",
                           usage_rules="Call before creating",
                           data_sensitivity="confidential")
    hint = store.get_tool_hint("acme", "apollo__people_match")
    assert hint["interpretation_hint"] == "Returns person records"
    assert hint["data_sensitivity"] == "confidential"

def test_upsert_tool_hint_overwrites(store):
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v1")
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v2")
    assert store.get_tool_hint("acme", "health_check")["interpretation_hint"] == "v2"

def test_list_tool_hints_returns_all_for_org(store):
    store.upsert_tool_hint("acme", "tool_a", interpretation_hint="a")
    store.upsert_tool_hint("acme", "tool_b", interpretation_hint="b")
    hints = store.list_tool_hints("acme")
    names = [h["tool_name"] for h in hints]
    assert "tool_a" in names
    assert "tool_b" in names
