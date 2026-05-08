# Skills Gating & Per-Tool Intent Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-(user, skill) permissions mirroring `tool_permissions`, plus a per-(user, tool) intent-required toggle with a hard-block list for bootstrap tools.

**Architecture:** Two new SQLite tables (`skill_permissions`, `tool_intent_overrides`) added to `_SCHEMA_TABLES` in `core/telemetry.py`. Telemetry exposes mirrored helper methods. Enforcement lives in `tools/_core/skill_manager.py` (skills) and `core/mcp_server.py` (intent). Admin API in `core/admin_api.py` exposes both. Admin UI gets a Skills permissions panel and a "Requires intent" column.

**Tech Stack:** Python 3.11+ (SQLite, FastMCP, Starlette), pytest, React + Vite + Tailwind 4 (admin UI).

**Spec:** `docs/superpowers/specs/2026-05-08-skills-gating-intent-toggle-design.md`

---

## File Map

**Modified:**
- `remote-gateway/core/telemetry.py` — add two tables, six new methods, two new caches, one constant
- `remote-gateway/tools/_core/skill_manager.py` — enforce skill perms in `skill_list` and `run_skill`
- `remote-gateway/core/mcp_server.py` — rename `_TASK_BYPASS` → `_TASK_BYPASS_DEFAULTS`, add `_tool_requires_intent`, replace 4 call sites
- `remote-gateway/core/admin_api.py` — add 5 new routes (skill perms GET/PUT, intent GET/PUT/DELETE)
- `remote-gateway/admin-ui/src/routes/operators/PermissionsPanel.tsx` — add "Requires intent" column
- `remote-gateway/admin-ui/src/routes/operators/index.tsx` (or equivalent) — tabbed Tools/Skills view

**Created:**
- `remote-gateway/admin-ui/src/routes/operators/SkillPermissionsPanel.tsx`
- `remote-gateway/admin-ui/src/hooks/useSkillPermissions.ts`
- `remote-gateway/admin-ui/src/hooks/useToolIntent.ts`
- `remote-gateway/tests/test_skill_permissions.py`
- `remote-gateway/tests/test_intent_overrides.py`

---

## Phase A — Skills permissions: telemetry layer

### Task 1: Add `skill_permissions` table and cache loader

**Files:**
- Modify: `remote-gateway/core/telemetry.py:84-96` (add new CREATE TABLE)
- Modify: `remote-gateway/core/telemetry.py:147-153` (add cache initialization in `__init__`)
- Test: `remote-gateway/tests/test_skill_permissions.py` (new)

- [ ] **Step 1: Create the test file with a schema-existence test**

Create `remote-gateway/tests/test_skill_permissions.py`:

```python
"""Tests for skill_permissions table and TelemetryStore methods."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


def test_skill_permissions_table_exists(store):
    """skill_permissions table must be created on init."""
    conn = store._connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_permissions'"
    ).fetchone()
    assert row is not None
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: FAIL — table does not exist.

- [ ] **Step 3: Add the table to `_SCHEMA_TABLES`**

In `remote-gateway/core/telemetry.py`, find the block ending at line 96 (after the `skills` table) and add immediately after it:

```sql
CREATE TABLE IF NOT EXISTS skill_permissions (
    user_id    TEXT    NOT NULL,
    skill_name TEXT    NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, skill_name)
);
```

(Place it inside the `_SCHEMA_TABLES` triple-quoted string; the existing `tool_permissions` block at line 68-73 is the structural template.)

- [ ] **Step 4: Add the cache initialization in `__init__`**

In `remote-gateway/core/telemetry.py:147-153`, add `_disabled_skills_cache` next to `_disabled_cache`:

```python
def __init__(self, db_path: Path = _DB_PATH) -> None:
    self._path = db_path
    self._enabled = False
    self._disabled_cache: dict[str, set[str]] = {}
    self._disabled_skills_cache: dict[str, set[str]] = {}
    self._hint_cache: dict[str, dict[str, dict]] = {}
    self._conn: sqlite3.Connection | None = None
    self._setup()
    self._load_disabled_cache()
    self._load_disabled_skills_cache()
```

- [ ] **Step 5: Add the `_load_disabled_skills_cache` method**

In `remote-gateway/core/telemetry.py`, immediately after `_load_disabled_cache` (around line 209), add:

```python
def _load_disabled_skills_cache(self) -> None:
    """Populate _disabled_skills_cache from all enabled=0 rows in skill_permissions.

    Called once at startup. After this, set_skill_permission keeps the cache
    consistent. Silent no-op if the DB is unavailable.
    """
    if not self._enabled:
        return
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT user_id, skill_name FROM skill_permissions WHERE enabled = 0"
        ).fetchall()
        for row in rows:
            self._disabled_skills_cache.setdefault(row["user_id"], set()).add(row["skill_name"])
    except Exception:
        pass
```

- [ ] **Step 6: Run the test, expect pass**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_skill_permissions.py
git commit -m "feat(telemetry): add skill_permissions table and disabled-skills cache"
```

---

### Task 2: `is_skill_enabled` method

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (add method after `has_permission` block at ~line 354)
- Test: `remote-gateway/tests/test_skill_permissions.py`

- [ ] **Step 1: Write failing tests**

Append to `remote-gateway/tests/test_skill_permissions.py`:

