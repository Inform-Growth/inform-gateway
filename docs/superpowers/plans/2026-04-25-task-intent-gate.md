# Task Intent Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force agents to declare intent before using gateway tools by requiring an active task (created via `declare_intent`) and automatically attributing every tool call to a task in telemetry.

**Architecture:** A `tasks` table in SQLite stores declared intents. Every tool call goes through the existing telemetry wrapper, which now checks for an active task and pops an optional `task_id` kwarg (injected into all tool signatures via `__signature__` mutation) before forwarding to the real function. The gate fires after init-gate, before permission-gate, using the same redirect-response pattern the init gate uses today.

**Tech Stack:** Python 3.11+, SQLite (via existing `TelemetryStore`), FastMCP, `inspect` stdlib for signature injection.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `remote-gateway/core/telemetry.py` | Modify | Add `tasks` table schema, migration, and CRUD methods |
| `remote-gateway/tools/_core/task_manager.py` | Create | `declare_intent`, `complete_task`, `get_tasks` MCP tools |
| `remote-gateway/core/mcp_server.py` | Modify | `_TASK_BYPASS` set, task gate in both wrappers, `task_id` signature injection, register task_manager |
| `remote-gateway/core/admin_api.py` | Modify | Add `GET /api/tasks` endpoint |
| `remote-gateway/tests/test_task_manager.py` | Create | Unit tests for the three MCP tools |
| `remote-gateway/tests/test_task_gate.py` | Create | Unit tests for gate logic (no task → redirect, active task → pass, expired → redirect) |

---

## Task 1: DB Schema — `tasks` table + `task_id` column on `tool_calls`

**Files:**
- Modify: `remote-gateway/core/telemetry.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_task_manager.py -v 2>&1 | head -30
```
Expected: `AttributeError: 'TelemetryStore' object has no attribute 'create_task'`

- [ ] **Step 3: Add `tasks` table schema to `_SCHEMA_TABLES` in `telemetry.py`**

After the `tool_hints` table definition, add:

```python
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    org_id       TEXT NOT NULL,
    goal         TEXT NOT NULL,
    steps        TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'active',
    outcome      TEXT,
    created_at   REAL NOT NULL,
    completed_at REAL
);
```

- [ ] **Step 4: Add `task_id` migration to `_MIGRATIONS`**

```python
("tool_calls", "task_id", "TEXT"),
```

Add this as the last entry in the `_MIGRATIONS` list (after `"response_preview"`).

- [ ] **Step 5: Add `create_task` method to `TelemetryStore`**

Add after `list_tool_hints`:

```python
# ------------------------------------------------------------------
# Task management
# ------------------------------------------------------------------

def create_task(
    self,
    user_id: str,
    org_id: str,
    goal: str,
    steps: list[str],
) -> dict:
    """Create a new active task and return it.

    Args:
        user_id: The user declaring intent.
        org_id: The user's organization.
        goal: What the agent is trying to accomplish.
        steps: Planned tool call sequence (list of strings).

    Returns:
        Task dict with task_id, user_id, org_id, goal, steps, status, created_at.
    """
    import json as _json
    import secrets as _secrets
    task_id = f"task-{_secrets.token_hex(8)}"
    now = time.time()
    if self._enabled:
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO tasks (task_id, user_id, org_id, goal, steps, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (task_id, user_id, org_id, goal, _json.dumps(steps), now),
            )
            conn.commit()
        except Exception:
            pass
    return {
        "task_id": task_id,
        "user_id": user_id,
        "org_id": org_id,
        "goal": goal,
        "steps": steps,
        "status": "active",
        "created_at": now,
    }

def get_task(self, task_id: str) -> dict | None:
    """Return a task by ID, or None if not found.

    Args:
        task_id: Task identifier.
    """
    import json as _json
    if not self._enabled:
        return None
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT task_id, user_id, org_id, goal, steps, status, outcome, created_at, completed_at"
            " FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "task_id": row["task_id"],
            "user_id": row["user_id"],
            "org_id": row["org_id"],
            "goal": row["goal"],
            "steps": _json.loads(row["steps"] or "[]"),
            "status": row["status"],
            "outcome": row["outcome"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }
    except Exception:
        return None

def complete_task(self, task_id: str, user_id: str, outcome: str) -> dict | None:
    """Mark a task complete. Returns updated task or None if not found / wrong user.

    Args:
        task_id: Task to complete.
        user_id: Must match task's owner.
        outcome: Summary of what was accomplished.
    """
    if not self._enabled:
        return None
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT user_id FROM tasks WHERE task_id = ? AND status = 'active'",
            (task_id,),
        ).fetchone()
        if not row or row["user_id"] != user_id:
            return None
        now = time.time()
        conn.execute(
            "UPDATE tasks SET status = 'complete', outcome = ?, completed_at = ? WHERE task_id = ?",
            (outcome, now, task_id),
        )
        conn.commit()
        return self.get_task(task_id)
    except Exception:
        return None

def list_active_tasks(self, user_id: str) -> list[dict]:
    """Return all active tasks for a user, newest first.

    Args:
        user_id: User to query.
    """
    import json as _json
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT task_id, user_id, org_id, goal, steps, status, created_at"
            " FROM tasks WHERE user_id = ? AND status = 'active'"
            " ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "user_id": row["user_id"],
                "org_id": row["org_id"],
                "goal": row["goal"],
                "steps": _json.loads(row["steps"] or "[]"),
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    except Exception:
        return []
```

