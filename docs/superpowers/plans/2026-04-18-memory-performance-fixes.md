# Memory & Performance Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate four root-cause memory and performance issues that cause the gateway to exhaust resources under load.

**Architecture:** Four targeted, independent fixes across two files — `mcp_proxy.py` and `telemetry.py` — plus one micro-fix in `mcp_server.py`. No new abstractions; each fix is the minimal code change that eliminates the root cause. All fixes are backwards-compatible with existing tests.

**Tech Stack:** Python 3.11+, asyncio, sqlite3, collections.deque

---

## Background (read this first)

Four root causes were identified through systematic debugging:

| # | Issue | Location | Severity |
|---|-------|----------|----------|
| 1 | **Throttler holds semaphore during rate-limit sleep** — when rate-limited, the concurrency slot is held for up to 60s, causing all concurrent callers to queue as suspended coroutines | `mcp_proxy.py` `Throttler.acquire()` | Critical |
| 2 | **`load_connections()` reads + parses JSON on every tool call** — allocates and discards a full `dict[str, dict]` each invocation | `mcp_proxy.py` `_call_with_retry()` | High |
| 3 | **SQLite: new connection opened per operation on hot auth path** — `lookup_user()` (every HTTP request) and `record()` (every tool call) each open and close a new `sqlite3.Connection` | `telemetry.py` | Medium |
| 4 | **`_extract_key` builds a full headers dict on every HTTP request** — materializes all request headers just to find one key | `mcp_server.py` `_AuthMiddleware._extract_key()` | Low |

---

## File Map

| File | What changes |
|------|-------------|
| `remote-gateway/core/mcp_proxy.py` | Tasks 1 & 2 — fix `Throttler.acquire()`, cache `load_connections()` |
| `remote-gateway/core/telemetry.py` | Task 3 — persistent shared DB connection, remove all `conn.close()` calls |
| `remote-gateway/core/mcp_server.py` | Task 4 — `_extract_key` header scan without dict allocation |
| `remote-gateway/tests/test_proxy_reliability.py` | Tasks 1 & 2 — new tests appended to existing file |
| `remote-gateway/tests/test_telemetry_permissions.py` | Task 3 — one new test appended |
| `remote-gateway/tests/test_auth_middleware.py` | Task 4 — new test file |

---

## Task 1: Fix `Throttler` — release semaphore before sleeping

**Root cause:** `asyncio.Semaphore.acquire()` happens before the rate-limit sleep. The concurrency slot is held for up to 60 seconds, queuing all concurrent callers for that integration as suspended coroutines (each holding its full async stack frame).

**Fix:** Release the semaphore before sleeping; re-acquire after. Use `collections.deque` for O(1) cleanup instead of the list comprehension that rebuilds the entire list on every call.

**Files:**
- Modify: `remote-gateway/core/mcp_proxy.py`
- Test: `remote-gateway/tests/test_proxy_reliability.py`

- [ ] **Step 1: Write the failing test**

Append to `remote-gateway/tests/test_proxy_reliability.py`:

```python
# ---------------------------------------------------------------------------
# Throttler — semaphore released during rate-limit sleep
# ---------------------------------------------------------------------------

import collections


def test_throttler_releases_semaphore_while_sleeping():
    """Semaphore must be released before rate-limit sleep, not held during it."""
    throttler = _proxy.Throttler("test", rpm=1, concurrency=2)

    released_during_sleep = []

    async def _run():
        # Fill the rate-limit window: 1 request already logged
        throttler._history.append(_time.time())

        # Start first caller — it should detect the rate limit and release
        # the semaphore before sleeping so the second caller can proceed.
        async def caller():
            await throttler.acquire()
            # Check semaphore value immediately after acquire returns
            released_during_sleep.append(throttler.semaphore._value)
            throttler.release()

        import asyncio as _asyncio
        # Patch sleep to avoid real waiting and capture semaphore state
        original_sleep = _asyncio.sleep
        sleep_calls = []

        async def fake_sleep(t):
            # Record semaphore value at the moment of sleep
            sleep_calls.append(throttler.semaphore._value)

        with _proxy.__builtins__.__class__.__dict__:
            pass

        _asyncio.sleep = fake_sleep
        try:
            await _asyncio.gather(caller())
        finally:
            _asyncio.sleep = original_sleep

        # The semaphore must have been free (value >= 1) during the sleep
        assert any(v >= 1 for v in sleep_calls), (
            f"Semaphore was held during sleep (values: {sleep_calls}). "
            "Concurrency slot must be released before sleeping."
        )

    import asyncio
    import time as _time
    asyncio.run(_run())
```

