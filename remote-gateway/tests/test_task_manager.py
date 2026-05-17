# remote-gateway/tests/test_task_manager.py
from __future__ import annotations
import sys
from pathlib import Path
import pytest
import time as _time_mod
from starlette.testclient import TestClient

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


def test_create_task_stores_decision_fields(store):
    task = store.create_task(
        "alice", "acme",
        "Evaluate renewal terms for Acme account",
        ["pull usage data", "check deal history"],
        decision_context="Should we extend renewal terms for Acme",
        decision_type="decision",
        stakes_hint="high",
    )
    fetched = store.get_task(task["task_id"])
    assert fetched["decision_context"] == "Should we extend renewal terms for Acme"
    assert fetched["decision_type"] == "decision"
    assert fetched["stakes_hint"] == "high"


def test_create_task_decision_fields_nullable(store):
    task = store.create_task("alice", "acme", "Pull weekly pipeline report", [])
    fetched = store.get_task(task["task_id"])
    assert fetched["decision_context"] is None
    assert fetched["decision_type"] is None
    assert fetched["stakes_hint"] is None


def test_list_active_tasks_includes_decision_fields(store):
    store.create_task(
        "alice", "acme", "Evaluate Acme renewal", [],
        decision_type="decision", stakes_hint="high",
    )
    tasks = store.list_active_tasks("alice")
    assert tasks[0]["decision_type"] == "decision"
    assert tasks[0]["stakes_hint"] == "high"


def test_clarity_check_passes_specific_goal():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity(
        "Search Attio for Series B companies in Vancouver with more than 50 employees"
    )
    assert result is None


def test_clarity_check_fails_short_goal():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity("Look into it")
    assert result is not None
    assert "clarity_warning" in result or "message" in result


def test_clarity_check_fails_vague_phrase():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity("Help with the prospecting list we discussed")
    assert result is not None


def test_clarity_check_fails_under_six_words():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity("Do some research now")
    assert result is not None


def test_clarity_check_passes_process_goal():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity(
        "Run the weekly pipeline enrichment job for all open opportunities in Attio"
    )
    assert result is None


def test_declare_intent_includes_shadow_operating_instructions(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Search Attio for Series B companies in Vancouver with over 50 employees",
        ["search attio"],
    )
    assert "shadow_operating_instructions" in result
    assert "report_issue" in result["shadow_operating_instructions"]
    assert "FRICTION" in result["shadow_operating_instructions"]
    assert "EFFICIENCY" in result["shadow_operating_instructions"]


def test_declare_intent_emits_clarity_warning_for_vague_goal(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"]("Help with things", [])
    assert "task_id" in result  # task still created
    assert "clarity_warning" in result
    assert "message" in result["clarity_warning"]


def test_declare_intent_no_clarity_warning_for_specific_goal(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Pull Apollo enrichment for all open Attio opportunities created this month",
        ["search apollo"],
    )
    assert "clarity_warning" not in result


def test_declare_intent_accepts_and_echoes_decision_fields(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Evaluate whether to expand Acme account to enterprise tier",
        ["pull usage data", "check deal history"],
        decision_context="Should we upgrade Acme to enterprise",
        decision_type="decision",
        stakes_hint="high",
    )
    assert result["decision_context"] == "Should we upgrade Acme to enterprise"
    assert result["decision_type"] == "decision"
    assert result["stakes_hint"] == "high"


def test_declare_intent_decision_fields_optional(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Run weekly pipeline enrichment job for all open opportunities",
        [],
    )
    assert result.get("decision_context") is None
    assert result.get("decision_type") is None
    assert result.get("stakes_hint") is None


def test_compound_index_exists(store):
    conn = store._connect()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tasks_org_created'"
    ).fetchall()
    assert len(rows) == 1, "compound index idx_tasks_org_created must exist"


