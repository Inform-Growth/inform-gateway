# Gateway Reliability Fixes — Design

**Date:** 2026-04-07  
**Scope:** Five targeted fixes to `remote-gateway/` addressing confirmed bugs surfaced by the gateway health check.

---

## Background

The gateway health check (2026-04-07) revealed five issues:

1. Apollo calls crash the entire FastMCP TaskGroup when one fails
2. Attio npm package (`attio-mcp`) sends malformed payloads for `search_records` and `create_record`
3. Proxy error responses are swallowed — callers get `{}` or `{"result": "..."}` with no error flag
4. `delete_note` has a SHA race condition causing ~40% errors during concurrent health checks
5. Telemetry wrapper is sync-only — async promoted tools would record 0ms/always-success

All five are code-level bugs, not credential issues.

---

## Fix 1 — Apollo TaskGroup Crash

**File:** `remote-gateway/core/mcp_proxy.py`

**Root cause:** `proxy_fn` closures in both `_register_proxy_tool` (stdio/SSE) and `_register_streamable_http_proxy_tool` (HTTP) let exceptions from `session.call_tool()` propagate. FastMCP runs concurrent tool calls inside `asyncio.TaskGroup`. Per Python semantics, one failing task cancels all sibling tasks — so a single Apollo rate-limit or connection error kills every concurrent call.

**Fix:** Wrap `session.call_tool(...)` in `try/except Exception` in both proxy_fn closures. On exception return:
```python
{"error": str(exc), "tool": upstream_name, "is_proxy_error": True}
```
The TaskGroup never sees the exception. Callers receive an actionable error dict instead of a cancelled call.

---

## Fix 2 — Attio Broken Tool Overrides

**Files:** `remote-gateway/mcp_connections.json`, `remote-gateway/tools/attio.py`, `remote-gateway/core/mcp_server.py`

**Root cause:** The `attio-mcp` npm package constructs malformed Attio REST payloads for at least `search_records` and `create_record`. Confirmed by the "(Field: are)" error and smoke call failures. The package is actively maintained (v1.4.1) and works for most tools — abandoning it would require owning the full Attio surface.

**Fix — three coordinated changes:**

**1. Suppress broken tools from npm proxy** (`mcp_connections.json`):
```json
"attio": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "attio-mcp"],
  "env": { "ATTIO_API_KEY": "${ATTIO_API_KEY}" },
  "tools": {
    "deny": ["search_records", "create_record"]
  }
}
```

**2. Python REST replacements** (`tools/attio.py`):

- `attio__search_records(object_type, query, limit=20)` — `POST /v2/objects/{object_type}/records/query` with a name-contains filter on `query`. Returns records array. Wraps response with `validated("attio", result)`.

- `attio__create_record(object_type, values)` — `POST /v2/objects/{object_type}/records` with `{"data": {"values": values}}`. Returns `record_id` and created record. Docstring documents schema.md quirks: people names require `first_name` + `last_name` + `full_name`; company refs require `target_object`.

Both use `httpx.Client` and `os.environ["ATTIO_API_KEY"]`.

**3. Register in server** (`mcp_server.py`):
```python
from tools import attio as _attio_tools
_attio_tools.register(mcp)
```

---

## Fix 3 — Error Surfacing in Proxy

**File:** `remote-gateway/core/mcp_proxy.py`

**Root cause:** Both proxy_fn closures inspect `result.content[0].text` but never check `result.isError`. MCP tool errors set `isError=True` with the error message in content — the proxy returns this as opaque text or `{}`, making debugging impossible (GITHUB-01, ATTIO-03 showed "no detail message").

**Fix:** Before the JSON parse block in both proxy_fn closures, add:
```python
if getattr(result, "isError", False):
    return {"error": content.text, "is_mcp_error": True}
```

---

## Fix 4 — Notes delete_note Race Condition

**File:** `remote-gateway/tools/notes.py`

**Root cause:** `delete_note` does GET (fetch SHA) → DELETE (with SHA). A concurrent `write_note` between those two calls updates the file's SHA. The DELETE then gets a 409 or 422 conflict from GitHub. During health check runs (which write then immediately delete test files), this caused a 40% error rate.

**Fix:** After the DELETE call, check for 409/422 status. If matched, re-fetch the SHA and retry the DELETE once:
```
GET → sha₁ → DELETE(sha₁) → 409/422 → GET → sha₂ → DELETE(sha₂) → raise_for_status()
```
`write_note` is not changed — its GET+PUT is idempotent and has lower conflict rate.

---

## Fix 5 — Telemetry Async Support

**File:** `remote-gateway/core/mcp_server.py`

**Root cause:** `_tracked_mcp_tool` produces a synchronous `tracked` wrapper. When `fn` is async (e.g., a future promoted async tool), `fn(*args, **kwargs)` returns a coroutine object — telemetry records 0ms/success before the coroutine executes.

**Fix:** Branch on `asyncio.iscoroutinefunction(fn)`:
```python
if asyncio.iscoroutinefunction(fn):
    @functools.wraps(fn)
    async def tracked_async(*fn_args, **fn_kwargs):
        t0 = _time.monotonic()
        try:
            result = await fn(*fn_args, **fn_kwargs)
            _telemetry.record(fn.__name__, int((_time.monotonic() - t0) * 1000), True)
            return result
        except Exception as exc:
            _telemetry.record(fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__)
            raise
    return fastmcp_decorator(tracked_async)
```
Sync path unchanged. No behavior change for current tools.

---

## Files Changed

| File | Change |
|---|---|
| `remote-gateway/core/mcp_proxy.py` | Fixes 1, 3: exception handling + isError check in both proxy_fn closures |
| `remote-gateway/core/mcp_server.py` | Fix 5: async branch in telemetry wrapper; Fix 2: register attio tools |
| `remote-gateway/mcp_connections.json` | Fix 2: deny list for attio |
| `remote-gateway/tools/attio.py` | Fix 2: new file with search_records and create_record |
| `remote-gateway/tools/notes.py` | Fix 4: delete_note retry on conflict |

---

## Testing

- **Fix 1:** Call two Apollo tools concurrently; both should return results (or error dicts), neither should see TaskGroup cancellation.
- **Fix 2:** `attio__search_records("companies", "Acme")` and `attio__create_record("companies", {"name": [{"value": "Test Co"}]})` should return valid responses, not "(Field: are)" errors.
- **Fix 3:** Trigger a known-bad tool call (e.g., a GitHub MCP call with bad params); response should contain `{"error": "...", "is_mcp_error": true}` rather than `{}`.
- **Fix 4:** Write then immediately delete a note in a tight loop; error rate should drop to near zero.
- **Fix 5:** Register an async test tool via `@mcp.tool()`; verify telemetry records realistic duration and correct success/error status.
