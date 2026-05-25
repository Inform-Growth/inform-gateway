# Input Size Tracking + Raw Logs View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store tool input bodies alongside existing response tracking, surface avg input/output sizes in the dashboard health table, and add a Logs tab with paginated raw call rows (including expandable input body inspection).

**Architecture:** Add `input_body TEXT` column to `tool_calls` via the existing migration pattern. Capture `json.dumps(fn_kwargs)` at the four telemetry call sites in `mcp_server.py`. Expose a paginated `/api/logs` endpoint. Update the dashboard HTML to add two size columns to the existing health table and a new "Logs" tab with filter controls and a click-to-expand input body panel.

**Tech Stack:** Python 3.11+, SQLite (via telemetry.py migration pattern), Starlette, vanilla JS (existing dashboard pattern)

---

## File Map

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Add `input_body TEXT` column + migration; update `record()`, `stats()`, add `raw_logs()` |
| `remote-gateway/core/mcp_server.py` | Add `import json`; compute `input_body` and pass to `record()` at 4 call sites |
| `remote-gateway/core/admin_api.py` | Add `GET /api/logs` handler + route |
| `remote-gateway/core/admin_dashboard.html` | Add Avg Input/Output columns to health table; add Logs tab + JS |
| `remote-gateway/tests/test_telemetry_permissions.py` | Tests for `input_body` in `record()`, `stats()`, `raw_logs()` |
| `remote-gateway/tests/test_admin_api.py` | Tests for `/api/logs` endpoint |

---

### Task 1: Extend TelemetryStore — schema, record(), stats(), raw_logs()

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Test: `remote-gateway/tests/test_telemetry_permissions.py`

- [ ] **Step 1: Write failing tests**

Append these tests to `remote-gateway/tests/test_telemetry_permissions.py`:

```python
def test_record_stores_input_body(store):
    store.record("health_check", 10, True, input_body='{"q": "hello"}')
    logs = store.raw_logs(limit=1)
    assert logs[0]["input_body"] == '{"q": "hello"}'


def test_stats_includes_avg_input_size(store):
    store.record("health_check", 10, True, input_body='{"q": "hello"}')
    stats = store.stats()
    tool = next(t for t in stats["tools"] if t["name"] == "health_check")
    assert "avg_input_size" in tool
    assert tool["avg_input_size"] > 0


def test_raw_logs_returns_recent_calls(store):
    store.record("tool_a", 10, True, user_id="alice", input_body='{"x": 1}')
    store.record("tool_b", 20, False, user_id="alice", error_type="ValueError")
    logs = store.raw_logs(limit=10)
    assert len(logs) == 2
    names = {l["tool_name"] for l in logs}
    assert names == {"tool_a", "tool_b"}


def test_raw_logs_filters_by_tool(store):
    store.record("tool_a", 10, True)
    store.record("tool_b", 20, True)
    logs = store.raw_logs(tool_name="tool_a")
    assert all(l["tool_name"] == "tool_a" for l in logs)


def test_raw_logs_filters_by_user(store):
    store.record("health_check", 10, True, user_id="alice")
    store.record("health_check", 10, True, user_id="bob")
    logs = store.raw_logs(user_id="alice")
    assert all(l["user_id"] == "alice" for l in logs)


def test_raw_logs_filters_errors_only(store):
    store.record("health_check", 10, True)
    store.record("health_check", 10, False, error_type="ValueError")
    logs = store.raw_logs(success=False)
    assert all(not l["success"] for l in logs)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest remote-gateway/tests/test_telemetry_permissions.py::test_record_stores_input_body -v
```
Expected: `FAILED` with `AttributeError: 'TelemetryStore' object has no attribute 'raw_logs'`

- [ ] **Step 3: Add `input_body` to `_SCHEMA_TABLES`**

In `remote-gateway/core/telemetry.py`, find the `CREATE TABLE IF NOT EXISTS tool_calls` block (lines 53–63) and add `input_body TEXT` as the last column:

```python
_SCHEMA_TABLES = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS api_keys (
    key         TEXT    PRIMARY KEY,
    user_id     TEXT    NOT NULL,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name     TEXT    NOT NULL,
    called_at     REAL    NOT NULL,
    duration_ms   INTEGER NOT NULL,
    success       INTEGER NOT NULL,
    error_type    TEXT,
    user_id       TEXT,
    request_id    TEXT,
    response_size INTEGER,
    input_body    TEXT
);

CREATE TABLE IF NOT EXISTS tool_permissions (
    user_id   TEXT    NOT NULL,
    tool_name TEXT    NOT NULL,
    enabled   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, tool_name)
);
"""
```

