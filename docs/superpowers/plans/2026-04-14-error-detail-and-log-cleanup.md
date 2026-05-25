# Error Detail Panel + Server Log Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface full error messages in the admin Logs tab when clicking a row, and eliminate the three sources of server log noise (FastMCP duplicate warnings, stdio subprocess JSON spam, Node.js DeprecationWarning).

**Architecture:** Add an `error_message` column to telemetry (DB migration + record() update + raw_logs() return), populate it in the mcp_server.py telemetry wrappers when an exception is caught, expose it in the admin API, and display it in the dashboard detail panel. Separately, suppress log noise at its three sources: FastMCP settings, stdio_client errlog, and NODE_NO_WARNINGS env var.

**Tech Stack:** Python 3.11+, SQLite (via stdlib sqlite3), Starlette TestClient, FastMCP, MCP Python SDK stdio_client, vanilla JS admin dashboard.

---

## File Map

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Add `error_message` column to schema + migration; add param to `record()`; return in `raw_logs()` |
| `remote-gateway/core/mcp_server.py` | Capture `str(exc)` as `error_message` in both telemetry wrappers; suppress FastMCP duplicate warnings |
| `remote-gateway/core/mcp_proxy.py` | Suppress stdio subprocess stderr; inject `NODE_NO_WARNINGS=1` |
| `remote-gateway/core/admin_dashboard.html` | Store error_message per row; expand detail panel to show Request + Error sections; make error rows clickable |
| `remote-gateway/tests/test_telemetry_permissions.py` | Add tests for error_message storage and retrieval |
| `remote-gateway/tests/test_admin_api.py` | Add test that error_message appears in /api/logs response |

---

## Task 1: Add `error_message` to telemetry DB

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Test: `remote-gateway/tests/test_telemetry_permissions.py`

- [ ] **Step 1: Write failing tests**

Add to `remote-gateway/tests/test_telemetry_permissions.py` (after the existing `test_record_stores_input_body` test):

```python
def test_record_stores_error_message(store):
    store.record("my_tool", 10, False, error_type="ValueError", error_message="bad value: foo")
    logs = store.raw_logs(limit=1)
    assert logs[0]["error_message"] == "bad value: foo"


def test_record_error_message_none_on_success(store):
    store.record("my_tool", 10, True)
    logs = store.raw_logs(limit=1)
    assert logs[0]["error_message"] is None


def test_record_error_message_missing_param_defaults_none(store):
    # Calling record() without error_message (old callers) must still work.
    store.record("my_tool", 10, False, error_type="Exception")
    logs = store.raw_logs(limit=1)
    assert "error_message" in logs[0]
    assert logs[0]["error_message"] is None
```

- [ ] **Step 2: Run failing tests**

```bash
pytest remote-gateway/tests/test_telemetry_permissions.py::test_record_stores_error_message remote-gateway/tests/test_telemetry_permissions.py::test_record_error_message_none_on_success remote-gateway/tests/test_telemetry_permissions.py::test_record_error_message_missing_param_defaults_none -v
```

Expected: FAIL — `record()` has no `error_message` param, `raw_logs()` dict has no `error_message` key.

- [ ] **Step 3: Add column to schema and migration**

In `remote-gateway/core/telemetry.py`, make these three edits:

**Edit 1** — add column to `_SCHEMA_TABLES` (the `CREATE TABLE IF NOT EXISTS tool_calls` block):

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
    error_message TEXT,
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

**Edit 2** — add migration entry to `_MIGRATIONS` list (after the existing `input_body` entry):

```python
_MIGRATIONS = [
    ("tool_calls", "user_id",        "TEXT"),
    ("tool_calls", "request_id",     "TEXT"),
    ("tool_calls", "response_size",  "INTEGER"),
    ("tool_calls", "input_body",     "TEXT"),
    ("tool_calls", "error_message",  "TEXT"),
]
```

**Edit 3** — update `record()` signature and INSERT:

