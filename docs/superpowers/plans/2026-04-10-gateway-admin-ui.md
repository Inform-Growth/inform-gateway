# Gateway Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a magic-link admin dashboard to the gateway that shows executive adoption/health metrics with Sankey charts and an ops view for per-user tool permission management.

**Architecture:** A Starlette sub-app mounted at `/admin` is added to the existing combined-transport server. It serves a single-page HTML dashboard and JSON API endpoints (`/admin/api/*`), all gated by a `?token=` query parameter (configurable via `ADMIN_TOKEN` env var, hardcoded default `inform-admin-2026`). The telemetry SQLite store gains a `tool_permissions` table and five new methods. Permission enforcement (deny a tool call when a user has it disabled) is injected into the existing telemetry patch in `mcp_server.py`.

**Tech Stack:** Python 3.11+, Starlette (already a dependency via FastMCP), SQLite (already in use), D3 v7 + d3-sankey 0.12 (CDN, no build step), vanilla JS ES2020.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `remote-gateway/core/telemetry.py` | Add `tool_permissions` table + 5 new methods |
| Create | `remote-gateway/core/admin_api.py` | Starlette sub-app, all `/admin/api/*` routes |
| Create | `remote-gateway/core/admin_dashboard.html` | Single-page dashboard HTML/JS |
| Modify | `remote-gateway/core/mcp_server.py` | Permission check in telemetry patch + mount admin app |
| Create | `remote-gateway/tests/test_telemetry_permissions.py` | TDD for new TelemetryStore methods |
| Create | `remote-gateway/tests/test_admin_api.py` | TDD for admin API routes |

---

## Task 1: Tests for TelemetryStore Extensions

**Files:**
- Create: `remote-gateway/tests/test_telemetry_permissions.py`

- [ ] **Step 1: Write the failing tests**

```python
"""
Tests for TelemetryStore permission methods.

Run with:
    pytest remote-gateway/tests/test_telemetry_permissions.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------------
# has_permission
# ---------------------------------------------------------------------------

def test_has_permission_default_true(store):
    """No row in tool_permissions means the user is allowed."""
    assert store.has_permission("alice", "some_tool") is True


def test_has_permission_disabled(store):
    store.add_api_key("alice", "sk-alice")
    store.set_tool_permission("alice", "some_tool", False)
    assert store.has_permission("alice", "some_tool") is False


def test_has_permission_re_enabled(store):
    store.set_tool_permission("alice", "some_tool", False)
    store.set_tool_permission("alice", "some_tool", True)
    assert store.has_permission("alice", "some_tool") is True


def test_has_permission_other_user_unaffected(store):
    store.set_tool_permission("alice", "some_tool", False)
    assert store.has_permission("bob", "some_tool") is True


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

def test_list_users_returns_created_users(store):
    store.add_api_key("alice@company.com", "sk-alice")
    store.add_api_key("bob@company.com", "sk-bob")
    users = store.list_users()
    user_ids = [u["user_id"] for u in users]
    assert "alice@company.com" in user_ids
    assert "bob@company.com" in user_ids


def test_list_users_includes_call_count(store):
    store.add_api_key("alice@company.com", "sk-alice")
    store.record("health_check", 10, True, user_id="alice@company.com")
    store.record("health_check", 12, True, user_id="alice@company.com")
    users = store.list_users()
    alice = next(u for u in users if u["user_id"] == "alice@company.com")
    assert alice["call_count"] == 2


def test_list_users_empty(store):
    assert store.list_users() == []


# ---------------------------------------------------------------------------
# delete_user
# ---------------------------------------------------------------------------

def test_delete_user_removes_key(store):
    store.add_api_key("alice@company.com", "sk-alice")
    count = store.delete_user("alice@company.com")
    assert count == 1
    assert store.lookup_user("sk-alice") is None


def test_delete_user_removes_permissions(store):
    store.add_api_key("alice@company.com", "sk-alice")
    store.set_tool_permission("alice@company.com", "some_tool", False)
    store.delete_user("alice@company.com")
    assert store.has_permission("alice@company.com", "some_tool") is True


def test_delete_user_unknown_returns_zero(store):
    assert store.delete_user("nobody@company.com") == 0


# ---------------------------------------------------------------------------
# get_tool_permissions
# ---------------------------------------------------------------------------

def test_get_tool_permissions_returns_explicit_settings(store):
    store.set_tool_permission("alice", "tool_a", False)
    store.set_tool_permission("alice", "tool_b", True)
    perms = store.get_tool_permissions("alice")
    by_tool = {p["tool_name"]: p["enabled"] for p in perms}
    assert by_tool["tool_a"] is False
    assert by_tool["tool_b"] is True


def test_get_tool_permissions_empty_for_new_user(store):
    assert store.get_tool_permissions("nobody") == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /path/to/inform-gateway
pytest remote-gateway/tests/test_telemetry_permissions.py -v
```

Expected: All tests fail with `AttributeError: 'TelemetryStore' object has no attribute 'has_permission'` (or similar).

- [ ] **Step 3: Commit the failing tests**

```bash
git add remote-gateway/tests/test_telemetry_permissions.py
git commit -m "test: add failing tests for TelemetryStore permission methods"
```

---

## Task 2: Implement TelemetryStore Extensions

**Files:**
- Modify: `remote-gateway/core/telemetry.py`

- [ ] **Step 1: Add `tool_permissions` table to `_SCHEMA_TABLES`**

In `telemetry.py`, find `_SCHEMA_TABLES` and append the new table definition:

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
    response_size INTEGER
);