- [ ] **Step 4: Add migration entry for `input_body`**

In the `_MIGRATIONS` list (lines 82–86), append the new column:

```python
_MIGRATIONS = [
    ("tool_calls", "user_id",       "TEXT"),
    ("tool_calls", "request_id",    "TEXT"),
    ("tool_calls", "response_size", "INTEGER"),
    ("tool_calls", "input_body",    "TEXT"),
]
```

- [ ] **Step 5: Update `record()` signature and INSERT**

Replace the `record()` method (lines 305–344) with:

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
) -> None:
    """Record a single tool invocation. Silent no-op if disabled.

    Args:
        tool_name: Name of the tool function that was called.
        duration_ms: Wall-clock time in milliseconds.
        success: True if the tool returned normally, False if it raised.
        error_type: Exception class name on failure, otherwise None.
        user_id: Resolved from the caller's API key by the auth middleware.
            None for unauthenticated calls.
        request_id: Unique MCP request ID for this invocation.
        response_size: Size of the response in characters/bytes.
        input_body: JSON-serialized tool arguments captured at call time.
    """
    if not self._enabled:
        return
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO tool_calls"
            " (tool_name, called_at, duration_ms, success,"
            "  error_type, user_id, request_id, response_size, input_body)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tool_name, time.time(), duration_ms, int(success),
                error_type, user_id, request_id, response_size, input_body,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # telemetry must never break the gateway
```

- [ ] **Step 6: Update `stats()` to include avg/max input size**

In the `stats()` SELECT query (lines 375–391), add two aggregates:

```python
rows = conn.execute(
    f"""
    SELECT
        tool_name,
        COUNT(*)                                       AS call_count,
        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END)  AS error_count,
        MAX(called_at)                                 AS last_called_ts,
        AVG(duration_ms)                               AS avg_ms,
        MAX(duration_ms)                               AS max_ms,
        AVG(response_size)                             AS avg_size,
        MAX(response_size)                             AS max_size,
        AVG(LENGTH(input_body))                        AS avg_input_size,
        MAX(LENGTH(input_body))                        AS max_input_size
    FROM tool_calls
    {where}
    GROUP BY tool_name
    ORDER BY call_count DESC
    """,
    params,
).fetchall()
```

And in the `tools.append(...)` dict (lines 413–425), add:

```python
tools.append(
    {
        "name": row["tool_name"],
        "call_count": call_count,
        "error_count": error_count,
        "error_rate": f"{error_rate:.1%}",
        "last_called": last_called,
        "avg_duration_ms": round(row["avg_ms"] or 0),
        "max_duration_ms": row["max_ms"] or 0,
        "avg_response_size": round(row["avg_size"] or 0),
        "max_response_size": row["max_size"] or 0,
        "avg_input_size": round(row["avg_input_size"] or 0),
        "max_input_size": row["max_input_size"] or 0,
    }
)
```

- [ ] **Step 7: Add `raw_logs()` method**

Add this method after `daily_activity()` (before the `# Module-level singleton` comment):

```python
def raw_logs(
    self,
    limit: int = 100,
    offset: int = 0,
    tool_name: str | None = None,
    user_id: str | None = None,
    success: bool | None = None,
) -> list[dict[str, Any]]:
    """Return recent raw tool call rows, newest first.

    Args:
        limit: Max rows to return.
        offset: Rows to skip for pagination.
        tool_name: Filter to an exact tool name.
        user_id: Filter to an exact user_id.
        success: If True, only successful calls; if False, only errors.

    Returns:
        List of dicts with id, tool_name, called_at, duration_ms, success,
        error_type, user_id, request_id, response_size, input_size, input_body.
    """
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        filters: list[str] = []
        params: list[Any] = []
        if tool_name is not None:
            filters.append("tool_name = ?")
            params.append(tool_name)
        if user_id is not None:
            filters.append("user_id = ?")
            params.append(user_id)
        if success is not None:
            filters.append("success = ?")
            params.append(int(success))
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"""
            SELECT id, tool_name, called_at, duration_ms, success,
                   error_type, user_id, request_id, response_size, input_body
            FROM tool_calls
            {where}
            ORDER BY called_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        conn.close()
    except Exception:
        return []
    result = []
    for row in rows:
        ts = row["called_at"]
        called_at_str = (
            datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            if ts
            else None
        )
        result.append(
            {
                "id": row["id"],
                "tool_name": row["tool_name"],
                "called_at": called_at_str,
                "duration_ms": row["duration_ms"],
                "success": bool(row["success"]),
                "error_type": row["error_type"],
                "user_id": row["user_id"],
                "request_id": row["request_id"],
                "response_size": row["response_size"],
                "input_size": len(row["input_body"]) if row["input_body"] else None,
                "input_body": row["input_body"],
            }
        )
    return result
```