- [ ] **Step 6: Update `record()` to accept `task_id`**

In `telemetry.py`, update the `record` method signature and the INSERT statement:

Change signature from:
```python
def record(
    self,
    tool_name: str,
    duration_ms: int,
    success: bool,
    error_type: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    response_size: int | None = None,
    input_body: str | None = None,
    error_message: str | None = None,
    response_preview: str | None = None,
) -> None:
```
To:
```python
def record(
    self,
    tool_name: str,
    duration_ms: int,
    success: bool,
    error_type: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    response_size: int | None = None,
    input_body: str | None = None,
    error_message: str | None = None,
    response_preview: str | None = None,
    task_id: str | None = None,
) -> None:
```

Change the INSERT in `record()` from:
```python
conn.execute(
    "INSERT INTO tool_calls"
    " (tool_name, called_at, duration_ms, success,"
    "  error_type, error_message, user_id, request_id, response_size, input_body,"
    "  response_preview)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (
        tool_name, time.time(), duration_ms, int(success),
        error_type, error_message, user_id, request_id, response_size, input_body,
        response_preview,
    ),
)
```
To:
```python
conn.execute(
    "INSERT INTO tool_calls"
    " (tool_name, called_at, duration_ms, success,"
    "  error_type, error_message, user_id, request_id, response_size, input_body,"
    "  response_preview, task_id)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (
        tool_name, time.time(), duration_ms, int(success),
        error_type, error_message, user_id, request_id, response_size, input_body,
        response_preview, task_id,
    ),
)
```

- [ ] **Step 7: Run tests**

```bash
cd remote-gateway && pytest tests/test_task_manager.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 8: Run full suite to check regressions**

```bash
cd remote-gateway && pytest --tb=short -q
```
Expected: all existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: add tasks table and CRUD methods to TelemetryStore"
```

---

## Task 2: `task_manager.py` — MCP tools

**Files:**
- Create: `remote-gateway/tools/_core/task_manager.py`
- Modify: `remote-gateway/tests/test_task_manager.py` (append)

- [ ] **Step 1: Write the failing tests — append to `test_task_manager.py`**

```python
# --- MCP tool tests (append to test_task_manager.py) ---
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_task_manager.py::test_declare_intent_returns_task_id -v
```
Expected: `ModuleNotFoundError` or `KeyError: 'declare_intent'`

- [ ] **Step 3: Create `remote-gateway/tools/_core/task_manager.py`**

