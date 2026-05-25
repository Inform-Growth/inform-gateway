# Admin-Gated Permission-Management MCP Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four admin-gated MCP tools (`list_users`, `set_user_role`, `set_tool_permission`, `set_skill_permission`) plus an `is_admin` enforcement check, an `api_keys.role` column with `BOOTSTRAP_ADMIN_USER_IDS` env-var seeding, an admin UI role-select column, and a `PUT /api/users/{user_id}/role` HTTP route. Closes #29 and resolves the access-grant half of #27 plus #25.

**Architecture:** Three layers: storage (`telemetry.py` — `role` column + helpers), MCP tool layer (new `tools/admin.py`), and HTTP/UI (new route in `admin_api.py` + role-select cell in `OperatorsTable.tsx`). A single `_require_admin()` chokepoint in `mcp_server.py` resolves the caller via the existing `_get_call_ids()` path and raises `PermissionError` for non-admins.

**Tech Stack:** Python 3.11+, FastMCP, Starlette, PostgreSQL via `psycopg2.extras`, pytest + pytest-postgresql, React + TypeScript + Vite + Tailwind + shadcn (admin UI).

**Spec:** `docs/superpowers/specs/2026-05-24-admin-permission-tools-design.md`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `remote-gateway/core/telemetry.py` | Modify | Schema `role` column; helpers `get_role`, `is_admin`, `set_user_role`, `bootstrap_admin_roles`; `list_users` returns `role`; `add_api_key` inherits existing role; add new tools to `INTENT_NEVER_REQUIRED`. |
| `remote-gateway/core/mcp_server.py` | Modify | `_require_admin()` helper; startup `bootstrap_admin_roles()` call. |
| `remote-gateway/core/admin_api.py` | Modify | New `PUT /api/users/{user_id}/role` route. |
| `remote-gateway/tools/admin.py` | Create | The four new MCP tools. |
| `remote-gateway/tools/meta.py` | Modify | Retrofit `create_user` with `_require_admin()`. |
| `remote-gateway/mcp_server.py` (registration) | Modify | Call `admin.register(mcp, telemetry)` at startup. |
| `remote-gateway/tests/test_telemetry_roles.py` | Create | Schema + helper tests. |
| `remote-gateway/tests/test_admin_tools.py` | Create | MCP tool admin-gate + bulk semantics tests. |
| `remote-gateway/tests/test_admin_api.py` | Modify | Tests for `PUT /api/users/{user_id}/role` and `GET /api/users` role field. |
| `remote-gateway/tests/test_init_gate.py` | Modify | Add 4 new tools to the allowlist assertion. |
| `remote-gateway/admin-ui/src/hooks/useOperators.ts` | Modify | Add `role` to `Operator` type + `useSetUserRole` mutation. |
| `remote-gateway/admin-ui/src/routes/operators/OperatorsTable.tsx` | Modify | Role-select column. |
| `CLAUDE.md` + `remote-gateway/CLAUDE.md` | Modify | Doc the new env var, tools, and column. |

---

## Task 1: Add `role` column + read helpers

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (schema, `INTENT_NEVER_REQUIRED` area, new helpers)
- Create: `remote-gateway/tests/test_telemetry_roles.py`

- [ ] **Step 1: Write the failing test for read helpers**

Create `remote-gateway/tests/test_telemetry_roles.py`:

```python
"""Tests for the api_keys.role column and read helpers (get_role, is_admin)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def test_role_column_defaults_to_user(store):
    """New api_keys row gets role='user' from the column default."""
    store.add_api_key("alice@example.com", "sk-alice")
    assert store.get_role("alice@example.com") == "user"
    assert store.is_admin("alice@example.com") is False


def test_get_role_returns_none_for_unknown_user(store):
    assert store.get_role("nobody@example.com") is None
    assert store.is_admin("nobody@example.com") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: FAIL with `AttributeError: 'TelemetryStore' object has no attribute 'get_role'`.

- [ ] **Step 3: Add schema + helpers**

In `remote-gateway/core/telemetry.py`, near the top (just after `INTENT_NEVER_REQUIRED`) add the role constants:

```python
ROLE_USER = "user"
ROLE_ADMIN = "admin"
VALID_ROLES: frozenset[str] = frozenset({ROLE_USER, ROLE_ADMIN})
"""Roles accepted by set_user_role. Custom roles are out of scope for now."""
```

Then in `_SCHEMA_STATEMENTS` (the list of `CREATE TABLE` statements), append the idempotent ALTER as a separate statement:

```python
"""
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'
""",
```

Then add `get_role` and `is_admin` to the `TelemetryStore` class (near `lookup_user`):

```python
def get_role(self, user_id: str) -> str | None:
    """Return the role of the user, or None if user_id has no api_keys row."""
    if not self._enabled:
        return None
    with self._cursor() as cur:
        cur.execute(
            "SELECT role FROM api_keys WHERE user_id = %s LIMIT 1", (user_id,)
        )
        row = cur.fetchone()
    return row["role"] if row else None

def is_admin(self, user_id: str) -> bool:
    """Single chokepoint for admin checks. Currently: role == 'admin'.

    Future role-and-permission-sets work can swap this implementation
    without touching the call sites in tools/admin.py or tools/meta.py.
    """
    return self.get_role(user_id) == ROLE_ADMIN
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_roles.py
git commit -m "feat(telemetry): add role column on api_keys + get_role/is_admin helpers"
```

---

## Task 2: Add `set_user_role` with multi-key invariant + validation

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Modify: `remote-gateway/tests/test_telemetry_roles.py`

- [ ] **Step 1: Write failing tests**

Append to `remote-gateway/tests/test_telemetry_roles.py`:

```python
import pytest


