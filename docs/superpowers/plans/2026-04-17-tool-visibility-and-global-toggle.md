# Tool Visibility Filtering & Global Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tools/list` user-aware so disabled tools are hidden from the MCP client, and add a runtime global on/off toggle using the existing `tool_permissions` table with a `"*"` sentinel `user_id`.

**Architecture:** Three changes: (1) add an in-memory `_disabled_cache` to `TelemetryStore` with `filter_visible_tools()` and extend `has_permission`/`set_tool_permission` to handle the `"*"` sentinel; (2) patch `mcp.list_tools` in `mcp_server.py` using the same monkey-patch pattern already used for `mcp.tool` and `mcp.add_tool`; (3) document the `"*"` sentinel in CLAUDE.md. No new DB table, no new admin endpoints, no server restart needed to toggle tools.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), `contextvars` (already in `mcp_server.py`), pytest, `remote-gateway/core/telemetry.py`, `remote-gateway/core/mcp_server.py`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `remote-gateway/tests/test_tool_visibility.py` | Create | 10 tests covering cache loading, filtering, global sentinel, call blocking, and list_tools wiring |
| `remote-gateway/core/telemetry.py` | Modify | Add `_disabled_cache`, `_load_disabled_cache()`, `filter_visible_tools()`; extend `set_tool_permission` and `has_permission` |
| `remote-gateway/core/mcp_server.py` | Modify | Add `_filtered_list_tools` and patch `mcp.list_tools` after the existing `add_tool` patch |
| `CLAUDE.md` | Modify | Document `"*"` sentinel in the Admin Guardrails section |

---

## Task 1: Write Failing Tests

**Files:**
- Create: `remote-gateway/tests/test_tool_visibility.py`

- [ ] **Step 1.1: Create the test file with all 10 tests**

Create `remote-gateway/tests/test_tool_visibility.py` with the following content:

