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


def test_clear_intent_override(store):
    store.set_tool_intent_override("alice", "search_records", True)
    store.clear_tool_intent_override("alice", "search_records")
    assert store.get_tool_intent_override("alice", "search_records") is None


def test_get_tool_intent_overrides_listing(store):
    store.set_tool_intent_override("alice", "search_records", True)
    store.set_tool_intent_override("alice", "create_record", False)
    rows = store.get_tool_intent_overrides("alice")
    by_name = {r["tool_name"]: r["requires_intent"] for r in rows}
    assert by_name == {"search_records": True, "create_record": False}


# ---------------------------------------------------------------------------
# Tests for mcp_server._tool_requires_intent
# ---------------------------------------------------------------------------

def test_tool_requires_intent_default_for_bypass_tools(store, monkeypatch):
    """Tools in _TASK_BYPASS_DEFAULTS default to NOT requiring intent."""
    sys.modules.pop("mcp_server", None)
    import mcp_server
    monkeypatch.setattr(mcp_server, "_telemetry", store)
    for name in ["health_check", "declare_intent", "skill_list", "run_skill",
                 "profile_get", "setup_start"]:
        assert mcp_server._tool_requires_intent("alice", name) is False, name


def test_tool_requires_intent_default_for_other_tools(store, monkeypatch):
    """Tools not in _TASK_BYPASS_DEFAULTS default to requiring intent."""
    sys.modules.pop("mcp_server", None)
    import mcp_server
    monkeypatch.setattr(mcp_server, "_telemetry", store)
    for name in ["search_records", "create_record", "enrich_person"]:
        assert mcp_server._tool_requires_intent("alice", name) is True, name


def test_tool_requires_intent_global_override(store, monkeypatch):
    """A global override can force a bypass-default tool to require intent."""
    sys.modules.pop("mcp_server", None)
    import mcp_server
    monkeypatch.setattr(mcp_server, "_telemetry", store)
    store.set_tool_intent_override("*", "run_skill", True)
    assert mcp_server._tool_requires_intent("alice", "run_skill") is True


def test_tool_requires_intent_hard_block(store, monkeypatch):
    """Tools in INTENT_NEVER_REQUIRED always return False regardless of overrides."""
    sys.modules.pop("mcp_server", None)
    import mcp_server
    monkeypatch.setattr(mcp_server, "_telemetry", store)
    # declare_intent is in INTENT_NEVER_REQUIRED — cannot be overridden
    assert mcp_server._tool_requires_intent("alice", "declare_intent") is False