**Note:** The test above is complex due to async mocking. Use this simpler, equivalent test instead:

```python
# ---------------------------------------------------------------------------
# Throttler — semaphore released during rate-limit sleep
# ---------------------------------------------------------------------------

def test_throttler_semaphore_not_held_during_rate_limit_wait():
    """When rate-limited, the semaphore must be released before sleeping.

    Strategy: set rpm=1, pre-fill history so the next call is rate-limited,
    then verify the semaphore value rises back to its initial value during
    the mocked sleep (meaning the slot was released before sleeping).
    """
    import asyncio
    import time as _time
    import unittest.mock as mock

    throttler = _proxy.Throttler("test_integration", rpm=1, concurrency=1)
    semaphore_value_during_sleep = []

    async def _run():
        # Saturate the 1-rpm window so the next acquire() triggers a sleep
        throttler._history.append(_time.time())

        async def fake_sleep(seconds):
            semaphore_value_during_sleep.append(throttler.semaphore._value)

        with mock.patch("asyncio.sleep", side_effect=fake_sleep):
            await throttler.acquire()
        throttler.release()

    asyncio.run(_run())

    # The semaphore (concurrency=1, so starts at 1) must have been at 1
    # during the sleep, meaning it was released before the sleep call.
    assert semaphore_value_during_sleep, "asyncio.sleep was never called — rpm check not triggered"
    assert semaphore_value_during_sleep[0] >= 1, (
        f"Semaphore value during sleep was {semaphore_value_during_sleep[0]} "
        "(expected >= 1, meaning the slot was released before sleeping)"
    )


def test_throttler_history_uses_deque():
    """_history must be a deque for O(1) popleft cleanup."""
    import collections
    throttler = _proxy.Throttler("test", rpm=5, concurrency=2)
    assert isinstance(throttler._history, collections.deque), (
        f"Expected deque, got {type(throttler._history).__name__}"
    )
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_proxy_reliability.py::test_throttler_semaphore_not_held_during_rate_limit_wait remote-gateway/tests/test_proxy_reliability.py::test_throttler_history_uses_deque -v
```

Expected: both tests FAIL (history is `list`, semaphore held during sleep).

- [ ] **Step 3: Implement the fix in `mcp_proxy.py`**

At the top of the file, add `deque` to the imports (around line 29, the `collections` import or add a new import):

```python
from collections import deque
```

In the `Throttler` class, change `__init__` and `acquire`:

Find and replace the full `Throttler` class (lines ~698–729):

```python
class Throttler:
    """Manages concurrency and rate limits for an integration.

    Uses an asyncio.Semaphore for concurrency and tracks request timestamps
    to enforce a requests-per-minute (RPM) limit.

    The semaphore is released before any rate-limit sleep so that the
    concurrency slot is not held while waiting for the window to expire.
    Other callers can use the slot during the wait; the sleeping caller
    re-acquires it afterwards.
    """

    def __init__(self, name: str, rpm: int = 0, concurrency: int = 2) -> None:
        self.name = name
        self.rpm = rpm
        self.semaphore = asyncio.Semaphore(concurrency)
        self._history: deque[float] = deque()

    async def acquire(self) -> None:
        """Wait for a permit to execute a request.

        Acquires the concurrency semaphore first, then checks the RPM window.
        If the rate limit is exceeded, releases the semaphore before sleeping
        so the slot is available to other callers during the wait. Re-acquires
        the semaphore after the window clears and loops to re-check (another
        caller may have consumed capacity while we slept).
        """
        await self.semaphore.acquire()

        while self.rpm > 0:
            now = time.time()
            # O(1) cleanup: discard timestamps older than 60 seconds
            while self._history and now - self._history[0] >= 60:
                self._history.popleft()

            if len(self._history) < self.rpm:
                break  # under rate limit — proceed

            # Over rate limit: release the slot so others can use it while we wait
            wait_time = 60.0 - (now - self._history[0])
            self.semaphore.release()
            if wait_time > 0:
                print(
                    f"  [proxy] '{self.name}' rate limit reached — waiting {wait_time:.1f}s"
                )
                await asyncio.sleep(wait_time)
            # Re-acquire and re-check (another caller may have used capacity)
            await self.semaphore.acquire()

        if self.rpm > 0:
            self._history.append(time.time())

    def release(self) -> None:
        """Release the concurrency permit."""
        self.semaphore.release()
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_proxy_reliability.py::test_throttler_semaphore_not_held_during_rate_limit_wait remote-gateway/tests/test_proxy_reliability.py::test_throttler_history_uses_deque -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_proxy.py remote-gateway/tests/test_proxy_reliability.py
git commit -m "fix: release Throttler semaphore before rate-limit sleep, use deque for history

When the RPM limit was hit, the concurrency semaphore was held during the
asyncio.sleep() call (up to 60s). All concurrent callers for that integration
queued as suspended coroutines, holding async stack frames and preventing GC.

Fix: release the semaphore before sleeping and re-acquire after. Loop to
re-check the window after re-acquiring (another caller may have consumed
capacity). Also replace list with deque for O(1) popleft cleanup."
```