CREATE TABLE IF NOT EXISTS tool_permissions (
    user_id   TEXT    NOT NULL,
    tool_name TEXT    NOT NULL,
    enabled   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, tool_name)
);
"""
```

- [ ] **Step 2: Add the five new methods to `TelemetryStore`**

Add these methods after the existing `revoke_api_key` method (around line 167):

```python
    def list_users(self) -> list[dict]:
        """Return all API key records with per-user call counts.

        Returns:
            List of dicts with user_id, key, created_at (ISO string),
            call_count, and last_active (ISO string or None).
        """
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            rows = conn.execute(
                """
                SELECT
                    ak.user_id,
                    ak.key,
                    ak.created_at,
                    COUNT(tc.id)     AS call_count,
                    MAX(tc.called_at) AS last_active
                FROM api_keys ak
                LEFT JOIN tool_calls tc ON ak.user_id = tc.user_id
                GROUP BY ak.user_id, ak.key
                ORDER BY ak.created_at DESC
                """
            ).fetchall()
            conn.close()
        except Exception:
            return []
        return [
            {
                "user_id": row["user_id"],
                "key": row["key"],
                "created_at": datetime.datetime.fromtimestamp(
                    row["created_at"], tz=datetime.UTC
                ).strftime("%Y-%m-%dT%H:%MZ"),
                "call_count": row["call_count"] or 0,
                "last_active": (
                    datetime.datetime.fromtimestamp(
                        row["last_active"], tz=datetime.UTC
                    ).strftime("%Y-%m-%dT%H:%MZ")
                    if row["last_active"]
                    else None
                ),
            }
            for row in rows
        ]

    def delete_user(self, user_id: str) -> int:
        """Delete all API keys and permissions for a user.

        Args:
            user_id: The user identifier to remove.

        Returns:
            Number of API key rows deleted (0 if user not found).
        """
        if not self._enabled:
            return 0
        try:
            conn = self._connect()
            cursor = conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
            deleted = cursor.rowcount
            conn.execute("DELETE FROM tool_permissions WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return deleted
        except Exception:
            return 0

    def has_permission(self, user_id: str, tool_name: str) -> bool:
        """Return True if user may call tool_name (default True when no row).

        Args:
            user_id: The resolved user identifier.
            tool_name: The tool being invoked.

        Returns:
            False only when an explicit disabled row exists; True otherwise.
        """
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

    def get_tool_permissions(self, user_id: str) -> list[dict]:
        """Return explicit permission settings for a user.

        Args:
            user_id: The user identifier.

        Returns:
            List of dicts with tool_name and enabled (bool).
            Only includes tools with an explicit row — absence means allowed.
        """
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            rows = conn.execute(
                "SELECT tool_name, enabled FROM tool_permissions WHERE user_id = ? ORDER BY tool_name",
                (user_id,),
            ).fetchall()
            conn.close()
        except Exception:
            return []
        return [{"tool_name": row["tool_name"], "enabled": bool(row["enabled"])} for row in rows]

    def set_tool_permission(self, user_id: str, tool_name: str, enabled: bool) -> None:
        """Insert or update a tool permission row for a user.

        Args:
            user_id: The user identifier.
            tool_name: The tool name to configure.
            enabled: True to allow, False to deny.
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
```

- [ ] **Step 3: Run tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_telemetry_permissions.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/core/telemetry.py
git commit -m "feat: add tool_permissions table and user/permission methods to TelemetryStore"
```

---

## Task 3: Tests for Permission Enforcement

**Files:**
- Create: `remote-gateway/tests/test_permission_enforcement.py`

- [ ] **Step 1: Write the failing tests**

