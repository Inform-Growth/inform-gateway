# Sensor Layer v0 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `list_tasks_for_org` and `GET /api/tasks` return the three decision fields (`decision_context`, `decision_type`, `stakes_hint`) and support time-window + process-exclusion filtering so the loom's Decision Assembler can cluster tasks.

**Architecture:** Three small, additive changes — update the DB query method signature, update the admin API handler to parse/forward the new params, and add a compound index for query performance. No new tables, endpoints, or auth.

**Tech Stack:** Python 3.11, SQLite (stdlib sqlite3), Starlette, pytest

---

## File Map

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Update `list_tasks_for_org` signature + SELECT + add compound index to `_SCHEMA_INDEXES` |
| `remote-gateway/core/admin_api.py` | Parse `from`, `to`, `exclude_process` in `api_tasks`; forward to `list_tasks_for_org` |
| `remote-gateway/tests/test_task_manager.py` | Append 3 new tests |

---

## Task 1: Add compound index to `_SCHEMA_INDEXES`

**Files:**
- Modify: `remote-gateway/core/telemetry.py:153-157`

- [ ] **Step 1: Write the failing test**

Append to `remote-gateway/tests/test_task_manager.py`:

```python
def test_compound_index_exists(store):
    conn = store._connect()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tasks_org_created'"
    ).fetchall()
    assert len(rows) == 1, "compound index idx_tasks_org_created must exist"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest remote-gateway/tests/test_task_manager.py::test_compound_index_exists -xvs
```

Expected: FAIL — index does not exist yet.

- [ ] **Step 3: Add the index**

In `remote-gateway/core/telemetry.py`, find the `_SCHEMA_INDEXES` string (around line 153) and append the new index:

```python
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls (tool_name);
CREATE INDEX IF NOT EXISTS idx_called_at ON tool_calls (called_at);
CREATE INDEX IF NOT EXISTS idx_user_id   ON tool_calls (user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_org_created ON tasks (org_id, created_at);
"""
```

- [ ] **Step 4: Run to verify it passes**

```
pytest remote-gateway/tests/test_task_manager.py::test_compound_index_exists -xvs
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: add compound index idx_tasks_org_created for loom time-window queries"
```

---

## Task 2: Update `list_tasks_for_org` to include decision fields and filters

**Files:**
- Modify: `remote-gateway/core/telemetry.py:1236-1278`
- Test: `remote-gateway/tests/test_task_manager.py`

- [ ] **Step 1: Write three failing tests**

Append to `remote-gateway/tests/test_task_manager.py`:

```python
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
    base = _time.time()
    store.create_task("alice", "acme", "Early task", [])
    # Manually insert tasks at controlled timestamps
    import json as _json
    import secrets as _secrets
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
```

- [ ] **Step 2: Run to verify they all fail**

```
pytest remote-gateway/tests/test_task_manager.py::test_list_tasks_for_org_includes_decision_fields remote-gateway/tests/test_task_manager.py::test_list_tasks_for_org_time_window remote-gateway/tests/test_task_manager.py::test_list_tasks_for_org_exclude_process -xvs
```

Expected: FAIL — `list_tasks_for_org` missing decision fields and new params.

- [ ] **Step 3: Replace `list_tasks_for_org` in `telemetry.py`**

Find the current method at line ~1236. Replace the entire method (from `def list_tasks_for_org` through its closing `except Exception: return []`) with:

```python
def list_tasks_for_org(
    self,
    org_id: str,
    status: str | None = None,
    limit: int = 100,
    from_ts: float | None = None,
    to_ts: float | None = None,
    exclude_process: bool = False,
) -> list[dict]:
    """Return tasks for an org, optionally filtered, newest first.

    Args:
        org_id: Organization identifier.
        status: 'active', 'complete', or None for all.
        limit: Maximum number of tasks to return.
        from_ts: Unix timestamp — include tasks created at or after this time.
        to_ts: Unix timestamp — include tasks created at or before this time.
        exclude_process: If True, omit tasks where decision_type = 'process'.
            NULL decision_type rows are kept (loom treats them as 'exploration').
    """
    import json as _json
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        filters: list[str] = ["org_id = ?"]
        params: list = [org_id]
        if status:
            filters.append("status = ?")
            params.append(status)
        if from_ts is not None:
            filters.append("created_at >= ?")
            params.append(from_ts)
        if to_ts is not None:
            filters.append("created_at <= ?")
            params.append(to_ts)
        if exclude_process:
            filters.append("(decision_type IS NULL OR decision_type != 'process')")
        where = "WHERE " + " AND ".join(filters)
        params.append(limit)
        rows = conn.execute(
            f"SELECT task_id, user_id, org_id, goal, steps, status, outcome,"
            f" created_at, completed_at, decision_context, decision_type, stakes_hint"
            f" FROM tasks {where}"
            f" ORDER BY created_at DESC LIMIT ?",
            params,
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
                "decision_context": row["decision_context"],
                "decision_type": row["decision_type"],
                "stakes_hint": row["stakes_hint"],
            }
            for row in rows
        ]
    except Exception:
        return []
```