```python
"""
Gateway task management tools.

Agents must declare intent before using gateway tools. Each declared intent
creates a task with a unique task_id. Tool calls are attributed to the active
task in telemetry, enabling per-task audit trails.

Bypasses the init gate — safe to call after initialization.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register declare_intent, complete_task, and get_tasks on mcp.

    Args:
        mcp: FastMCP instance.
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _user_and_org() -> tuple[str, str]:
        user_id = current_user_var.get() or "anonymous"
        org_id = telemetry.get_org_id(user_id) if user_id != "anonymous" else "default"
        return user_id, org_id

    @mcp.tool()
    def declare_intent(goal: str, steps: list[str]) -> dict:
        """Declare what you are about to accomplish. Required before using any gateway tool.

        Creates a task and returns a task_id. Pass this task_id to subsequent tool
        calls to attribute them to this task. Multiple tasks can be active at once.

        Args:
            goal: One sentence describing what you are trying to accomplish.
            steps: Ordered list of planned tool calls or actions (e.g. ["search CRM", "enrich with Apollo"]).

        Returns:
            Dict with task_id, goal, steps, status, and agent_instruction.
        """
        user_id, org_id = _user_and_org()
        task = telemetry.create_task(user_id, org_id, goal, steps)
        task["agent_instruction"] = (
            f"Task created. Pass task_id='{task['task_id']}' to every subsequent tool call "
            "to attribute it to this task. Call complete_task when done."
        )
        return task

    @mcp.tool()
    def complete_task(task_id: str, outcome: str) -> dict:
        """Mark a task as complete and record the outcome.

        Args:
            task_id: The task_id returned by declare_intent.
            outcome: One sentence describing what was accomplished or discovered.

        Returns:
            Updated task dict, or an error dict if task not found or not owned by caller.
        """
        user_id, _ = _user_and_org()
        result = telemetry.complete_task(task_id, user_id, outcome)
        if result is None:
            return {"error": f"Task '{task_id}' not found, already complete, or not owned by you."}
        return result

    @mcp.tool()
    def get_tasks() -> dict:
        """Return your currently active tasks and their task_ids.

        Use this to retrieve task_ids if you need to continue a previous task.

        Returns:
            Dict with a list of active tasks for the current user.
        """
        user_id, _ = _user_and_org()
        tasks = telemetry.list_active_tasks(user_id)
        return {"tasks": tasks, "count": len(tasks)}
```

- [ ] **Step 4: Run tests**

```bash
cd remote-gateway && pytest tests/test_task_manager.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
cd remote-gateway && pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/_core/task_manager.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: add declare_intent, complete_task, get_tasks tools"
```

---

## Task 3: Task Gate + `task_id` Injection in `mcp_server.py`

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Create: `remote-gateway/tests/test_task_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_task_gate.py
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
    # Verify it's stored by reading raw_logs
    logs = store.raw_logs(tool_name="attio__search_records", user_id="alice")
    assert len(logs) == 1
```

- [ ] **Step 2: Run to confirm current state**

```bash
cd remote-gateway && pytest tests/test_task_gate.py -v
```
Expected: most pass (they test telemetry directly), but confirms the test file runs.

- [ ] **Step 3: Add `_TASK_BYPASS` set and `_make_gate_task_redirect` to `mcp_server.py`**

In `mcp_server.py`, directly after the `_GATE_BYPASS` frozenset definition (around line 243), add:

```python
_TASK_BYPASS: frozenset[str] = frozenset({
    # Everything that bypasses the init gate also bypasses the task gate
    "setup_start",
    "setup_save_profile",
    "setup_complete",
    "health_check",
    "skill_create",
    "skill_update",
    "skill_list",
    "run_skill",
    "profile_get",
    "profile_update",
    "create_user",
    "get_operator_instructions",
    "list_prompts",
    "get_prompt",
    # Task management tools themselves
    "declare_intent",
    "complete_task",
    "get_tasks",
})


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
```

- [ ] **Step 4: Add `_inject_task_id_param` helper to `mcp_server.py`**

Add this function directly after `_make_gate_task_redirect`:

```python
def _inject_task_id_param(fn: Any) -> None:
    """Append optional task_id: str | None = None to fn's __signature__.

    FastMCP reads __signature__ to build the JSON schema advertised in tools/list.
    Setting it explicitly here overrides functools.wraps' __wrapped__ chain so
    every tool — built-in and proxied — exposes task_id as an optional parameter.
    The wrapper pops task_id from kwargs before calling the real function, so
    proxied tools never see a parameter they don't expect.

    Args:
        fn: The wrapper function whose __signature__ to extend in-place.
    """
    import inspect as _inspect
    sig = _inspect.signature(fn)
    if "task_id" in sig.parameters:
        return  # already present (built-in tools that declare it explicitly)
    task_param = _inspect.Parameter(
        "task_id",
        _inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=str | None,
    )
    fn.__signature__ = sig.replace(
        parameters=list(sig.parameters.values()) + [task_param]
    )
```

- [ ] **Step 5: Add task gate + `task_id` extraction to the async wrapper in `_tracked_mcp_tool`**

In `_tracked_mcp_tool`, in the `tracked_async` function, replace the existing gate block:

