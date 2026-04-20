# Response Preview in Log Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the first 400 chars of every tool response in telemetry and display it as a "Response Preview" section in the log details drawer so operators can spot-check whether a successful response looks sane.

**Architecture:** Three-layer change — (1) `telemetry.py` gains a `response_preview` column and passes it through `record()` / `raw_logs()`; (2) `mcp_server.py` captures `str(result)[:400]` at every success recording site; (3) `admin_dashboard.html` shows the preview in the drawer between Error and Request, with a `(preview · full response: N chars)` hint for truncated responses.

**Tech Stack:** Python 3.11+, SQLite (via telemetry.py), vanilla JS/HTML/CSS (no build step)

**Spec:** `docs/superpowers/specs/2026-04-20-response-preview-in-log-drawer-design.md`

---

## File Map

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Add `response_preview TEXT` column, migration, `record()` param, `raw_logs()` return field |
| `remote-gateway/core/mcp_server.py` | Add `_get_response_preview()`, pass to all 4 success `record()` call sites |
| `remote-gateway/core/admin_dashboard.html` | CSS, drawer HTML section, JS data maps, `openLogDrawer` update, `renderLogsTable` update |
| `remote-gateway/tests/test_admin_api.py` | Tests: `response_preview` present in `/api/logs` response |
| `remote-gateway/tests/test_telemetry_async.py` | Update mock lambda + test that preview is captured and truncated |

---

## Task 1: Add `response_preview` to telemetry.py

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing tests**

Add these two tests at the end of the `# Logs` section in `remote-gateway/tests/test_admin_api.py` (after `test_logs_filters_by_user`):

```python
def test_logs_includes_response_preview(client):
    c, store = client
    store.record("health_check", 10, True, response_preview='{"status": "ok"}')
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["response_preview"] == '{"status": "ok"}'


def test_logs_response_preview_none_when_not_provided(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/logs?token={TOKEN}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["response_preview"] is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_admin_api.py::test_logs_includes_response_preview remote-gateway/tests/test_admin_api.py::test_logs_response_preview_none_when_not_provided -v
```

Expected: `FAILED` — `TypeError: record() got an unexpected keyword argument 'response_preview'`

- [ ] **Step 3: Add column to `_SCHEMA`**

In `remote-gateway/core/telemetry.py`, the `_SCHEMA` string ends with `input_body TEXT`. Add `response_preview` after it:

```python
    response_size INTEGER,
    input_body    TEXT,
    response_preview TEXT
```

- [ ] **Step 4: Add migration entry**

In `_MIGRATIONS` (line ~84), append:

```python
_MIGRATIONS = [
    ("tool_calls", "user_id",          "TEXT"),
    ("tool_calls", "request_id",       "TEXT"),
    ("tool_calls", "response_size",    "INTEGER"),
    ("tool_calls", "input_body",       "TEXT"),
    ("tool_calls", "error_message",    "TEXT"),
    ("tool_calls", "response_preview", "TEXT"),
]
```

- [ ] **Step 5: Add `response_preview` param to `record()`**