def test_list_tasks_for_org_includes_decision_fields(store):
    store.create_task(
        "alice", "acme",
        "Evaluate whether to expand Acme account to enterprise tier",
        ["pull usage data", "check deal history"],
        decision_context="Should we upgrade Acme to enterprise",
        decision_type="decision",
        stakes_hint="high",
    )
    tasks = store.list_tasks_for_org("acme")
    assert len(tasks) == 1
    assert tasks[0]["decision_context"] == "Should we upgrade Acme to enterprise"
    assert tasks[0]["decision_type"] == "decision"
    assert tasks[0]["stakes_hint"] == "high"


def test_list_tasks_for_org_time_window(store):
    import time as _time
    import secrets as _secrets
    base = _time.time()
    conn = store._connect()

    def _insert(goal: str, ts: float):
        tid = f"task-{_secrets.token_hex(8)}"
        conn.execute(
            "INSERT INTO tasks (task_id, user_id, org_id, goal, steps, status, created_at)"
            " VALUES (?, 'alice', 'acme', ?, '[]', 'active', ?)",
            (tid, goal, ts),
        )
        conn.commit()

    _insert("Too early", base - 7200)
    _insert("In window", base)
    _insert("Too late", base + 7200)

    tasks = store.list_tasks_for_org(
        "acme",
        from_ts=base - 3600,
        to_ts=base + 3600,
    )
    goals = [t["goal"] for t in tasks]
    assert "In window" in goals
    assert "Too early" not in goals
    assert "Too late" not in goals


def test_list_tasks_for_org_exclude_process(store):
    store.create_task(
        "alice", "acme", "Weekly enrichment job", [],
        decision_type="process",
    )
    store.create_task(
        "alice", "acme", "Evaluate Acme expansion", [],
        decision_type="decision",
    )
    store.create_task(
        "alice", "acme", "Explore new market segment", [],
        # decision_type is None — loom treats as "exploration", must be included
    )
    tasks = store.list_tasks_for_org("acme", exclude_process=True)
    types = [t["decision_type"] for t in tasks]
    assert "process" not in types
    assert "decision" in types
    assert None in types  # NULL rows are kept