- [ ] **Step 4: Run to verify the three new tests pass**

```
pytest remote-gateway/tests/test_task_manager.py::test_list_tasks_for_org_includes_decision_fields remote-gateway/tests/test_task_manager.py::test_list_tasks_for_org_time_window remote-gateway/tests/test_task_manager.py::test_list_tasks_for_org_exclude_process -xvs
```

Expected: all three PASS.

- [ ] **Step 5: Run the full test file to check for regressions**

```
pytest remote-gateway/tests/test_task_manager.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: update list_tasks_for_org with decision fields and time-window/process filters"
```

---

## Task 3: Update `GET /api/tasks` to accept and forward new query params

**Files:**
- Modify: `remote-gateway/core/admin_api.py:418-428`

- [ ] **Step 1: Write the failing test**

This is an integration test at the HTTP layer. Append to `remote-gateway/tests/test_task_manager.py`:

```python
import time as _time_mod
from starlette.testclient import TestClient


def test_api_tasks_filters_passed_through(store):
    """GET /api/tasks?from=&to=&exclude_process=true filters tasks correctly."""
    from admin_api import create_admin_app
    import os
    os.environ["ADMIN_TOKEN"] = "test-token"

    app = create_admin_app(store)
    client = TestClient(app, raise_server_exceptions=True)

    base = _time_mod.time()
    # Insert tasks at controlled timestamps via SQL
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
    # decision fields present
    for task in data["tasks"]:
        assert "decision_context" in task
        assert "decision_type" in task
        assert "stakes_hint" in task
```

- [ ] **Step 2: Run to verify it fails**

```
pytest remote-gateway/tests/test_task_manager.py::test_api_tasks_filters_passed_through -xvs
```

Expected: FAIL — `api_tasks` doesn't parse `from`, `to`, or `exclude_process`.

- [ ] **Step 3: Update `api_tasks` in `admin_api.py`**

Find the `api_tasks` async function (around line 418). Replace it with:

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
    from_ts: float | None = None
    to_ts: float | None = None
    try:
        if "from" in request.query_params:
            from_ts = float(request.query_params["from"])
        if "to" in request.query_params:
            to_ts = float(request.query_params["to"])
    except ValueError:
        pass
    exclude_process = request.query_params.get("exclude_process", "").lower() == "true"
    tasks = telemetry.list_tasks_for_org(
        org_id,
        status=status,
        limit=limit,
        from_ts=from_ts,
        to_ts=to_ts,
        exclude_process=exclude_process,
    )
    return JSONResponse({"org_id": org_id, "tasks": tasks, "count": len(tasks)})
```

- [ ] **Step 4: Run to verify the new test passes**

```
pytest remote-gateway/tests/test_task_manager.py::test_api_tasks_filters_passed_through -xvs
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```
pytest remote-gateway/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: expose from/to/exclude_process query params on GET /api/tasks"
```

---

## Self-Review Against Spec

| Spec requirement | Task that covers it |
|---|---|
| `list_tasks_for_org` includes `decision_context`, `decision_type`, `stakes_hint` | Task 2 step 3 (SELECT + returned dict) |
| `from_ts` / `to_ts` filtering in `list_tasks_for_org` | Task 2 step 3 |
| `exclude_process` filtering (NULL rows kept) | Task 2 step 3 |
| `GET /api/tasks` accepts `from`, `to`, `exclude_process` params | Task 3 step 3 |
| Compound index `idx_tasks_org_created ON tasks (org_id, created_at)` | Task 1 step 3 |
| 3 tests in `test_task_manager.py`: decision fields, time window, exclude process | Task 2 steps 1–4 |
| Response shape includes decision fields per task | Task 2 (telemetry method) + Task 3 (API test assertion) |