```python
"""
Tests for per-user tool permission enforcement in the telemetry patch.

The _tracked_mcp_tool and _tracked_add_tool wrappers must check
_telemetry.has_permission(user_id, tool_name) before calling the tool,
and raise PermissionError if it returns False.

Run with:
    pytest remote-gateway/tests/test_permission_enforcement.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _import_server_with_permission_mock(has_permission_return: bool):
    """Import mcp_server with all deps stubbed and has_permission returning the given value."""
    import importlib.util
    import contextvars

    # Use a unique module name so each call gets a fresh import
    mod_name = f"_mcp_server_perm_{has_permission_return}"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    for dep in (
        "mcp", "mcp.server", "mcp.server.fastmcp",
        "mcp.server.lowlevel", "mcp.server.lowlevel.server",
    ):
        sys.modules.setdefault(dep, types.ModuleType(dep))

    sys.modules["mcp.server.lowlevel.server"].request_ctx = contextvars.ContextVar("request_ctx")

    mock_fastmcp_class = MagicMock()
    mock_mcp_instance = MagicMock()
    mock_mcp_instance.tool = MagicMock(side_effect=lambda *a, **kw: (lambda fn: fn))
    mock_fastmcp_class.return_value = mock_mcp_instance
    sys.modules["mcp.server.fastmcp"].FastMCP = mock_fastmcp_class

    if "field_registry" not in sys.modules:
        fr = types.ModuleType("field_registry")
        fr.registry = MagicMock()
        sys.modules["field_registry"] = fr

    if "mcp_proxy" not in sys.modules:
        mp = types.ModuleType("mcp_proxy")
        mp.mount_all_proxies = MagicMock(return_value=[])
        sys.modules["mcp_proxy"] = mp

    mock_tel = MagicMock()
    mock_tel.record = MagicMock()
    mock_tel.lookup_user = MagicMock(return_value="alice")
    mock_tel.has_permission = MagicMock(return_value=has_permission_return)
    mod_tel = types.ModuleType("telemetry")
    mod_tel.telemetry = mock_tel
    sys.modules["telemetry"] = mod_tel

    for tool_mod in ("tools", "tools.meta", "tools.notes", "tools.registry", "tools.attio"):
        if tool_mod not in sys.modules:
            m = types.ModuleType(tool_mod)
            sys.modules[tool_mod] = m
        if not hasattr(sys.modules[tool_mod], "register"):
            sys.modules[tool_mod].register = MagicMock()

    path = Path(__file__).parent.parent / "core" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = types.ModuleType(mod_name)
    module.__file__ = str(path)
    spec.loader.exec_module(module)
    return module, mock_tel


def test_permission_denied_sync_raises_permission_error():
    """Sync tool must raise PermissionError when user has it disabled."""
    server, mock_tel = _import_server_with_permission_mock(has_permission_return=False)

    def my_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_tool)

    token = server._current_user.set("alice")
    try:
        try:
            tracked()
        except PermissionError as exc:
            assert "my_tool" in str(exc)
        else:
            raise AssertionError("Expected PermissionError")
    finally:
        server._current_user.reset(token)


def test_permission_denied_async_raises_permission_error():
    """Async tool must raise PermissionError when user has it disabled."""
    server, mock_tel = _import_server_with_permission_mock(has_permission_return=False)

    async def my_async_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_async_tool)

    token = server._current_user.set("alice")
    try:
        try:
            asyncio.run(tracked())
        except PermissionError as exc:
            assert "my_async_tool" in str(exc)
        else:
            raise AssertionError("Expected PermissionError")
    finally:
        server._current_user.reset(token)


def test_permission_allowed_sync_calls_through():
    """Sync tool must execute normally when has_permission returns True."""
    server, _ = _import_server_with_permission_mock(has_permission_return=True)

    def my_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_tool)
    token = server._current_user.set("alice")
    try:
        result = tracked()
        assert result == {"ok": True}
    finally:
        server._current_user.reset(token)


def test_unauthenticated_user_not_blocked():
    """When user_id is None (no API key), the permission check must be skipped."""
    server, mock_tel = _import_server_with_permission_mock(has_permission_return=False)

    def my_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_tool)
    # _current_user is None by default — no permission check should run
    result = tracked()
    assert result == {"ok": True}
    mock_tel.has_permission.assert_not_called()
```

- [ ] **Step 2: Run to confirm failures**

```bash
pytest remote-gateway/tests/test_permission_enforcement.py -v
```

Expected: All 4 tests fail — `PermissionError` is not yet raised by the tracked wrappers.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tests/test_permission_enforcement.py
git commit -m "test: add failing tests for per-user tool permission enforcement"
```

---

## Task 4: Implement Permission Enforcement in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Add permission check to `_tracked_mcp_tool` async branch**

Locate the async wrapper inside `_tracked_mcp_tool` (around line 278). Add the permission check immediately after `sid, rid = _get_call_ids()`:

```python
            @functools.wraps(fn)
            async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
                t0 = _time.monotonic()
                sid, rid = _get_call_ids()
                if sid and not _telemetry.has_permission(sid, fn.__name__):
                    raise PermissionError(
                        f"Tool '{fn.__name__}' is disabled for your account."
                    )
                try:
                    result = await fn(*fn_args, **fn_kwargs)
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                        user_id=sid, request_id=rid, response_size=_calculate_response_size(result),
                    )
                    return result
                except Exception as exc:
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                        type(exc).__name__, user_id=sid, request_id=rid,
                    )
                    raise
```

- [ ] **Step 2: Add permission check to `_tracked_mcp_tool` sync branch**

Find the sync `tracked` wrapper inside `_tracked_mcp_tool` (around line 297). Add the same check:

```python
        @functools.wraps(fn)
        def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            if sid and not _telemetry.has_permission(sid, fn.__name__):
                raise PermissionError(
                    f"Tool '{fn.__name__}' is disabled for your account."
                )
            try:
                result = fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid, response_size=_calculate_response_size(result),
                )
                return result
            except Exception as exc:
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                )
                raise
```

- [ ] **Step 3: Add permission check to `_tracked_add_tool` async branch**

Locate the async wrapper inside `_tracked_add_tool` (around line 336). Add after `sid, rid = _get_call_ids()`:

```python
        @functools.wraps(fn)
        async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            if sid and not _telemetry.has_permission(sid, tool_name):
                raise PermissionError(
                    f"Tool '{tool_name}' is disabled for your account."
                )
            try:
                result = await fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid, response_size=_calculate_response_size(result),
                )
                return result
            except Exception as exc:
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                )
                raise
```

- [ ] **Step 4: Add permission check to `_tracked_add_tool` sync branch**

```python
    @functools.wraps(fn)
    def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
        t0 = _time.monotonic()
        sid, rid = _get_call_ids()
        if sid and not _telemetry.has_permission(sid, tool_name):
            raise PermissionError(
                f"Tool '{tool_name}' is disabled for your account."
            )
        try:
            result = fn(*fn_args, **fn_kwargs)
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), True,
                user_id=sid, request_id=rid, response_size=_calculate_response_size(result),
            )
            return result
        except Exception as exc:
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                user_id=sid, request_id=rid,
            )
            raise