```python
def test_is_skill_enabled_default_true(store):
    """No row means the skill is allowed."""
    assert store.is_skill_enabled("alice", "briefing") is True


def test_is_skill_enabled_user_disabled(store):
    store.set_skill_permission("alice", "briefing", False)
    assert store.is_skill_enabled("alice", "briefing") is False


def test_is_skill_enabled_other_user_unaffected(store):
    store.set_skill_permission("alice", "briefing", False)
    assert store.is_skill_enabled("bob", "briefing") is True


def test_is_skill_enabled_global_star_disabled(store):
    store.set_skill_permission("*", "briefing", False)
    assert store.is_skill_enabled("alice", "briefing") is False
    assert store.is_skill_enabled("bob", "briefing") is False


def test_is_skill_enabled_user_override_beats_global(store):
    store.set_skill_permission("*", "briefing", False)
    store.set_skill_permission("alice", "briefing", True)
    assert store.is_skill_enabled("alice", "briefing") is True
    assert store.is_skill_enabled("bob", "briefing") is False
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: FAIL — `is_skill_enabled` and `set_skill_permission` not defined.

- [ ] **Step 3: Implement `is_skill_enabled`**

In `remote-gateway/core/telemetry.py`, immediately after `has_permission` (around line 354), add:

```python
def is_skill_enabled(self, user_id: str, skill_name: str) -> bool:
    """Return whether a user is allowed to run a skill.

    Resolution: per-user row → global '*' row → default True. The user-specific
    row beats the global toggle, mirroring how tool permissions resolve.

    Fails open: if telemetry is disabled or the DB lookup raises, returns True.
    """
    if not self._enabled:
        return True
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT enabled FROM skill_permissions WHERE user_id = ? AND skill_name = ?",
            (user_id, skill_name),
        ).fetchone()
        if row is not None:
            return bool(row["enabled"])
        if skill_name in self._disabled_skills_cache.get("*", set()):
            return False
        return True
    except Exception:
        return True
```

- [ ] **Step 4: Implement `set_skill_permission` (minimal — needed by the tests)**

In `remote-gateway/core/telemetry.py`, immediately after `is_skill_enabled`, add:

```python
def set_skill_permission(self, user_id: str, skill_name: str, enabled: bool) -> None:
    """Insert or update a skill permission. user_id='*' for the global toggle."""
    if not self._enabled:
        return
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO skill_permissions (user_id, skill_name, enabled) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, skill_name) DO UPDATE SET enabled = excluded.enabled",
            (user_id, skill_name, int(enabled)),
        )
        conn.commit()
    except Exception:
        pass
    if enabled:
        if user_id in self._disabled_skills_cache:
            self._disabled_skills_cache[user_id].discard(skill_name)
    else:
        self._disabled_skills_cache.setdefault(user_id, set()).add(skill_name)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_skill_permissions.py
git commit -m "feat(telemetry): add is_skill_enabled and set_skill_permission"
```

---

### Task 3: `get_skill_permissions` listing method

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (add after `set_skill_permission`)
- Test: `remote-gateway/tests/test_skill_permissions.py`

- [ ] **Step 1: Write failing test**

Append to `remote-gateway/tests/test_skill_permissions.py`:

```python
def test_get_skill_permissions_returns_explicit_rows(store):
    store.set_skill_permission("alice", "briefing", False)
    store.set_skill_permission("alice", "summary", True)
    rows = store.get_skill_permissions("alice")
    by_name = {r["skill_name"]: r["enabled"] for r in rows}
    assert by_name == {"briefing": False, "summary": True}


def test_get_skill_permissions_empty_for_unknown_user(store):
    assert store.get_skill_permissions("nobody") == []
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: FAIL — `get_skill_permissions` not defined.

- [ ] **Step 3: Implement**

In `remote-gateway/core/telemetry.py`, immediately after `set_skill_permission`, add:

```python
def get_skill_permissions(self, user_id: str) -> list[dict]:
    """Return explicit skill permission rows for a user."""
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT skill_name, enabled FROM skill_permissions"
            " WHERE user_id = ? ORDER BY skill_name",
            (user_id,),
        ).fetchall()
    except Exception:
        return []
    return [{"skill_name": row["skill_name"], "enabled": bool(row["enabled"])} for row in rows]
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_skill_permissions.py
git commit -m "feat(telemetry): add get_skill_permissions listing"
```

---

### Task 4: `filter_visible_skills` helper

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (add after `get_skill_permissions`)
- Test: `remote-gateway/tests/test_skill_permissions.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_filter_visible_skills_hides_globally_disabled(store):
    store.set_skill_permission("*", "briefing", False)
    visible = store.filter_visible_skills("alice", ["briefing", "summary"])
    assert visible == {"summary"}


def test_filter_visible_skills_hides_user_disabled(store):
    store.set_skill_permission("alice", "briefing", False)
    visible = store.filter_visible_skills("alice", ["briefing", "summary"])
    assert visible == {"summary"}


def test_filter_visible_skills_other_user_unaffected(store):
    store.set_skill_permission("alice", "briefing", False)
    visible = store.filter_visible_skills("bob", ["briefing", "summary"])
    assert visible == {"briefing", "summary"}
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def filter_visible_skills(self, user_id: str | None, skill_names: list[str]) -> set[str]:
    """Return the subset of skill_names the user is permitted to see.

    Reads only the in-memory _disabled_skills_cache — no DB query. Mirrors
    filter_visible_tools.
    """
    if not self._enabled:
        return set(skill_names)
    globally_disabled = self._disabled_skills_cache.get("*", set())
    user_disabled = self._disabled_skills_cache.get(user_id, set()) if user_id else set()
    hidden = globally_disabled | user_disabled
    return {name for name in skill_names if name not in hidden}
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest remote-gateway/tests/test_skill_permissions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_skill_permissions.py
git commit -m "feat(telemetry): add filter_visible_skills helper"
```

---

## Phase B — Skills permissions: enforcement

### Task 5: `skill_list` filters disabled skills