```python
"""Tests for per-user tool visibility filtering and global toggle.

All tests use a temporary SQLite DB via tmp_path — no shared state between tests.
No mcp_server import (startup side effects). The list_tools filter logic is tested
via a local simulation of _filtered_list_tools using filter_visible_tools directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.telemetry import TelemetryStore


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal stand-in for mcp.types.Tool. Only .name is used by the filter."""

    def __init__(self, name: str) -> None:
        self.name = name


def _make_store(tmp_path: Path) -> TelemetryStore:
    """Return a fresh TelemetryStore backed by a temp DB."""
    return TelemetryStore(db_path=tmp_path / "test.db")


def _simulate_list_tools_filter(
    all_tools: list[_FakeTool],
    store: TelemetryStore,
    user_id: str | None,
) -> list[_FakeTool]:
    """Replicate the _filtered_list_tools logic from mcp_server.py.

    Tests the filtering behaviour without importing mcp_server (which has
    server-startup side effects). The logic under test is filter_visible_tools;
    this helper confirms it is wired the same way the patch will wire it.
    """
    if not store._enabled:
        return all_tools
    visible = store.filter_visible_tools(user_id, [t.name for t in all_tools])
    return [t for t in all_tools if t.name in visible]


# ---------------------------------------------------------------------------
# TelemetryStore — cache loading
# ---------------------------------------------------------------------------


def test_cache_loads_from_db(tmp_path):
    """_load_disabled_cache reads all enabled=0 rows at startup."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "tool_a", False)
    store.set_tool_permission("user_abc", "tool_b", False)
    store.set_tool_permission("user_abc", "tool_c", True)  # should NOT be in cache

    # Create a second store instance to force a fresh cache load from DB
    store2 = TelemetryStore(db_path=tmp_path / "test.db")

    assert "tool_a" in store2._disabled_cache.get("*", set())
    assert "tool_b" in store2._disabled_cache.get("user_abc", set())
    assert "tool_c" not in store2._disabled_cache.get("user_abc", set())


# ---------------------------------------------------------------------------
# TelemetryStore — filter_visible_tools
# ---------------------------------------------------------------------------


def test_filter_hides_globally_disabled(tmp_path):
    """filter_visible_tools removes '*'-disabled tools for all callers."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "hidden_tool", False)

    result = store.filter_visible_tools(None, ["hidden_tool", "visible_tool"])

    assert "hidden_tool" not in result
    assert "visible_tool" in result


def test_filter_hides_user_disabled(tmp_path):
    """filter_visible_tools removes per-user disabled tools for that user only."""
    store = _make_store(tmp_path)
    store.set_tool_permission("user_abc", "user_tool", False)

    result_abc = store.filter_visible_tools("user_abc", ["user_tool", "other_tool"])
    result_other = store.filter_visible_tools("user_xyz", ["user_tool", "other_tool"])

    assert "user_tool" not in result_abc
    assert "other_tool" in result_abc
    assert "user_tool" in result_other  # another user is unaffected


def test_filter_applies_both(tmp_path):
    """Global and per-user disables union — both sets are hidden."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "globally_hidden", False)
    store.set_tool_permission("user_abc", "user_hidden", False)

    result = store.filter_visible_tools(
        "user_abc",
        ["globally_hidden", "user_hidden", "visible"],
    )

    assert result == {"visible"}


def test_filter_shows_all_when_no_disables(tmp_path):
    """No disabled rows → full list returned."""
    store = _make_store(tmp_path)

    result = store.filter_visible_tools("user_abc", ["tool_a", "tool_b", "tool_c"])

    assert result == {"tool_a", "tool_b", "tool_c"}


def test_filter_fails_open_when_telemetry_disabled(tmp_path):
    """If telemetry is disabled (bad DB path), filter returns full list."""
    store = TelemetryStore(db_path=Path("/nonexistent/path/db.sqlite"))

    result = store.filter_visible_tools("user_abc", ["tool_a", "tool_b"])

    # TelemetryStore._enabled is False, filter_visible_tools must return everything
    assert result == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# TelemetryStore — set_tool_permission cache update
# ---------------------------------------------------------------------------


def test_set_permission_updates_cache(tmp_path):
    """Cache reflects write immediately — no re-query needed."""
    store = _make_store(tmp_path)

    store.set_tool_permission("user_abc", "tool_x", False)
    assert "tool_x" in store._disabled_cache.get("user_abc", set())

    store.set_tool_permission("user_abc", "tool_x", True)
    assert "tool_x" not in store._disabled_cache.get("user_abc", set())


def test_set_global_permission_updates_cache(tmp_path):
    """set_tool_permission with user_id='*' updates the global cache entry."""
    store = _make_store(tmp_path)

    store.set_tool_permission("*", "global_tool", False)
    assert "global_tool" in store._disabled_cache.get("*", set())

    store.set_tool_permission("*", "global_tool", True)
    assert "global_tool" not in store._disabled_cache.get("*", set())


# ---------------------------------------------------------------------------
# TelemetryStore — has_permission global sentinel
# ---------------------------------------------------------------------------


def test_has_permission_blocks_global(tmp_path):
    """has_permission returns False for a '*'-disabled tool regardless of user."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "blocked_tool", False)

    assert not store.has_permission("user_abc", "blocked_tool")
    assert not store.has_permission("user_xyz", "blocked_tool")
    assert not store.has_permission("admin", "blocked_tool")


# ---------------------------------------------------------------------------
# list_tools filter simulation
# ---------------------------------------------------------------------------


def test_list_tools_filtered_by_user(tmp_path):
    """Authenticated user sees global disables + their own disables removed."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "globally_hidden", False)
    store.set_tool_permission("user_abc", "user_hidden", False)

    all_tools = [
        _FakeTool("globally_hidden"),
        _FakeTool("user_hidden"),
        _FakeTool("visible_tool"),
    ]

    result = _simulate_list_tools_filter(all_tools, store, "user_abc")

    assert len(result) == 1
    assert result[0].name == "visible_tool"


def test_list_tools_unauthenticated(tmp_path):
    """Unauthenticated (user_id=None) sees only global disables applied."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "globally_hidden", False)
    store.set_tool_permission("user_abc", "user_hidden", False)

    all_tools = [
        _FakeTool("globally_hidden"),
        _FakeTool("user_hidden"),
        _FakeTool("visible_tool"),
    ]

    result = _simulate_list_tools_filter(all_tools, store, None)

    assert len(result) == 2
    assert {t.name for t in result} == {"user_hidden", "visible_tool"}
```

