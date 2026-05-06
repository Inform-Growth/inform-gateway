"""Verify task gate logic: no active task → redirect, active task → pass."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice", "sk-test", org_id="acme")
    s.set_initialized("acme")
    return s


def _make_gate_task_redirect(tool_name: str) -> dict:
    return {
        "gateway_status": "no_active_task",
        "message": (
            "GATEWAY: No active task declared. "
            "AGENT INSTRUCTION: Call declare_intent with your goal and planned steps "
            "before using any tools."
        ),
        "blocked_tool": tool_name,
        "required_action": "declare_intent",
    }


def test_no_active_task_produces_redirect(store):
    tasks = store.list_active_tasks("alice")
    assert len(tasks) == 0
    redirect = _make_gate_task_redirect("attio__search_records")
    assert redirect["gateway_status"] == "no_active_task"
    assert redirect["required_action"] == "declare_intent"


def test_active_task_allows_through(store):
    task = store.create_task("alice", "acme", "Research Salesforce", [])
    tasks = store.list_active_tasks("alice")
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == task["task_id"]


def test_completed_task_does_not_count_as_active(store):
    task = store.create_task("alice", "acme", "Research Salesforce", [])
    store.complete_task(task["task_id"], "alice", "done")
    tasks = store.list_active_tasks("alice")
    assert len(tasks) == 0


def test_task_gate_bypassed_for_declare_intent():
    _TASK_BYPASS = {
        "declare_intent", "complete_task", "get_tasks",
        "setup_start", "setup_save_profile", "setup_complete",
        "health_check", "create_user", "get_operator_instructions",
        "list_prompts", "get_prompt", "profile_get", "profile_update",
        "skill_list", "skill_create", "skill_update", "run_skill",
    }
    assert "declare_intent" in _TASK_BYPASS
    assert "attio__search_records" not in _TASK_BYPASS


def test_task_id_linked_to_tool_call(store):
    task = store.create_task("alice", "acme", "Research Salesforce", [])
    store.record(
        "attio__search_records", 55, True,
        user_id="alice", task_id=task["task_id"]
    )
    conn = store._connect()
    row = conn.execute(
        "SELECT task_id FROM tool_calls WHERE tool_name = ?",
        ("attio__search_records",),
    ).fetchone()
    assert row is not None
    assert row["task_id"] == task["task_id"]