- [ ] **Step 8: Run all new tests to confirm they pass**

```
pytest remote-gateway/tests/test_telemetry_permissions.py -v -k "input or raw_logs"
```
Expected: all 6 new tests PASS.

- [ ] **Step 9: Run full test suite to check for regressions**

```
pytest remote-gateway/tests/test_telemetry_permissions.py remote-gateway/tests/test_admin_api.py -v
```
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_permissions.py
git commit -m "feat: add input_body to tool_calls; expose avg_input_size in stats + raw_logs()"
```

---

### Task 2: Capture input body at all 4 call sites in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Add `import json` to imports**

In `remote-gateway/core/mcp_server.py`, find the imports block (around lines 19–27). Add `import json` after `import functools`:

```python
import asyncio
import contextvars
import functools
import inspect
import json
import os
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
```

- [ ] **Step 2: Update `tracked_async` inside `_tracked_mcp_tool` (lines ~281–298)**

Replace the `tracked_async` function body:

```python
async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
    t0 = _time.monotonic()
    sid, rid = _get_call_ids()
    input_body = json.dumps(fn_kwargs, default=str)
    if sid and not _telemetry.has_permission(sid, fn.__name__):
        raise PermissionError(f"Tool '{fn.__name__}' is disabled for your account.")
    try:
        result = await fn(*fn_args, **fn_kwargs)
        _telemetry.record(
            fn.__name__, int((_time.monotonic() - t0) * 1000), True,
            user_id=sid, request_id=rid,
            response_size=_calculate_response_size(result),
            input_body=input_body,
        )
        return result
    except Exception as exc:
        _telemetry.record(
            fn.__name__, int((_time.monotonic() - t0) * 1000), False,
            type(exc).__name__, user_id=sid, request_id=rid,
            input_body=input_body,
        )
        raise
```

- [ ] **Step 3: Update `tracked` (sync) inside `_tracked_mcp_tool` (lines ~302–320)**

Replace the `tracked` function body:

```python
def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
    t0 = _time.monotonic()
    sid, rid = _get_call_ids()
    input_body = json.dumps(fn_kwargs, default=str)
    if sid and not _telemetry.has_permission(sid, fn.__name__):
        raise PermissionError(f"Tool '{fn.__name__}' is disabled for your account.")
    try:
        result = fn(*fn_args, **fn_kwargs)
        _telemetry.record(
            fn.__name__, int((_time.monotonic() - t0) * 1000), True,
            user_id=sid, request_id=rid,
            response_size=_calculate_response_size(result),
            input_body=input_body,
        )
        return result
    except Exception as exc:
        _telemetry.record(
            fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
            user_id=sid, request_id=rid,
            input_body=input_body,
        )
        raise
```

- [ ] **Step 4: Update `tracked_async` inside `_tracked_add_tool` (lines ~341–360)**

Replace the `tracked_async` function body:

```python
async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
    t0 = _time.monotonic()
    sid, rid = _get_call_ids()
    input_body = json.dumps(fn_kwargs, default=str)
    if sid and not _telemetry.has_permission(sid, tool_name):
        raise PermissionError(f"Tool '{tool_name}' is disabled for your account.")
    try:
        result = await fn(*fn_args, **fn_kwargs)
        _telemetry.record(
            tool_name, int((_time.monotonic() - t0) * 1000), True,
            user_id=sid, request_id=rid,
            response_size=_calculate_response_size(result),
            input_body=input_body,
        )
        return result
    except Exception as exc:
        _telemetry.record(
            tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
            user_id=sid, request_id=rid,
            input_body=input_body,
        )
        raise
```

- [ ] **Step 5: Update `tracked` (sync) inside `_tracked_add_tool` (lines ~364–382)**

Replace the `tracked` function body:

```python
def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
    t0 = _time.monotonic()
    sid, rid = _get_call_ids()
    input_body = json.dumps(fn_kwargs, default=str)
    if sid and not _telemetry.has_permission(sid, tool_name):
        raise PermissionError(f"Tool '{tool_name}' is disabled for your account.")
    try:
        result = fn(*fn_args, **fn_kwargs)
        _telemetry.record(
            tool_name, int((_time.monotonic() - t0) * 1000), True,
            user_id=sid, request_id=rid,
            response_size=_calculate_response_size(result),
            input_body=input_body,
        )
        return result
    except Exception as exc:
        _telemetry.record(
            tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
            user_id=sid, request_id=rid,
            input_body=input_body,
        )
        raise