```

- [ ] **Step 5: Run all permission and telemetry tests**

```bash
pytest remote-gateway/tests/test_permission_enforcement.py remote-gateway/tests/test_telemetry_async.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat: enforce per-user tool permissions in telemetry patch"
```

---

## Task 5: Create the Admin API Backend

**Files:**
- Create: `remote-gateway/core/admin_api.py`

- [ ] **Step 1: Create `admin_api.py` with token validation and all API routes**

```python
"""
Gateway Admin API — Starlette sub-app mounted at /admin.

All routes require ?token=<ADMIN_TOKEN>. The token is read from the
ADMIN_TOKEN environment variable; it defaults to "inform-admin-2026" for
local development.

Mount in mcp_server.py:
    from admin_api import create_admin_app
    Mount("/admin", app=create_admin_app(telemetry_instance))
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route

_DASHBOARD_HTML = Path(__file__).parent / "admin_dashboard.html"
_DEFAULT_TOKEN = "inform-admin-2026"


def _admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", _DEFAULT_TOKEN)


def _is_authorized(request: Request) -> bool:
    return request.query_params.get("token", "") == _admin_token()


def _forbidden() -> Response:
    return JSONResponse({"error": "forbidden — invalid admin token"}, status_code=403)


def create_admin_app(telemetry: Any) -> Starlette:
    """Return a Starlette sub-app with all admin routes bound to telemetry.

    Args:
        telemetry: A TelemetryStore instance.
    """

    async def dashboard(request: Request) -> Response:
        if not _is_authorized(request):
            return HTMLResponse(
                "<h1>403 Forbidden</h1><p>Invalid or missing admin token.</p>",
                status_code=403,
            )
        if not _DASHBOARD_HTML.exists():
            return HTMLResponse("<h1>Admin dashboard not found.</h1>", status_code=500)
        return HTMLResponse(_DASHBOARD_HTML.read_text())

    async def api_stats(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        return JSONResponse(telemetry.stats())

    async def api_sessions(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        session_data = telemetry.session_usage(limit=200)
        flow_data = telemetry.user_flow_analysis(limit=500)
        # Build Sankey nodes/links from common_flows
        sankey = _build_sankey(flow_data.get("common_flows", []))
        return JSONResponse({
            "sankey": sankey,
            "user_breakdown": session_data.get("user_breakdown", {}),
            "recent_sequences": session_data.get("recent_sequences", {}),
        })

    async def api_users_list(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        return JSONResponse(telemetry.list_users())

    async def api_users_create(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        user_id = (body.get("user_id") or "").strip()
        if not user_id:
            return JSONResponse({"error": "user_id is required"}, status_code=400)
        key = telemetry.add_api_key(user_id)
        return JSONResponse({"user_id": user_id, "key": key}, status_code=201)

    async def api_users_delete(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        deleted = telemetry.delete_user(user_id)
        if deleted == 0:
            return JSONResponse({"error": "user not found"}, status_code=404)
        return JSONResponse({"deleted": deleted, "user_id": user_id})

    async def api_permissions_get(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        perms = telemetry.get_tool_permissions(user_id)
        return JSONResponse({"user_id": user_id, "permissions": perms})

    async def api_permissions_set(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        tool_name = request.path_params["tool_name"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if "enabled" not in body:
            return JSONResponse({"error": "enabled (bool) is required"}, status_code=400)
        telemetry.set_tool_permission(user_id, tool_name, bool(body["enabled"]))
        return JSONResponse({"ok": True, "user_id": user_id, "tool_name": tool_name,
                             "enabled": bool(body["enabled"])})

    routes = [
        Route("/", dashboard),
        Route("/api/stats", api_stats),
        Route("/api/sessions", api_sessions),
        Route("/api/users", api_users_list, methods=["GET"]),
        Route("/api/users", api_users_create, methods=["POST"]),
        Route("/api/users/{user_id}", api_users_delete, methods=["DELETE"]),
        Route("/api/permissions/{user_id}", api_permissions_get, methods=["GET"]),
        Route("/api/permissions/{user_id}/{tool_name:path}", api_permissions_set, methods=["PUT"]),
    ]

    return Starlette(routes=routes)


def _build_sankey(common_flows: list[dict]) -> dict:
    """Convert user_flow_analysis common_flows into D3-sankey nodes/links format.

    Args:
        common_flows: List of {"sequence": "tool_a -> tool_b", "count": N} dicts.

    Returns:
        Dict with "nodes" (list of {id, name}) and "links" (list of {source, target, value}).
        Only includes pair-level flows (exactly one "->").
    """
    node_set: set[str] = set()
    links: list[dict] = []

    for item in common_flows:
        parts = item["sequence"].split(" -> ")
        if len(parts) != 2:
            continue  # skip triplets — they'd double-count pairs
        src, tgt = parts
        node_set.add(src)
        node_set.add(tgt)
        links.append({"source": src, "target": tgt, "value": item["count"]})

    nodes = [{"id": name, "name": name} for name in sorted(node_set)]
    return {"nodes": nodes, "links": links}
```

- [ ] **Step 2: Commit**

```bash
git add remote-gateway/core/admin_api.py
git commit -m "feat: add admin API Starlette sub-app with stats/users/permissions routes"
```

---

## Task 6: Tests for the Admin API

**Files:**
- Create: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write the tests**

```python
"""
Tests for the admin API routes in admin_api.py.

Uses Starlette's TestClient for HTTP-level testing with a real
in-memory TelemetryStore.

Run with:
    pytest remote-gateway/tests/test_admin_api.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from admin_api import create_admin_app, _DEFAULT_TOKEN
from telemetry import TelemetryStore

TOKEN = _DEFAULT_TOKEN


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


@pytest.fixture()
def client(store):
    app = create_admin_app(store)
    return TestClient(app, raise_server_exceptions=True), store