def test_set_user_role_roundtrip(store):
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    assert store.get_role("alice@example.com") == "admin"
    assert store.is_admin("alice@example.com") is True
    store.set_user_role("alice@example.com", "user")
    assert store.is_admin("alice@example.com") is False


def test_set_user_role_rejects_invalid_role(store):
    store.add_api_key("alice@example.com", "sk-alice")
    with pytest.raises(ValueError):
        store.set_user_role("alice@example.com", "superadmin")


def test_set_user_role_updates_all_keys_for_user(store):
    """Multi-key invariant: set_user_role moves every row for a user_id."""
    store.add_api_key("alice@example.com", "sk-alice-1")
    store.add_api_key("alice@example.com", "sk-alice-2")
    store.set_user_role("alice@example.com", "admin")
    with store._cursor() as cur:
        cur.execute(
            "SELECT role FROM api_keys WHERE user_id = %s ORDER BY key",
            ("alice@example.com",),
        )
        roles = [r["role"] for r in cur.fetchall()]
    assert roles == ["admin", "admin"]


def test_set_user_role_unknown_user_is_noop(store):
    """No api_keys row -> no error, no effect."""
    store.set_user_role("nobody@example.com", "admin")
    assert store.get_role("nobody@example.com") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: 4 new FAILs (`set_user_role` not defined).

- [ ] **Step 3: Implement `set_user_role`**

In `remote-gateway/core/telemetry.py`, add to the `TelemetryStore` class (just below `is_admin`):

```python
def set_user_role(self, user_id: str, role: str) -> None:
    """Set the role for every api_keys row matching user_id.

    Args:
        user_id: The user to update.
        role: Must be a member of VALID_ROLES.

    Raises:
        ValueError: If role is not in VALID_ROLES.

    No-op if user_id has no rows in api_keys.
    """
    if role not in VALID_ROLES:
        raise ValueError(
            f"role must be one of {sorted(VALID_ROLES)}, got {role!r}"
        )
    if not self._enabled:
        return
    with self._cursor() as cur:
        cur.execute(
            "UPDATE api_keys SET role = %s WHERE user_id = %s", (role, user_id)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: 6 PASS total (2 from Task 1 + 4 from Task 2).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_roles.py
git commit -m "feat(telemetry): add set_user_role with validation and multi-key invariant"
```

---

## Task 3: `add_api_key` inherits the existing role for a user

**Files:**
- Modify: `remote-gateway/core/telemetry.py:321-345` (the `add_api_key` method)
- Modify: `remote-gateway/tests/test_telemetry_roles.py`

- [ ] **Step 1: Write failing test**

Append to `remote-gateway/tests/test_telemetry_roles.py`:

```python
def test_add_api_key_inherits_admin_role(store):
    """Second key for an existing admin user stays admin."""
    store.add_api_key("alice@example.com", "sk-alice-1")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("alice@example.com", "sk-alice-2")
    with store._cursor() as cur:
        cur.execute(
            "SELECT role FROM api_keys WHERE key = %s", ("sk-alice-2",)
        )
        row = cur.fetchone()
    assert row["role"] == "admin"


def test_add_api_key_defaults_new_user_to_user_role(store):
    store.add_api_key("bob@example.com", "sk-bob")
    assert store.get_role("bob@example.com") == "user"
```