```

- [ ] **Step 6: Run existing telemetry tests to confirm no regressions**

```
pytest remote-gateway/tests/test_telemetry_permissions.py remote-gateway/tests/test_admin_api.py -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat: capture input_body from fn_kwargs at all telemetry call sites"
```

---

### Task 3: Add GET /api/logs endpoint to admin_api.py

**Files:**
- Modify: `remote-gateway/core/admin_api.py`
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing tests**

Append to `remote-gateway/tests/test_admin_api.py`:

```python
# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def test_logs_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/api/logs")
    assert resp.status_code == 403


def test_logs_returns_list(client):
    c, store = client
    store.record("health_check", 10, True, user_id="alice", input_body='{"x": 1}')
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["tool_name"] == "health_check"
    assert "input_body" in body[0]
    assert "input_size" in body[0]


def test_logs_filters_by_tool(client):
    c, store = client
    store.record("tool_a", 10, True)
    store.record("tool_b", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}&tool=tool_a")
    assert resp.status_code == 200
    assert all(row["tool_name"] == "tool_a" for row in resp.json())


def test_logs_filters_errors_only(client):
    c, store = client
    store.record("health_check", 10, True)
    store.record("health_check", 10, False, error_type="ValueError")
    resp = c.get(f"/api/logs?token={TOKEN}&success=false")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["success"] is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest remote-gateway/tests/test_admin_api.py::test_logs_returns_list -v