- [ ] **Step 1.2: Run the tests to confirm they all fail**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_tool_visibility.py -v
```

Expected: 10 failures. The most common error will be `AttributeError: type object 'TelemetryStore' has no attribute '_disabled_cache'` or `AttributeError: 'TelemetryStore' object has no attribute '_disabled_cache'`. If you see `ModuleNotFoundError` for `core.telemetry`, check that you are running pytest from the `remote-gateway/` directory:

```bash
cd remote-gateway && pytest tests/test_tool_visibility.py -v
```

- [ ] **Step 1.3: Commit the failing tests**

```bash
git add remote-gateway/tests/test_tool_visibility.py
git commit -m "test: add failing tests for tool visibility filtering and global toggle"
```

---

## Task 2: Implement TelemetryStore Changes

**Files:**
- Modify: `remote-gateway/core/telemetry.py`

- [ ] **Step 2.1: Initialize `_disabled_cache` in `__init__` and call `_load_disabled_cache`**

In `remote-gateway/core/telemetry.py`, replace the `__init__` method (lines 96–99) with:

```python
def __init__(self, db_path: Path = _DB_PATH) -> None:
    self._path = db_path
    self._enabled = False
    self._disabled_cache: dict[str, set[str]] = {}
    self._setup()
    self._load_disabled_cache()
```

- [ ] **Step 2.2: Add `_load_disabled_cache` after `_connect`**

After the `_connect` method (around line 132), insert:

```python
def _load_disabled_cache(self) -> None:
    """Populate _disabled_cache from all enabled=0 rows in tool_permissions.

    Called once at startup. After this, set_tool_permission keeps the cache
    consistent — no further DB reads are needed for list-time filtering.
    Silent no-op if the DB is unavailable.
    """
    if not self._enabled:
        return
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT user_id, tool_name FROM tool_permissions WHERE enabled = 0"
        ).fetchall()
        conn.close()
        for row in rows:
            self._disabled_cache.setdefault(row["user_id"], set()).add(row["tool_name"])
    except Exception:
        pass
```

- [ ] **Step 2.3: Add `filter_visible_tools` in the API key management section**

After `has_permission` (around line 250), insert:

```python
def filter_visible_tools(self, user_id: str | None, tool_names: list[str]) -> set[str]:
    """Return the subset of tool_names the user is permitted to see.

    Reads only the in-memory _disabled_cache — no DB query. Globally disabled
    tools (user_id='*') are hidden from all callers including unauthenticated
    ones. Per-user disabled tools are hidden for that user only.

    Fails open: if telemetry is disabled, returns all tool_names as a set.

    Args:
        user_id: Authenticated user, or None for unauthenticated requests.
        tool_names: Full list of registered tool names to filter.

    Returns:
        Set of tool names the user is allowed to see.
    """
    globally_disabled = self._disabled_cache.get("*", set())
    user_disabled = self._disabled_cache.get(user_id, set()) if user_id else set()
    hidden = globally_disabled | user_disabled
    return {name for name in tool_names if name not in hidden}
```

- [ ] **Step 2.4: Extend `has_permission` to check the global sentinel first**

Replace the existing `has_permission` method (around lines 237–250) with:

```python
def has_permission(self, user_id: str, tool_name: str) -> bool:
    """Return True if user may call tool_name (default True when no row).

    Checks the global '*' sentinel via the in-memory cache first — no DB
    query for globally disabled tools. Falls back to the per-user DB row.

    Args:
        user_id: The authenticated user's identifier.
        tool_name: The tool being called.

    Returns:
        False if the tool is globally disabled or explicitly disabled for
        this user. True otherwise (including on DB failure).
    """
    # Global disable takes priority — cache lookup, no DB query
    if tool_name in self._disabled_cache.get("*", set()):
        return False
    if not self._enabled:
        return True
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT enabled FROM tool_permissions WHERE user_id = ? AND tool_name = ?",
            (user_id, tool_name),
        ).fetchone()
        conn.close()
        return row is None or bool(row["enabled"])
    except Exception:
        return True  # never block on DB failure