- [ ] **Step 2: Run tests to verify the inheritance test fails**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py::test_add_api_key_inherits_admin_role -v`
Expected: FAIL — the new key gets role `'user'` (column default) instead of inheriting.

- [ ] **Step 3: Update `add_api_key` to inherit role**

In `remote-gateway/core/telemetry.py`, replace the INSERT in `add_api_key` (around line 339-344) with a SELECT-based INSERT that inherits any existing role for the user:

```python
        if not self._enabled:
            return key
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_keys (key, user_id, org_id, created_at, role)
                VALUES (
                    %s, %s, %s, %s,
                    COALESCE(
                        (SELECT role FROM api_keys WHERE user_id = %s LIMIT 1),
                        'user'
                    )
                )
                """,
                (key, user_id, org_id, time.time(), user_id),
            )
        return key
```

- [ ] **Step 4: Run tests**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: 8 PASS total.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_roles.py
git commit -m "feat(telemetry): add_api_key inherits existing role to preserve per-user invariant"
```

---

## Task 4: `bootstrap_admin_roles` for startup env-var seeding

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Modify: `remote-gateway/tests/test_telemetry_roles.py`

- [ ] **Step 1: Write failing tests**

Append to `remote-gateway/tests/test_telemetry_roles.py`:

```python
def test_bootstrap_admin_roles_promotes_known_users(store):
    store.add_api_key("alice@example.com", "sk-alice")
    store.add_api_key("bob@example.com", "sk-bob")
    result = store.bootstrap_admin_roles(["alice@example.com", "bob@example.com"])
    assert sorted(result["promoted"]) == ["alice@example.com", "bob@example.com"]
    assert result["skipped_unknown"] == []
    assert store.is_admin("alice@example.com") is True
    assert store.is_admin("bob@example.com") is True


def test_bootstrap_admin_roles_skips_unknown_users(store):
    store.add_api_key("alice@example.com", "sk-alice")
    result = store.bootstrap_admin_roles(["alice@example.com", "ghost@example.com"])
    assert result["promoted"] == ["alice@example.com"]
    assert result["skipped_unknown"] == ["ghost@example.com"]


def test_bootstrap_admin_roles_never_demotes(store):
    """An admin not listed in the bootstrap call stays admin."""
    store.add_api_key("alice@example.com", "sk-alice")
    store.add_api_key("bob@example.com", "sk-bob")
    store.set_user_role("alice@example.com", "admin")
    store.bootstrap_admin_roles(["bob@example.com"])
    assert store.is_admin("alice@example.com") is True
    assert store.is_admin("bob@example.com") is True


def test_bootstrap_admin_roles_empty_list_is_noop(store):
    store.add_api_key("alice@example.com", "sk-alice")
    result = store.bootstrap_admin_roles([])
    assert result == {"promoted": [], "skipped_unknown": []}
    assert store.is_admin("alice@example.com") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: 4 new FAILs (`bootstrap_admin_roles` not defined).

- [ ] **Step 3: Implement `bootstrap_admin_roles`**

In `remote-gateway/core/telemetry.py`, add to `TelemetryStore` (just below `set_user_role`):

```python
def bootstrap_admin_roles(self, user_ids: list[str]) -> dict:
    """Promote each listed user_id to ROLE_ADMIN if a matching api_keys row exists.

    Never demotes anyone. Unknown user_ids are recorded and skipped.

    Args:
        user_ids: List of user identifiers to promote.

    Returns:
        Dict with 'promoted' (list[str]) and 'skipped_unknown' (list[str]).
    """
    if not user_ids or not self._enabled:
        return {"promoted": [], "skipped_unknown": list(user_ids or [])}
    promoted: list[str] = []
    skipped: list[str] = []
    with self._cursor() as cur:
        for uid in user_ids:
            cur.execute(
                "SELECT 1 FROM api_keys WHERE user_id = %s LIMIT 1", (uid,)
            )
            if cur.fetchone() is None:
                skipped.append(uid)
                continue
            cur.execute(
                "UPDATE api_keys SET role = %s WHERE user_id = %s",
                (ROLE_ADMIN, uid),
            )
            promoted.append(uid)
    return {"promoted": promoted, "skipped_unknown": skipped}
```

- [ ] **Step 4: Run tests**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: 12 PASS total.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_roles.py
git commit -m "feat(telemetry): bootstrap_admin_roles for startup env-var seeding"
```

---

## Task 5: `list_users` returns the `role` field

**Files:**
- Modify: `remote-gateway/core/telemetry.py:361-411` (the `list_users` method)
- Modify: `remote-gateway/tests/test_telemetry_roles.py`

- [ ] **Step 1: Write failing test**

Append to `remote-gateway/tests/test_telemetry_roles.py`:

```python
def test_list_users_includes_role(store):
    store.add_api_key("alice@example.com", "sk-alice")
    store.add_api_key("bob@example.com", "sk-bob")
    store.set_user_role("alice@example.com", "admin")
    users = {u["user_id"]: u for u in store.list_users()}
    assert users["alice@example.com"]["role"] == "admin"
    assert users["bob@example.com"]["role"] == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py::test_list_users_includes_role -v`
Expected: FAIL — `KeyError: 'role'`.

- [ ] **Step 3: Update `list_users`**

In `remote-gateway/core/telemetry.py`, modify the SELECT in `list_users` to include `ak.role`, the GROUP BY to include `ak.role`, and the returned dict to expose it. The exact change to the SELECT:

```python
                cur.execute(
                    """
                    SELECT
                        ak.user_id,
                        ak.key,
                        ak.role,
                        ak.created_at,
                        COUNT(tc.id)      AS call_count,
                        MAX(tc.called_at) AS last_active
                    FROM api_keys ak
                    LEFT JOIN tool_calls tc ON ak.user_id = tc.user_id
                    GROUP BY ak.user_id, ak.key, ak.role
                    ORDER BY ak.created_at DESC
                    """
                )
```

And add `"role": row["role"]` to each entry in the returned list comprehension at the bottom of the method.

- [ ] **Step 4: Run test**

Run: `pytest remote-gateway/tests/test_telemetry_roles.py -v`
Expected: 13 PASS total. Also run `pytest remote-gateway/tests/test_admin_api.py -v` to confirm no existing user-list test regressed.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_roles.py
git commit -m "feat(telemetry): list_users returns role field"
```

---

## Task 6: `_require_admin` helper in `mcp_server.py`

**Files:**
- Modify: `remote-gateway/core/mcp_server.py` (add helper near `_get_call_ids`, ~line 520)
- Create: `remote-gateway/tests/test_admin_tools.py`

- [ ] **Step 1: Write failing test**

Create `remote-gateway/tests/test_admin_tools.py`:

```python
"""Tests for the admin-gated MCP tools and the _require_admin chokepoint."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import mcp_server as server  # noqa: E402


def test_require_admin_allows_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        assert server._require_admin() == "alice@example.com"
    finally:
        server._current_user.reset(token)


def test_require_admin_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError, match="admin role required"):
            server._require_admin()
    finally:
        server._current_user.reset(token)


def test_require_admin_blocks_unauthenticated(monkeypatch, store):
    monkeypatch.setattr(server, "_telemetry", store)
    token = server._current_user.set(None)
    try:
        with pytest.raises(PermissionError, match="admin role required"):
            server._require_admin()
    finally:
        server._current_user.reset(token)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v`
Expected: FAIL with `AttributeError: module 'mcp_server' has no attribute '_require_admin'`.

- [ ] **Step 3: Add `_require_admin`**

In `remote-gateway/core/mcp_server.py`, just after `_get_call_ids` (around line 540) add:

```python
def _require_admin() -> str:
    """Resolve the calling user_id and require role='admin'.

    Resolution path: live request context first (HTTP transports), then
    the _current_user ContextVar (stdio + tests).

    Returns:
        The caller's user_id.

    Raises:
        PermissionError: If no caller is resolved or the caller is not an admin.
    """
    user_id = _resolve_user_from_request_ctx() or _current_user.get()
    if user_id is None or not _telemetry.is_admin(user_id):
        raise PermissionError("admin role required")
    return user_id