Change the method signature from:
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
```
to:
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
) -> None:
```

Update the docstring Args block — add after `input_body`:
```
            error_message: str(exc) on failure, otherwise None.
```

Update the INSERT statement:
```python
conn.execute(
    "INSERT INTO tool_calls"
    " (tool_name, called_at, duration_ms, success,"
    "  error_type, error_message, user_id, request_id, response_size, input_body)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (
        tool_name, time.time(), duration_ms, int(success),
        error_type, error_message, user_id, request_id, response_size, input_body,
    ),
)
```

- [ ] **Step 4: Return `error_message` from `raw_logs()`**

In `raw_logs()`, update the SELECT query to include `error_message`:

```python
rows = conn.execute(
    f"""
    SELECT id, tool_name, called_at, duration_ms, success,
           error_type, error_message, user_id, request_id, response_size, input_body
    FROM tool_calls
    {where}
    ORDER BY called_at DESC
    LIMIT ? OFFSET ?
    """,
    params,
).fetchall()
```

Update the dict in the `result.append(...)` call — add `error_message` after `error_type`:

```python
result.append(
    {
        "id": row["id"],
        "tool_name": row["tool_name"],
        "called_at": called_at_str,
        "duration_ms": row["duration_ms"],
        "success": bool(row["success"]),
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "user_id": row["user_id"],
        "request_id": row["request_id"],
        "response_size": row["response_size"],
        "input_size": len(row["input_body"]) if row["input_body"] else None,
        "input_body": row["input_body"],
    }
)
```

- [ ] **Step 5: Run tests — all three should pass**

```bash
pytest remote-gateway/tests/test_telemetry_permissions.py::test_record_stores_error_message remote-gateway/tests/test_telemetry_permissions.py::test_record_error_message_none_on_success remote-gateway/tests/test_telemetry_permissions.py::test_record_error_message_missing_param_defaults_none -v
```

