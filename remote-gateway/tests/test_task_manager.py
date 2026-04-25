# remote-gateway/tests/test_task_manager.py
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


def test_create_task_returns_task_id(store):
    task = store.create_task("alice", "acme", "Research Salesforce", ["search CRM", "check Apollo"])
    assert task["task_id"].startswith("task-")
    assert task["status"] == "active"
    assert task["goal"] == "Research Salesforce"


def test_get_task_by_id(store):
    task = store.create_task("alice", "acme", "Research Salesforce", [])
    fetched = store.get_task(task["task_id"])
    assert fetched is not None
    assert fetched["task_id"] == task["task_id"]


def test_complete_task(store):
    task = store.create_task("alice", "acme", "Research Salesforce", [])
    result = store.complete_task(task["task_id"], "alice", "Found 3 contacts")
    assert result["status"] == "complete"
    assert result["outcome"] == "Found 3 contacts"


def test_complete_task_wrong_user_returns_none(store):
    task = store.create_task("alice", "acme", "Research Salesforce", [])
    result = store.complete_task(task["task_id"], "bob", "whatever")
    assert result is None


def test_list_active_tasks_for_user(store):
    store.create_task("alice", "acme", "Task A", [])
    store.create_task("alice", "acme", "Task B", [])
    store.create_task("bob", "acme", "Task C", [])
    tasks = store.list_active_tasks("alice")
    assert len(tasks) == 2
    assert all(t["user_id"] == "alice" for t in tasks)


def test_tool_calls_can_store_task_id(store):
    store.record("attio__search_records", 42, True, user_id="alice", task_id="task-abc123")
    # If no exception, the column exists and the value was stored