Replace the `record()` signature and INSERT statement. The current signature ends with `error_message: str | None = None`. Add `response_preview` after it:

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
        error_message: Full exception message string on failure (e.g. str(exc)),
            complementing error_type which holds only the class name. None on success.
        response_preview: First 400 chars of str(result) on success. None on
            failure or when result is None.
    """
    if not self._enabled:
        return
    try:
        conn = self._connect()
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
        conn.commit()
    except Exception:
        pass  # telemetry must never break the gateway
```

- [ ] **Step 6: Add `response_preview` to `raw_logs()` SELECT and returned dict**

In `raw_logs()`, update the SELECT query (line ~800):

```python
rows = conn.execute(
    f"""
    SELECT id, tool_name, called_at, duration_ms, success,
           error_type, error_message, user_id, request_id, response_size, input_body,
           response_preview
    FROM tool_calls
    {where}
    ORDER BY called_at DESC
    LIMIT ? OFFSET ?
    """,
    params,
).fetchall()
```

And in the result dict built in the loop (after `"input_body": row["input_body"]`), add:

```python
"response_preview": row["response_preview"],
```

The full updated dict:
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
        "response_preview": row["response_preview"],
    }
)
```

- [ ] **Step 7: Run tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_admin_api.py::test_logs_includes_response_preview remote-gateway/tests/test_admin_api.py::test_logs_response_preview_none_when_not_provided -v
```

Expected: `PASSED`

- [ ] **Step 8: Run full test suite to confirm no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_admin_api.py
git commit -m "feat: add response_preview column to telemetry and raw_logs output"
```

---

## Task 2: Capture response preview in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Test: `remote-gateway/tests/test_telemetry_async.py`

- [ ] **Step 1: Write failing test**

In `remote-gateway/tests/test_telemetry_async.py`, the `_import_mcp_server()` function builds a mock lambda for `telemetry.record`. It currently does NOT capture `response_preview`. Update the lambda **and** add a new test.

First, update the `mock_tel.record` lambda inside `_import_mcp_server()` (line ~65) to capture `response_preview`:

```python
mock_tel.record = lambda name, duration_ms, success, exc_type=None, user_id=None, request_id=None, response_size=None, input_body=None, error_message=None, response_preview=None: recorded.append(  # noqa: E501
    {"name": name, "duration_ms": duration_ms, "success": success, "exc_type": exc_type,
     "user_id": user_id, "request_id": request_id, "error_message": error_message,
     "response_preview": response_preview}
)
```

Then add this test at the end of the file:

```python
def test_async_tool_captures_response_preview():
    """response_preview passed to record() must be str(result)[:400]."""
    long_response = "x" * 800

    async def big_tool() -> str:
        return long_response

    tracked = _server._tracked_mcp_tool()(big_tool)
    result = asyncio.run(tracked())

    assert result == long_response
    assert len(_recorded) == 1
    assert _recorded[0]["response_preview"] == "x" * 400
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest remote-gateway/tests/test_telemetry_async.py::test_async_tool_captures_response_preview -v
```

Expected: `FAILED` — `AssertionError: assert None == 'xxxx...'`

- [ ] **Step 3: Add `_get_response_preview` helper to mcp_server.py**

In `remote-gateway/core/mcp_server.py`, add this function directly after `_calculate_response_size` (line ~315):

```python
def _get_response_preview(result: Any) -> str | None:
    """Return the first 400 chars of str(result), or None if result is None."""
    if result is None:
        return None
    try:
        return str(result)[:400]
    except Exception:
        return None
```

- [ ] **Step 4: Update success `record()` calls in `_tracked_mcp_tool` async branch**

There are two success `_telemetry.record()` calls inside `_tracked_mcp_tool` — one in the async branch, one in the sync branch. Add `response_preview=_get_response_preview(result)` to each.

**Async branch** (inside `tracked_async`, success path, ~line 343):
```python
_telemetry.record(
    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
    user_id=sid, request_id=rid,
    response_size=_calculate_response_size(result),
    input_body=input_body,
    response_preview=_get_response_preview(result),
)
```

**Sync branch** (inside `tracked`, success path, ~line 377):
```python
_telemetry.record(
    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
    user_id=sid, request_id=rid,
    response_size=_calculate_response_size(result),
    input_body=input_body,
    response_preview=_get_response_preview(result),
)
```

- [ ] **Step 5: Update success `record()` calls in `_tracked_add_tool`**

Same change for both branches inside `_tracked_add_tool` (proxy tools).

**Async branch** (~line 429):
```python
_telemetry.record(
    tool_name, int((_time.monotonic() - t0) * 1000), True,
    user_id=sid, request_id=rid,
    response_size=_calculate_response_size(result),
    input_body=input_body,
    response_preview=_get_response_preview(result),
)
```

**Sync branch** (~line 463):
```python
_telemetry.record(
    tool_name, int((_time.monotonic() - t0) * 1000), True,
    user_id=sid, request_id=rid,
    response_size=_calculate_response_size(result),
    input_body=input_body,
    response_preview=_get_response_preview(result),
)
```

- [ ] **Step 6: Run test to confirm it passes**

```bash
pytest remote-gateway/tests/test_telemetry_async.py::test_async_tool_captures_response_preview -v
```

Expected: `PASSED`

- [ ] **Step 7: Run full test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_telemetry_async.py
git commit -m "feat: capture response_preview (first 400 chars) in telemetry recording"
```

---

## Task 3: Add Response Preview section to log drawer

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

No automated tests — verify manually in the browser (server start instructions below).

- [ ] **Step 1: Add CSS for the response section**

In the `<style>` block, find the existing lines:

```css
.drawer-section-label.error  { color: var(--orange); }
.drawer-section-label.request { color: var(--text-muted); }
```

Replace with:

```css
.drawer-section-label.error    { color: var(--orange); }
.drawer-section-label.response { color: var(--green); }
.drawer-section-label.request  { color: var(--text-muted); }
.drawer-pre.response { color: var(--text); }
.drawer-response-hint {
  font-family: 'Courier New', monospace;
  font-size: 0.68rem;
  color: var(--text-muted);
  margin-top: -0.8rem;
  margin-bottom: 1.2rem;
}
```

- [ ] **Step 2: Add response preview HTML to the drawer body**

Find the existing drawer body HTML:

```html
  <div class="drawer-body">
    <div id="drawer-error-section" style="display:none;">
      <div class="drawer-section-label error">Error</div>
      <pre class="drawer-pre error" id="drawer-error-content"></pre>
    </div>
    <div id="drawer-request-section" style="display:none;">
      <div class="drawer-section-label request">Request</div>
      <pre class="drawer-pre request" id="drawer-request-content"></pre>
    </div>
  </div>
```

Replace with:

```html
  <div class="drawer-body">
    <div id="drawer-error-section" style="display:none;">
      <div class="drawer-section-label error">Error</div>
      <pre class="drawer-pre error" id="drawer-error-content"></pre>
    </div>
    <div id="drawer-response-section" style="display:none;">
      <div class="drawer-section-label response">Response Preview</div>
      <pre class="drawer-pre response" id="drawer-response-content"></pre>
      <div class="drawer-response-hint" id="drawer-response-hint"></div>
    </div>
    <div id="drawer-request-section" style="display:none;">
      <div class="drawer-section-label request">Request</div>
      <pre class="drawer-pre request" id="drawer-request-content"></pre>
    </div>
  </div>
```

- [ ] **Step 3: Add `_logsResponseMap` and `_logsResponseSizeMap` declarations**

Find the existing variable declarations block:

```javascript
  let _logsBodyMap = {};
  let _logsErrorMap = {};
  let _logsToolMap = {};
  let _logsTimeMap = {};
  let _selectedLogId = null;
```

Replace with:

```javascript
  let _logsBodyMap = {};
  let _logsErrorMap = {};
  let _logsToolMap = {};
  let _logsTimeMap = {};
  let _logsResponseMap = {};
  let _logsResponseSizeMap = {};
  let _selectedLogId = null;
```

- [ ] **Step 4: Populate the new maps and update `hasDetail` in `renderLogsTable`**

Find the `renderLogsTable` reset and population block:

```javascript
  function renderLogsTable(logs) {
    _logsBodyMap = {};
    _logsErrorMap = {};
    _logsToolMap = {};
    _logsTimeMap = {};
    _selectedLogId = null;
    closeLogDrawer();

    const tbody = document.getElementById('logs-tbody');

    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);font-style:italic;text-align:center;">No log entries match.</td></tr>';
      return;
    }

    logs.forEach(row => {
      if (row.input_body   != null) _logsBodyMap[row.id]  = row.input_body;
      if (row.error_message != null) _logsErrorMap[row.id] = row.error_message;
      _logsToolMap[row.id] = row.tool_name || '';
      _logsTimeMap[row.id] = row.called_at || '';
    });
```

Replace with:

```javascript
  function renderLogsTable(logs) {
    _logsBodyMap = {};
    _logsErrorMap = {};
    _logsToolMap = {};
    _logsTimeMap = {};
    _logsResponseMap = {};
    _logsResponseSizeMap = {};
    _selectedLogId = null;
    closeLogDrawer();

    const tbody = document.getElementById('logs-tbody');

    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);font-style:italic;text-align:center;">No log entries match.</td></tr>';
      return;
    }

    logs.forEach(row => {
      if (row.input_body      != null) _logsBodyMap[row.id]        = row.input_body;
      if (row.error_message   != null) _logsErrorMap[row.id]       = row.error_message;
      if (row.response_preview != null) _logsResponseMap[row.id]   = row.response_preview;
      if (row.response_size   != null) _logsResponseSizeMap[row.id] = row.response_size;
      _logsToolMap[row.id] = row.tool_name || '';
      _logsTimeMap[row.id] = row.called_at || '';
    });
```

Also update the `hasDetail` check in the `tbody.innerHTML = logs.map(row => {` block that follows. Find:

```javascript
      const hasDetail = row.input_body != null || row.error_message != null;
```

Replace with:

```javascript
      const hasDetail = row.input_body != null || row.error_message != null || row.response_preview != null;
```

- [ ] **Step 5: Populate response section in `openLogDrawer`**

Find the block in `openLogDrawer` that handles the error section and ends with the request section:

```javascript
    const errorMsg = _logsErrorMap[id];
    const errorSection = document.getElementById('drawer-error-section');
    document.getElementById('drawer-error-content').textContent = errorMsg || '';
    errorSection.style.display = errorMsg ? 'block' : 'none';

    const body = _logsBodyMap[id];
    const requestSection = document.getElementById('drawer-request-section');
```

Replace with:

```javascript
    const errorMsg = _logsErrorMap[id];
    const errorSection = document.getElementById('drawer-error-section');
    document.getElementById('drawer-error-content').textContent = errorMsg || '';
    errorSection.style.display = errorMsg ? 'block' : 'none';

    const preview = _logsResponseMap[id];
    const responseSection = document.getElementById('drawer-response-section');
    if (preview != null) {
      document.getElementById('drawer-response-content').textContent = preview;
      const fullSize = _logsResponseSizeMap[id];
      const hint = fullSize && fullSize > 400
        ? 'preview · full response: ' + fullSize.toLocaleString() + ' chars'
        : 'full response';
      document.getElementById('drawer-response-hint').textContent = hint;
      responseSection.style.display = 'block';
    } else {
      responseSection.style.display = 'none';
    }

    const body = _logsBodyMap[id];
    const requestSection = document.getElementById('drawer-request-section');
```

- [ ] **Step 6: Verify in browser**

Start the server:

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pip install -e .
python remote-gateway/core/mcp_server.py
# Open: http://localhost:8000/admin/?token=inform-admin-2026
```

Checklist:
- Clicking a log row that has a response preview → drawer shows green "Response Preview" section between Error and Request ✓
- For a response > 400 chars → hint reads `preview · full response: N chars` ✓
- For a response ≤ 400 chars → hint reads `full response` ✓
- Old log rows (no `response_preview`) → Response Preview section is hidden ✓
- Rows with only a response preview (no input_body, no error) → drawer opens on click ✓
- Error section still appears orange and first when present ✓
- Request section still appears last ✓

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: show response preview in log drawer"
```