**Files:**
- Modify: `remote-gateway/tools/_core/skill_manager.py:27-33`
- Test: `remote-gateway/tests/test_skill_manager.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `remote-gateway/tests/test_skill_manager.py`:

```python
def test_skill_list_hides_disabled_skill(tools, store):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    tools["skill_create"]("recap", "Recap meeting", "Recap {meeting}")
    store.set_skill_permission("alice@example.com", "briefing", False)
    names = [s["name"] for s in tools["skill_list"]()]
    assert "briefing" not in names
    assert "recap" in names


def test_skill_list_hides_globally_disabled_skill(tools, store):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    store.set_skill_permission("*", "briefing", False)
    assert tools["skill_list"]() == []
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_skill_manager.py -v`
Expected: FAIL — `skill_list` returns disabled skills.

- [ ] **Step 3: Update `skill_list` to filter**

Replace the body of `skill_list` in `remote-gateway/tools/_core/skill_manager.py` (lines 27-33):

```python
@mcp.tool()
def skill_list() -> list[dict]:
    """Return all active, permitted skills for the calling user.

    Bypasses the init gate — available even before setup. Skills disabled for
    the user (or globally via '*') are filtered out.
    """
    user_id = current_user_var.get()
    skills = telemetry.list_skills(_org_id())
    if user_id is None:
        return skills
    visible = telemetry.filter_visible_skills(user_id, [s["name"] for s in skills])
    return [s for s in skills if s["name"] in visible]
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest remote-gateway/tests/test_skill_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/_core/skill_manager.py remote-gateway/tests/test_skill_manager.py
git commit -m "feat(skills): filter skill_list by per-user permissions"
```

---

### Task 6: `run_skill` blocks disabled skills

**Files:**
- Modify: `remote-gateway/tools/_core/skill_manager.py:87-104`
- Test: `remote-gateway/tests/test_skill_manager.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_run_skill_blocked_when_disabled(tools, store):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    store.set_skill_permission("alice@example.com", "briefing", False)
    with pytest.raises(PermissionError) as exc_info:
        tools["run_skill"]("briefing", {"topic": "x"})
    assert "briefing" in str(exc_info.value)


def test_run_skill_blocked_when_globally_disabled(tools, store):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    store.set_skill_permission("*", "briefing", False)
    with pytest.raises(PermissionError):
        tools["run_skill"]("briefing", {"topic": "x"})