```
Expected: `FAILED` — 404 or attribute error because route doesn't exist.

- [ ] **Step 3: Add `api_logs` handler inside `create_admin_app()` in admin_api.py**

Add this handler after `api_tools` (around line 158), before the `routes` list:

```python
async def api_logs(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    try:
        limit = int(request.query_params.get("limit", "100"))
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        limit, offset = 100, 0
    tool = request.query_params.get("tool") or None
    user = request.query_params.get("user") or None
    success_param = request.query_params.get("success")
    success: bool | None = None
    if success_param == "true":
        success = True
    elif success_param == "false":
        success = False
    return JSONResponse(
        telemetry.raw_logs(
            limit=limit,
            offset=offset,
            tool_name=tool,
            user_id=user,
            success=success,
        )
    )
```

- [ ] **Step 4: Register the route**

In the `routes` list (around line 176), add:

```python
Route("/api/logs", api_logs),
```

- [ ] **Step 5: Run tests to confirm they pass**

```
pytest remote-gateway/tests/test_admin_api.py -v -k "logs"
```
Expected: 4 new tests PASS.

- [ ] **Step 6: Run full test suite**

```
pytest remote-gateway/tests/test_admin_api.py remote-gateway/tests/test_telemetry_permissions.py -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat: add GET /api/logs endpoint with tool/user/success filters"
```

---

### Task 4: Update dashboard — size columns + Logs tab

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

No automated tests — verify visually in browser after completion.

- [ ] **Step 1: Add "Logs" tab to the tab-bar**

Find the tab-bar block (around line 436–440):
```html
<div class="tab-bar">
  <div class="tab active" id="tab-exec" onclick="switchTab('exec')">Executive</div>
  <div class="tab" id="tab-ops" onclick="switchTab('ops')">Ops</div>
  <div class="tab" id="tab-tools" onclick="switchTab('tools')">Tools</div>
</div>
```

Replace with:
```html
<div class="tab-bar">
  <div class="tab active" id="tab-exec" onclick="switchTab('exec')">Executive</div>
  <div class="tab" id="tab-ops" onclick="switchTab('ops')">Ops</div>
  <div class="tab" id="tab-tools" onclick="switchTab('tools')">Tools</div>
  <div class="tab" id="tab-logs" onclick="switchTab('logs')">Logs</div>
</div>
```

- [ ] **Step 2: Add view-logs div**

Find the closing `</div>` of `view-tools` (line ~574) and the `</main>` tag (line ~576). Insert the new view between them:

```html
  <!-- ======== LOGS VIEW ======== -->
  <div class="view" id="view-logs">
    <div class="section-box">
      <div class="section-title">Raw Tool Logs</div>
      <div style="display:flex;gap:0.6rem;margin-bottom:1rem;flex-wrap:wrap;">
        <input type="text" id="logs-filter-tool" placeholder="Filter by tool…"
          style="padding:0.35rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;flex:1;min-width:160px;"
          oninput="loadLogs()" />
        <input type="text" id="logs-filter-user" placeholder="Filter by user…"
          style="padding:0.35rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;flex:1;min-width:160px;"
          oninput="loadLogs()" />
        <select id="logs-filter-success"
          style="padding:0.35rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-size:0.82rem;"
          onchange="loadLogs()">
          <option value="">All</option>
          <option value="true">Success only</option>
          <option value="false">Errors only</option>
        </select>
      </div>
      <div style="overflow-x:auto;">
        <table id="logs-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Tool</th>
              <th>User</th>
              <th>Duration</th>
              <th>In Size</th>
              <th>Out Size</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="logs-tbody"></tbody>
        </table>
      </div>
      <div id="logs-body-panel" style="display:none;margin-top:1rem;padding:0.8rem 1rem;background:var(--cream-dark);border:1px solid var(--border);">
        <div style="font-family:'Arial',sans-serif;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--text-muted);margin-bottom:0.4rem;">Input Body</div>
        <pre id="logs-body-content" style="font-family:'Courier New',monospace;font-size:0.78rem;white-space:pre-wrap;word-break:break-word;color:var(--text);max-height:300px;overflow-y:auto;margin:0;"></pre>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Update `switchTab()` to include `'logs'`**

Find `switchTab` (around line 636):
```javascript
function switchTab(tab) {
  currentTab = tab;
  ['exec', 'ops', 'tools'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('active', t === tab);
    document.getElementById('view-' + t).classList.toggle('active', t === tab);
  });
  if (tab === 'exec') loadExec();
  else if (tab === 'ops') loadOps();
  else loadTools();
}
```

Replace with:
```javascript
function switchTab(tab) {
  currentTab = tab;
  ['exec', 'ops', 'tools', 'logs'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('active', t === tab);
    document.getElementById('view-' + t).classList.toggle('active', t === tab);
  });
  if (tab === 'exec') loadExec();
  else if (tab === 'ops') loadOps();
  else if (tab === 'logs') loadLogs();
  else loadTools();
}
```

- [ ] **Step 4: Update `refreshCurrent()` to include logs**

Find `refreshCurrent` (around line 647):
```javascript
function refreshCurrent() {
  if (currentTab === 'exec') loadExec();
  else loadOps();
}
```

Replace with:
```javascript
function refreshCurrent() {
  if (currentTab === 'exec') loadExec();
  else if (currentTab === 'ops') loadOps();
  else if (currentTab === 'logs') loadLogs();
  else loadTools();
}
```

- [ ] **Step 5: Add `fmtBytes()` utility function**

Find `fmtDate` (around line 617) and add `fmtBytes` after it:

```javascript
function fmtBytes(v) {
  if (v == null || v === 0) return '—';
  const n = Number(v);
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / (1024 * 1024)).toFixed(1) + ' MB';
}
```

- [ ] **Step 6: Add Avg Input / Avg Output columns to health table header**

Find the health table `<thead>` (around line 490–498):
```html
<thead>
  <tr>
    <th onclick="sortHealth('tool_name')">Tool</th>
    <th onclick="sortHealth('calls')">Calls</th>
    <th onclick="sortHealth('errors')">Errors</th>
    <th onclick="sortHealth('error_rate')">Error Rate</th>
    <th onclick="sortHealth('avg_latency_ms')">Avg Latency</th>
    <th onclick="sortHealth('max_latency_ms')">Max Latency</th>
    <th onclick="sortHealth('last_called_at')">Last Called</th>
  </tr>
</thead>
```

Replace with:
```html
<thead>
  <tr>
    <th onclick="sortHealth('tool_name')">Tool</th>
    <th onclick="sortHealth('calls')">Calls</th>
    <th onclick="sortHealth('errors')">Errors</th>
    <th onclick="sortHealth('error_rate')">Error Rate</th>
    <th onclick="sortHealth('avg_latency_ms')">Avg Latency</th>
    <th onclick="sortHealth('max_latency_ms')">Max Latency</th>
    <th onclick="sortHealth('avg_input_size')">Avg Input</th>
    <th onclick="sortHealth('avg_response_size')">Avg Output</th>
    <th onclick="sortHealth('last_called_at')">Last Called</th>
  </tr>
</thead>
```

- [ ] **Step 7: Add size values to `renderHealthTable()` row template**

Find the row template in `renderHealthTable()` (around lines 897–906):
```javascript
return `<tr>
  <td>${escHtml(t.name)}</td>
  <td>${escHtml(calls)}</td>
  <td>${escHtml(errors)}</td>
  <td><span class="badge ${badgeCls}">${ratePct}%</span></td>
  <td>${fmtMs(t.avg_duration_ms)}</td>
  <td>${fmtMs(t.max_duration_ms)}</td>
  <td>${fmtDate(t.last_called)}</td>
</tr>`;
```

Replace with:
```javascript
return `<tr>
  <td>${escHtml(t.name)}</td>
  <td>${escHtml(calls)}</td>
  <td>${escHtml(errors)}</td>
  <td><span class="badge ${badgeCls}">${ratePct}%</span></td>
  <td>${fmtMs(t.avg_duration_ms)}</td>
  <td>${fmtMs(t.max_duration_ms)}</td>
  <td>${fmtBytes(t.avg_input_size)}</td>
  <td>${fmtBytes(t.avg_response_size)}</td>
  <td>${fmtDate(t.last_called)}</td>
</tr>`;
```

- [ ] **Step 8: Add `loadLogs()` and `renderLogsTable()` JS functions**

Find the `// Init` comment (around line 1169) and insert the following block before it:

```javascript
// ----------------------------------------------------------------
// Logs view
// ----------------------------------------------------------------
let _logsBodyMap = {};
let _selectedLogId = null;

async function loadLogs() {
  const tool = (document.getElementById('logs-filter-tool').value || '').trim();
  const user = (document.getElementById('logs-filter-user').value || '').trim();
  const success = document.getElementById('logs-filter-success').value;
  let url = apiUrl('/api/logs') + '&limit=200';
  if (tool) url += '&tool=' + encodeURIComponent(tool);
  if (user) url += '&user=' + encodeURIComponent(user);
  if (success) url += '&success=' + encodeURIComponent(success);
  try {
    const res = await fetch(url);
    const logs = await res.json();
    renderLogsTable(Array.isArray(logs) ? logs : []);
    updateTimestamp();
  } catch (e) {
    console.error('loadLogs error:', e);
  }
}

function renderLogsTable(logs) {
  _logsBodyMap = {};
  _selectedLogId = null;
  document.getElementById('logs-body-panel').style.display = 'none';
  const tbody = document.getElementById('logs-tbody');

  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);font-style:italic;text-align:center;">No log entries match.</td></tr>';
    return;
  }

  logs.forEach(row => {
    if (row.input_body != null) _logsBodyMap[row.id] = row.input_body;
  });

  tbody.innerHTML = logs.map(row => {
    const statusBadge = row.success
      ? '<span class="badge badge-green">OK</span>'
      : '<span class="badge badge-orange" title="' + escHtml(row.error_type || '') + '">' + escHtml(row.error_type || 'ERR') + '</span>';
    const hasBody = row.input_body != null;
    const rowStyle = hasBody ? 'cursor:pointer;' : '';
    const onclick = hasBody ? ' onclick="showLogBody(' + row.id + ')"' : '';
    return '<tr style="' + rowStyle + '"' + onclick + '>'
      + '<td style="white-space:nowrap;font-size:0.75rem;">' + escHtml(row.called_at || '—') + '</td>'
      + '<td>' + escHtml(row.tool_name) + '</td>'
      + '<td style="font-size:0.78rem;">' + escHtml(row.user_id || '—') + '</td>'
      + '<td>' + fmtMs(row.duration_ms) + '</td>'
      + '<td>' + fmtBytes(row.input_size) + '</td>'
      + '<td>' + fmtBytes(row.response_size) + '</td>'
      + '<td>' + statusBadge + '</td>'
      + '</tr>';
  }).join('');
}

function showLogBody(id) {
  const panel = document.getElementById('logs-body-panel');
  const content = document.getElementById('logs-body-content');
  if (_selectedLogId === id) {
    panel.style.display = 'none';
    _selectedLogId = null;
    return;
  }
  _selectedLogId = id;
  const body = _logsBodyMap[id] || '';
  try {
    content.textContent = JSON.stringify(JSON.parse(body), null, 2);
  } catch (_) {
    content.textContent = body;
  }
  panel.style.display = 'block';
}
```

- [ ] **Step 9: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add Logs tab and avg input/output size columns to dashboard"
```