Expected: PASS for all three.

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all existing tests pass (migration is additive; old callers don't pass `error_message`, it defaults to None).

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_permissions.py
git commit -m "feat: add error_message column to telemetry for full exception detail"
```

---

## Task 2: Populate `error_message` in mcp_server.py wrappers

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Test: `remote-gateway/tests/test_telemetry_async.py`

- [ ] **Step 1: Write failing test**

In `remote-gateway/tests/test_telemetry_async.py`, add a new test after the existing async failure tests. First, look at how the file stubs things — the key pattern is calling the wrapped function and inspecting `recorded_calls`. Add:

```python
def test_error_message_captured_on_failure():
    """Telemetry wrapper must pass str(exc) as error_message when a tool raises."""
    mod, recorded_calls = _import_mcp_server()

    # Simulate an async tool that raises with a message
    async def broken_tool(x: int) -> str:
        raise ValueError("bad input: x must be positive")

    wrapped = mod.mcp.tool()(broken_tool)

    import asyncio
    try:
        asyncio.run(wrapped(x=-1))
    except ValueError:
        pass

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["error_type"] == "ValueError"
    assert call["error_message"] == "bad input: x must be positive"
```

Note: this test relies on `recorded_calls` being populated by the mock telemetry. Check how the existing async tests wire the mock — `_import_mcp_server()` returns `(module, recorded_calls)` where `recorded_calls` is a list that gets appended to by a mock `_telemetry.record`. The mock captures kwargs. Inspect the existing tests to confirm the mock's `record` stores kwargs in `recorded_calls` as dicts.

- [ ] **Step 2: Run failing test**

```bash
pytest remote-gateway/tests/test_telemetry_async.py::test_error_message_captured_on_failure -v
```

Expected: FAIL — `error_message` key not present in recorded call dict.

- [ ] **Step 3: Update both wrappers in mcp_server.py**

There are two wrappers: `_tracked_mcp_tool` (for `@mcp.tool()` decorated functions) and `_tracked_add_tool` (for proxy tools via `add_tool()`). Each has an async and sync path. Update all four `except Exception as exc` blocks.

**In `_tracked_mcp_tool` — async path** (around line 341):
```python
except Exception as exc:
    _telemetry.record(
        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
        type(exc).__name__, user_id=sid, request_id=rid,
        input_body=input_body,
        error_message=str(exc),
    )
    raise
```

**In `_tracked_mcp_tool` — sync path** (around line 372):
```python
except Exception as exc:
    _telemetry.record(
        fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
        user_id=sid, request_id=rid,
        input_body=input_body,
        error_message=str(exc),
    )
    raise
```

**In `_tracked_add_tool` — async path** (around line 422):
```python
except Exception as exc:
    _telemetry.record(
        tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
        user_id=sid, request_id=rid,
        input_body=input_body,
        error_message=str(exc),
    )
    raise
```

**In `_tracked_add_tool` — sync path** (around line 453):
```python
except Exception as exc:
    _telemetry.record(
        tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
        user_id=sid, request_id=rid,
        input_body=input_body,
        error_message=str(exc),
    )
    raise
```

Also update the two `PermissionError` recording calls (one in each wrapper's async path) to pass `error_message`:
```python
_telemetry.record(
    fn.__name__, int((_time.monotonic() - t0) * 1000), False,
    "PermissionError", user_id=sid, request_id=rid,
    input_body=input_body,
    error_message=f"Tool '{fn.__name__}' is disabled for your account.",
)
```
(And the equivalent in `_tracked_add_tool` using `tool_name` instead of `fn.__name__`.)

- [ ] **Step 4: Run failing test — should pass now**

```bash
pytest remote-gateway/tests/test_telemetry_async.py::test_error_message_captured_on_failure -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_telemetry_async.py
git commit -m "feat: capture error_message string in telemetry wrappers on exception"
```

---

## Task 3: Expose `error_message` in the admin API + add API test

**Files:**
- Modify: `remote-gateway/tests/test_admin_api.py`
- (No change needed in `admin_api.py` — `api_logs` passes through whatever `raw_logs()` returns)

- [ ] **Step 1: Write failing test**

Add to `remote-gateway/tests/test_admin_api.py` (after `test_logs_filters_errors_only`):

```python
def test_logs_includes_error_message(client):
    c, store = client
    store.record(
        "attio__create_note", 50, False,
        error_type="Exception",
        error_message="Missing required parameter: resource_type",
    )
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["error_message"] == "Missing required parameter: resource_type"


def test_logs_error_message_none_on_success(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["error_message"] is None
```

- [ ] **Step 2: Run failing tests**

```bash
pytest remote-gateway/tests/test_admin_api.py::test_logs_includes_error_message remote-gateway/tests/test_admin_api.py::test_logs_error_message_none_on_success -v
```

Expected: FAIL (Task 1 must be done first — `error_message` not in response dict yet without Task 1).
After Task 1 is done, these should PASS without any changes to `admin_api.py`.

- [ ] **Step 3: Verify tests pass**

```bash
pytest remote-gateway/tests/test_admin_api.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/tests/test_admin_api.py
git commit -m "test: verify error_message exposed in /api/logs endpoint"
```

---

## Task 4: Update admin dashboard detail panel to show error detail

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

No automated test for HTML/JS — verify manually by loading the admin and clicking log rows.

- [ ] **Step 1: Update the `logs-body-panel` HTML structure**

Find this block in the HTML (around line 616):

```html
<div id="logs-body-panel" style="display:none;margin-top:1rem;padding:0.8rem 1rem;background:var(--cream-dark);border:1px solid var(--border);">
  <div style="font-family:'Arial',sans-serif;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--text-muted);margin-bottom:0.4rem;">Input Body</div>
  <pre id="logs-body-content" style="font-family:'Courier New',monospace;font-size:0.78rem;white-space:pre-wrap;word-break:break-word;color:var(--text);max-height:300px;overflow-y:auto;margin:0;"></pre>
</div>
```

Replace with:

```html
<div id="logs-body-panel" style="display:none;margin-top:1rem;padding:0.8rem 1rem;background:var(--cream-dark);border:1px solid var(--border);">
  <div id="logs-error-section" style="display:none;margin-bottom:0.8rem;">
    <div style="font-family:'Arial',sans-serif;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--orange);margin-bottom:0.4rem;">Error</div>
    <pre id="logs-error-content" style="font-family:'Courier New',monospace;font-size:0.78rem;white-space:pre-wrap;word-break:break-word;color:var(--orange);max-height:200px;overflow-y:auto;margin:0;"></pre>
  </div>
  <div id="logs-request-section" style="display:none;">
    <div style="font-family:'Arial',sans-serif;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--text-muted);margin-bottom:0.4rem;">Request</div>
    <pre id="logs-body-content" style="font-family:'Courier New',monospace;font-size:0.78rem;white-space:pre-wrap;word-break:break-word;color:var(--text);max-height:300px;overflow-y:auto;margin:0;"></pre>
  </div>
</div>
```

- [ ] **Step 2: Update `renderLogsTable` to store `error_message` and make error rows clickable**

Find this section in `renderLogsTable` (around line 1314):

```js
logs.forEach(row => {
  if (row.input_body != null) _logsBodyMap[row.id] = row.input_body;
});

tbody.innerHTML = logs.map(row => {
  const statusBadge = row.success
    ? '<span class="badge badge-green">OK</span>'
    : row.error_type === 'PermissionError'
      ? '<span class="badge badge-red" title="Tool blocked by permissions">BLOCKED</span>'
      : '<span class="badge badge-orange" title="' + escHtml(row.error_type || '') + '">' + escHtml(row.error_type || 'ERR') + '</span>';
  const hasBody = row.input_body != null;
  const rowStyle = hasBody ? 'cursor:pointer;' : '';
  const onclick = hasBody ? ' onclick="showLogBody(' + escJs(String(row.id)) + ')"' : '';
  return '<tr style="' + rowStyle + '"' + onclick + '>'
```

Replace with:

```js
// Declare these maps at the top of renderLogsTable (alongside _logsBodyMap reset):
_logsBodyMap = {};
_logsErrorMap = {};
_selectedLogId = null;

logs.forEach(row => {
  if (row.input_body != null) _logsBodyMap[row.id] = row.input_body;
  if (row.error_message != null) _logsErrorMap[row.id] = row.error_message;
});

tbody.innerHTML = logs.map(row => {
  const statusBadge = row.success
    ? '<span class="badge badge-green">OK</span>'
    : row.error_type === 'PermissionError'
      ? '<span class="badge badge-red" title="Tool blocked by permissions">BLOCKED</span>'
      : '<span class="badge badge-orange" title="' + escHtml(row.error_type || '') + '">' + escHtml(row.error_type || 'ERR') + '</span>';
  const hasDetail = row.input_body != null || row.error_message != null;
  const rowStyle = hasDetail ? 'cursor:pointer;' : '';
  const onclick = hasDetail ? ' onclick="showLogBody(' + escJs(String(row.id)) + ')"' : '';
  return '<tr style="' + rowStyle + '"' + onclick + '>'
```

- [ ] **Step 3: Declare `_logsErrorMap` alongside `_logsBodyMap`**

Find the variable declaration for `_logsBodyMap` in the script section (it will be near the top of the Logs tab JS, something like `let _logsBodyMap = {};`). Add `_logsErrorMap` next to it:

```js
let _logsBodyMap = {};
let _logsErrorMap = {};
```

- [ ] **Step 4: Update `showLogBody` to render both sections**

Find the `showLogBody` function:

```js
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

Replace with:

```js
function showLogBody(id) {
  const panel = document.getElementById('logs-body-panel');
  if (_selectedLogId === id) {
    panel.style.display = 'none';
    _selectedLogId = null;
    return;
  }
  _selectedLogId = id;

  const errorSection = document.getElementById('logs-error-section');
  const errorContent = document.getElementById('logs-error-content');
  const requestSection = document.getElementById('logs-request-section');
  const requestContent = document.getElementById('logs-body-content');

  const errorMsg = _logsErrorMap[id];
  if (errorMsg) {
    errorContent.textContent = errorMsg;
    errorSection.style.display = 'block';
  } else {
    errorSection.style.display = 'none';
  }

  const body = _logsBodyMap[id];
  if (body) {
    try {
      requestContent.textContent = JSON.stringify(JSON.parse(body), null, 2);
    } catch (_) {
      requestContent.textContent = body;
    }
    requestSection.style.display = 'block';
  } else {
    requestSection.style.display = 'none';
  }

  panel.style.display = 'block';
}
```

- [ ] **Step 5: Also update `renderLogsTable`'s panel hide at the top to reset both sections**

In `renderLogsTable`, the first line hides the panel:
```js
document.getElementById('logs-body-panel').style.display = 'none';
```
Add two more lines after it to reset sections:
```js
document.getElementById('logs-body-panel').style.display = 'none';
document.getElementById('logs-error-section').style.display = 'none';
document.getElementById('logs-request-section').style.display = 'none';
```

- [ ] **Step 6: Manual verification**

Start the gateway (`MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py`) and open the admin dashboard Logs tab. Trigger an error (e.g., call `attio__create_note` without `resource_type`). Confirm:
- The error row has `cursor:pointer` style
- Clicking it opens the panel showing both an **Error** section (in orange with the message) and a **Request** section (with the input params JSON)
- Clicking the same row again collapses the panel
- A success row with no input_body is not clickable
- A success row with input_body shows only the **Request** section (no Error section)

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: show error message and request body in logs detail panel"
```

---

## Task 5: Suppress FastMCP duplicate tool/prompt warnings

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Update `FastMCP()` constructor call**

In `remote-gateway/core/mcp_server.py`, find the `FastMCP(...)` instantiation (around line 100):

```python
mcp = FastMCP(
    os.environ.get("MCP_SERVER_NAME", "inform-gateway"),
    instructions=_instructions,
    lifespan=lifespan,
    host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
)
```

Replace with:

```python
mcp = FastMCP(
    os.environ.get("MCP_SERVER_NAME", "inform-gateway"),
    instructions=_instructions,
    lifespan=lifespan,
    host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
    warn_on_duplicate_tools=False,
    warn_on_duplicate_prompts=False,
    warn_on_duplicate_resources=False,
)
```

- [ ] **Step 2: Verify server starts without duplicate warnings**

```bash
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py 2>&1 | grep -i "already\|duplicate\|warn" | head -10
```

Expected: no "Tool already exists" or "Prompt already exists" lines in output. (The `[admin] WARNING: ADMIN_TOKEN` line will still appear in local dev without the env var set — that's expected.)

- [ ] **Step 3: Run test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "fix: suppress FastMCP duplicate tool/prompt/resource warnings on startup"
```

---

## Task 6: Suppress stdio subprocess stderr noise and Node.js DeprecationWarning

**Files:**
- Modify: `remote-gateway/core/mcp_proxy.py`

- [ ] **Step 1: Add `NODE_NO_WARNINGS` to merged env and suppress subprocess stderr**

In `_run_stdio_proxy`, find the section that builds `merged_env` and opens `stdio_client` (around line 404):

```python
merged_env = {**os.environ, **env_overrides}

server_params = StdioServerParameters(
    command=_resolve_command(config["command"], merged_env),
    args=config.get("args", []),
    env=merged_env,
)

try:
    async with (
        stdio_client(server_params) as (read, write),
        ClientSession(read, write) as session,
    ):
```

Replace with:

```python
# Silence Node.js deprecation warnings (e.g. punycode) from stdio subprocesses.
merged_env = {**os.environ, **env_overrides, "NODE_NO_WARNINGS": "1"}

server_params = StdioServerParameters(
    command=_resolve_command(config["command"], merged_env),
    args=config.get("args", []),
    env=merged_env,
)

# Suppress verbose subprocess stderr (JSON debug logs from attio-mcp, github-mcp, etc.).
# Errors are captured by our telemetry wrappers; raw subprocess stderr is not useful.
import contextlib as _contextlib
_errlog = open(os.devnull, "w")
try:
    async with _contextlib.AsyncExitStack() as _stack:
        read, write = await _stack.enter_async_context(
            stdio_client(server_params, errlog=_errlog)
        )
        session = await _stack.enter_async_context(ClientSession(read, write))
```

Then find the matching `except Exception as exc:` and add a `finally` to close errlog:

```python
    except Exception as exc:  # noqa: BLE001
        # Unwrap ExceptionGroup (raised by asyncio.TaskGroup / stdio_client) to
        # surface the real sub-exception rather than the generic outer message.
        if isinstance(exc, BaseExceptionGroup):
            causes = "; ".join(repr(e) for e in exc.exceptions)
            print(f"  [proxy] '{name}' failed to connect: {causes}")
        else:
            print(f"  [proxy] '{name}' failed to connect: {exc}")
        ready.set()  # Unblock startup so the gateway still comes up
    finally:
        _errlog.close()
```

Note: the existing `async with (stdio_client(...) as (read, write), ClientSession(...) as session):` syntax is a Python 3.10+ parenthesized context manager. The replacement uses `AsyncExitStack` to accommodate the additional `errlog` argument while keeping the same cleanup semantics. Make sure the body of the `async with` block (the `session.initialize()`, tool enumeration, `await asyncio.Event().wait()`, etc.) is unchanged inside the new context manager scope.

- [ ] **Step 2: Verify quiet startup**

```bash
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py 2>&1 | head -20
```

Expected output should now be clean — only these lines (approximately):

```
[admin] WARNING: ADMIN_TOKEN env var not set — using insecure default token. Set ADMIN_TOKEN in production.
INFO:     Started server process [...]
INFO:     Waiting for application startup.
  [proxy] 'exa' connected — 2 tool(s) registered
  [proxy] 'apollo' connected — 21 tool(s) registered
  [proxy] 'attio' connected — 42 tool(s) registered (N filtered)
  [proxy] 'github' connected — 6 tool(s) registered
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

The attio JSON debug blobs, GitHub "running on stdio" line, and `[DEP0040] DeprecationWarning: The punycode module` should be gone.

- [ ] **Step 3: Run test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all pass. (The proxy tests mock `stdio_client` so they are not affected by the errlog change.)

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/core/mcp_proxy.py
git commit -m "fix: suppress stdio subprocess stderr and Node.js DeprecationWarning on startup"
```

---

## Self-Review

**Spec coverage check:**
- Error detail panel → Tasks 1, 2, 3, 4 cover DB migration, wrapper capture, API passthrough, and UI display. ✓
- Log noise: FastMCP duplicate warnings → Task 5. ✓
- Log noise: subprocess stderr + Node.js DeprecationWarning → Task 6. ✓

**Placeholder scan:** No TBDs, all code is complete. ✓

**Type/name consistency:**
- `error_message` is the field name used consistently in schema, `record()` param, `raw_logs()` dict key, API response, and JS maps (`_logsErrorMap`). ✓
- `_logsErrorMap` declared in Task 4 Step 3 and used in Steps 2 and 4. ✓
- `logs-error-section`, `logs-error-content`, `logs-request-section` IDs declared in Step 1 and referenced in Steps 4 and 5. ✓
- `AsyncExitStack` used in Task 6 Step 1 — `contextlib` is already in stdlib, no new dependency. ✓