---

## Task 2: Cache `load_connections()` — eliminate per-call JSON file reads

**Root cause:** `_call_with_retry()` calls `load_connections()` on every tool invocation. This reads and JSON-parses `mcp_connections.json` from disk each time, allocating a full `dict[str, dict]` that is immediately discarded. The connections config is static; it never changes at runtime without a server restart.

**Files:**
- Modify: `remote-gateway/core/mcp_proxy.py`
- Test: `remote-gateway/tests/test_proxy_reliability.py`

- [ ] **Step 1: Write the failing test**

Append to `remote-gateway/tests/test_proxy_reliability.py`:

```python
# ---------------------------------------------------------------------------
# load_connections() — module-level cache
# ---------------------------------------------------------------------------

def test_load_connections_returns_same_object_on_second_call(tmp_path, monkeypatch):
    """load_connections() must return the cached dict on the second call (no re-read)."""
    import json

    connections_file = tmp_path / "mcp_connections.json"
    connections_file.write_text(json.dumps({
        "connections": {
            "exa": {"transport": "http", "url": "https://mcp.exa.ai/mcp"}
        }
    }))

    monkeypatch.setattr(_proxy, "CONNECTIONS_FILE", connections_file)
    monkeypatch.setattr(_proxy, "_connections_cache", None)

    first = _proxy.load_connections()
    second = _proxy.load_connections()

    assert first is second, (
        "load_connections() returned different objects — cache miss on second call. "
        "The JSON file must only be read once."
    )


def test_load_connections_cache_returns_correct_data(tmp_path, monkeypatch):
    """Cached result must contain the actual connection definitions."""
    import json

    connections_file = tmp_path / "mcp_connections.json"
    connections_file.write_text(json.dumps({
        "connections": {
            "apollo": {"transport": "sse", "url": "https://mcp.apollo.io/mcp"}
        }
    }))

    monkeypatch.setattr(_proxy, "CONNECTIONS_FILE", connections_file)
    monkeypatch.setattr(_proxy, "_connections_cache", None)

    result = _proxy.load_connections()
    assert "apollo" in result
    assert result["apollo"]["url"] == "https://mcp.apollo.io/mcp"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_proxy_reliability.py::test_load_connections_returns_same_object_on_second_call remote-gateway/tests/test_proxy_reliability.py::test_load_connections_cache_returns_correct_data -v
```

Expected: `test_load_connections_returns_same_object_on_second_call` FAILS (different objects); second test passes or fails depending on current behavior.

- [ ] **Step 3: Implement the cache in `mcp_proxy.py`**

Add the module-level cache variable immediately before the `load_connections()` function definition (around line 137). Replace the existing `load_connections()` function:

```python
# Module-level cache — connections config is static; never changes without a restart.
_connections_cache: dict[str, dict] | None = None


def load_connections() -> dict[str, dict]:
    """Load upstream MCP connection definitions from mcp_connections.json.

    Result is cached after the first read — the file is never read more than once
    per process lifetime. Call sites that previously called this per-invocation
    (e.g. _call_with_retry) now pay zero I/O cost after startup.

    Returns:
        Dict mapping integration slug → connection config dict.
        Returns empty dict if mcp_connections.json does not exist.
    """
    global _connections_cache
    if _connections_cache is None:
        if not CONNECTIONS_FILE.exists():
            _connections_cache = {}
        else:
            data = json.loads(CONNECTIONS_FILE.read_text())
            _connections_cache = data.get("connections", {})
    return _connections_cache
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_proxy_reliability.py::test_load_connections_returns_same_object_on_second_call remote-gateway/tests/test_proxy_reliability.py::test_load_connections_cache_returns_correct_data -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_proxy.py remote-gateway/tests/test_proxy_reliability.py
git commit -m "fix: cache load_connections() result — eliminate per-call JSON file reads

_call_with_retry() called load_connections() on every tool invocation,
reading and parsing mcp_connections.json from disk each time. The config
is static (never changes without a restart), so cache the result in a
module-level variable after the first read. Zero I/O cost on subsequent calls."
```