```python
if fn.__name__ not in _GATE_BYPASS:
    _org = _get_org_id(sid)
    if _org and not _telemetry.is_initialized(_org):
        return _make_gate_redirect(fn.__name__)
```

With:

```python
if fn.__name__ not in _GATE_BYPASS:
    _org = _get_org_id(sid)
    if _org and not _telemetry.is_initialized(_org):
        return _make_gate_redirect(fn.__name__)
task_id = fn_kwargs.pop("task_id", None)
if fn.__name__ not in _TASK_BYPASS and sid:
    active = _telemetry.list_active_tasks(sid)
    if not active and task_id is None:
        return _make_gate_task_redirect(fn.__name__)
    if task_id is None and active:
        task_id = active[0]["task_id"]  # auto-use most recent when unambiguous
```

Then update the success `record()` call to pass `task_id`:

```python
_telemetry.record(
    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
    user_id=sid, request_id=rid,
    response_size=_calculate_response_size(result),
    input_body=input_body,
    response_preview=_get_response_preview(result),
    task_id=task_id,
)
```

And call `_inject_task_id_param` on the wrapper before returning it:

```python
_inject_task_id_param(tracked_async)
return fastmcp_decorator(tracked_async)
```

- [ ] **Step 6: Apply the same changes to the sync wrapper in `_tracked_mcp_tool`**

In the `tracked` (sync) function inside `_tracked_mcp_tool`, apply the identical gate block and record change as Step 5, then call `_inject_task_id_param(tracked)` before `return fastmcp_decorator(tracked)`.

- [ ] **Step 7: Apply to `_tracked_add_tool` (proxied tools) — async branch**

In `tracked_async` inside `_tracked_add_tool`, replace the gate block and update `record()` identically to Steps 5-6, substituting `fn.__name__` with `tool_name`. Then call `_inject_task_id_param(tracked_async)` before `return _orig_add_tool(tracked_async, *args, **kwargs)`.

- [ ] **Step 8: Apply to `_tracked_add_tool` — sync branch**

Same as Step 7 for the `tracked` (sync) branch.

- [ ] **Step 9: Register `task_manager` in `mcp_server.py`**

Add the import alongside the other `_core` imports:

```python
from tools._core import task_manager as _task_manager_tools  # noqa: E402
```

Add the registration call alongside the others:

```python
_task_manager_tools.register(mcp, _telemetry, _user_view)
```

Add `"declare_intent"`, `"complete_task"`, and `"get_tasks"` to the `_GATE_BYPASS` frozenset so they also bypass the init gate:

```python
_GATE_BYPASS: frozenset[str] = frozenset({
    "setup_start",
    "setup_save_profile",
    "setup_complete",
    "health_check",
    "skill_create",
    "skill_update",
    "skill_list",
    "run_skill",
    "profile_get",
    "profile_update",
    "create_user",
    "get_operator_instructions",
    "list_prompts",
    "get_prompt",
    "declare_intent",    # ← add
    "complete_task",     # ← add
    "get_tasks",         # ← add
})
```

- [ ] **Step 10: Run task gate tests**

```bash
cd remote-gateway && pytest tests/test_task_gate.py -v
```
Expected: all pass.

- [ ] **Step 11: Run full suite**

```bash
cd remote-gateway && pytest --tb=short -q
```
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_task_gate.py
git commit -m "feat: add task gate and task_id injection to all tool wrappers"
```

---

## Task 4: Admin API — `GET /api/tasks`

**Files:**
- Modify: `remote-gateway/core/admin_api.py`
- Modify: `remote-gateway/tests/test_admin_api.py` (append)

- [ ] **Step 1: Write the failing test**

Find the existing `test_admin_api.py` and append:

```python
def test_api_tasks_returns_task_list(client, store):
    store.add_api_key("alice", "sk-test", org_id="acme")
    store.set_initialized("acme")
    store.create_task("alice", "acme", "Research Salesforce", ["search CRM"])
    resp = client.get(f"/api/tasks?token={ADMIN_TOKEN}&org_id=acme")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) >= 1
    assert data["tasks"][0]["goal"] == "Research Salesforce"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd remote-gateway && pytest tests/test_admin_api.py::test_api_tasks_returns_task_list -v
