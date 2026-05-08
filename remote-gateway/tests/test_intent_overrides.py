"""Tests for tool_intent_overrides table and TelemetryStore methods."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore, INTENT_NEVER_REQUIRED  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


def test_intent_overrides_table_exists(store):
    conn = store._connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_intent_overrides'"
    ).fetchone()
    assert row is not None


def test_intent_never_required_contains_bootstrap_tools():
    """The hard-block list must include every bootstrap tool."""
    expected = {
        "setup_start", "setup_save_profile", "setup_complete",
        "health_check",
        "declare_intent", "complete_task", "get_tasks",
        "get_operator_instructions", "create_user",
        "profile_get", "profile_update",
        "list_prompts", "get_prompt",
    }
    assert expected.issubset(INTENT_NEVER_REQUIRED)


def test_get_tool_intent_override_default_none(store):
    assert store.get_tool_intent_override("alice", "search_records") is None


def test_set_and_get_user_specific(store):
    store.set_tool_intent_override("alice", "search_records", True)
    assert store.get_tool_intent_override("alice", "search_records") is True


def test_user_override_beats_global(store):
    store.set_tool_intent_override("*", "search_records", True)
    store.set_tool_intent_override("alice", "search_records", False)
    assert store.get_tool_intent_override("alice", "search_records") is False
    assert store.get_tool_intent_override("bob", "search_records") is True


def test_set_rejects_never_required_tools(store):
    for name in ["setup_start", "declare_intent", "health_check", "create_user"]:
        with pytest.raises(ValueError) as exc_info:
            store.set_tool_intent_override("alice", name, True)
        assert name in str(exc_info.value)


def test_set_allows_skill_management_tools(store):
    """skill_create / run_skill etc. are NOT in the hard-block list."""
    for name in ["skill_create", "skill_update", "skill_list", "run_skill"]:
        store.set_tool_intent_override("*", name, True)
        assert store.get_tool_intent_override("alice", name) is True