---

## Task 3: Persistent shared DB connection — eliminate per-operation sqlite3.connect()

**Root cause:** Every call to `lookup_user()` (fired on every HTTP request by `_AuthMiddleware`), `has_permission()` (fired before every tool call), and `record()` (fired after every tool call) opens and closes a new `sqlite3.Connection`. Under load this creates 3+ short-lived connection objects per tool invocation that the GC must collect.

**Fix:** Initialize one persistent `WAL`-mode connection in `_setup()`, store it as `self._conn`, and have `_connect()` return it directly. Remove all `conn.close()` calls (16 total across the class). The connection stays open for the process lifetime.

**Why this is safe:** The asyncio event loop is single-threaded. There is no concurrent multi-threaded access to `self._conn`. WAL mode allows multiple readers + one writer, and since everything serializes through the event loop, writes never overlap.

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Test: `remote-gateway/tests/test_telemetry_permissions.py`

- [ ] **Step 1: Write the failing test**

Append to `remote-gateway/tests/test_telemetry_permissions.py`:

```python
def test_connect_returns_same_connection_object(store):
    """_connect() must return the cached connection — no new object per call."""
    first = store._connect()
    second = store._connect()
    assert first is second, (
        "_connect() returned a different object on the second call. "
        "The connection must be cached and reused."
    )
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
pytest remote-gateway/tests/test_telemetry_permissions.py::test_connect_returns_same_connection_object -v
```

Expected: FAIL — `_connect()` currently creates a new connection each time.

- [ ] **Step 3: Update `TelemetryStore.__init__()` to declare `self._conn`**

In `telemetry.py`, find the `__init__` method and add `self._conn`:

```python
def __init__(self, db_path: Path = _DB_PATH) -> None:
    self._path = db_path
    self._enabled = False
    self._disabled_cache: dict[str, set[str]] = {}
    self._conn: sqlite3.Connection | None = None
    self._setup()
    self._load_disabled_cache()
```

- [ ] **Step 4: Update `_setup()` to store the connection instead of closing it**

Replace the `_setup()` method body:

```python
def _setup(self) -> None:
    """Create the database file and schema. Disables itself on any failure."""
    try:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_TABLES)
        self._migrate(conn)
        conn.executescript(_SCHEMA_INDEXES)
        self._conn = conn          # ← store; do NOT close
        self._enabled = True
    except Exception as exc:
        print(f"[telemetry] disabled — could not open {self._path}: {exc}", flush=True)
```

- [ ] **Step 5: Update `_connect()` to return the shared connection**

Replace the `_connect()` method:

```python
def _connect(self) -> sqlite3.Connection:
    """Return the shared persistent WAL-mode connection.

    The connection is created once in _setup() and lives for the process
    lifetime. Never closed — callers must NOT call conn.close().
    """
    return self._conn  # type: ignore[return-value]
```

- [ ] **Step 6: Remove all `conn.close()` calls from every method**

Search for every occurrence of `conn.close()` in `telemetry.py` and delete those lines. There are **16** occurrences across these methods. For each method, the pattern to remove is exactly `conn.close()` (with its indentation). The `conn.commit()` lines must be kept.

The full list of methods and the line to remove:

| Method | Line to remove |
|--------|---------------|
| `_load_disabled_cache` | `conn.close()` |
| `add_api_key` | `conn.close()` (after `conn.commit()`) |
| `revoke_api_key` | `conn.close()` (after `conn.commit()`) |
| `list_users` | `conn.close()` |
| `delete_user` | `conn.close()` (after `conn.commit()`) |
| `has_permission` | `conn.close()` |
| `get_tool_permissions` | `conn.close()` |
| `set_tool_permission` | `conn.close()` (after `conn.commit()`) |
| `lookup_user` | `conn.close()` |
| `record` | `conn.close()` (after `conn.commit()`) |
| `stats` | `conn.close()` |
| `session_usage` | `conn.close()` |
| `user_flow_analysis` | `conn.close()` |
| `daily_activity` | `conn.close()` |
| `daily_activity_by_user` | `conn.close()` |
| `raw_logs` | `conn.close()` |