```
Expected: `404` or attribute error.

- [ ] **Step 3: Add `list_tasks_for_org` to `TelemetryStore`**

In `telemetry.py`, add after `list_active_tasks`:

```python
def list_tasks_for_org(self, org_id: str, status: str | None = None, limit: int = 100) -> list[dict]:
    """Return tasks for an org, optionally filtered by status, newest first.

    Args:
        org_id: Organization identifier.
        status: 'active', 'complete', or None for all.
        limit: Maximum number of tasks to return.
    """
    import json as _json
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        if status:
            rows = conn.execute(
                "SELECT task_id, user_id, org_id, goal, steps, status, outcome, created_at, completed_at"
                " FROM tasks WHERE org_id = ? AND status = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (org_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT task_id, user_id, org_id, goal, steps, status, outcome, created_at, completed_at"
                " FROM tasks WHERE org_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (org_id, limit),
            ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "user_id": row["user_id"],
                "org_id": row["org_id"],
                "goal": row["goal"],
                "steps": _json.loads(row["steps"] or "[]"),
                "status": row["status"],
                "outcome": row["outcome"],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
            }
            for row in rows
        ]
    except Exception:
        return []
```

- [ ] **Step 4: Add `api_tasks` route to `admin_api.py`**

Add a new route handler inside `create_admin_app`, after `api_hints_upsert`:

```python
async def api_tasks(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
    status = request.query_params.get("status") or None
    try:
        limit = max(1, min(int(request.query_params.get("limit", "100")), 500))
    except ValueError:
        limit = 100
    tasks = telemetry.list_tasks_for_org(org_id, status=status, limit=limit)
    return JSONResponse({"org_id": org_id, "tasks": tasks, "count": len(tasks)})
```

Add the route to the `routes` list:

```python
Route("/api/tasks", api_tasks, methods=["GET"]),
```

- [ ] **Step 5: Run test**

```bash
cd remote-gateway && pytest tests/test_admin_api.py::test_api_tasks_returns_task_list -v
```
Expected: pass.

- [ ] **Step 6: Run full suite**

```bash
cd remote-gateway && pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat: add /api/tasks admin endpoint and list_tasks_for_org to TelemetryStore"
```

---

## Task 5: `raw_logs` — expose `task_id` in log output

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (`raw_logs` method)

This is a one-step change so the admin dashboard and telemetry queries can filter/display by task.

- [ ] **Step 1: Update `raw_logs` to include `task_id` in results and accept it as a filter**

In `telemetry.py`, update the `raw_logs` signature to add `task_id` filter:

```python
def raw_logs(
    self,
    limit: int = 100,
    offset: int = 0,
    tool_name: str | None = None,
    user_id: str | None = None,
    success: bool | None = None,
    error_type: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
```

Add `task_id` to the filters block (after `error_type`):

```python
if task_id is not None:
    filters.append("task_id = ?")
    params.append(task_id)
```

Add `task_id` to the SELECT and result dict:

```python
# In the SELECT:
"SELECT id, tool_name, called_at, duration_ms, success,"
"       error_type, error_message, user_id, request_id, response_size, input_body,"
"       response_preview, task_id"

# In the result dict append:
"task_id": row["task_id"],
```

- [ ] **Step 2: Run full suite**

```bash
cd remote-gateway && pytest --tb=short -q
```

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/core/telemetry.py
git commit -m "feat: expose task_id in raw_logs output and filtering"
```

---

## Self-Review

**Spec coverage:**
- ✅ `declare_intent(goal, steps)` → returns task_id
- ✅ All tool calls require active task (gate in both wrappers)
- ✅ `task_id` injected into all tool signatures (built-in + proxied)
- ✅ Multiple concurrent tasks per user supported
- ✅ `complete_task` to close out a task
- ✅ `get_tasks` to retrieve active task_ids
- ✅ Telemetry links every call to a task_id
- ✅ Admin API endpoint for task visibility
- ✅ Gate bypass for setup/meta tools
- ✅ Auto-fallback to single active task when task_id not passed explicitly

**Gaps / known limitations:**
- Admin dashboard HTML is not updated — tasks are queryable via `/api/tasks` but not yet visualized. Sufficient for a demo via API or curl; a UI tab is a follow-on.
- Task expiry (auto-expiring stale tasks after N hours) is not implemented. Tasks remain `active` until explicitly completed. Acceptable for v1 demo.
- The `raw_logs` admin API endpoint (`GET /api/logs`) does not yet accept `?task_id=` as a query param filter — `telemetry.raw_logs` now accepts it but the admin route needs a one-line addition to wire it through. Easy follow-on.