def test_api_tasks_filters_passed_through(store, monkeypatch):
    """GET /api/tasks?from=&to=&exclude_process=true filters tasks correctly."""
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")

    from admin_api import create_admin_app
    app = create_admin_app(store)
    client = TestClient(app, raise_server_exceptions=True)

    base = _time_mod.time()
    import secrets as _sec
    conn = store._connect()

    def _ins(goal: str, ts: float, dtype: str | None = None):
        tid = f"task-{_sec.token_hex(8)}"
        conn.execute(
            "INSERT INTO tasks"
            " (task_id, user_id, org_id, goal, steps, status, created_at, decision_type)"
            " VALUES (?, 'alice', 'acme', ?, '[]', 'active', ?, ?)",
            (tid, goal, ts, dtype),
        )
        conn.commit()

    _ins("Too early", base - 7200, "decision")
    _ins("In window process", base, "process")
    _ins("In window decision", base, "decision")
    _ins("Too late", base + 7200, "decision")

    resp = client.get(
        "/api/tasks",
        params={
            "token": "test-token",
            "org_id": "acme",
            "from": base - 3600,
            "to": base + 3600,
            "exclude_process": "true",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    goals = [t["goal"] for t in data["tasks"]]
    assert "In window decision" in goals
    assert "In window process" not in goals
    assert "Too early" not in goals
    assert "Too late" not in goals
    # decision fields present on every task
    for task in data["tasks"]:
        assert "decision_context" in task
        assert "decision_type" in task
        assert "stakes_hint" in task


# --- declare_intent criteria block ---

def test_declare_intent_returns_task_criteria_block(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Search Attio for open Series B companies in Vancouver",
        ["search attio"],
    )
    assert "task_criteria" in result
    assert "checklist" in result["task_criteria"]
    assert "instruction" in result["task_criteria"]
    assert isinstance(result["task_criteria"]["checklist"], list)
    assert len(result["task_criteria"]["checklist"]) >= 4
    assert "update_task" in result["task_criteria"]["instruction"]


def test_declare_intent_docstring_has_no_decision_tracking_language(task_tools):
    fn = task_tools["declare_intent"]
    doc = fn.__doc__ or ""
    assert "what decision does this task feed" not in doc.lower()
    assert "decision or measure impact" not in doc.lower()


# --- update_task MCP tool ---

def test_update_task_tool_returns_updated_task(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"]("Vague goal", [])
    result = task_tools["update_task"](
        created["task_id"],
        goal="Search Attio for open Series B companies in Vancouver",
        context="Evaluating whether to expand territory",
        stakes_hint="high",
        work_type="decision",
        steps=["search attio", "enrich top 10"],
    )
    assert "error" not in result
    assert result["goal"] == "Search Attio for open Series B companies in Vancouver"
    assert result["decision_context"] == "Evaluating whether to expand territory"
    assert result["stakes_hint"] == "high"
    assert result["decision_type"] == "decision"
    assert result["steps"] == ["search attio", "enrich top 10"]


def test_update_task_tool_wrong_user_returns_error(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    store.add_api_key("bob", "sk-bob", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"](
        "Search Attio for open Series B companies in Vancouver", []
    )
    user_var.set("bob")
    result = task_tools["update_task"](created["task_id"], goal="Overwritten")
    assert "error" in result


def test_update_task_tool_partial_update_leaves_other_fields(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"](
        "Search Attio for open Series B companies",
        ["step a", "step b"],
        decision_context="Territory expansion",
    )
    result = task_tools["update_task"](created["task_id"], stakes_hint="medium")
    assert result["stakes_hint"] == "medium"
    assert result["decision_context"] == "Territory expansion"  # unchanged
    assert result["steps"] == ["step a", "step b"]  # unchanged


# --- update_task telemetry tests ---

def test_update_task_modifies_goal(store):
    task = store.create_task("alice", "acme", "Vague goal", ["step 1"])
    result = store.update_task(
        task["task_id"], "alice",
        goal="Search Attio for open Series B companies in Vancouver",
    )
    assert result is not None
    assert result["goal"] == "Search Attio for open Series B companies in Vancouver"
    assert result["steps"] == ["step 1"]  # unchanged


def test_update_task_modifies_context_and_stakes(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", [])
    result = store.update_task(
        task["task_id"], "alice",
        decision_context="Evaluating whether to expand Vancouver territory",
        stakes_hint="high",
        decision_type="decision",
    )
    assert result is not None
    assert result["decision_context"] == "Evaluating whether to expand Vancouver territory"
    assert result["stakes_hint"] == "high"
    assert result["decision_type"] == "decision"


def test_update_task_wrong_user_returns_none(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", [])
    result = store.update_task(task["task_id"], "bob", goal="Overwritten")
    assert result is None


def test_update_task_on_complete_task_returns_none(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", [])
    store.complete_task(task["task_id"], "alice", "done")
    result = store.update_task(task["task_id"], "alice", goal="Too late")
    assert result is None


def test_update_task_no_fields_returns_unchanged_task(store):
    task = store.create_task(
        "alice", "acme", "Search Attio for open Series B companies", ["step a"]
    )
    result = store.update_task(task["task_id"], "alice")
    assert result is not None
    assert result["goal"] == "Search Attio for open Series B companies"
    assert result["steps"] == ["step a"]


def test_update_task_modifies_steps(store):
    task = store.create_task(
        "alice", "acme", "Search Attio for open Series B companies", ["old step"]
    )
    result = store.update_task(
        task["task_id"], "alice", steps=["search attio", "enrich with apollo"]
    )
    assert result is not None
    assert result["steps"] == ["search attio", "enrich with apollo"]


# --- gate message content ---

def test_gate_task_redirect_contains_operator_instructions(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    sys.modules.pop("mcp_server", None)
    from mcp_server import _make_gate_task_redirect
    result = _make_gate_task_redirect("attio__search_records")
    assert result["gateway_status"] == "no_active_task"
    assert result["blocked_tool"] == "attio__search_records"
    assert result["required_action"] == "declare_intent"
    msg = result["message"]
    assert "AGENT INSTRUCTION" in msg
    assert "declare_intent" in msg
    # must contain the three context prompts
    assert "system" in msg.lower()
    assert "matters" in msg.lower()
    assert "important" in msg.lower()