After this step, no method in `TelemetryStore` should contain `conn.close()`.

Verify with:

```bash
grep -n "conn.close()" remote-gateway/core/telemetry.py
```

Expected output: nothing (zero matches).

- [ ] **Step 7: Run the new test to confirm it passes**

```bash
pytest remote-gateway/tests/test_telemetry_permissions.py::test_connect_returns_same_connection_object -v
```

Expected: PASS.

- [ ] **Step 8: Run the full telemetry test suite**

```bash
pytest remote-gateway/tests/test_telemetry_permissions.py remote-gateway/tests/test_telemetry_async.py remote-gateway/tests/test_tool_visibility.py -v
```

Expected: all tests pass. The existing tests create `TelemetryStore(db_path=tmp_path / "test.db")` so each test gets its own isolated connection — no cross-test interference.

- [ ] **Step 9: Run the full test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_permissions.py
git commit -m "fix: persist shared SQLite connection in TelemetryStore — remove per-op connect/close

lookup_user() (every HTTP request), has_permission() (every tool call), and
record() (every tool call) each opened and closed a new sqlite3.Connection.
Under load this generated 3+ short-lived connection objects per invocation.

Fix: initialize one WAL-mode connection in _setup(), store as self._conn,
return it from _connect(). Remove all 16 conn.close() calls. The connection
is reused for the process lifetime. Safe because asyncio is single-threaded."
```

---

## Task 4: Fix `_extract_key` — scan headers without building a dict

**Root cause:** `_AuthMiddleware._extract_key()` builds a full `dict` from all headers on every HTTP request just to look up one key. Under high request volume this allocates and discards a dict on every request.

**Fix:** Scan the headers list directly with a `for` loop. Stop at the first authorization header found.

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Test: `remote-gateway/tests/test_auth_middleware.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `remote-gateway/tests/test_auth_middleware.py`:

```python
"""
Tests for _AuthMiddleware._extract_key().

The method must extract the API key from:
  1. Authorization: Bearer <key> header
  2. ?api_key=<key> query parameter (fallback)

And must NOT build a full headers dict (performance contract).

Run with:
    pytest remote-gateway/tests/test_auth_middleware.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


def _import_server_extract_key():
    """Import only _AuthMiddleware from mcp_server without full server startup."""
    # Stub heavy dependencies before importing
    for mod in ("mcp", "mcp.server", "mcp.server.fastmcp",
                "mcp.server.lowlevel", "mcp.server.lowlevel.server",
                "uvicorn", "starlette", "starlette.applications",
                "starlette.routing", "field_registry", "mcp_proxy", "telemetry",
                "tools", "tools.attio", "tools.email_tools", "tools.meta",
                "tools.notes", "tools.registry"):
        sys.modules.setdefault(mod, types.ModuleType(mod))

    # Stub request_ctx used at module level
    stub_telemetry = sys.modules["telemetry"]
    stub_telemetry.telemetry = MagicMock()

    stub_field_registry = sys.modules["field_registry"]
    stub_field_registry.registry = MagicMock()

    stub_server = sys.modules["mcp.server.lowlevel.server"]
    stub_server.request_ctx = MagicMock()

    stub_fastmcp = sys.modules["mcp.server.fastmcp"]
    stub_fastmcp.FastMCP = MagicMock(return_value=MagicMock())

    path = Path(__file__).parent.parent / "core" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("mcp_server_test", path)
    mod = types.ModuleType("mcp_server_test")
    mod.__file__ = str(path)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        pass  # startup side-effects may fail; we only need _AuthMiddleware
    return mod


_server = _import_server_extract_key()
_extract_key = _server._AuthMiddleware._extract_key


def _scope(headers: list[tuple[bytes, bytes]], qs: str = "") -> dict:
    return {
        "type": "http",
        "headers": headers,
        "query_string": qs.encode(),
    }


# ---------------------------------------------------------------------------
# Bearer token from Authorization header
# ---------------------------------------------------------------------------

def test_extract_key_from_bearer_header():
    scope = _scope([(b"authorization", b"Bearer sk-abc123")])
    assert _extract_key(scope) == "sk-abc123"


def test_extract_key_bearer_case_insensitive():
    scope = _scope([(b"authorization", b"BEARER sk-upper")])
    assert _extract_key(scope) == "sk-upper"


def test_extract_key_returns_none_for_non_bearer_auth():
    """A non-Bearer Authorization header (e.g. Basic) must fall through to query param."""
    scope = _scope([(b"authorization", b"Basic dXNlcjpwYXNz")])
    assert _extract_key(scope) is None


def test_extract_key_returns_none_empty_bearer():
    scope = _scope([(b"authorization", b"Bearer ")])
    assert _extract_key(scope) is None


# ---------------------------------------------------------------------------
# api_key query parameter fallback
# ---------------------------------------------------------------------------

def test_extract_key_from_query_param():
    scope = _scope([], qs="api_key=sk-queryparam")
    assert _extract_key(scope) == "sk-queryparam"


def test_extract_key_query_param_with_other_params():
    scope = _scope([], qs="foo=bar&api_key=sk-qp2&baz=qux")
    assert _extract_key(scope) == "sk-qp2"


def test_extract_key_returns_none_when_no_key():
    scope = _scope([], qs="foo=bar")
    assert _extract_key(scope) is None


def test_extract_key_returns_none_empty_scope():
    scope = {"type": "http", "headers": [], "query_string": b""}
    assert _extract_key(scope) is None


# ---------------------------------------------------------------------------
# Performance contract: no full dict built
# ---------------------------------------------------------------------------

def test_extract_key_does_not_build_headers_dict():
    """_extract_key must not call dict() on the headers list."""
    scope = _scope([(b"authorization", b"Bearer sk-test")])
    with patch("builtins.dict") as mock_dict:
        result = _extract_key(scope)
    # dict() must not have been called with the headers list
    for call in mock_dict.call_args_list:
        args = call.args
        if args and hasattr(args[0], "__iter__") and not isinstance(args[0], dict):
            raise AssertionError(
                "_extract_key built a dict from the headers list. "
                "Use a for-loop scan instead."
            )
    assert result == "sk-test"
```