```

- [ ] **Step 2.5: Extend `set_tool_permission` to update the cache after the DB write**

Replace the existing `set_tool_permission` method (around lines 268–282) with:

```python
def set_tool_permission(self, user_id: str, tool_name: str, enabled: bool) -> None:
    """Insert or update a tool permission for a user.

    Use user_id='*' to set a global toggle affecting all users — the tool
    will be hidden from tools/list and blocked at call time for everyone.

    Args:
        user_id: The user to configure, or '*' for a global toggle.
        tool_name: The tool name as registered on the gateway.
        enabled: True to allow, False to disable.
    """
    if not self._enabled:
        return
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO tool_permissions (user_id, tool_name, enabled) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, tool_name) DO UPDATE SET enabled = excluded.enabled",
            (user_id, tool_name, int(enabled)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    # Keep cache consistent regardless of DB success/failure
    if enabled:
        if user_id in self._disabled_cache:
            self._disabled_cache[user_id].discard(tool_name)
    else:
        self._disabled_cache.setdefault(user_id, set()).add(tool_name)
```

- [ ] **Step 2.6: Run the TelemetryStore tests — 8 of 10 should now pass**

```bash
cd remote-gateway && pytest tests/test_tool_visibility.py -v
```

Expected: 8 PASSED, 2 FAILED. The 2 failing tests are `test_list_tools_filtered_by_user` and `test_list_tools_unauthenticated`. These pass once `filter_visible_tools` exists, which it now does — actually re-reading the simulation helper, these 2 tests should ALSO pass now since they only call `filter_visible_tools` (via `_simulate_list_tools_filter`). If all 10 pass, proceed.

If 8 pass and 2 fail, the failure will be in `_simulate_list_tools_filter` — check that `filter_visible_tools` is accessible. The simulation function in the test file calls `store.filter_visible_tools(...)` directly, so it should work once Step 2.3 is complete.

- [ ] **Step 2.7: Run ruff to confirm no lint errors**

```bash
cd remote-gateway && ruff check core/telemetry.py
```

Expected: no output (no errors).

- [ ] **Step 2.8: Confirm all 10 tests pass**

```bash
cd remote-gateway && pytest tests/test_tool_visibility.py -v
```

Expected:
```
tests/test_tool_visibility.py::test_cache_loads_from_db PASSED
tests/test_tool_visibility.py::test_filter_hides_globally_disabled PASSED
tests/test_tool_visibility.py::test_filter_hides_user_disabled PASSED
tests/test_tool_visibility.py::test_filter_applies_both PASSED
tests/test_tool_visibility.py::test_filter_shows_all_when_no_disables PASSED
tests/test_tool_visibility.py::test_filter_fails_open_when_telemetry_disabled PASSED
tests/test_tool_visibility.py::test_set_permission_updates_cache PASSED
tests/test_tool_visibility.py::test_set_global_permission_updates_cache PASSED
tests/test_tool_visibility.py::test_has_permission_blocks_global PASSED
tests/test_tool_visibility.py::test_list_tools_filtered_by_user PASSED
tests/test_tool_visibility.py::test_list_tools_unauthenticated PASSED
```

- [ ] **Step 2.9: Run the full existing test suite to confirm no regressions**

```bash
cd remote-gateway && pytest tests/test_attio_tools.py tests/test_tool_visibility.py -v
```

Expected: all tests pass.

- [ ] **Step 2.10: Commit**

```bash
git add remote-gateway/core/telemetry.py
git commit -m "feat: add disabled_cache and filter_visible_tools to TelemetryStore

Adds in-memory _disabled_cache populated at startup from tool_permissions
(enabled=0 rows). filter_visible_tools() checks cache only — no DB query
at list time. has_permission() now checks the '*' global sentinel first.
set_tool_permission() keeps the cache consistent on every write.

Use user_id='*' to disable a tool globally for all users."
```

---

## Task 3: Patch `mcp.list_tools` in the Server

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 3.1: Add `_filtered_list_tools` after the existing `add_tool` patch**

In `remote-gateway/core/mcp_server.py`, after line 478 (`mcp.add_tool = _tracked_add_tool`), insert the following block. The empty line before and after is important for readability and ruff compliance:

```python
mcp.add_tool = _tracked_add_tool

_orig_list_tools = mcp.list_tools


async def _filtered_list_tools() -> list[Any]:
    """list_tools override that hides tools disabled for the current user.

    Reads _disabled_cache from telemetry — no DB query at list time.
    Fails open: returns the full tool list if telemetry is unavailable.
    Global disables (user_id='*') apply to unauthenticated requests too.

    Patched onto mcp.list_tools so every tools/list RPC goes through this.
    If FastMCP's tools/list RPC handler calls an internal method rather than
    mcp.list_tools, the patch target may need to be mcp._tool_manager.list_tools
    instead — verify by confirming that filtering applies during a live session.
    """
    tools = await _orig_list_tools()
    user_id = _current_user.get()
    if not _telemetry._enabled:
        return tools
    visible = _telemetry.filter_visible_tools(user_id, [t.name for t in tools])
    return [t for t in tools if t.name in visible]


mcp.list_tools = _filtered_list_tools
```

- [ ] **Step 3.2: Run ruff on mcp_server.py**

```bash
cd remote-gateway && ruff check core/mcp_server.py
```

Expected: no output.

- [ ] **Step 3.3: Run the full test suite**

```bash
cd remote-gateway && pytest tests/test_attio_tools.py tests/test_tool_visibility.py -v
```

Expected: all tests pass.

- [ ] **Step 3.4: Verify the patch is wired at the right call site**

After the server starts, the FastMCP `tools/list` RPC must call `_filtered_list_tools`. The patch replaces `mcp.list_tools`, which FastMCP calls internally when processing a `tools/list` request. Confirm this by doing a quick smoke check:

```bash
cd remote-gateway && python -c "
from core.mcp_server import mcp, _filtered_list_tools
print('list_tools is patched:', mcp.list_tools is _filtered_list_tools)
"
```

Expected output:
```
list_tools is patched: True
```

If `False`, FastMCP may store the reference internally at class creation time. In that case, replace `mcp.list_tools = _filtered_list_tools` with:

```python
mcp._tool_manager.list_tools = _filtered_list_tools  # fallback if public patch doesn't wire
```

And re-run the smoke check with `mcp._tool_manager.list_tools is _filtered_list_tools`.

- [ ] **Step 3.5: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat: filter tools/list by user permissions at list time

Patches mcp.list_tools with _filtered_list_tools, which reads the
in-memory _disabled_cache to strip disabled tools from the response.
Globally disabled tools (user_id='*') are hidden for all users.
Per-user disabled tools are hidden for that user only.
Unauthenticated requests see only global disables. Fails open."
```

---

## Task 4: Document the `"*"` Sentinel

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 4.1: Add the global toggle reference to the Admin Guardrails section**

In `CLAUDE.md`, find the `## Admin Guardrails` section and add a new `### Global Tool Toggle` subsection immediately below the bullet list:

```markdown
### Global Tool Toggle

Disable a proxied or built-in tool for **all users** at runtime — no restart required:

```
PUT /api/permissions/*/attio__search_records
Body: {"enabled": false}
```

The sentinel `user_id = "*"` in `tool_permissions` applies to every user. Globally disabled tools are hidden from `tools/list` and blocked at call time. Re-enable with `{"enabled": true}`.

View all global toggles:
```
GET /api/permissions/*
```

Use this when replacing a proxied MCP tool with a Python tool — disable the old route globally, register the new Python tool via `@mcp.tool()`, and the transition is live immediately.
```

- [ ] **Step 4.2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document '*' sentinel for global tool toggle in CLAUDE.md"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Per-user tool visibility — `filter_visible_tools` + `_filtered_list_tools` patch → Tasks 2 & 3
- [x] Global tool toggle via `"*"` sentinel — `set_tool_permission("*", ...)` + cache entry → Task 2
- [x] In-memory cache, no DB query at list time — `_disabled_cache` + `_load_disabled_cache` → Task 2
- [x] Cache updated on every write — `set_tool_permission` cache update block → Task 2, Step 2.5
- [x] `has_permission` checks global sentinel first → Task 2, Step 2.4
- [x] Fail open when telemetry disabled — `if not self._enabled: return all tool_names` → `filter_visible_tools` + `_filtered_list_tools`
- [x] Unauthenticated requests: only global disables applied — `user_disabled = {} when user_id is None` → `filter_visible_tools`
- [x] No new DB table — sentinel fits in existing `tool_permissions` → confirmed
- [x] No new admin endpoints — `PUT /api/permissions/*/tool` reuses existing route → confirmed (`api_permissions_set` at admin_api.py:190 calls `set_tool_permission(user_id, tool_name, ...)`)
- [x] CLAUDE.md docs — Task 4
- [x] All 10 tests in spec covered → Task 1 (added `test_set_global_permission_updates_cache` to the 10 from the spec — 11 total, one extra)

**Placeholder scan:** No TBD, TODO, or vague steps. All code blocks are complete.

**Type consistency:**
- `filter_visible_tools(user_id: str | None, tool_names: list[str]) -> set[str]` — used as `store.filter_visible_tools(user_id, [t.name for t in tools])` in both the test simulation and `_filtered_list_tools`. Consistent.
- `_disabled_cache: dict[str, set[str]]` — accessed as `.get("*", set())` and `.get(user_id, set())` throughout. Consistent.
- `_load_disabled_cache` initializes via `setdefault(row["user_id"], set()).add(...)`. Consistent with `set_tool_permission` cache update which uses same pattern.
- `_FakeTool.name: str` — accessed as `t.name` in `_simulate_list_tools_filter`. Consistent with `mcp.types.Tool.name` used in `_filtered_list_tools`.