# ---------------------------------------------------------------------------
# Token enforcement
# ---------------------------------------------------------------------------

def test_dashboard_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/")
    assert resp.status_code == 403


def test_api_stats_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/api/stats")
    assert resp.status_code == 403


def test_dashboard_allowed_with_token(client, tmp_path):
    c, _ = client
    # Create a minimal dashboard HTML so the endpoint doesn't 500
    dash_path = Path(__file__).parent.parent / "core" / "admin_dashboard.html"
    if not dash_path.exists():
        pytest.skip("admin_dashboard.html not yet created")
    resp = c.get(f"/?token={TOKEN}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_returns_tools_key(client):
    c, store = client
    store.record("health_check", 10, True)
    resp = c.get(f"/api/stats?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert "tools" in body
    assert "summary" in body


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def test_list_users_empty(client):
    c, _ = client
    resp = c.get(f"/api/users?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_user_returns_key(client):
    c, _ = client
    resp = c.post(f"/api/users?token={TOKEN}", json={"user_id": "alice@example.com"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == "alice@example.com"
    assert body["key"].startswith("sk-")


def test_create_user_missing_user_id(client):
    c, _ = client
    resp = c.post(f"/api/users?token={TOKEN}", json={})
    assert resp.status_code == 400


def test_delete_user_success(client):
    c, store = client
    store.add_api_key("alice@example.com", "sk-alice")
    resp = c.delete(f"/api/users/alice@example.com?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


def test_delete_user_not_found(client):
    c, _ = client
    resp = c.delete(f"/api/users/nobody@example.com?token={TOKEN}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def test_get_permissions_empty(client):
    c, _ = client
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.json()["permissions"] == []


def test_set_and_get_permission(client):
    c, _ = client
    resp = c.put(
        f"/api/permissions/alice@example.com/health_check?token={TOKEN}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert perms["health_check"] is False


def test_set_permission_missing_enabled(client):
    c, _ = client
    resp = c.put(
        f"/api/permissions/alice@example.com/health_check?token={TOKEN}",
        json={},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Sessions / Sankey
# ---------------------------------------------------------------------------

def test_sessions_returns_sankey_key(client):
    c, store = client
    store.record("tool_a", 10, True, user_id="alice")
    store.record("tool_b", 10, True, user_id="alice")
    resp = c.get(f"/api/sessions?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert "sankey" in body
    assert "nodes" in body["sankey"]
    assert "links" in body["sankey"]
```

- [ ] **Step 2: Run tests**

```bash
pytest remote-gateway/tests/test_admin_api.py -v
```

Expected: Token tests and API shape tests PASS. The dashboard test skips until the HTML file exists.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tests/test_admin_api.py
git commit -m "test: add admin API tests for token enforcement, users, permissions, sessions"
```

---

## Task 7: Build the Admin Dashboard HTML

**Files:**
- Create: `remote-gateway/core/admin_dashboard.html`

- [ ] **Step 1: Create the complete dashboard HTML**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gateway Admin</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
    header { display: flex; align-items: center; gap: 1rem; padding: 1rem 1.5rem; background: #1a1d27; border-bottom: 1px solid #2d3148; }
    header h1 { font-size: 1.1rem; font-weight: 600; color: #fff; flex: 1; }
    .tabs { display: flex; gap: 0.25rem; }
    .tab { padding: 0.4rem 1rem; border: 1px solid #2d3148; border-radius: 6px; background: transparent; color: #94a3b8; cursor: pointer; font-size: 0.85rem; }
    .tab.active { background: #2563eb; border-color: #2563eb; color: #fff; }
    .refresh-btn { padding: 0.35rem 0.75rem; border: 1px solid #374151; border-radius: 6px; background: transparent; color: #94a3b8; cursor: pointer; font-size: 0.8rem; }
    .refresh-btn:hover { background: #1f2937; }
    main { padding: 1.5rem; }
    .view { display: none; }
    .view.active { display: block; }
    /* Cards */
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
    .card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 10px; padding: 1.25rem; }
    .card .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: .05em; color: #64748b; margin-bottom: 0.4rem; }
    .card .value { font-size: 2rem; font-weight: 700; color: #fff; }
    .card .value.red { color: #f87171; }
    .card .value.green { color: #34d399; }
    /* Section titles */
    h2 { font-size: 0.85rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 0.75rem; }
    .section { background: #1a1d27; border: 1px solid #2d3148; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.5rem; }
    /* Tables */
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th { text-align: left; padding: 0.5rem 0.75rem; font-size: 0.72rem; text-transform: uppercase; color: #64748b; border-bottom: 1px solid #2d3148; cursor: pointer; user-select: none; }
    th:hover { color: #94a3b8; }
    td { padding: 0.5rem 0.75rem; border-bottom: 1px solid #1e2132; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #20253a; }
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; font-size: 0.7rem; font-weight: 600; }
    .badge.red { background: #7f1d1d; color: #fca5a5; }
    .badge.green { background: #14532d; color: #86efac; }
    .badge.yellow { background: #78350f; color: #fcd34d; }
    /* Charts */
    .charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem; }
    #sankey-container svg text { fill: #94a3b8; }
    .bar-chart { display: flex; flex-direction: column; gap: 0.4rem; }
    .bar-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.78rem; }
    .bar-label { width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #94a3b8; text-align: right; }
    .bar-track { flex: 1; background: #2d3148; border-radius: 3px; height: 18px; overflow: hidden; }
    .bar-fill { height: 100%; background: #2563eb; border-radius: 3px; display: flex; align-items: center; padding: 0 6px; font-size: 0.7rem; color: #fff; white-space: nowrap; transition: width 0.4s; }
    /* Ops */
    .ops-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .add-user-form { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
    .add-user-form input { flex: 1; padding: 0.4rem 0.75rem; background: #0f1117; border: 1px solid #374151; border-radius: 6px; color: #e2e8f0; font-size: 0.85rem; }
    .add-user-form input:focus { outline: none; border-color: #2563eb; }
    .btn { padding: 0.4rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.82rem; font-weight: 500; }
    .btn-primary { background: #2563eb; color: #fff; }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-danger { background: #7f1d1d; color: #fca5a5; }
    .btn-danger:hover { background: #991b1b; }
    .btn-sm { padding: 0.2rem 0.6rem; font-size: 0.75rem; }
    .key-reveal { font-family: monospace; font-size: 0.8rem; background: #0f1117; border: 1px solid #374151; border-radius: 4px; padding: 0.4rem 0.75rem; color: #34d399; margin-top: 0.5rem; display: none; }
    /* Permission grid */
    .perm-header { display: flex; justify-content: space-between; align-items: center; }
    .perm-placeholder { color: #64748b; font-size: 0.82rem; padding: 1rem 0; }
    .perm-grid { display: flex; flex-direction: column; gap: 0.3rem; max-height: 450px; overflow-y: auto; margin-top: 0.5rem; }
    .perm-row { display: flex; align-items: center; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid #2d3148; font-size: 0.82rem; }
    .perm-row:last-child { border-bottom: none; }
    .toggle { position: relative; width: 36px; height: 20px; }
    .toggle input { opacity: 0; width: 0; height: 0; }
    .toggle-slider { position: absolute; inset: 0; background: #374151; border-radius: 20px; cursor: pointer; transition: background 0.2s; }
    .toggle input:checked + .toggle-slider { background: #2563eb; }
    .toggle-slider::before { content: ''; position: absolute; width: 14px; height: 14px; left: 3px; top: 3px; background: white; border-radius: 50%; transition: transform 0.2s; }
    .toggle input:checked + .toggle-slider::before { transform: translateX(16px); }
    .muted { color: #64748b; font-size: 0.82rem; }
    .error { color: #f87171; font-size: 0.82rem; }
  </style>
</head>
<body>
<header>
  <h1>⚡ Gateway Admin</h1>
  <div class="tabs">
    <button class="tab active" onclick="switchTab('exec')">Executive</button>
    <button class="tab" onclick="switchTab('ops')">Ops</button>
  </div>
  <button class="refresh-btn" onclick="loadCurrentTab()">↻ Refresh</button>
  <span id="last-updated" style="font-size:0.72rem;color:#64748b;"></span>
</header>
<main>
  <!-- Executive View -->
  <div id="exec-view" class="view active">
    <div class="cards" id="summary-cards"></div>
    <div class="charts-row">
      <div class="section">
        <h2>Tool Flow Patterns</h2>
        <div id="sankey-container"><p class="muted">Loading…</p></div>
      </div>
      <div class="section">
        <h2>User Adoption</h2>
        <div id="adoption-chart"><p class="muted">Loading…</p></div>
      </div>
    </div>
    <div class="section">
      <h2>Tool Health</h2>
      <table id="tool-table">
        <thead>
          <tr>
            <th onclick="sortTable('name')">Tool ▾</th>
            <th onclick="sortTable('call_count')">Calls</th>
            <th onclick="sortTable('error_count')">Errors</th>
            <th onclick="sortTable('error_rate')">Error Rate</th>
            <th onclick="sortTable('avg_duration_ms')">Avg Latency</th>
            <th onclick="sortTable('max_duration_ms')">Max Latency</th>
            <th onclick="sortTable('last_called')">Last Called</th>
          </tr>
        </thead>
        <tbody id="tool-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Ops View -->
  <div id="ops-view" class="view">
    <div class="ops-grid">
      <div class="section">
        <h2>Users</h2>
        <div id="user-list"></div>
        <div class="add-user-form">
          <input id="new-user-id" type="text" placeholder="user@company.com" />
          <button class="btn btn-primary" onclick="createUser()">+ Add User</button>
        </div>
        <div class="key-reveal" id="key-reveal"></div>
      </div>
      <div class="section">
        <div class="perm-header">
          <h2 id="perm-title">Tool Permissions</h2>
        </div>
        <div id="perm-content"><p class="perm-placeholder">Select a user to manage permissions.</p></div>
      </div>
    </div>
  </div>
</main>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-sankey@0.12.3/dist/d3-sankey.min.js"></script>
<script>
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const api = path => `/admin/api${path}?token=${TOKEN}`;

let _toolData = [];
let _sortKey = 'call_count';
let _sortDir = -1;

// ─── Tab switching ───────────────────────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((el, i) => {
    el.classList.toggle('active', ['exec','ops'][i] === name);
  });
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.getElementById(name + '-view').classList.add('active');
  if (name === 'exec') loadExec();
  else loadOps();
}

function loadCurrentTab() {
  const activeTab = document.querySelector('.tab.active');
  if (activeTab && activeTab.textContent.trim() === 'Ops') loadOps();
  else loadExec();
}

// ─── Executive view ──────────────────────────────────────────────────────────

async function loadExec() {
  const [statsResp, sessionResp] = await Promise.all([
    fetch(api('/stats')),
    fetch(api('/sessions')),
  ]);
  const stats = await statsResp.json();
  const sessions = await sessionResp.json();
  _toolData = stats.tools || [];
  renderCards(stats);
  renderToolTable();
  renderSankey(sessions.sankey);
  renderAdoption(sessions.user_breakdown || {});
  document.getElementById('last-updated').textContent =
    'Updated ' + new Date().toLocaleTimeString();
}

function renderCards(stats) {
  const s = stats.summary || {};
  const highErr = (s.high_error_rate || []).length;
  const avgLatency = _toolData.length
    ? Math.round(_toolData.reduce((a, t) => a + t.avg_duration_ms, 0) / _toolData.length)
    : 0;
  const cards = [
    { label: 'Total Calls', value: (s.total_calls || 0).toLocaleString(), cls: '' },
    { label: 'Tools Tracked', value: s.total_tools_seen || 0, cls: '' },
    { label: 'High Error Rate', value: highErr, cls: highErr > 0 ? 'red' : 'green' },
    { label: 'Avg Latency (ms)', value: avgLatency, cls: avgLatency > 2000 ? 'yellow' : '' },
  ];
  document.getElementById('summary-cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="label">${c.label}</div><div class="value ${c.cls}">${c.value}</div></div>`
  ).join('');
}

function renderToolTable() {
  const sorted = [..._toolData].sort((a, b) => {
    const av = a[_sortKey], bv = b[_sortKey];
    if (typeof av === 'string') return _sortDir * av.localeCompare(bv);
    return _sortDir * ((parseFloat(av) || 0) - (parseFloat(bv) || 0));
  });
  document.getElementById('tool-tbody').innerHTML = sorted.map(t => {
    const rate = parseFloat(t.error_rate) || 0;
    const badgeCls = rate >= 5 ? 'red' : rate >= 1 ? 'yellow' : 'green';
    return `<tr>
      <td style="font-family:monospace;font-size:0.78rem">${t.name}</td>
      <td>${t.call_count.toLocaleString()}</td>
      <td>${t.error_count}</td>
      <td><span class="badge ${badgeCls}">${t.error_rate}</span></td>
      <td>${t.avg_duration_ms} ms</td>
      <td>${t.max_duration_ms} ms</td>
      <td class="muted">${t.last_called || '—'}</td>
    </tr>`;
  }).join('');
}

function sortTable(key) {
  if (_sortKey === key) _sortDir *= -1;
  else { _sortKey = key; _sortDir = -1; }
  renderToolTable();
}

function renderSankey(data) {
  const el = document.getElementById('sankey-container');
  if (!data || !data.nodes || data.nodes.length < 2) {
    el.innerHTML = '<p class="muted">Not enough flow data yet — keep using the gateway!</p>';
    return;
  }
  el.innerHTML = '';
  const W = el.clientWidth || 500, H = 320;
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H);
  const sankey = d3.sankey()
    .nodeId(d => d.id)
    .nodeWidth(14)
    .nodePadding(12)
    .extent([[1, 1], [W - 1, H - 6]]);

  const graph = sankey({
    nodes: data.nodes.map(d => ({...d})),
    links: data.links.map(d => ({...d})),
  });

  svg.append('g').selectAll('path')
    .data(graph.links).join('path')
    .attr('d', d3.sankeyLinkHorizontal())
    .attr('stroke', '#2563eb')
    .attr('stroke-width', d => Math.max(1, d.width))
    .attr('fill', 'none')
    .attr('opacity', 0.35);

  svg.append('g').selectAll('rect')
    .data(graph.nodes).join('rect')
    .attr('x', d => d.x0).attr('y', d => d.y0)
    .attr('width', d => d.x1 - d.x0)
    .attr('height', d => Math.max(1, d.y1 - d.y0))
    .attr('fill', '#3b82f6').attr('rx', 2);

  svg.append('g').selectAll('text')
    .data(graph.nodes).join('text')
    .attr('x', d => d.x0 < W / 2 ? d.x1 + 6 : d.x0 - 6)
    .attr('y', d => (d.y0 + d.y1) / 2)
    .attr('dy', '0.35em')
    .attr('text-anchor', d => d.x0 < W / 2 ? 'start' : 'end')
    .attr('font-size', '10px')
    .text(d => d.name.length > 22 ? d.name.slice(0, 20) + '…' : d.name);
}

function renderAdoption(breakdown) {
  const entries = Object.entries(breakdown)
    .sort((a, b) => b[1] - a[1]).slice(0, 10);
  const el = document.getElementById('adoption-chart');
  if (!entries.length) { el.innerHTML = '<p class="muted">No usage data yet.</p>'; return; }
  const max = entries[0][1];
  el.innerHTML = `<div class="bar-chart">${entries.map(([uid, count]) =>
    `<div class="bar-row">
      <div class="bar-label">${uid}</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${Math.max(4, (count/max)*100)}%">${count}</div>
      </div>
    </div>`).join('')}</div>`;
}

// ─── Ops view ────────────────────────────────────────────────────────────────

let _allTools = [];
let _selectedUser = null;

async function loadOps() {
  const [usersResp, statsResp] = await Promise.all([
    fetch(api('/users')),
    fetch(api('/stats')),
  ]);
  const users = await usersResp.json();
  const stats = await statsResp.json();
  _allTools = (stats.tools || []).map(t => t.name).sort();
  renderUserList(users);
  if (_selectedUser) loadPermissions(_selectedUser);
}

function renderUserList(users) {
  const el = document.getElementById('user-list');
  if (!users.length) { el.innerHTML = '<p class="muted">No users yet.</p>'; return; }
  el.innerHTML = `<table>
    <thead><tr><th>User</th><th>Key</th><th>Calls</th><th>Last Active</th><th></th></tr></thead>
    <tbody>${users.map(u => `
      <tr style="cursor:pointer" onclick="selectUser('${escHtml(u.user_id)}')">
        <td>${escHtml(u.user_id)}</td>
        <td style="font-family:monospace;font-size:0.72rem;color:#64748b">${u.key.slice(0, 12)}…</td>
        <td>${u.call_count}</td>
        <td class="muted">${u.last_active || '—'}</td>
        <td><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteUser('${escHtml(u.user_id)}')">Revoke</button></td>
      </tr>`).join('')}
    </tbody>
  </table>`;
}

async function selectUser(userId) {
  _selectedUser = userId;
  document.getElementById('perm-title').textContent =
    'Permissions — ' + userId;
  await loadPermissions(userId);
}

async function loadPermissions(userId) {
  const resp = await fetch(api(`/permissions/${encodeURIComponent(userId)}`));
  const data = await resp.json();
  const explicit = {};
  (data.permissions || []).forEach(p => { explicit[p.tool_name] = p.enabled; });

  const el = document.getElementById('perm-content');
  if (!_allTools.length) {
    el.innerHTML = '<p class="perm-placeholder">No tools tracked yet.</p>';
    return;
  }
  el.innerHTML = `<div class="perm-grid">${_allTools.map(tool => {
    const enabled = tool in explicit ? explicit[tool] : true;
    return `<div class="perm-row">
      <span style="font-family:monospace;font-size:0.78rem">${escHtml(tool)}</span>
      <label class="toggle">
        <input type="checkbox" ${enabled ? 'checked' : ''}
          onchange="setPermission('${escHtml(userId)}','${escHtml(tool)}',this.checked)">
        <span class="toggle-slider"></span>
      </label>
    </div>`;
  }).join('')}</div>`;
}

async function setPermission(userId, toolName, enabled) {
  await fetch(api(`/permissions/${encodeURIComponent(userId)}/${encodeURIComponent(toolName)}`), {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled}),
  });
}

async function createUser() {
  const userId = document.getElementById('new-user-id').value.trim();
  if (!userId) return;
  const resp = await fetch(api('/users'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user_id: userId}),
  });
  const data = await resp.json();
  if (resp.ok) {
    document.getElementById('new-user-id').value = '';
    const reveal = document.getElementById('key-reveal');
    reveal.textContent = '🔑 ' + data.key + ' (copy now — shown once)';
    reveal.style.display = 'block';
    setTimeout(() => reveal.style.display = 'none', 30000);
    loadOps();
  }
}

async function deleteUser(userId) {
  if (!confirm(`Revoke all access for ${userId}?`)) return;
  await fetch(api(`/users/${encodeURIComponent(userId)}`), {method: 'DELETE'});
  if (_selectedUser === userId) {
    _selectedUser = null;
    document.getElementById('perm-title').textContent = 'Tool Permissions';
    document.getElementById('perm-content').innerHTML =
      '<p class="perm-placeholder">Select a user to manage permissions.</p>';
  }
  loadOps();
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Init ────────────────────────────────────────────────────────────────────
loadExec();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the dashboard test now passes**

```bash
pytest remote-gateway/tests/test_admin_api.py::test_dashboard_allowed_with_token -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add admin dashboard HTML with executive and ops views"
```

---

## Task 8: Mount the Admin App in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Import the admin app factory at the top of the combined server block**

Locate the `if __name__ == "__main__":` block. At the top of the `if transport in ("sse", "combined"):` branch, add the import:

```python
    if transport in ("sse", "combined"):
        import uvicorn
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route

        from admin_api import create_admin_app as _create_admin_app
```

- [ ] **Step 2: Mount the admin sub-app in the combined Starlette routes**

Find where `_combined` is built. Add the admin mount:

```python
        async def health_check_handler(request):
            return JSONResponse({"status": "ok", "transport": transport})

        _combined = Starlette(
            routes=[
                Mount("/admin", app=_create_admin_app(_telemetry)),
                *_sse.routes,
                *_http.routes,
                Route("/health", health_check_handler),
                Route("/", health_check_handler),
            ],
            lifespan=combined_lifespan,
        )
```

Note: `/admin` must be listed **before** the wildcard SSE/HTTP routes so Starlette matches it first.

- [ ] **Step 3: Start the gateway and manually verify the admin page loads**

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

Open in browser: `http://localhost:8000/admin?token=inform-admin-2026`

Expected: Dashboard loads with two tabs. Executive tab shows cards and an empty tool table. Ops tab shows empty user list and an "Add User" form.

- [ ] **Step 4: Create a test user and verify permission toggle works**

In the Ops tab, enter `test@example.com` and click Add User. Copy the displayed key. Click on the new user row — the permission grid should appear. Toggle any tool off and on.

From a separate terminal, verify the permission is persisted:

```bash
curl "http://localhost:8000/admin/api/permissions/test%40example.com?token=inform-admin-2026"
```

Expected: JSON response with the toggled tool shown as `"enabled": false`.

- [ ] **Step 5: Run the full test suite**

```bash
pytest remote-gateway/tests/ -v --ignore=remote-gateway/tests/test_attio_tools.py
```

Expected: All tests PASS (attio tests require live credentials — excluded).

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat: mount admin UI at /admin in combined transport server"
```

---

## Environment Variables Reference

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_TOKEN` | `inform-admin-2026` | Magic link token — change for production |

**Admin URL pattern:** `https://<your-gateway-host>/admin?token=<ADMIN_TOKEN>`

The admin UI is only available in `sse` and `combined` transport modes. It is not reachable in `stdio` mode.