```

- [ ] **Step 4: Run tests**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_admin_tools.py
git commit -m "feat(mcp_server): _require_admin chokepoint for admin-gated tools"
```

---

## Task 7: Create `tools/admin.py` with the four new MCP tools

**Files:**
- Create: `remote-gateway/tools/admin.py`
- Modify: `remote-gateway/tests/test_admin_tools.py`

- [ ] **Step 1: Write failing tests for `list_users` and `set_user_role`**

Append to `remote-gateway/tests/test_admin_tools.py`:

```python
from tools.admin import (  # noqa: E402
    make_list_users,
    make_set_user_role,
    make_set_tool_permission,
    make_set_skill_permission,
)


# ---- list_users ----

def test_list_users_returns_users_with_role(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_list_users(store)()
    finally:
        server._current_user.reset(token)
    user_ids = {u["user_id"] for u in result["users"]}
    assert user_ids == {"alice@example.com", "bob@example.com"}
    roles = {u["user_id"]: u["role"] for u in result["users"]}
    assert roles == {"alice@example.com": "admin", "bob@example.com": "user"}


def test_list_users_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_list_users(store)()
    finally:
        server._current_user.reset(token)


# ---- set_user_role ----

def test_set_user_role_promotes(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_user_role(store)("bob@example.com", "admin")
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "role": "admin"}
    assert store.is_admin("bob@example.com") is True


def test_set_user_role_rejects_invalid_role(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        with pytest.raises(ValueError):
            make_set_user_role(store)("alice@example.com", "superadmin")
    finally:
        server._current_user.reset(token)


def test_set_user_role_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_set_user_role(store)("bob@example.com", "admin")
    finally:
        server._current_user.reset(token)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v`
Expected: ImportError — `tools.admin` doesn't exist.

- [ ] **Step 3: Create `tools/admin.py` with `list_users` and `set_user_role`**

Create `remote-gateway/tools/admin.py`:

```python
"""Admin-gated MCP tools — user listing, role management, bulk permission grants.

All tools call _require_admin() before touching telemetry. The check resolves
the caller via mcp_server._resolve_user_from_request_ctx() with a ContextVar
fallback. Non-admin callers receive PermissionError; the telemetry patch in
mcp_server.py records the failure with error_type="PermissionError".
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _admin_check() -> str:
    """Lazy import to avoid a circular import with mcp_server at module load."""
    from mcp_server import _require_admin

    return _require_admin()


def make_list_users(telemetry: Any) -> Callable[[], dict]:
    def list_users() -> dict:
        """List all gateway users with their role and activity. Admin only.

        Returns:
            Dict with 'users': list of {user_id, role, created_at, call_count, last_active}.
        """
        _admin_check()
        return {"users": telemetry.list_users()}

    return list_users


def make_set_user_role(telemetry: Any) -> Callable[[str, str], dict]:
    def set_user_role(user_id: str, role: str) -> dict:
        """Set a user's role. Admin only.

        Args:
            user_id: The user whose role to update.
            role: 'user' or 'admin'. Other values are rejected.

        Returns:
            Dict with user_id and role.
        """
        _admin_check()
        telemetry.set_user_role(user_id, role)
        return {"user_id": user_id, "role": role}

    return set_user_role


def make_set_tool_permission(
    telemetry: Any,
) -> Callable[[str, list[dict]], dict]:
    def set_tool_permission(user_id: str, permissions: list[dict]) -> dict:
        """Bulk grant/revoke per-tool access for a user. Admin only.

        Args:
            user_id: The user whose tool allowlist to modify.
            permissions: List of {"tool_name": str, "enabled": bool}.
                tool_name uses the gateway-exposed name (e.g.
                "apollo__enrich_organization"). enabled=False denies.

        Returns:
            Dict with user_id and the count of upserts applied.
        """
        _admin_check()
        applied = 0
        for entry in permissions:
            telemetry.set_tool_permission(
                user_id, entry["tool_name"], bool(entry["enabled"])
            )
            applied += 1
        return {"user_id": user_id, "applied": applied}

    return set_tool_permission


def make_set_skill_permission(
    telemetry: Any,
) -> Callable[[str, list[dict]], dict]:
    def set_skill_permission(user_id: str, permissions: list[dict]) -> dict:
        """Bulk grant/revoke per-skill access for a user. Admin only.

        Args:
            user_id: The user whose skill allowlist to modify.
            permissions: List of {"skill_name": str, "enabled": bool}.

        Returns:
            Dict with user_id and the count of upserts applied.
        """
        _admin_check()
        applied = 0
        for entry in permissions:
            telemetry.set_skill_permission(
                user_id, entry["skill_name"], bool(entry["enabled"])
            )
            applied += 1
        return {"user_id": user_id, "applied": applied}

    return set_skill_permission


def register(mcp: Any, telemetry: Any) -> None:
    """Register the four admin MCP tools on the given FastMCP server instance."""
    mcp.tool()(make_list_users(telemetry))
    mcp.tool()(make_set_user_role(telemetry))
    mcp.tool()(make_set_tool_permission(telemetry))
    mcp.tool()(make_set_skill_permission(telemetry))
```

- [ ] **Step 4: Run tests**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v`
Expected: 5 new tests PASS (8 total in this file so far).

- [ ] **Step 5: Add bulk-permission tests**

Append to `remote-gateway/tests/test_admin_tools.py`:

```python
# ---- set_tool_permission ----

