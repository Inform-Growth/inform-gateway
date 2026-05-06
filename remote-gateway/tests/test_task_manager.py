# remote-gateway/tests/test_task_manager.py
from __future__ import annotations
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
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
    conn = store._connect()
    row = conn.execute(
        "SELECT task_id FROM tool_calls WHERE tool_name = ?",
        ("attio__search_records",),
    ).fetchone()
    assert row is not None
    assert row["task_id"] == "task-abc123"


# --- MCP tool tests ---
import contextvars


@pytest.fixture()
def user_var():
    return contextvars.ContextVar("_current_user", default=None)


@pytest.fixture()
def task_tools(store, user_var):
    tools: dict = {}

    class _MCP:
        def tool(self):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

    from tools._core import task_manager
    task_manager.register(_MCP(), store, user_var)
    return tools


def test_declare_intent_returns_task_id(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"]("Research Salesforce", ["search CRM"])
    assert "task_id" in result
    assert result["task_id"].startswith("task-")
    assert result["status"] == "active"


def test_declare_intent_stores_goal(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"]("Research Salesforce", ["search CRM"])
    fetched = store.get_task(result["task_id"])
    assert fetched["goal"] == "Research Salesforce"
    assert fetched["steps"] == ["search CRM"]


def test_complete_task_tool_marks_done(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"]("Research Salesforce", [])
    result = task_tools["complete_task"](created["task_id"], "Found 3 contacts")
    assert result["status"] == "complete"


def test_complete_task_wrong_user_returns_error(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    store.add_api_key("bob", "sk-bob", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"]("Research Salesforce", [])
    user_var.set("bob")
    result = task_tools["complete_task"](created["task_id"], "sneaky")
    assert "error" in result


def test_get_tasks_returns_active_tasks(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    task_tools["declare_intent"]("Task A", [])
    task_tools["declare_intent"]("Task B", [])
    result = task_tools["get_tasks"]()
    assert len(result["tasks"]) == 2