def test_run_skill_user_override_beats_global(tools, store):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    store.set_skill_permission("*", "briefing", False)
    store.set_skill_permission("alice@example.com", "briefing", True)
    result = tools["run_skill"]("briefing", {"topic": "x"})
    assert result == "Summarize x"
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_skill_manager.py -v -k run_skill`
Expected: FAIL.

- [ ] **Step 3: Update `run_skill` to enforce**

Replace `run_skill` body in `remote-gateway/tools/_core/skill_manager.py` (lines 87-104):

```python
@mcp.tool()
def run_skill(name: str, variables: dict | None = None) -> str:
    """Render a skill's prompt template with variables and return the prompt.

    The returned string is a prompt for you (Claude) to act on. Execute it
    using whatever gateway tools are available.

    Args:
        name: Skill name to render.
        variables: Dict of {placeholder: value} pairs to fill into the template.
    """
    user_id = current_user_var.get()
    if user_id is not None and not telemetry.is_skill_enabled(user_id, name):
        raise PermissionError(
            f"Skill '{name}' is disabled for your account. "
            "Contact a gateway administrator to request access."
        )
    skill = telemetry.get_skill(_org_id(), name)
    if skill is None:
        raise ValueError(f"Skill '{name}' not found.")
    template: str = skill["prompt_template"]
    if variables:
        template = template.format(**variables)
    return template
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest remote-gateway/tests/test_skill_manager.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/_core/skill_manager.py remote-gateway/tests/test_skill_manager.py
git commit -m "feat(skills): block run_skill when disabled for the calling user"
```

---

## Phase C — Skills permissions: admin API

### Task 7: GET /api/skill-permissions/{user_id}

**Files:**
- Modify: `remote-gateway/core/admin_api.py` (add handler near other permission handlers, register route)
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing test**

Append to `remote-gateway/tests/test_admin_api.py` (use existing test patterns; if there's no existing pattern for a request fixture, mirror `test_admin_routes.py`). Use this test:

```python
def test_get_skill_permissions_returns_explicit_with_known_skills(client, store):
    store.add_api_key("alice@example.com", "sk-a", org_id="acme")
    store.create_skill("acme", "briefing", "Morning summary", "Summarize {topic}")
    store.set_skill_permission("alice@example.com", "briefing", False)
    resp = client.get(
        "/admin/api/skill-permissions/alice@example.com?token=test-admin-token"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "alice@example.com"
    by_name = {p["skill_name"]: p["enabled"] for p in body["permissions"]}
    assert by_name["briefing"] is False
```

If the existing test file uses a different fixture style (read it first), adapt the test to match. The assertion contract — status 200, body shape — stays the same.

- [ ] **Step 2: Run, expect 404**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k skill_permissions`
Expected: FAIL — route not registered (404 or AssertionError).

- [ ] **Step 3: Add the handler**

In `remote-gateway/core/admin_api.py`, immediately after `api_permissions_set` (around line 227), add:

```python
async def api_skill_permissions_get(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    user_id = request.path_params["user_id"]
    org_id = _get_primary_org_id(telemetry)
    explicit = {
        row["skill_name"]: row["enabled"]
        for row in telemetry.get_skill_permissions(user_id)
    }
    known = {s["name"] for s in telemetry.list_skills(org_id)}
    skill_names = sorted(known | explicit.keys())
    permissions = [
        {"skill_name": name, "enabled": explicit.get(name, True)}
        for name in skill_names
    ]
    return JSONResponse({"user_id": user_id, "permissions": permissions})
```

- [ ] **Step 4: Register the route**

In `remote-gateway/core/admin_api.py:362-363` (route table), add immediately after the existing permissions routes:

```python
Route("/api/skill-permissions/{user_id}", api_skill_permissions_get, methods=["GET"]),
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k skill_permissions`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat(admin-api): GET /api/skill-permissions/{user_id}"
```

---

### Task 8: PUT /api/skill-permissions/{user_id}/{skill_name}

**Files:**
- Modify: `remote-gateway/core/admin_api.py`
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_put_skill_permissions_disables_skill(client, store):
    store.add_api_key("alice@example.com", "sk-a", org_id="acme")
    store.create_skill("acme", "briefing", "Morning summary", "Summarize {topic}")
    resp = client.put(
        "/admin/api/skill-permissions/alice@example.com/briefing?token=test-admin-token",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert store.is_skill_enabled("alice@example.com", "briefing") is False


def test_put_skill_permissions_requires_enabled_field(client):
    resp = client.put(
        "/admin/api/skill-permissions/alice@example.com/briefing?token=test-admin-token",
        json={},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k skill_permissions`
Expected: FAIL — route not registered for PUT.

- [ ] **Step 3: Add the handler**

In `remote-gateway/core/admin_api.py`, immediately after `api_skill_permissions_get`, add:

```python
async def api_skill_permissions_set(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    user_id = request.path_params["user_id"]
    skill_name = request.path_params["skill_name"]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if "enabled" not in body:
        return JSONResponse({"error": "enabled (bool) is required"}, status_code=400)
    telemetry.set_skill_permission(user_id, skill_name, bool(body["enabled"]))
    return JSONResponse({"ok": True, "user_id": user_id, "skill_name": skill_name,
                         "enabled": bool(body["enabled"])})
```

- [ ] **Step 4: Register the route**

In `remote-gateway/core/admin_api.py` route table, immediately after the GET line added in Task 7:

```python
Route("/api/skill-permissions/{user_id}/{skill_name:path}",
      api_skill_permissions_set, methods=["PUT"]),
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k skill_permissions`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat(admin-api): PUT /api/skill-permissions/{user_id}/{skill_name}"
```

---

## Phase D — Intent overrides: telemetry layer

### Task 9: Define `_INTENT_NEVER_REQUIRED` constant and add `tool_intent_overrides` table

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (add module-level constant near top + new CREATE TABLE)
- Test: `remote-gateway/tests/test_intent_overrides.py` (new)

- [ ] **Step 1: Create the test file with a schema test**

Create `remote-gateway/tests/test_intent_overrides.py`:

```python
"""Tests for tool_intent_overrides table and TelemetryStore methods."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore, INTENT_NEVER_REQUIRED  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


def test_intent_overrides_table_exists(store):
    conn = store._connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_intent_overrides'"
    ).fetchone()
    assert row is not None


def test_intent_never_required_contains_bootstrap_tools():
    """The hard-block list must include every bootstrap tool."""
    expected = {
        "setup_start", "setup_save_profile", "setup_complete",
        "health_check",
        "declare_intent", "complete_task", "get_tasks",
        "get_operator_instructions", "create_user",
        "profile_get", "profile_update",
        "list_prompts", "get_prompt",
    }
    assert expected.issubset(INTENT_NEVER_REQUIRED)
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v`
Expected: FAIL — `INTENT_NEVER_REQUIRED` symbol not defined.

- [ ] **Step 3: Add the constant**

At the top of `remote-gateway/core/telemetry.py`, after the imports (around line 30), add:

```python
INTENT_NEVER_REQUIRED: frozenset[str] = frozenset({
    "setup_start", "setup_save_profile", "setup_complete",
    "health_check",
    "declare_intent", "complete_task", "get_tasks",
    "get_operator_instructions", "create_user",
    "profile_get", "profile_update",
    "list_prompts", "get_prompt",
})
"""Tools that are always exempt from the intent (declare_intent) gate.

The admin API rejects any attempt to require intent for these tools, since
toggling them on would lock the org out of bootstrap operations (you cannot
declare_intent if declare_intent itself requires intent).
"""
```

- [ ] **Step 4: Add the table**

In `_SCHEMA_TABLES` in `remote-gateway/core/telemetry.py`, add immediately after the `skill_permissions` table from Task 1:

```sql
CREATE TABLE IF NOT EXISTS tool_intent_overrides (
    user_id         TEXT    NOT NULL,
    tool_name       TEXT    NOT NULL,
    requires_intent INTEGER NOT NULL,
    PRIMARY KEY (user_id, tool_name)
);
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_intent_overrides.py
git commit -m "feat(telemetry): add tool_intent_overrides table and INTENT_NEVER_REQUIRED"
```

---

### Task 10: `get_tool_intent_override` and `set_tool_intent_override` methods

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (add after `get_skill_permissions` block)
- Test: `remote-gateway/tests/test_intent_overrides.py`

- [ ] **Step 1: Write failing tests**

Append to `remote-gateway/tests/test_intent_overrides.py`:

```python
def test_get_tool_intent_override_default_none(store):
    assert store.get_tool_intent_override("alice", "search_records") is None


def test_set_and_get_user_specific(store):
    store.set_tool_intent_override("alice", "search_records", True)
    assert store.get_tool_intent_override("alice", "search_records") is True


def test_user_override_beats_global(store):
    store.set_tool_intent_override("*", "search_records", True)
    store.set_tool_intent_override("alice", "search_records", False)
    assert store.get_tool_intent_override("alice", "search_records") is False
    assert store.get_tool_intent_override("bob", "search_records") is True


def test_set_rejects_never_required_tools(store):
    for name in ["setup_start", "declare_intent", "health_check", "create_user"]:
        with pytest.raises(ValueError) as exc_info:
            store.set_tool_intent_override("alice", name, True)
        assert name in str(exc_info.value)


def test_set_allows_skill_management_tools(store):
    """skill_create / run_skill etc. are NOT in the hard-block list."""
    for name in ["skill_create", "skill_update", "skill_list", "run_skill"]:
        store.set_tool_intent_override("*", name, True)
        assert store.get_tool_intent_override("alice", name) is True
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `remote-gateway/core/telemetry.py`, immediately after `filter_visible_skills` (added in Task 4), add:

```python
def get_tool_intent_override(
    self, user_id: str | None, tool_name: str
) -> bool | None:
    """Return user/global override for a tool's intent requirement.

    Resolution: per-user row → global '*' row → None (no override).
    """
    if not self._enabled:
        return None
    try:
        conn = self._connect()
        if user_id is not None:
            row = conn.execute(
                "SELECT requires_intent FROM tool_intent_overrides "
                "WHERE user_id = ? AND tool_name = ?",
                (user_id, tool_name),
            ).fetchone()
            if row is not None:
                return bool(row["requires_intent"])
        row = conn.execute(
            "SELECT requires_intent FROM tool_intent_overrides "
            "WHERE user_id = '*' AND tool_name = ?",
            (tool_name,),
        ).fetchone()
        if row is not None:
            return bool(row["requires_intent"])
        return None
    except Exception:
        return None


def set_tool_intent_override(
    self, user_id: str, tool_name: str, requires_intent: bool
) -> None:
    """Insert or update an intent override. Raises ValueError for hard-blocked tools."""
    if tool_name in INTENT_NEVER_REQUIRED:
        raise ValueError(
            f"Tool '{tool_name}' is bootstrap-critical and cannot be required to "
            f"declare intent — toggling it would lock the org out."
        )
    if not self._enabled:
        return
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO tool_intent_overrides (user_id, tool_name, requires_intent) "
            "VALUES (?, ?, ?) ON CONFLICT(user_id, tool_name) "
            "DO UPDATE SET requires_intent = excluded.requires_intent",
            (user_id, tool_name, int(requires_intent)),
        )
        conn.commit()
    except Exception:
        pass
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_intent_overrides.py
git commit -m "feat(telemetry): add get/set_tool_intent_override with hard-block validation"
```

---

### Task 11: `clear_tool_intent_override` and `get_tool_intent_overrides` listing

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Test: `remote-gateway/tests/test_intent_overrides.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_clear_intent_override(store):
    store.set_tool_intent_override("alice", "search_records", True)
    store.clear_tool_intent_override("alice", "search_records")
    assert store.get_tool_intent_override("alice", "search_records") is None


def test_get_tool_intent_overrides_listing(store):
    store.set_tool_intent_override("alice", "search_records", True)
    store.set_tool_intent_override("alice", "create_record", False)
    rows = store.get_tool_intent_overrides("alice")
    by_name = {r["tool_name"]: r["requires_intent"] for r in rows}
    assert by_name == {"search_records": True, "create_record": False}
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `remote-gateway/core/telemetry.py`, append after `set_tool_intent_override`:

```python
def clear_tool_intent_override(self, user_id: str, tool_name: str) -> None:
    """Delete an override row, restoring default behavior."""
    if not self._enabled:
        return
    try:
        conn = self._connect()
        conn.execute(
            "DELETE FROM tool_intent_overrides WHERE user_id = ? AND tool_name = ?",
            (user_id, tool_name),
        )
        conn.commit()
    except Exception:
        pass


def get_tool_intent_overrides(self, user_id: str) -> list[dict]:
    """Return explicit intent override rows for a user."""
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT tool_name, requires_intent FROM tool_intent_overrides "
            "WHERE user_id = ? ORDER BY tool_name",
            (user_id,),
        ).fetchall()
    except Exception:
        return []
    return [
        {"tool_name": row["tool_name"], "requires_intent": bool(row["requires_intent"])}
        for row in rows
    ]
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_intent_overrides.py
git commit -m "feat(telemetry): add clear_tool_intent_override and listing"
```

---

## Phase E — Intent enforcement in mcp_server

### Task 12: Rename `_TASK_BYPASS` → `_TASK_BYPASS_DEFAULTS` and add `_tool_requires_intent`

**Files:**
- Modify: `remote-gateway/core/mcp_server.py:182-200` (rename + replace 4 call sites)
- Test: existing `remote-gateway/tests/test_task_gate.py` (must remain green); new test added below

- [ ] **Step 1: Write a failing test for the new helper**

Append to `remote-gateway/tests/test_intent_overrides.py`:

```python
def test_tool_requires_intent_default_for_bypass_tools(store):
    """Tools currently in _TASK_BYPASS default to NOT requiring intent."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
    sys.modules.pop("mcp_server", None)
    # Import the helper without booting the full server
    import importlib
    import mcp_server
    importlib.reload(mcp_server)
    mcp_server._telemetry = store  # rebind for the test
    for name in ["health_check", "declare_intent", "skill_list", "run_skill",
                 "profile_get", "setup_start"]:
        assert mcp_server._tool_requires_intent("alice", name) is False, name


def test_tool_requires_intent_default_for_other_tools(store):
    sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
    sys.modules.pop("mcp_server", None)
    import importlib
    import mcp_server
    importlib.reload(mcp_server)
    mcp_server._telemetry = store
    for name in ["search_records", "create_record", "enrich_person"]:
        assert mcp_server._tool_requires_intent("alice", name) is True, name


def test_tool_requires_intent_global_override(store):
    sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
    sys.modules.pop("mcp_server", None)
    import importlib
    import mcp_server
    importlib.reload(mcp_server)
    mcp_server._telemetry = store
    store.set_tool_intent_override("*", "run_skill", True)
    assert mcp_server._tool_requires_intent("alice", "run_skill") is True


def test_tool_requires_intent_hard_block(store):
    sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
    sys.modules.pop("mcp_server", None)
    import importlib
    import mcp_server
    importlib.reload(mcp_server)
    mcp_server._telemetry = store
    # Even if a (somehow) override exists, never-required tools stay False
    assert mcp_server._tool_requires_intent("alice", "declare_intent") is False
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_intent_overrides.py -v -k tool_requires_intent`
Expected: FAIL — `_tool_requires_intent` not defined.

- [ ] **Step 3: Rename in mcp_server.py**

In `remote-gateway/core/mcp_server.py`, rename the frozenset (line 182):

```python
# Tools listed here default to NOT requiring an active task. Admins can
# override via tool_intent_overrides; tools also in INTENT_NEVER_REQUIRED
# cannot be overridden in either direction.
_TASK_BYPASS_DEFAULTS: frozenset[str] = frozenset({
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
    "declare_intent",
    "complete_task",
    "get_tasks",
})
```

- [ ] **Step 4: Add the helper and import**

In `remote-gateway/core/mcp_server.py`, near the existing telemetry import (look for `from telemetry import`), update to import `INTENT_NEVER_REQUIRED`. Then immediately after `_TASK_BYPASS_DEFAULTS`, add:

```python
def _tool_requires_intent(user_id: str | None, tool_name: str) -> bool:
    """Return whether a tool requires an active task_id for the calling user.

    Resolution:
        1. If tool is in INTENT_NEVER_REQUIRED → False (hard block)
        2. If user/global override exists in tool_intent_overrides → use it
        3. Else: True if tool is NOT in _TASK_BYPASS_DEFAULTS
    """
    from telemetry import INTENT_NEVER_REQUIRED
    if tool_name in INTENT_NEVER_REQUIRED:
        return False
    override = _telemetry.get_tool_intent_override(user_id, tool_name)
    if override is not None:
        return override
    return tool_name not in _TASK_BYPASS_DEFAULTS
```

- [ ] **Step 5: Replace the four call sites**

In `remote-gateway/core/mcp_server.py`, replace each of these (current line numbers in parens — use grep if drifted):

- Line ~500: `if fn.__name__ not in _TASK_BYPASS and sid:` → `if _tool_requires_intent(_current_user.get(), fn.__name__) and sid:`
- Line ~557: same replacement
- Line ~642: `if tool_name not in _TASK_BYPASS and sid:` → `if _tool_requires_intent(_current_user.get(), tool_name) and sid:`
- Line ~696: same replacement

Verification command: `grep -n "_TASK_BYPASS\b" remote-gateway/core/mcp_server.py` should return zero hits (only `_TASK_BYPASS_DEFAULTS` remains).

- [ ] **Step 6: Run all relevant tests**

Run: `pytest remote-gateway/tests/test_intent_overrides.py remote-gateway/tests/test_task_gate.py remote-gateway/tests/test_init_gate.py -v`
Expected: PASS — including the existing task gate tests, since defaults are unchanged.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_intent_overrides.py
git commit -m "feat(server): replace _TASK_BYPASS with overridable _tool_requires_intent"
```

---

## Phase F — Intent overrides: admin API

### Task 13: GET /api/tool-intent/{user_id}

**Files:**
- Modify: `remote-gateway/core/admin_api.py`
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_get_tool_intent_lists_overrides_with_locked_flag(client, store):
    store.add_api_key("alice@example.com", "sk-a", org_id="acme")
    store.set_tool_intent_override("alice@example.com", "search_records", True)
    resp = client.get(
        "/admin/api/tool-intent/alice@example.com?token=test-admin-token"
    )
    assert resp.status_code == 200
    body = resp.json()
    by_name = {r["tool_name"]: r for r in body["overrides"]}
    assert by_name["search_records"]["requires_intent"] is True
    assert by_name["search_records"]["locked"] is False
    # health_check is in INTENT_NEVER_REQUIRED — should appear locked
    assert any(r["tool_name"] == "health_check" and r["locked"] is True
               for r in body["overrides"])
```

- [ ] **Step 2: Run, expect 404**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k tool_intent`
Expected: FAIL.

- [ ] **Step 3: Add the handler**

In `remote-gateway/core/admin_api.py`, near the imports, add to the `from telemetry import` line (find existing line): `, INTENT_NEVER_REQUIRED`. Then immediately after `api_skill_permissions_set`, add:

```python
async def api_tool_intent_get(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    user_id = request.path_params["user_id"]
    explicit = {
        row["tool_name"]: row["requires_intent"]
        for row in telemetry.get_tool_intent_overrides(user_id)
    }
    tool_names = sorted(explicit.keys() | set(INTENT_NEVER_REQUIRED))
    if list_tools_fn is not None:
        try:
            tools = await list_tools_fn()
            tool_names = sorted(set(t.name for t in tools) | explicit.keys()
                                | set(INTENT_NEVER_REQUIRED))
        except Exception:
            pass
    overrides = []
    for name in tool_names:
        locked = name in INTENT_NEVER_REQUIRED
        if locked:
            requires_intent = False
        elif name in explicit:
            requires_intent = explicit[name]
        else:
            # Reflect default resolution
            from mcp_server import _tool_requires_intent  # local import to avoid cycle at module load
            requires_intent = _tool_requires_intent(user_id, name)
        overrides.append({
            "tool_name": name,
            "requires_intent": requires_intent,
            "locked": locked,
            "explicit": name in explicit,
        })
    return JSONResponse({"user_id": user_id, "overrides": overrides})
```

- [ ] **Step 4: Register the route**

Add to the route table:

```python
Route("/api/tool-intent/{user_id}", api_tool_intent_get, methods=["GET"]),
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k tool_intent`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat(admin-api): GET /api/tool-intent/{user_id}"
```

---

### Task 14: PUT /api/tool-intent/{user_id}/{tool_name}

**Files:**
- Modify: `remote-gateway/core/admin_api.py`
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_put_tool_intent_sets_override(client, store):
    resp = client.put(
        "/admin/api/tool-intent/alice@example.com/search_records?token=test-admin-token",
        json={"requires_intent": True},
    )
    assert resp.status_code == 200
    assert store.get_tool_intent_override("alice@example.com", "search_records") is True


def test_put_tool_intent_rejects_locked_tool(client):
    resp = client.put(
        "/admin/api/tool-intent/alice@example.com/declare_intent?token=test-admin-token",
        json={"requires_intent": True},
    )
    assert resp.status_code == 400
    assert "bootstrap" in resp.json()["error"].lower()


def test_put_tool_intent_allows_skill_management(client, store):
    """skill_create is NOT in the hard-block list, so this should succeed."""
    resp = client.put(
        "/admin/api/tool-intent/*/run_skill?token=test-admin-token",
        json={"requires_intent": True},
    )
    assert resp.status_code == 200
    assert store.get_tool_intent_override("*", "run_skill") is True
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k tool_intent`
Expected: FAIL.

- [ ] **Step 3: Add the handler**

In `remote-gateway/core/admin_api.py`, immediately after `api_tool_intent_get`, add:

```python
async def api_tool_intent_set(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    user_id = request.path_params["user_id"]
    tool_name = request.path_params["tool_name"]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if "requires_intent" not in body:
        return JSONResponse({"error": "requires_intent (bool) is required"},
                            status_code=400)
    try:
        telemetry.set_tool_intent_override(user_id, tool_name,
                                           bool(body["requires_intent"]))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "user_id": user_id, "tool_name": tool_name,
                         "requires_intent": bool(body["requires_intent"])})
```

- [ ] **Step 4: Register the route**

Add to route table:

```python
Route("/api/tool-intent/{user_id}/{tool_name:path}",
      api_tool_intent_set, methods=["PUT"]),
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k tool_intent`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat(admin-api): PUT /api/tool-intent/{user_id}/{tool_name}"
```

---

### Task 15: DELETE /api/tool-intent/{user_id}/{tool_name}

**Files:**
- Modify: `remote-gateway/core/admin_api.py`
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_delete_tool_intent_clears_override(client, store):
    store.set_tool_intent_override("alice@example.com", "search_records", True)
    resp = client.delete(
        "/admin/api/tool-intent/alice@example.com/search_records?token=test-admin-token"
    )
    assert resp.status_code == 200
    assert store.get_tool_intent_override("alice@example.com", "search_records") is None
```

- [ ] **Step 2: Run, expect 405 or 404**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k delete_tool_intent`
Expected: FAIL.

- [ ] **Step 3: Add the handler**

```python
async def api_tool_intent_delete(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    user_id = request.path_params["user_id"]
    tool_name = request.path_params["tool_name"]
    telemetry.clear_tool_intent_override(user_id, tool_name)
    return JSONResponse({"ok": True, "cleared": True,
                         "user_id": user_id, "tool_name": tool_name})
```

- [ ] **Step 4: Register the route**

Update the existing PUT line to be a list of methods, or add a new line:

```python
Route("/api/tool-intent/{user_id}/{tool_name:path}",
      api_tool_intent_delete, methods=["DELETE"]),
```

(Starlette allows multiple Route entries with the same path but different methods.)

- [ ] **Step 5: Run, expect pass**

Run: `pytest remote-gateway/tests/test_admin_api.py -v -k delete_tool_intent`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat(admin-api): DELETE /api/tool-intent/{user_id}/{tool_name}"
```

---

## Phase G — Admin UI

### Task 16: `useSkillPermissions` hook

**Files:**
- Create: `remote-gateway/admin-ui/src/hooks/useSkillPermissions.ts`
- Test: `remote-gateway/admin-ui/src/hooks/useSkillPermissions.test.ts` (mirror existing `usePermissions.test.ts`)

- [ ] **Step 1: Read the existing hook for the exact pattern**

Run: `cat remote-gateway/admin-ui/src/hooks/usePermissions.ts`

Mirror its shape: same imports (likely SWR/React Query), same fetcher style, same return shape (loading/error/data + setter).

- [ ] **Step 2: Write the test mirroring `usePermissions.test.ts`**

Mirror the existing test, swapping the URL and shape:
- URL: `/admin/api/skill-permissions/${userId}`
- PUT URL: `/admin/api/skill-permissions/${userId}/${skillName}`
- Body shape: `{ skill_name: string; enabled: boolean }`

- [ ] **Step 3: Implement the hook**

Mirror `usePermissions.ts` line-for-line, replacing:
- `tool_name` → `skill_name`
- `/permissions/` → `/skill-permissions/`
- `permissions` (response field) stays the same

- [ ] **Step 4: Run tests**

Run: `cd remote-gateway/admin-ui && npm test -- useSkillPermissions`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/admin-ui/src/hooks/useSkillPermissions.ts \
        remote-gateway/admin-ui/src/hooks/useSkillPermissions.test.ts
git commit -m "feat(admin-ui): add useSkillPermissions hook"
```

---

### Task 17: `SkillPermissionsPanel` component

**Files:**
- Create: `remote-gateway/admin-ui/src/routes/operators/SkillPermissionsPanel.tsx`

- [ ] **Step 1: Read `PermissionsPanel.tsx` to mirror structure**

Run: `cat remote-gateway/admin-ui/src/routes/operators/PermissionsPanel.tsx`

The new panel should be structurally identical: a table of rows, each with a toggle, calling the setter from the hook on change.

- [ ] **Step 2: Implement the component**

Create `SkillPermissionsPanel.tsx` mirroring `PermissionsPanel.tsx`, with these substitutions:

| Tool | Skill |
|---|---|
| `usePermissions` | `useSkillPermissions` |
| `tool_name` | `skill_name` |
| `permissions` (returned key) | unchanged |
| Header text "Tool" | "Skill" |
| Empty-state copy | "No skills available" |

- [ ] **Step 3: Render the panel from a tabbed view**

Find the operator detail page (search for where `PermissionsPanel` is used: `grep -rn "PermissionsPanel" remote-gateway/admin-ui/src/`). Wrap the existing usage in a tabbed layout (use whatever tabs primitive the codebase already uses — likely shadcn / base-ui Tabs):

```tsx
<Tabs defaultValue="tools">
  <TabsList>
    <TabsTrigger value="tools">Tools</TabsTrigger>
    <TabsTrigger value="skills">Skills</TabsTrigger>
  </TabsList>
  <TabsContent value="tools"><PermissionsPanel userId={userId} /></TabsContent>
  <TabsContent value="skills"><SkillPermissionsPanel userId={userId} /></TabsContent>
</Tabs>
```

- [ ] **Step 4: Manual smoke test**

Run: `./dev.sh` and open `http://localhost:5173/admin`. Navigate to an operator. Verify:
1. Tools tab still works.
2. Skills tab loads, shows skills, toggling one calls the API and persists on reload.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/admin-ui/src/routes/operators/SkillPermissionsPanel.tsx \
        remote-gateway/admin-ui/src/routes/operators/  # whatever index file got the tabs
git commit -m "feat(admin-ui): SkillPermissionsPanel and tabbed operator view"
```

---

### Task 18: `useToolIntent` hook + "Requires intent" column in `PermissionsPanel`

**Files:**
- Create: `remote-gateway/admin-ui/src/hooks/useToolIntent.ts`
- Modify: `remote-gateway/admin-ui/src/routes/operators/PermissionsPanel.tsx`

- [ ] **Step 1: Implement `useToolIntent`**

Mirror `usePermissions` shape, with these endpoints:
- GET `/admin/api/tool-intent/${userId}`
- PUT `/admin/api/tool-intent/${userId}/${toolName}` body `{ requires_intent: boolean }`
- DELETE `/admin/api/tool-intent/${userId}/${toolName}`

Return shape includes `locked: boolean` and `explicit: boolean` per row from the API response.

- [ ] **Step 2: Add "Requires intent" column to PermissionsPanel**

In `PermissionsPanel.tsx`, add a second column next to the existing enabled toggle:
- A toggle that reads from `useToolIntent`
- Disabled (greyed) when `row.locked === true`, with a tooltip: "Bootstrap tool — intent cannot be required"
- On change: call setter (PUT). If user wants to clear an explicit override and return to default, provide a small "↻ Default" button that calls DELETE.

Pseudocode for the row:

```tsx
<tr>
  <td>{tool.name}</td>
  <td>
    <Toggle checked={enabled} onChange={(v) => setEnabled(tool.name, v)} />
  </td>
  <td>
    <Toggle
      checked={intent.requires_intent}
      disabled={intent.locked}
      onChange={(v) => setIntent(tool.name, v)}
    />
    {intent.explicit && !intent.locked && (
      <button onClick={() => clearIntent(tool.name)}>↻ Default</button>
    )}
  </td>
</tr>
```

- [ ] **Step 3: Manual smoke test**

Run: `./dev.sh`. In the operators page:
1. Toggle "Requires intent" on for `search_records`. Reload — sticks.
2. Confirm `declare_intent` row's "Requires intent" toggle is disabled with tooltip.
3. Click "↻ Default" — toggle returns to its default state.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/admin-ui/src/hooks/useToolIntent.ts \
        remote-gateway/admin-ui/src/routes/operators/PermissionsPanel.tsx
git commit -m "feat(admin-ui): add Requires intent column to permissions panel"
```

---

## Final verification

- [ ] **Step 1: Full test suite**

Run: `pytest remote-gateway/tests/ -v`
Expected: PASS — all new tests, all existing tests.

- [ ] **Step 2: Lint**

Run: `ruff check remote-gateway/`
Expected: clean.

- [ ] **Step 3: Front-end tests**

Run: `cd remote-gateway/admin-ui && npm test`
Expected: PASS.

- [ ] **Step 4: Build the admin UI to confirm no compile errors**

Run: `cd remote-gateway/admin-ui && npm run build`
Expected: clean build into `dist/`.

- [ ] **Step 5: Manual end-to-end smoke**

1. Start the gateway: `python remote-gateway/core/mcp_server.py`
2. Connect with an MCP client.
3. Verify default behavior unchanged: `skill_list` shows skills; `run_skill` works without override; gated tools still require intent.
4. Set a global skill override via `PUT /admin/api/skill-permissions/*/<skill>` `{"enabled": false}` — confirm the skill disappears from `skill_list`.
5. Set a global intent override on `run_skill` via `PUT /admin/api/tool-intent/*/run_skill` `{"requires_intent": true}` — confirm `run_skill` without `task_id` returns the `no_active_task` redirect.

- [ ] **Step 6: Open a PR**

Use the gh CLI per project conventions. PR title: `feat: skills gating and per-tool intent toggle`. Body summarizes Phase A–G and references the spec.

---

## Out of scope (do NOT implement)

- Roles / permission sets (deferred future work).
- Bulk operations in admin UI.
- Audit log table (telemetry already records every admin API call).
- Versioned migration tooling (Alembic, etc.).
- Port to `template/clean-gateway` — separate follow-up plan after this lands and soaks in production.