def test_set_tool_permission_bulk_applies_all(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_tool_permission(store)(
            "bob@example.com",
            [
                {"tool_name": "apollo__enrich_person", "enabled": True},
                {"tool_name": "buffer__create_post", "enabled": False},
                {"tool_name": "exa__web_search_exa", "enabled": True},
            ],
        )
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "applied": 3}
    perms = {
        row["tool_name"]: row["enabled"]
        for row in store.get_tool_permissions("bob@example.com")
    }
    assert perms == {
        "apollo__enrich_person": 1,
        "buffer__create_post": 0,
        "exa__web_search_exa": 1,
    }


def test_set_tool_permission_empty_list_returns_zero(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_tool_permission(store)("bob@example.com", [])
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "applied": 0}


def test_set_tool_permission_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_set_tool_permission(store)(
                "bob@example.com",
                [{"tool_name": "anything", "enabled": True}],
            )
    finally:
        server._current_user.reset(token)


# ---- set_skill_permission ----

def test_set_skill_permission_bulk_applies_all(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_set_skill_permission(store)(
            "bob@example.com",
            [
                {"skill_name": "role_signal_scout", "enabled": True},
                {"skill_name": "schedule_linkedin_post", "enabled": False},
            ],
        )
    finally:
        server._current_user.reset(token)
    assert result == {"user_id": "bob@example.com", "applied": 2}
    perms = {
        row["skill_name"]: row["enabled"]
        for row in store.get_skill_permissions("bob@example.com")
    }
    assert perms == {"role_signal_scout": 1, "schedule_linkedin_post": 0}


def test_set_skill_permission_blocks_non_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_set_skill_permission(store)(
                "bob@example.com",
                [{"skill_name": "anything", "enabled": True}],
            )
    finally:
        server._current_user.reset(token)
```

- [ ] **Step 6: Run all admin tool tests**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v`
Expected: 13 PASS total.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/tools/admin.py remote-gateway/tests/test_admin_tools.py
git commit -m "feat(tools): admin.py with list_users, set_user_role, bulk permission setters"
```

---

## Task 8: Register `tools/admin.py` on the FastMCP server + bootstrap on startup

**Files:**
- Modify: `remote-gateway/core/mcp_server.py` (the function that builds + returns the FastMCP instance — search for `meta.register` or similar to find the right spot)

- [ ] **Step 1: Find the registration site**

Run: `grep -n "tools\\..*register\\|\\.register(mcp" remote-gateway/core/mcp_server.py`
Expected: lines where existing tool modules are registered (e.g., `meta.register(mcp, ...)`).

- [ ] **Step 2: Add the import and registration call**

Near the other `from tools import …` / `from tools._core import …` imports, add:

```python
from tools import admin as admin_tools  # noqa: E402
```

At the registration site (alongside `meta.register(...)`, `friction.register(...)`, etc.), add:

```python
admin_tools.register(mcp, _telemetry)
```

- [ ] **Step 3: Add startup bootstrap call**

Locate the startup path (typically around `if __name__ == "__main__":` or `def run()`). After `_telemetry` is constructed and the schema is initialized, before `mcp.run(...)`, add:

```python
admin_ids_raw = os.environ.get("BOOTSTRAP_ADMIN_USER_IDS", "")
if admin_ids_raw.strip():
    user_ids = [s.strip() for s in admin_ids_raw.split(",") if s.strip()]
    result = _telemetry.bootstrap_admin_roles(user_ids)
    print(
        f"[admin-bootstrap] promoted {len(result['promoted'])} users, "
        f"skipped {len(result['skipped_unknown'])} unknown: "
        f"promoted={result['promoted']} skipped={result['skipped_unknown']}",
        flush=True,
    )
```

- [ ] **Step 4: Smoke-test via test suite**

Run: `pytest remote-gateway/tests/test_admin_tools.py remote-gateway/tests/test_telemetry_roles.py -v`
Expected: all PASS, no import errors.

Also run: `python -c "from core.mcp_server import _telemetry; print(_telemetry.is_admin('nobody'))"` from `remote-gateway/` to confirm the module still imports cleanly. Expected: `False`, no exception.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat(mcp_server): register admin tools + bootstrap admin roles on startup"
```

---

## Task 9: Retrofit `create_user` with `_require_admin`

**Files:**
- Modify: `remote-gateway/tools/meta.py:56-84` (`make_create_user`)
- Modify: `remote-gateway/tests/test_admin_tools.py`

- [ ] **Step 1: Write failing test**

Append to `remote-gateway/tests/test_admin_tools.py`:

```python
from tools.meta import make_create_user  # noqa: E402


def test_create_user_requires_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("bob@example.com", "sk-bob")  # non-admin
    token = server._current_user.set("bob@example.com")
    try:
        with pytest.raises(PermissionError):
            make_create_user(store)("ghost@example.com", "")
    finally:
        server._current_user.reset(token)


def test_create_user_allows_admin(store, monkeypatch):
    monkeypatch.setattr(server, "_telemetry", store)
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    token = server._current_user.set("alice@example.com")
    try:
        result = make_create_user(store)("new_user", "")
    finally:
        server._current_user.reset(token)
    assert result["user_id"] == "new_user"
    assert result["key"].startswith("sk-")
```

- [ ] **Step 2: Run tests to verify the require-admin test fails**

Run: `pytest remote-gateway/tests/test_admin_tools.py::test_create_user_requires_admin -v`
Expected: FAIL — `create_user` currently has no gate, returns a key for `ghost@example.com`.

- [ ] **Step 3: Add the admin check to `create_user`**

In `remote-gateway/tools/meta.py`, inside the `create_user` closure body, add `_admin_check()` as the first line. To avoid circular imports, mirror the lazy-import pattern from `tools/admin.py`:

```python
def make_create_user(telemetry: Any) -> Callable[[str, str], dict]:
    """Return a create_user tool function bound to the given telemetry instance."""

    def create_user(user_id: str, key: str = "") -> dict:
        """Create an API key for a new user. Admin only (role='admin').

        … (existing docstring body unchanged) …
        """
        from mcp_server import _require_admin
        _require_admin()
        created_key = telemetry.add_api_key(user_id, key or None)
        return {
            "user_id": user_id,
            "key": created_key,
            "usage": {
                "header": f"Authorization: Bearer {created_key}",
                "query_param": f"?api_key={created_key}",
            },
        }

    return create_user
```

- [ ] **Step 4: Run tests**

Run: `pytest remote-gateway/tests/test_admin_tools.py -v`
Expected: 15 PASS total.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/meta.py remote-gateway/tests/test_admin_tools.py
git commit -m "feat(meta): create_user now requires role=admin"
```

---

## Task 10: Add the 4 new tools to `INTENT_NEVER_REQUIRED`

**Files:**
- Modify: `remote-gateway/core/telemetry.py:44-51` (`INTENT_NEVER_REQUIRED`)
- Modify: `remote-gateway/tests/test_init_gate.py`

- [ ] **Step 1: Inspect existing init-gate test**

Run: `grep -n "INTENT_NEVER_REQUIRED\\|list_users\\|set_user_role" remote-gateway/tests/test_init_gate.py`
This shows the existing pattern so the new assertion follows it.

- [ ] **Step 2: Write failing test**

Append to `remote-gateway/tests/test_init_gate.py`:

```python
def test_admin_tools_in_intent_never_required():
    """Admin permission management tools must bypass the intent gate so an admin
    can provision users without first calling declare_intent."""
    from telemetry import INTENT_NEVER_REQUIRED
    assert "list_users" in INTENT_NEVER_REQUIRED
    assert "set_user_role" in INTENT_NEVER_REQUIRED
    assert "set_tool_permission" in INTENT_NEVER_REQUIRED
    assert "set_skill_permission" in INTENT_NEVER_REQUIRED
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest remote-gateway/tests/test_init_gate.py::test_admin_tools_in_intent_never_required -v`
Expected: FAIL with `AssertionError`.

- [ ] **Step 4: Update `INTENT_NEVER_REQUIRED`**

In `remote-gateway/core/telemetry.py`, extend the frozenset:

```python
INTENT_NEVER_REQUIRED: frozenset[str] = frozenset({
    "setup_start", "setup_save_profile", "setup_complete",
    "health_check",
    "declare_intent", "complete_task", "get_tasks",
    "get_operator_instructions", "create_user",
    "profile_get", "profile_update",
    "list_prompts", "get_prompt",
    "list_users", "set_user_role",
    "set_tool_permission", "set_skill_permission",
})
```

- [ ] **Step 5: Run test**

Run: `pytest remote-gateway/tests/test_init_gate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_init_gate.py
git commit -m "feat(init-gate): admin permission tools bypass declare_intent"
```

---

## Task 11: `PUT /api/users/{user_id}/role` HTTP route

**Files:**
- Modify: `remote-gateway/core/admin_api.py` (new route + register in routes list)
- Modify: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing tests**

Append to `remote-gateway/tests/test_admin_api.py`:

```python
def test_set_user_role_promotes(client):
    c, store = client
    store.add_api_key("alice@example.com", "sk-alice")
    resp = c.put(
        f"/api/users/alice@example.com/role?token={TOKEN}",
        json={"role": "admin"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "user_id": "alice@example.com", "role": "admin"}
    assert store.is_admin("alice@example.com") is True


def test_set_user_role_invalid_role_returns_400(client):
    c, store = client
    store.add_api_key("alice@example.com", "sk-alice")
    resp = c.put(
        f"/api/users/alice@example.com/role?token={TOKEN}",
        json={"role": "superadmin"},
    )
    assert resp.status_code == 400


def test_set_user_role_missing_body_returns_400(client):
    c, store = client
    store.add_api_key("alice@example.com", "sk-alice")
    resp = c.put(
        f"/api/users/alice@example.com/role?token={TOKEN}", json={}
    )
    assert resp.status_code == 400


def test_list_users_includes_role_field(client):
    c, store = client
    store.add_api_key("alice@example.com", "sk-alice")
    store.set_user_role("alice@example.com", "admin")
    resp = c.get(f"/api/users?token={TOKEN}")
    assert resp.status_code == 200
    users = {u["user_id"]: u for u in resp.json()}
    assert users["alice@example.com"]["role"] == "admin"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_admin_api.py -k role -v`
Expected: 4 FAILs (route doesn't exist; `list_users` test depends on Task 5 which already passed but the route returns whatever telemetry yields — verify by running this one in isolation if curious).

- [ ] **Step 3: Add the route**

In `remote-gateway/core/admin_api.py`, near the existing `api_users_delete` route, add the handler and import `VALID_ROLES`:

At the top of the file, with the other imports:

```python
from telemetry import VALID_ROLES
```

Then the handler:

```python
async def api_user_role_set(request: Request) -> Response:
    user_id = request.path_params["user_id"]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    role = body.get("role")
    if role not in VALID_ROLES:
        return JSONResponse(
            {"error": f"role must be one of {sorted(VALID_ROLES)}"},
            status_code=400,
        )
    telemetry.set_user_role(user_id, role)
    return JSONResponse({"ok": True, "user_id": user_id, "role": role})
```

And register the route in the `Route(...)` list near the other `/api/users` routes:

```python
Route("/api/users/{user_id}/role", api_user_role_set, methods=["PUT"]),
```

- [ ] **Step 4: Run tests**

Run: `pytest remote-gateway/tests/test_admin_api.py -v`
Expected: all PASS (including the 4 new).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat(admin_api): PUT /api/users/{user_id}/role for the UI toggle"
```

---

## Task 12: Admin UI — surface `role` and a role-select column

**Files:**
- Modify: `remote-gateway/admin-ui/src/hooks/useOperators.ts`
- Modify: `remote-gateway/admin-ui/src/routes/operators/OperatorsTable.tsx`

- [ ] **Step 1: Extend `Operator` type + add `useSetUserRole` mutation**

In `remote-gateway/admin-ui/src/hooks/useOperators.ts`, add the `role` field and a new mutation hook:

```typescript
export type Role = 'user' | 'admin';

export type Operator = {
  user_id: string;
  key: string;
  role: Role;
  call_count: number;
  last_active: string | null;
  [extra: string]: unknown;
};
```

And append:

```typescript
export function useSetUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ user_id, role }: { user_id: string; role: Role }) =>
      api.put<{ ok: boolean; user_id: string; role: Role }>(
        `/admin/api/users/${encodeURIComponent(user_id)}/role`,
        { role },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
```

If `api.put` doesn't exist in `@/lib/api`, check the existing `api` object — if only `get`/`post`/`delete` are defined, add a `put` method following the same pattern as `post`. (Confirm with: `cat remote-gateway/admin-ui/src/lib/api.ts`.)

- [ ] **Step 2: Add a Role column to the table**

In `remote-gateway/admin-ui/src/routes/operators/OperatorsTable.tsx`, import the new hook and add a column. Replace the columns array with:

```typescript
import { useOperators, useDeleteOperator, useSetUserRole, type Operator, type Role } from '@/hooks/useOperators';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

// inside the component, before columns useMemo:
const setRole = useSetUserRole();

// columns:
const columns = useMemo<ColumnDef<Operator>[]>(() => [
  { accessorKey: 'user_id', header: 'User ID' },
  { accessorKey: 'key', header: 'Key', cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
  {
    accessorKey: 'role',
    header: 'Role',
    cell: ({ row }) => (
      <Select
        value={row.original.role}
        onValueChange={(next: Role) => {
          setRole.mutate(
            { user_id: row.original.user_id, role: next },
            {
              onSuccess: () => toast.success(`${row.original.user_id} is now ${next}`),
              onError: (err) => toast.error(err instanceof Error ? err.message : 'Update failed'),
            },
          );
        }}
      >
        <SelectTrigger className="h-7 w-24" onClick={(e) => e.stopPropagation()}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="user">User</SelectItem>
          <SelectItem value="admin">Admin</SelectItem>
        </SelectContent>
      </Select>
    ),
  },
  { accessorKey: 'call_count', header: 'Calls' },
  // … existing last_active and actions columns unchanged …
], [del, setRole]);
```

If `@/components/ui/select` doesn't exist, check what the codebase uses (likely a base-ui Select wrapper); follow the existing convention. If no select primitive exists, fall back to a small native `<select>` with `className="border rounded h-7 px-2 text-sm"`.

- [ ] **Step 3: Smoke-test in the dev server**

Run `./dev.sh` from the repo root, open `http://localhost:5173/admin`, sign in with the admin token, navigate to Operators, and verify:
1. The role column shows for each user.
2. Changing the dropdown PUTs `/admin/api/users/<id>/role` and updates the UI optimistically (check Network tab).
3. The dropdown click does NOT trigger the row's `onSelect` handler (`e.stopPropagation()` on the trigger).

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/admin-ui/src/hooks/useOperators.ts \
        remote-gateway/admin-ui/src/routes/operators/OperatorsTable.tsx
git commit -m "feat(admin-ui): role select column on the operators table"
```

---

## Task 13: Documentation updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `remote-gateway/CLAUDE.md`

- [ ] **Step 1: Add `BOOTSTRAP_ADMIN_USER_IDS` to env-var tables**

In `remote-gateway/CLAUDE.md`, in the **Environment Variables** table, add the row:

```markdown
| `BOOTSTRAP_ADMIN_USER_IDS` | No | Comma-separated user_ids to promote to role='admin' on every startup. Idempotent; never demotes. Unknown user_ids are logged and skipped. |
```

- [ ] **Step 2: Document the new MCP tools**

In the root `CLAUDE.md`, in the **Built-in tools** table, add rows alongside `create_user`:

```markdown
| `list_users` | Admin — list all gateway users with role and activity |
| `set_user_role` | Admin — set a user's role (`user` or `admin`) |
| `set_tool_permission` | Admin — bulk grant/revoke per-tool access for a user |
| `set_skill_permission` | Admin — bulk grant/revoke per-skill access for a user |
```

- [ ] **Step 3: Note the role column + admin gate**

In `remote-gateway/CLAUDE.md` under **Admin Guardrails**, add:

```markdown
### Admin role

A new `api_keys.role` column distinguishes `'admin'` from `'user'`. Five tools are admin-gated (require `role='admin'` on the caller): `create_user`, `list_users`, `set_user_role`, `set_tool_permission`, `set_skill_permission`. Seed admins on startup via the `BOOTSTRAP_ADMIN_USER_IDS` env var. The UI exposes a role-select cell on the Operators page, backed by `PUT /api/users/{user_id}/role`.

Custom roles and role→permission-set lookups are out of scope here — tracked separately.
```

In root `CLAUDE.md`, under a new **Testing discipline** subsection (anywhere in the coding-standards area), add:

```markdown
### Friction-to-test discipline

Every PR that closes a `source:report_issue` issue must state which test was added that would have caught the gap — or explicitly note that no test could have caught it (e.g. missing-feature gaps that need agent-contract tests, tracked separately). This keeps the test suite getting strictly stronger over time and prevents the same shape of friction from re-shipping.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md
git commit -m "docs: BOOTSTRAP_ADMIN_USER_IDS, admin role, and new admin MCP tools"
```

---

## Task 14: Cluster closeout — comment, close, file follow-ons

This task uses the `mcp__claude_ai_Inform_Growth_Business_Tools__github__*` MCP tools and the `report_issue` tool. It must run AFTER the implementation PR is open, so steps reference `<PR-NUMBER>`.

- [ ] **Step 1: Open the implementation PR**

Push the branch and open a PR. Title: `feat(gateway): admin-gated permission MCP tools (closes #29)`. Body should reference the spec and plan paths, and include "Closes #29".

- [ ] **Step 2: Comment + close #27**

Post on issue #27:

> Per-tool scoping for proxied integrations already works — `tool_permissions.tool_name` is treated as a path parameter throughout the admin API (`PUT /api/permissions/{user_id}/{tool_name:path}`), so `apollo__enrich_organization` granularity is supported today. With the bulk `set_tool_permission` MCP tool from #29 (PR #<PR-NUMBER>), the Lead Researcher allowlist can now be applied programmatically.
>
> The API credit cost metadata half of this issue (Apollo / Wiza / Exa per-call cost) is a separate concern from access grants. Filed as a new issue: #<NEW-ISSUE-COST>. Closing this one.

Then close.

- [ ] **Step 3: Comment + close #25**

Post on issue #25:

> The four MCP tools from #29 (PR #<PR-NUMBER>) supersede this manual playbook: `list_users`, `set_user_role`, `set_tool_permission`, `set_skill_permission`. Bootstrap admins via `BOOTSTRAP_ADMIN_USER_IDS`. Closing.

Then close.

- [ ] **Step 4: File the cost-metadata follow-on issue**

Use `report_issue` with:
- title: `Surface API credit cost metadata for Apollo / Wiza / Exa`
- body: Refer to #27 (now closed) for context. Two options the spec considers: (a) gateway wraps response with estimated cost per call type, or (b) gateway-resident reference note. Needed for the Lead Researcher's `estimated_cost` field on `update_signal` notes.
- labels: `type:feature`, `priority:p2`, `tool:apollo`

- [ ] **Step 5: File the permission-sets follow-on issue**

Use `report_issue` with:
- title: `Permission sets / custom roles built on the role column`
- body: With the `role` column now in place (from PR #<PR-NUMBER>), the next iteration is `role → permission_set → {tools, skills}` lookups so admins don't toggle tools one-by-one. Cites #25's "tedious one-by-one" complaint as the motivating UX.
- labels: `type:feature`, `priority:p2`

- [ ] **Step 6: File the agent-contract test follow-on issue**

Use `report_issue` with:
- title: `Add agent-contract test layer (would have caught #29)`
- body: |
    #29 shipped to production because no test ever asked "can an admin agent bootstrap a user end-to-end using only MCP tools?" — every existing test is developer-perspective. The gap was caught by `report_issue` at runtime, which is the right safety net but shouldn't be the first line of defense.

    **Proposed work:**
    1. One e2e test that connects via MCP with an admin key and runs the full agent-org provisioning playbook (`create_user` → `set_tool_permission` → `set_skill_permission` → smoke-test as that user).
    2. A capability-parity meta-test enumerating admin HTTP routes and asserting each has a paired MCP tool (with an explicit allowlist for routes intentionally UI-only).
    3. Process change in `CLAUDE.md`: every PR that closes a `source:report_issue` issue must state which test was added that would have caught the gap (or explicitly note that none could).

    The first item is the highest ROI — the gateway's thesis is "an agent operates here" but no test operates as an agent.
- labels: `type:recommendation`, `priority:p2`

- [ ] **Step 7: Verify #29 auto-closes on PR merge**

After the PR merges, confirm #29 closes (the PR body's "Closes #29" should trigger it). If not, close manually.

---

## Self-Review

**Spec coverage:**
- Storage layer (role column, helpers, list_users update, add_api_key inheritance): Tasks 1-5 ✓
- `_require_admin` chokepoint: Task 6 ✓
- 4 new MCP tools with bulk semantics: Task 7 ✓
- Registration + startup bootstrap: Task 8 ✓
- `create_user` retrofit: Task 9 ✓
- `INTENT_NEVER_REQUIRED` additions: Task 10 ✓
- HTTP route: Task 11 ✓
- UI toggle: Task 12 ✓
- Docs: Task 13 ✓
- Cluster closeout (#25, #27, #29 + 2 follow-on issues): Task 14 ✓
- Observability (PermissionError telemetry): inherited from existing telemetry patch in `mcp_server.py` — no separate task needed; verified by the existing failure path in `_tracked_mcp_tool`.

**Placeholder scan:** No "TBD", no "implement later". Each step has the actual code or exact command. Task 8's "find the registration site" step uses an exact grep command rather than a hard-coded line number because the registration site is one of several similar registrations and the exact line is volatile.

**Type / name consistency:**
- `ROLE_USER` / `ROLE_ADMIN` / `VALID_ROLES`: defined in Task 1, used in Tasks 2/4/11 ✓
- `set_user_role(user_id, role)` signature: Tasks 2, 7, 11, 12 — all match ✓
- `bootstrap_admin_roles(user_ids) -> {promoted, skipped_unknown}`: Tasks 4 and 8 — match ✓
- `make_list_users(telemetry)() -> {users: [...]}`: Task 7 and 12 — match ✓
- HTTP body `{role}`: Task 11 (handler) and Task 12 (UI hook) — match ✓
- `_require_admin()` returns `str` user_id: Task 6 (helper + tests) and Task 7 (used via lazy import) — match ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-24-admin-permission-tools.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