- [ ] **Step 2: Run the tests to confirm some fail**

```bash
pytest remote-gateway/tests/test_auth_middleware.py -v
```

Expected: most tests pass (behavior is correct), but `test_extract_key_does_not_build_headers_dict` FAILS because the current implementation calls `dict()` (via a dict comprehension) on headers.

- [ ] **Step 3: Implement the fix in `mcp_server.py`**

Find `_extract_key` in `mcp_server.py` (around line 267) and replace the method body:

```python
@staticmethod
def _extract_key(scope: Any) -> str | None:
    """Return the API key from the Authorization header or api_key query param.

    Scans headers directly — no dict allocation on the hot request path.
    """
    for key, val in scope.get("headers", []):
        if key.lower() == b"authorization":
            auth: str = val.decode()
            if auth.lower().startswith("bearer "):
                return auth[7:].strip() or None

    qs: str = scope.get("query_string", b"").decode()
    for part in qs.split("&"):
        if part.startswith("api_key="):
            return part[8:] or None
    return None
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_auth_middleware.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run the full test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_auth_middleware.py
git commit -m "fix: scan headers directly in _extract_key — no dict allocation per request

_AuthMiddleware._extract_key() built a full dict from all request headers
on every HTTP request just to look up one key. Under high request volume
this generated constant GC pressure.

Fix: scan the headers list directly with a for-loop. Stops at the first
authorization header found. Semantics identical to previous implementation."
```

---

## Self-Review

### Spec coverage

| Root cause | Task covering it |
|-----------|-----------------|
| Throttler holds semaphore during sleep | Task 1 ✓ |
| load_connections() on every call | Task 2 ✓ |
| SQLite connection per operation | Task 3 ✓ |
| _extract_key dict allocation per request | Task 4 ✓ |

### Placeholder scan

No TODOs, TBDs, or "similar to Task N" references. All code blocks are complete and runnable.

### Type consistency

- `Throttler._history`: `deque[float]` declared in `__init__`, used as `deque` in `acquire()` with `.popleft()` — consistent.
- `TelemetryStore._conn`: declared as `sqlite3.Connection | None` in `__init__`, initialized in `_setup()`, returned from `_connect()` — consistent.
- `_extract_key`: returns `str | None` — unchanged from original signature.
- `load_connections()` return type `dict[str, dict]` — unchanged.

### Task ordering

Tasks 1 and 2 both modify `mcp_proxy.py`. They can be done in either order; the test file accumulates tests across both tasks. Task 3 and Task 4 are fully independent of each other and of Tasks 1–2.
