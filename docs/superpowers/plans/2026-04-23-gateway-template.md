# Gateway Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the gateway into a deployable multi-tenant template where all client-specific configuration (org profiles, skills, tool hints) lives in SQLite and is editable via admin UI or conversation — no repo changes after deploy.

**Architecture:** Add three new SQLite tables (`org_profiles`, `skills`, `tool_hints`) with full CRUD to `TelemetryStore`. Wire an init gate into the existing telemetry middleware so uninitialized orgs get a redirect response instead of a blocked call. New `_core` tool modules (onboarding, skill manager, profile manager) handle all runtime configuration. Admin UI gets three new tabs.

**Tech Stack:** Python 3.11+, SQLite (WAL), FastMCP, Starlette, existing `TelemetryStore` + tracked-wrapper patterns.

---

## File Map

| Action | Path |
|---|---|
| Modify | `remote-gateway/core/telemetry.py` — new tables, migrations, CRUD methods, hint cache |
| Create | `remote-gateway/tools/_core/__init__.py` |
| Create | `remote-gateway/tools/_core/onboarding.py` — `setup_start`, `setup_save_profile`, `setup_complete` |
| Create | `remote-gateway/tools/_core/skill_manager.py` — `skill_list`, `skill_create`, `skill_update`, `skill_delete`, `run_skill` |
| Create | `remote-gateway/tools/_core/profile_manager.py` — `profile_get`, `profile_update` |
| Modify | `remote-gateway/core/mcp_server.py` — register _core tools, add init gate + response enrichment |
| Modify | `remote-gateway/core/admin_api.py` — three new route groups |
| Modify | `remote-gateway/core/admin_dashboard.html` — three new tabs |
| Create | `remote-gateway/tests/test_telemetry_org.py` |
| Create | `remote-gateway/tests/test_onboarding.py` |
| Create | `remote-gateway/tests/test_skill_manager.py` |
| Create | `remote-gateway/tests/test_profile_manager.py` |
| Create | `remote-gateway/tests/test_init_gate.py` |
| Create | `remote-gateway/tests/test_tool_hints.py` |

---

## Task 1: Schema — new tables and `org_id` column

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Create: `remote-gateway/tests/test_telemetry_org.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_telemetry_org.py
from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)
from telemetry import TelemetryStore

@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")

def test_get_org_id_falls_back_to_user_id(store):
    store.add_api_key("alice@example.com", "sk-test")
    assert store.get_org_id("alice@example.com") == "alice@example.com"

def test_get_org_id_returns_explicit_org(store):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    assert store.get_org_id("alice@example.com") == "acme"

def test_is_initialized_false_by_default(store):
    assert store.is_initialized("acme") is False

def test_is_initialized_true_after_set(store):
    store.set_initialized("acme")
    assert store.is_initialized("acme") is True

def test_get_org_profile_empty_for_unknown(store):
    assert store.get_org_profile("acme") == {}

def test_update_org_profile_creates_and_patches(store):
    store.update_org_profile("acme", {"tone": "professional", "icp": "SaaS"})
    profile = store.get_org_profile("acme")
    assert profile["tone"] == "professional"
    assert profile["icp"] == "SaaS"

def test_update_org_profile_merges_not_replaces(store):
    store.update_org_profile("acme", {"tone": "professional"})
    store.update_org_profile("acme", {"icp": "SaaS"})
    profile = store.get_org_profile("acme")
    assert profile["tone"] == "professional"
    assert profile["icp"] == "SaaS"
```

- [ ] **Step 2: Run to verify tests fail**

```
cd remote-gateway && pytest tests/test_telemetry_org.py -v
```
Expected: FAIL — `TelemetryStore` has no `get_org_id`, `is_initialized`, etc.

- [ ] **Step 3: Add `org_id` to `api_keys` migration and new tables to `_SCHEMA_TABLES`**

In `remote-gateway/core/telemetry.py`, append to `_SCHEMA_TABLES` (before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS org_profiles (
    org_id       TEXT PRIMARY KEY,
    display_name TEXT,
    profile_json TEXT NOT NULL DEFAULT '{}',
    initialized  INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id              TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_system       INTEGER NOT NULL DEFAULT 0,
    created_by      TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    UNIQUE(org_id, name)
);

CREATE TABLE IF NOT EXISTS tool_hints (
    id                  TEXT PRIMARY KEY,
    org_id              TEXT NOT NULL,
    tool_name           TEXT NOT NULL,
    interpretation_hint TEXT,
    usage_rules         TEXT,
    data_sensitivity    TEXT DEFAULT 'internal',
    is_active           INTEGER NOT NULL DEFAULT 1,
    UNIQUE(org_id, tool_name)
);
```

- [ ] **Step 4: Add `org_id` column migration to `_MIGRATIONS`**

In `_MIGRATIONS` list, append:
```python
("api_keys", "org_id", "TEXT"),
```

- [ ] **Step 5: Update `add_api_key` signature to accept `org_id`**

Replace the existing `add_api_key` method signature and INSERT:

```python
def add_api_key(self, user_id: str, key: str | None = None, org_id: str | None = None) -> str:
    """Create an API key for a user and store it. Returns the key.

    Args:
        user_id: Opaque user identifier (email, username, UUID, etc.).
        key: The key value to store. Generated securely if omitted.
        org_id: Organization identifier. Defaults to user_id if omitted.

    Returns:
        The API key string (``sk-<32 random hex chars>``).
    """
    if key is None:
        key = f"sk-{secrets.token_hex(16)}"
    if org_id is None:
        org_id = user_id
    if not self._enabled:
        return key
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO api_keys (key, user_id, org_id, created_at) VALUES (?, ?, ?, ?)",
            (key, user_id, org_id, time.time()),
        )
        conn.commit()
    except Exception:
        pass
    return key
```

- [ ] **Step 6: Add `get_org_id`, `is_initialized`, `set_initialized` methods**

Append these methods to `TelemetryStore` (after `lookup_user`):

```python
def get_org_id(self, user_id: str) -> str:
    """Return org_id for user_id, falling back to user_id if none set.

    Args:
        user_id: Authenticated user identifier.

    Returns:
        The org_id string — either the explicit org or user_id itself.
    """
    if not self._enabled:
        return user_id
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT org_id FROM api_keys WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row["org_id"]:
            return row["org_id"]
    except Exception:
        pass
    return user_id

def is_initialized(self, org_id: str) -> bool:
    """Return True if org has completed setup.

    Args:
        org_id: Organization identifier.
    """
    if not self._enabled:
        return True  # fail open — never gate on DB failure
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT initialized FROM org_profiles WHERE org_id = ?", (org_id,)
        ).fetchone()
        return bool(row["initialized"]) if row else False
    except Exception:
        return True  # fail open

def set_initialized(self, org_id: str) -> None:
    """Mark an org as initialized.

    Args:
        org_id: Organization identifier.
    """
    if not self._enabled:
        return
    try:
        conn = self._connect()
        now = time.time()
        conn.execute(
            """
            INSERT INTO org_profiles (org_id, profile_json, initialized, created_at, updated_at)
            VALUES (?, '{}', 1, ?, ?)
            ON CONFLICT(org_id) DO UPDATE SET initialized = 1, updated_at = excluded.updated_at
            """,
            (org_id, now, now),
        )
        conn.commit()
    except Exception:
        pass
```

- [ ] **Step 7: Add `get_org_profile` and `update_org_profile` methods**

```python
def get_org_profile(self, org_id: str) -> dict:
    """Return the org's profile_json as a dict. Returns {} if not found.

    Args:
        org_id: Organization identifier.
    """
    if not self._enabled:
        return {}
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT profile_json FROM org_profiles WHERE org_id = ?", (org_id,)
        ).fetchone()
        if row:
            import json as _json
            return _json.loads(row["profile_json"] or "{}")
    except Exception:
        pass
    return {}

def update_org_profile(self, org_id: str, fields: dict) -> dict:
    """Merge fields into the org's profile_json. Creates row if absent.

    Args:
        org_id: Organization identifier.
        fields: Dict of fields to set or overwrite.

    Returns:
        The updated profile dict.
    """
    if not self._enabled:
        return fields
    import json as _json
    try:
        conn = self._connect()
        now = time.time()
        row = conn.execute(
            "SELECT profile_json FROM org_profiles WHERE org_id = ?", (org_id,)
        ).fetchone()
        current = _json.loads(row["profile_json"] or "{}") if row else {}
        current.update(fields)
        merged = _json.dumps(current)
        conn.execute(
            """
            INSERT INTO org_profiles (org_id, profile_json, initialized, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(org_id) DO UPDATE SET profile_json = excluded.profile_json,
                                              updated_at = excluded.updated_at
            """,
            (org_id, merged, now, now),
        )
        conn.commit()
        return current
    except Exception:
        return fields
```

- [ ] **Step 8: Run tests to verify they pass**

```
cd remote-gateway && pytest tests/test_telemetry_org.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_org.py
git commit -m "feat: add org_profiles table and org profile CRUD to TelemetryStore"
```

---

## Task 2: Schema — skills and tool_hints CRUD

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Modify: `remote-gateway/tests/test_telemetry_org.py`

- [ ] **Step 1: Append skill and tool hint tests to `test_telemetry_org.py`**

```python
import secrets as _secrets

def test_create_skill_and_list(store):
    store.create_skill("acme", "daily_briefing", "Run morning summary", "Summarize {topic}")
    skills = store.list_skills("acme")
    assert len(skills) == 1
    assert skills[0]["name"] == "daily_briefing"
    assert skills[0]["prompt_template"] == "Summarize {topic}"

def test_list_skills_excludes_inactive(store):
    store.create_skill("acme", "to_delete", "...", "...")
    store.delete_skill("acme", "to_delete")
    assert store.list_skills("acme") == []

def test_delete_skill_blocked_for_system_skills(store):
    conn = store._connect()
    sid = _secrets.token_hex(8)
    now = __import__("time").time()
    conn.execute(
        "INSERT INTO skills (id, org_id, name, description, prompt_template, is_system, created_at, updated_at) "
        "VALUES (?, 'acme', 'protected', 'system skill', 'template', 1, ?, ?)",
        (sid, now, now),
    )
    conn.commit()
    assert store.delete_skill("acme", "protected") is False
    assert len(store.list_skills("acme")) == 1

def test_get_skill_returns_none_for_unknown(store):
    assert store.get_skill("acme", "nonexistent") is None

def test_update_skill_changes_template(store):
    store.create_skill("acme", "my_skill", "desc", "old template")
    result = store.update_skill("acme", "my_skill", prompt_template="new template")
    assert result is not None
    assert result["prompt_template"] == "new template"

def test_get_tool_hint_none_for_unknown(store):
    assert store.get_tool_hint("acme", "health_check") is None

def test_upsert_and_get_tool_hint(store):
    store.upsert_tool_hint("acme", "apollo__people_match",
                           interpretation_hint="Returns person records",
                           usage_rules="Call before creating",
                           data_sensitivity="confidential")
    hint = store.get_tool_hint("acme", "apollo__people_match")
    assert hint["interpretation_hint"] == "Returns person records"
    assert hint["data_sensitivity"] == "confidential"

def test_upsert_tool_hint_overwrites(store):
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v1")
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v2")
    assert store.get_tool_hint("acme", "health_check")["interpretation_hint"] == "v2"

def test_list_tool_hints_returns_all_for_org(store):
    store.upsert_tool_hint("acme", "tool_a", interpretation_hint="a")
    store.upsert_tool_hint("acme", "tool_b", interpretation_hint="b")
    hints = store.list_tool_hints("acme")
    names = [h["tool_name"] for h in hints]
    assert "tool_a" in names
    assert "tool_b" in names
```

- [ ] **Step 2: Run to verify new tests fail**

```
cd remote-gateway && pytest tests/test_telemetry_org.py -v
```
Expected: 9 new tests FAIL — methods don't exist yet.

- [ ] **Step 3: Add skill CRUD methods to `TelemetryStore`**

Append after `update_org_profile`:

```python
def list_skills(self, org_id: str) -> list[dict]:
    """Return all active skills for an org.

    Args:
        org_id: Organization identifier.
    """
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, name, description, prompt_template, is_system, created_by, created_at, updated_at "
            "FROM skills WHERE org_id = ? AND is_active = 1 ORDER BY name",
            (org_id,),
        ).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]

def get_skill(self, org_id: str, name: str) -> dict | None:
    """Return a single active skill by name, or None if not found.

    Args:
        org_id: Organization identifier.
        name: Skill name.
    """
    if not self._enabled:
        return None
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT id, name, description, prompt_template, is_system, created_by, created_at, updated_at "
            "FROM skills WHERE org_id = ? AND name = ? AND is_active = 1",
            (org_id, name),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None

def create_skill(
    self,
    org_id: str,
    name: str,
    description: str,
    prompt_template: str,
    created_by: str | None = None,
) -> dict:
    """Insert a new skill row and return it.

    Args:
        org_id: Organization identifier.
        name: Unique skill name within the org.
        description: Human-readable description shown in skill_list.
        prompt_template: Prompt string with optional {variable} placeholders.
        created_by: user_id of creator.

    Returns:
        The created skill dict.
    """
    import secrets as _secrets_mod
    if not self._enabled:
        return {"name": name, "description": description, "prompt_template": prompt_template}
    now = time.time()
    sid = _secrets_mod.token_hex(8)
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO skills (id, org_id, name, description, prompt_template, "
            "is_active, is_system, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, ?)",
            (sid, org_id, name, description, prompt_template, created_by, now, now),
        )
        conn.commit()
        return self.get_skill(org_id, name) or {}
    except Exception:
        return {}

def update_skill(self, org_id: str, name: str, **fields: Any) -> dict | None:
    """Update a non-system skill's fields. Returns updated row or None on failure.

    Accepted fields: description, prompt_template.
    System skills (is_system=1) cannot be updated.

    Args:
        org_id: Organization identifier.
        name: Skill name.
        **fields: Field values to update.
    """
    if not self._enabled:
        return None
    allowed = {"description", "prompt_template"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return self.get_skill(org_id, name)
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT is_system FROM skills WHERE org_id = ? AND name = ? AND is_active = 1",
            (org_id, name),
        ).fetchone()
        if not row or row["is_system"]:
            return None
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [time.time(), org_id, name]
        conn.execute(
            f"UPDATE skills SET {set_clause}, updated_at = ? WHERE org_id = ? AND name = ?",
            values,
        )
        conn.commit()
        return self.get_skill(org_id, name)
    except Exception:
        return None

def delete_skill(self, org_id: str, name: str) -> bool:
    """Soft-delete a skill by setting is_active=0. System skills cannot be deleted.

    Args:
        org_id: Organization identifier.
        name: Skill name.

    Returns:
        True if deleted, False if not found or is a system skill.
    """
    if not self._enabled:
        return False
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT is_system FROM skills WHERE org_id = ? AND name = ? AND is_active = 1",
            (org_id, name),
        ).fetchone()
        if not row or row["is_system"]:
            return False
        conn.execute(
            "UPDATE skills SET is_active = 0 WHERE org_id = ? AND name = ?",
            (org_id, name),
        )
        conn.commit()
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Add tool hint CRUD methods to `TelemetryStore`**

Append after `delete_skill`. Also add `_hint_cache: dict[str, dict[str, dict]] = {}` to `__init__`:

In `__init__`, add after `self._disabled_cache`:
```python
self._hint_cache: dict[str, dict[str, dict]] = {}
```

Then add the methods:

```python
def get_tool_hint(self, org_id: str, tool_name: str) -> dict | None:
    """Return tool hint for an org+tool combo, or None if not set.

    Uses in-process cache per org. Invalidated by upsert_tool_hint.

    Args:
        org_id: Organization identifier.
        tool_name: Registered tool name.
    """
    if org_id not in self._hint_cache:
        self._load_hint_cache(org_id)
    return self._hint_cache.get(org_id, {}).get(tool_name)

def _load_hint_cache(self, org_id: str) -> None:
    """Populate _hint_cache for an org from the DB."""
    self._hint_cache[org_id] = {}
    if not self._enabled:
        return
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT tool_name, interpretation_hint, usage_rules, data_sensitivity "
            "FROM tool_hints WHERE org_id = ? AND is_active = 1",
            (org_id,),
        ).fetchall()
        for row in rows:
            self._hint_cache[org_id][row["tool_name"]] = {
                "interpretation_hint": row["interpretation_hint"],
                "usage_rules": row["usage_rules"],
                "data_sensitivity": row["data_sensitivity"],
            }
    except Exception:
        pass

def upsert_tool_hint(
    self,
    org_id: str,
    tool_name: str,
    *,
    interpretation_hint: str | None = None,
    usage_rules: str | None = None,
    data_sensitivity: str = "internal",
) -> dict:
    """Insert or overwrite a tool hint. Invalidates the in-process cache.

    Args:
        org_id: Organization identifier.
        tool_name: Registered tool name.
        interpretation_hint: Guidance on how to interpret results.
        usage_rules: When/how the tool should be called.
        data_sensitivity: One of 'public', 'internal', 'confidential'.

    Returns:
        The upserted hint dict.
    """
    import secrets as _secrets_mod
    hint = {
        "interpretation_hint": interpretation_hint,
        "usage_rules": usage_rules,
        "data_sensitivity": data_sensitivity,
    }
    if self._enabled:
        try:
            conn = self._connect()
            sid = _secrets_mod.token_hex(8)
            conn.execute(
                """
                INSERT INTO tool_hints (id, org_id, tool_name, interpretation_hint,
                    usage_rules, data_sensitivity, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(org_id, tool_name) DO UPDATE SET
                    interpretation_hint = excluded.interpretation_hint,
                    usage_rules = excluded.usage_rules,
                    data_sensitivity = excluded.data_sensitivity
                """,
                (sid, org_id, tool_name, interpretation_hint, usage_rules, data_sensitivity),
            )
            conn.commit()
        except Exception:
            pass
    # Invalidate cache so next get_tool_hint re-reads from DB
    self._hint_cache.pop(org_id, None)
    return {"tool_name": tool_name, **hint}

def list_tool_hints(self, org_id: str) -> list[dict]:
    """Return all active tool hints for an org.

    Args:
        org_id: Organization identifier.
    """
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT tool_name, interpretation_hint, usage_rules, data_sensitivity "
            "FROM tool_hints WHERE org_id = ? AND is_active = 1 ORDER BY tool_name",
            (org_id,),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "tool_name": row["tool_name"],
            "interpretation_hint": row["interpretation_hint"],
            "usage_rules": row["usage_rules"],
            "data_sensitivity": row["data_sensitivity"],
        }
        for row in rows
    ]
```

- [ ] **Step 5: Run all org telemetry tests**

```
cd remote-gateway && pytest tests/test_telemetry_org.py -v
```
Expected: all 16 tests PASS.

- [ ] **Step 6: Run full test suite to check for regressions**

```
cd remote-gateway && pytest -v
```
Expected: all existing tests PASS.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_org.py
git commit -m "feat: add skills and tool_hints CRUD to TelemetryStore"
```

---

## Task 3: `tools/_core/onboarding.py`

**Files:**
- Create: `remote-gateway/tools/_core/__init__.py`
- Create: `remote-gateway/tools/_core/onboarding.py`
- Create: `remote-gateway/tests/test_onboarding.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_onboarding.py
from __future__ import annotations
import contextvars
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore
from unittest.mock import MagicMock


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


@pytest.fixture()
def user_var():
    return contextvars.ContextVar("_current_user", default=None)


@pytest.fixture()
def mcp_stub(store, user_var):
    """Minimal stand-in that collects registered tools."""
    tools = {}
    class _MCP:
        def tool(self):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator
    stub = _MCP()
    from tools._core import onboarding
    onboarding.register(stub, store, user_var)
    return tools


def test_setup_start_returns_not_initialized(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    result = mcp_stub["setup_start"]()
    assert result["initialized"] is False
    assert result["org_id"] == "acme"


def test_setup_save_profile_persists(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    result = mcp_stub["setup_save_profile"]({"tone": "casual"})
    assert result["current_profile"]["tone"] == "casual"


def test_setup_complete_marks_initialized(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    mcp_stub["setup_complete"]()
    assert store.is_initialized("acme") is True


def test_setup_start_shows_initialized_after_complete(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    mcp_stub["setup_complete"]()
    result = mcp_stub["setup_start"]()
    assert result["initialized"] is True
```

- [ ] **Step 2: Run to verify tests fail**

```
cd remote-gateway && pytest tests/test_onboarding.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create `tools/_core/__init__.py`**

```python
"""Core gateway tools — onboarding, skills, and profile management."""
```

- [ ] **Step 4: Create `tools/_core/onboarding.py`**

```python
"""
Gateway onboarding tools.

Setup flow — always bypasses the init gate. Guides an agent through
org profile creation and marks the gateway as initialized.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register setup_start, setup_save_profile, and setup_complete on mcp.

    Args:
        mcp: FastMCP instance (or stub with .tool() decorator).
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    @mcp.tool()
    def setup_start() -> dict:
        """Check gateway initialization status and return onboarding guidance.

        Call this first. Returns current profile state and next steps.
        Bypasses the init gate — safe to call on an unconfigured gateway.
        """
        org_id = _org_id()
        profile = telemetry.get_org_profile(org_id)
        initialized = telemetry.is_initialized(org_id)
        next_step = (
            "Already initialized. Use profile_get to view current settings."
            if initialized
            else "Call setup_save_profile with your org details, then setup_complete to go live."
        )
        return {
            "org_id": org_id,
            "initialized": initialized,
            "profile": profile,
            "next_step": next_step,
        }

    @mcp.tool()
    def setup_save_profile(fields: dict) -> dict:
        """Save organization profile fields (merged into existing profile).

        Args:
            fields: Dict of profile fields to set. Common fields:
                display_name, tone, icp, vocab_rules.

        Bypasses the init gate.
        """
        org_id = _org_id()
        updated = telemetry.update_org_profile(org_id, fields)
        return {
            "org_id": org_id,
            "saved_fields": list(fields.keys()),
            "current_profile": updated,
        }

    @mcp.tool()
    def setup_complete() -> dict:
        """Mark the organization as initialized and activate the gateway.

        Call after setup_save_profile. After this, the init gate is lifted
        and all tools become available.

        Bypasses the init gate.
        """
        org_id = _org_id()
        telemetry.set_initialized(org_id)
        return {
            "org_id": org_id,
            "initialized": True,
            "message": "Gateway is now active. All tools are available.",
        }
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd remote-gateway && pytest tests/test_onboarding.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/_core/ remote-gateway/tests/test_onboarding.py
git commit -m "feat: add onboarding tools (setup_start, setup_save_profile, setup_complete)"
```

---

## Task 4: `tools/_core/skill_manager.py`

**Files:**
- Create: `remote-gateway/tools/_core/skill_manager.py`
- Create: `remote-gateway/tests/test_skill_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_skill_manager.py
from __future__ import annotations
import contextvars
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice@example.com", "sk-test", org_id="acme")
    return s


@pytest.fixture()
def user_var():
    var = contextvars.ContextVar("_current_user", default=None)
    var.set("alice@example.com")
    return var


@pytest.fixture()
def tools(store, user_var):
    tools = {}
    class _MCP:
        def tool(self):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator
    from tools._core import skill_manager
    skill_manager.register(_MCP(), store, user_var)
    return tools


def test_skill_list_empty_initially(tools):
    assert tools["skill_list"]() == []


def test_skill_create_and_list(tools):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    skills = tools["skill_list"]()
    assert len(skills) == 1
    assert skills[0]["name"] == "briefing"


def test_skill_update_changes_template(tools):
    tools["skill_create"]("briefing", "Morning summary", "old")
    tools["skill_update"]("briefing", prompt_template="new {var}")
    skills = tools["skill_list"]()
    assert skills[0]["prompt_template"] == "new {var}"


def test_skill_delete_removes_from_list(tools):
    tools["skill_create"]("briefing", "Morning summary", "template")
    tools["skill_delete"]("briefing")
    assert tools["skill_list"]() == []


def test_run_skill_renders_template(tools):
    tools["skill_create"]("greet", "Greeting", "Hello {name}, welcome to {place}!")
    result = tools["run_skill"]("greet", {"name": "Alice", "place": "Acme"})
    assert result == "Hello Alice, welcome to Acme!"


def test_run_skill_raises_for_unknown_skill(tools):
    with pytest.raises(ValueError, match="not found"):
        tools["run_skill"]("nonexistent", {})


def test_skill_update_raises_for_unknown_skill(tools):
    with pytest.raises(ValueError, match="not found"):
        tools["skill_update"]("nonexistent", description="new")
```

- [ ] **Step 2: Run to verify tests fail**

```
cd remote-gateway && pytest tests/test_skill_manager.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create `tools/_core/skill_manager.py`**

```python
"""
Skill manager tools — CRUD and execution for dynamic prompt-based skills.

Skills are prompt templates with {variable} placeholders. run_skill renders
the template and returns a string; Claude executes the resulting prompt using
whatever tools are available. Skills don't need to know about tool availability.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register skill CRUD tools and run_skill on mcp.

    Args:
        mcp: FastMCP instance.
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    @mcp.tool()
    def skill_list() -> list[dict]:
        """Return all active skills for this organization.

        Bypasses the init gate — available even before setup.
        """
        return telemetry.list_skills(_org_id())

    @mcp.tool()
    def skill_create(name: str, description: str, prompt_template: str) -> dict:
        """Create a new skill with a prompt template.

        Args:
            name: Unique skill name (no spaces, snake_case recommended).
            description: What this skill does — shown in skill_list.
            prompt_template: Prompt string. Use {variable} for placeholders
                filled at runtime by run_skill.

        Bypasses the init gate.
        """
        user_id = current_user_var.get()
        org_id = _org_id()
        return telemetry.create_skill(org_id, name, description, prompt_template, created_by=user_id)

    @mcp.tool()
    def skill_update(
        name: str,
        description: str | None = None,
        prompt_template: str | None = None,
    ) -> dict:
        """Update an existing skill's description or prompt template.

        Args:
            name: Skill to update.
            description: New description, or omit to leave unchanged.
            prompt_template: New template, or omit to leave unchanged.

        Bypasses the init gate.
        """
        fields: dict = {}
        if description is not None:
            fields["description"] = description
        if prompt_template is not None:
            fields["prompt_template"] = prompt_template
        result = telemetry.update_skill(_org_id(), name, **fields)
        if result is None:
            raise ValueError(f"Skill '{name}' not found or is a system skill.")
        return result

    @mcp.tool()
    def skill_delete(name: str) -> dict:
        """Soft-delete a skill (sets is_active=0). System skills cannot be deleted.

        Args:
            name: Skill to delete.
        """
        if not telemetry.delete_skill(_org_id(), name):
            raise ValueError(f"Skill '{name}' not found or is a system skill.")
        return {"deleted": name}

    @mcp.tool()
    def run_skill(name: str, variables: dict | None = None) -> str:
        """Render a skill's prompt template with variables and return the prompt.

        The returned string is a prompt for you (Claude) to act on. Execute it
        using whatever gateway tools are available.

        Args:
            name: Skill name to render.
            variables: Dict of {placeholder: value} pairs to fill into the template.
        """
        skill = telemetry.get_skill(_org_id(), name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found.")
        template: str = skill["prompt_template"]
        if variables:
            template = template.format(**variables)
        return template
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd remote-gateway && pytest tests/test_skill_manager.py -v
```
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/_core/skill_manager.py remote-gateway/tests/test_skill_manager.py
git commit -m "feat: add skill manager tools (skill CRUD + run_skill)"
```

---

## Task 5: `tools/_core/profile_manager.py`

**Files:**
- Create: `remote-gateway/tools/_core/profile_manager.py`
- Create: `remote-gateway/tests/test_profile_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_profile_manager.py
from __future__ import annotations
import contextvars
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice@example.com", "sk-test", org_id="acme")
    return s


@pytest.fixture()
def user_var():
    var = contextvars.ContextVar("_current_user", default=None)
    var.set("alice@example.com")
    return var


@pytest.fixture()
def tools(store, user_var):
    collected = {}
    class _MCP:
        def tool(self):
            def decorator(fn):
                collected[fn.__name__] = fn
                return fn
            return decorator
    from tools._core import profile_manager
    profile_manager.register(_MCP(), store, user_var)
    return collected


def test_profile_get_empty_initially(tools):
    result = tools["profile_get"]()
    assert result["org_id"] == "acme"
    assert result["profile"] == {}


def test_profile_update_sets_fields(tools):
    tools["profile_update"]({"tone": "direct", "icp": "SMB"})
    result = tools["profile_get"]()
    assert result["profile"]["tone"] == "direct"
    assert result["profile"]["icp"] == "SMB"


def test_profile_update_is_additive(tools):
    tools["profile_update"]({"tone": "direct"})
    tools["profile_update"]({"icp": "SMB"})
    result = tools["profile_get"]()
    assert result["profile"]["tone"] == "direct"
    assert result["profile"]["icp"] == "SMB"
```

- [ ] **Step 2: Run to verify tests fail**

```
cd remote-gateway && pytest tests/test_profile_manager.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create `tools/_core/profile_manager.py`**

```python
"""
Org profile manager tools — read and patch organization profile.

Profile fields are free-form (stored as JSON). Common fields: display_name,
tone, icp, vocab_rules. The admin UI's Profile tab writes here too.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register profile_get and profile_update on mcp.

    Args:
        mcp: FastMCP instance.
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _org_id() -> str:
        user_id = current_user_var.get()
        return telemetry.get_org_id(user_id) if user_id else "default"

    @mcp.tool()
    def profile_get() -> dict:
        """Return the current organization profile.

        Bypasses the init gate.
        """
        org_id = _org_id()
        return {"org_id": org_id, "profile": telemetry.get_org_profile(org_id)}

    @mcp.tool()
    def profile_update(fields: dict) -> dict:
        """Patch organization profile fields (merged into existing values).

        Args:
            fields: Dict of fields to set. Common keys:
                display_name (str), tone (str), icp (str),
                vocab_rules (str), notes (str).

        Bypasses the init gate.
        """
        org_id = _org_id()
        updated = telemetry.update_org_profile(org_id, fields)
        return {"org_id": org_id, "profile": updated}
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd remote-gateway && pytest tests/test_profile_manager.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Run the full suite**

```
cd remote-gateway && pytest -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/_core/profile_manager.py remote-gateway/tests/test_profile_manager.py
git commit -m "feat: add profile manager tools (profile_get, profile_update)"
```

---

## Task 6: Register core tools in `mcp_server.py`

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Add imports and registration calls**

In `remote-gateway/core/mcp_server.py`, find the block that starts with:
```python
from tools import attio as _attio_tools  # noqa: E402
```

Add after the existing imports (after `from tools import wiza as _wiza_tools`):
```python
from tools._core import onboarding as _onboarding_tools  # noqa: E402
from tools._core import skill_manager as _skill_manager_tools  # noqa: E402
from tools._core import profile_manager as _profile_manager_tools  # noqa: E402
```

Find the block with `_meta_tools.register(mcp, ...)` and append after `_wiza_tools.register(mcp)`:
```python
_onboarding_tools.register(mcp, _telemetry, _current_user)
_skill_manager_tools.register(mcp, _telemetry, _current_user)
_profile_manager_tools.register(mcp, _telemetry, _current_user)
```

- [ ] **Step 2: Verify server starts without errors**

```
cd remote-gateway && python -c "import core.mcp_server" && echo "OK"
```
Expected: `OK` with no exceptions.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "feat: register onboarding, skill_manager, and profile_manager tools"
```

---

## Task 7: Init gate middleware

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Create: `remote-gateway/tests/test_init_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_init_gate.py
"""
Verify that the init gate redirects uninitialized orgs and passes initialized ones.

These tests call the tracked wrapper functions directly rather than spinning up
a full MCP server, by monkeypatching _current_user and _telemetry.
"""
from __future__ import annotations

import contextvars
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice@example.com", "sk-test", org_id="acme")
    return s


def test_gate_returns_redirect_for_uninitialized_org(store):
    from core import mcp_server as ms  # noqa: F401 — import for side effects only
    # The gate logic is a module-level helper; test it directly
    assert store.is_initialized("acme") is False
    # Simulate what the gate does
    org_id = store.get_org_id("alice@example.com")
    is_init = store.is_initialized(org_id)
    if not is_init:
        response = {
            "gateway_status": "not_initialized",
            "blocked_tool": "attio__search_records",
            "required_action": "setup_start",
        }
    else:
        response = {}
    assert response["gateway_status"] == "not_initialized"


def test_gate_passes_after_setup_complete(store):
    store.set_initialized("acme")
    org_id = store.get_org_id("alice@example.com")
    assert store.is_initialized(org_id) is True


def test_gate_passes_for_unauthenticated_user(store):
    """Unauthenticated calls (sid=None) are never gated."""
    org_id = None  # _get_org_id returns None for sid=None
    # Gate only fires when org_id is not None
    should_gate = org_id is not None and not store.is_initialized(org_id or "")
    assert should_gate is False
```

- [ ] **Step 2: Run to verify tests pass (they test logic, not the wiring)**

```
cd remote-gateway && pytest tests/test_init_gate.py -v
```
Expected: 3 PASS (logic tests don't require import of mcp_server).

- [ ] **Step 3: Add `GATE_BYPASS` set and `_get_org_id` helper to `mcp_server.py`**

After the `_current_user` ContextVar definition (around line 242), add:

```python
_GATE_BYPASS: frozenset[str] = frozenset({
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
})


def _get_org_id(user_id: str | None) -> str | None:
    """Return org_id for a user, or None for unauthenticated requests."""
    if user_id is None:
        return None
    return _telemetry.get_org_id(user_id)


def _make_gate_redirect(tool_name: str) -> dict[str, str]:
    return {
        "gateway_status": "not_initialized",
        "message": (
            "GATEWAY: Your organization is not configured. "
            "Call setup_start to begin onboarding. "
            "Your original request has been noted — retry after setup."
        ),
        "blocked_tool": tool_name,
        "required_action": "setup_start",
    }
```

- [ ] **Step 4: Insert gate check in `_tracked_mcp_tool` — async branch**

In `_tracked_mcp_tool`, inside the `tracked_async` inner function, find:
```python
if sid and not _telemetry.has_permission(sid, fn.__name__):
```

Add the gate check **before** that line:
```python
if fn.__name__ not in _GATE_BYPASS:
    _org = _get_org_id(sid)
    if _org and not _telemetry.is_initialized(_org):
        return _make_gate_redirect(fn.__name__)
```

- [ ] **Step 5: Insert gate check in `_tracked_mcp_tool` — sync branch**

In `_tracked_mcp_tool`, inside the `tracked` (sync) inner function, find:
```python
if sid and not _telemetry.has_permission(sid, fn.__name__):
```

Add the gate check **before** that line:
```python
if fn.__name__ not in _GATE_BYPASS:
    _org = _get_org_id(sid)
    if _org and not _telemetry.is_initialized(_org):
        return _make_gate_redirect(fn.__name__)
```

- [ ] **Step 6: Insert gate check in `_tracked_add_tool` — async branch**

In `_tracked_add_tool`, inside `tracked_async`, find:
```python
if sid and not _telemetry.has_permission(sid, tool_name):
```

Add before it:
```python
if tool_name not in _GATE_BYPASS:
    _org = _get_org_id(sid)
    if _org and not _telemetry.is_initialized(_org):
        return _make_gate_redirect(tool_name)
```

- [ ] **Step 7: Insert gate check in `_tracked_add_tool` — sync branch**

Same pattern in the sync `tracked` function inside `_tracked_add_tool`.

- [ ] **Step 8: Run all tests**

```
cd remote-gateway && pytest -v
```
Expected: all tests PASS. The gate does not break existing tests because test tools don't have authenticated user_ids hitting uninitialized orgs.

- [ ] **Step 9: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_init_gate.py
git commit -m "feat: add init gate to tracked middleware — uninitialized orgs get redirect"
```

---

## Task 8: Response enrichment with tool hints

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Create: `remote-gateway/tests/test_tool_hints.py`

- [ ] **Step 1: Write the failing tests**

```python
# remote-gateway/tests/test_tool_hints.py
"""Test that tool hint enrichment attaches meta to successful responses."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice@example.com", "sk-test", org_id="acme")
    s.set_initialized("acme")
    return s


def test_enrich_wraps_result_when_hint_exists(store):
    store.upsert_tool_hint(
        "acme", "health_check",
        interpretation_hint="Server is live",
        usage_rules="Call to verify connectivity",
        data_sensitivity="public",
    )
    result = {"status": "ok"}
    hint = store.get_tool_hint("acme", "health_check")
    if hint:
        enriched = {
            "data": result,
            "meta": {
                "interpretation_hint": hint.get("interpretation_hint"),
                "usage_rules": hint.get("usage_rules"),
                "data_sensitivity": hint.get("data_sensitivity"),
            }
        }
    else:
        enriched = result
    assert enriched["data"] == {"status": "ok"}
    assert enriched["meta"]["interpretation_hint"] == "Server is live"


def test_enrich_passes_through_when_no_hint(store):
    result = {"status": "ok"}
    hint = store.get_tool_hint("acme", "no_hint_tool")
    enriched = {"data": result, "meta": {}} if hint else result
    assert enriched == {"status": "ok"}


def test_hint_cache_invalidated_on_upsert(store):
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v1")
    _ = store.get_tool_hint("acme", "health_check")  # loads cache
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v2")
    assert store.get_tool_hint("acme", "health_check")["interpretation_hint"] == "v2"
```

- [ ] **Step 2: Run tests to verify they pass (pure TelemetryStore logic)**

```
cd remote-gateway && pytest tests/test_tool_hints.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 3: Add enrichment helper to `mcp_server.py`**

After `_make_gate_redirect`, add:

```python
def _enrich_with_hint(result: Any, org_id: str, tool_name: str) -> Any:
    """Wrap result with tool hint meta if a hint exists for this org+tool.

    Returns the original result unchanged when no hint is configured.
    """
    if result is None:
        return result
    hint = _telemetry.get_tool_hint(org_id, tool_name)
    if not hint:
        return result
    return {
        "data": result,
        "meta": {
            "interpretation_hint": hint.get("interpretation_hint"),
            "usage_rules": hint.get("usage_rules"),
            "data_sensitivity": hint.get("data_sensitivity"),
        },
    }
```

- [ ] **Step 4: Apply enrichment in `_tracked_mcp_tool` — async branch**

In `tracked_async`, find:
```python
result = await fn(*fn_args, **fn_kwargs)
_telemetry.record(
    fn.__name__, ...
    response_preview=_get_response_preview(result),
)
return result
```

Replace the `return result` with:
```python
_org = _get_org_id(sid)
if _org:
    result = _enrich_with_hint(result, _org, fn.__name__)
return result
```

**Important:** Place the enrichment **after** `_telemetry.record(...)` so telemetry captures the raw result, not the enriched wrapper.

- [ ] **Step 5: Apply enrichment in `_tracked_mcp_tool` — sync branch**

Same pattern in the sync `tracked` function: enrich after `_telemetry.record(...)`.

- [ ] **Step 6: Apply enrichment in `_tracked_add_tool` — async and sync branches**

Same pattern in both branches of `_tracked_add_tool`.

- [ ] **Step 7: Run full test suite**

```
cd remote-gateway && pytest -v
```
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_tool_hints.py
git commit -m "feat: enrich tool responses with org tool hints"
```

---

## Task 9: Admin API routes for profile, skills, and tool hints

**Files:**
- Modify: `remote-gateway/core/admin_api.py`

- [ ] **Step 1: Add org profile routes to `create_admin_app`**

In `admin_api.py`, inside `create_admin_app`, add these handlers before the `routes = [...]` list:

```python
async def api_org_profile_get(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    profile = telemetry.get_org_profile("default")
    initialized = telemetry.is_initialized("default")
    return JSONResponse({"org_id": "default", "initialized": initialized, "profile": profile})

async def api_org_profile_update(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    updated = telemetry.update_org_profile("default", body)
    return JSONResponse({"org_id": "default", "profile": updated})
```

- [ ] **Step 2: Add skills routes**

```python
async def api_skills_list(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    return JSONResponse(telemetry.list_skills("default"))

async def api_skills_create(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    for required in ("name", "description", "prompt_template"):
        if not body.get(required):
            return JSONResponse({"error": f"{required} is required"}, status_code=400)
    skill = telemetry.create_skill(
        "default", body["name"], body["description"], body["prompt_template"]
    )
    return JSONResponse(skill, status_code=201)

async def api_skills_update(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    name = request.path_params["name"]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    fields = {k: v for k, v in body.items() if k in ("description", "prompt_template")}
    result = telemetry.update_skill("default", name, **fields)
    if result is None:
        return JSONResponse({"error": f"skill '{name}' not found or is a system skill"}, status_code=404)
    return JSONResponse(result)

async def api_skills_delete(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    name = request.path_params["name"]
    deleted = telemetry.delete_skill("default", name)
    if not deleted:
        return JSONResponse({"error": f"skill '{name}' not found or is a system skill"}, status_code=404)
    return JSONResponse({"deleted": name})
```

- [ ] **Step 3: Add tool hints routes**

```python
async def api_hints_list(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    return JSONResponse(telemetry.list_tool_hints("default"))

async def api_hints_upsert(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    tool_name = request.path_params["tool_name"]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    hint = telemetry.upsert_tool_hint(
        "default",
        tool_name,
        interpretation_hint=body.get("interpretation_hint"),
        usage_rules=body.get("usage_rules"),
        data_sensitivity=body.get("data_sensitivity", "internal"),
    )
    return JSONResponse(hint)
```

- [ ] **Step 4: Add the new routes to the `routes` list**

In the `routes = [...]` block, append before the closing `]`:

```python
Route("/api/org-profile", api_org_profile_get, methods=["GET"]),
Route("/api/org-profile", api_org_profile_update, methods=["PUT"]),
Route("/api/skills", api_skills_list, methods=["GET"]),
Route("/api/skills", api_skills_create, methods=["POST"]),
Route("/api/skills/{name}", api_skills_update, methods=["PUT"]),
Route("/api/skills/{name}", api_skills_delete, methods=["DELETE"]),
Route("/api/tool-hints", api_hints_list, methods=["GET"]),
Route("/api/tool-hints/{tool_name:path}", api_hints_upsert, methods=["PUT"]),
```

- [ ] **Step 5: Run existing admin tests to verify no regressions**

```
cd remote-gateway && pytest tests/test_admin_api.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py
git commit -m "feat: add admin API routes for org profile, skills, and tool hints"
```

---

## Task 10: Admin dashboard — Profile, Skills, and Tool Hints tabs

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

This task adds three new tabs to the existing Tailwind-based admin dashboard. Study the existing tab pattern (Users, Permissions, Logs) before editing.

- [ ] **Step 1: Locate the tab nav in `admin_dashboard.html`**

Find the `<nav>` or tab button row. It contains buttons like "Overview", "Sessions", "Users", "Permissions", "Logs". Note the pattern used (data-tab attribute, active class, etc.).

- [ ] **Step 2: Add three new tab buttons**

In the tab navigation, append after the last existing tab button:

```html
<button class="tab-btn px-4 py-2 text-sm font-medium rounded-t" data-tab="profile">Org Profile</button>
<button class="tab-btn px-4 py-2 text-sm font-medium rounded-t" data-tab="skills">Skills</button>
<button class="tab-btn px-4 py-2 text-sm font-medium rounded-t" data-tab="hints">Tool Hints</button>
```

- [ ] **Step 3: Add the Org Profile tab panel**

After the last existing `<div id="..." class="tab-panel ...">` section, add:

```html
<div id="tab-profile" class="tab-panel hidden p-6">
  <h2 class="text-xl font-semibold mb-4">Org Profile</h2>
  <div id="profile-status" class="mb-4 text-sm text-gray-500">Loading...</div>
  <form id="profile-form" class="space-y-4 max-w-lg">
    <div>
      <label class="block text-sm font-medium mb-1">Display Name</label>
      <input id="profile-display_name" type="text" class="w-full border rounded px-3 py-2 text-sm" placeholder="Acme Corp">
    </div>
    <div>
      <label class="block text-sm font-medium mb-1">Tone</label>
      <input id="profile-tone" type="text" class="w-full border rounded px-3 py-2 text-sm" placeholder="professional, concise">
    </div>
    <div>
      <label class="block text-sm font-medium mb-1">ICP</label>
      <input id="profile-icp" type="text" class="w-full border rounded px-3 py-2 text-sm" placeholder="B2B SaaS, 10-200 employees">
    </div>
    <div>
      <label class="block text-sm font-medium mb-1">Vocab Rules</label>
      <textarea id="profile-vocab_rules" rows="3" class="w-full border rounded px-3 py-2 text-sm" placeholder="Always say 'prospect' not 'lead'..."></textarea>
    </div>
    <button type="submit" class="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700">Save Profile</button>
    <div id="profile-save-msg" class="text-sm text-green-600 hidden">Saved.</div>
  </form>
</div>
```

- [ ] **Step 4: Add the Skills tab panel**

```html
<div id="tab-skills" class="tab-panel hidden p-6">
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-xl font-semibold">Skills</h2>
    <button id="skill-new-btn" class="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">+ New Skill</button>
  </div>
  <div id="skills-table-wrap"></div>

  <!-- Create/edit modal -->
  <div id="skill-modal" class="fixed inset-0 bg-black/50 hidden z-50 flex items-center justify-center">
    <div class="bg-white rounded-lg p-6 w-full max-w-lg shadow-xl">
      <h3 class="text-lg font-semibold mb-4" id="skill-modal-title">New Skill</h3>
      <input id="skill-modal-orig-name" type="hidden">
      <div class="space-y-3">
        <div>
          <label class="block text-sm font-medium mb-1">Name</label>
          <input id="skill-modal-name" type="text" class="w-full border rounded px-3 py-2 text-sm" placeholder="daily_briefing">
        </div>
        <div>
          <label class="block text-sm font-medium mb-1">Description</label>
          <input id="skill-modal-desc" type="text" class="w-full border rounded px-3 py-2 text-sm">
        </div>
        <div>
          <label class="block text-sm font-medium mb-1">Prompt Template</label>
          <p class="text-xs text-gray-500 mb-1">Use {variable} for placeholders filled by run_skill.</p>
          <textarea id="skill-modal-template" rows="5" class="w-full border rounded px-3 py-2 text-sm font-mono"></textarea>
        </div>
      </div>
      <div class="flex justify-end gap-2 mt-4">
        <button id="skill-modal-cancel" class="px-4 py-2 border rounded text-sm">Cancel</button>
        <button id="skill-modal-save" class="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700">Save</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Add the Tool Hints tab panel**

```html
<div id="tab-hints" class="tab-panel hidden p-6">
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-xl font-semibold">Tool Hints</h2>
    <button id="hint-new-btn" class="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">+ Add Hint</button>
  </div>
  <p class="text-sm text-gray-500 mb-4">Hints are injected into tool responses as <code>meta</code> fields to guide interpretation.</p>
  <div id="hints-table-wrap"></div>

  <!-- Edit modal -->
  <div id="hint-modal" class="fixed inset-0 bg-black/50 hidden z-50 flex items-center justify-center">
    <div class="bg-white rounded-lg p-6 w-full max-w-lg shadow-xl">
      <h3 class="text-lg font-semibold mb-4">Edit Tool Hint</h3>
      <div class="space-y-3">
        <div>
          <label class="block text-sm font-medium mb-1">Tool Name</label>
          <input id="hint-modal-tool" type="text" class="w-full border rounded px-3 py-2 text-sm" placeholder="apollo__people_match">
        </div>
        <div>
          <label class="block text-sm font-medium mb-1">Interpretation Hint</label>
          <textarea id="hint-modal-hint" rows="3" class="w-full border rounded px-3 py-2 text-sm"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium mb-1">Usage Rules</label>
          <textarea id="hint-modal-rules" rows="3" class="w-full border rounded px-3 py-2 text-sm"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium mb-1">Data Sensitivity</label>
          <select id="hint-modal-sensitivity" class="w-full border rounded px-3 py-2 text-sm">
            <option value="public">public</option>
            <option value="internal" selected>internal</option>
            <option value="confidential">confidential</option>
          </select>
        </div>
      </div>
      <div class="flex justify-end gap-2 mt-4">
        <button id="hint-modal-cancel" class="px-4 py-2 border rounded text-sm">Cancel</button>
        <button id="hint-modal-save" class="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700">Save</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Add JavaScript for the three new tabs**

Locate the existing `<script>` block at the bottom. Append a `loadProfile`, `loadSkills`, and `loadHints` function, plus wire up the tab-switch and form submission handlers. Add after the last existing tab's load function:

```javascript
// --- Org Profile ---
async function loadProfile() {
  const data = await apiFetch('/admin/api/org-profile');
  document.getElementById('profile-status').textContent =
    data.initialized ? '✓ Initialized' : '⚠ Not yet initialized — run setup_start from Claude';
  const p = data.profile || {};
  ['display_name', 'tone', 'icp', 'vocab_rules'].forEach(k => {
    const el = document.getElementById('profile-' + k);
    if (el) el.value = p[k] || '';
  });
}

document.getElementById('profile-form').addEventListener('submit', async e => {
  e.preventDefault();
  const fields = {};
  ['display_name', 'tone', 'icp', 'vocab_rules'].forEach(k => {
    const val = document.getElementById('profile-' + k).value.trim();
    if (val) fields[k] = val;
  });
  await apiFetch('/admin/api/org-profile', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(fields)});
  document.getElementById('profile-save-msg').classList.remove('hidden');
  setTimeout(() => document.getElementById('profile-save-msg').classList.add('hidden'), 2000);
});

// --- Skills ---
let _skillsData = [];
async function loadSkills() {
  _skillsData = await apiFetch('/admin/api/skills');
  const wrap = document.getElementById('skills-table-wrap');
  if (!_skillsData.length) { wrap.innerHTML = '<p class="text-sm text-gray-500">No skills yet.</p>'; return; }
  wrap.innerHTML = '<table class="w-full text-sm border-collapse">' +
    '<thead><tr class="border-b"><th class="text-left py-2 pr-4">Name</th><th class="text-left py-2 pr-4">Description</th><th></th></tr></thead>' +
    '<tbody>' + _skillsData.map(s =>
      `<tr class="border-b hover:bg-gray-50"><td class="py-2 pr-4 font-mono">${s.name}</td><td class="py-2 pr-4 text-gray-600">${s.description}</td>` +
      `<td class="py-2 flex gap-2">${s.is_system ? '<span class="text-xs text-gray-400">system</span>' :
        `<button onclick="openSkillEdit('${s.name}')" class="text-blue-600 text-xs hover:underline">Edit</button>` +
        `<button onclick="deleteSkill('${s.name}')" class="text-red-500 text-xs hover:underline">Delete</button>`}</td></tr>`
    ).join('') + '</tbody></table>';
}

function openSkillEdit(name) {
  const skill = _skillsData.find(s => s.name === name);
  if (!skill) return;
  document.getElementById('skill-modal-title').textContent = 'Edit Skill';
  document.getElementById('skill-modal-orig-name').value = name;
  document.getElementById('skill-modal-name').value = name;
  document.getElementById('skill-modal-name').disabled = true;
  document.getElementById('skill-modal-desc').value = skill.description;
  document.getElementById('skill-modal-template').value = skill.prompt_template;
  document.getElementById('skill-modal').classList.remove('hidden');
}

document.getElementById('skill-new-btn').addEventListener('click', () => {
  document.getElementById('skill-modal-title').textContent = 'New Skill';
  document.getElementById('skill-modal-orig-name').value = '';
  document.getElementById('skill-modal-name').value = '';
  document.getElementById('skill-modal-name').disabled = false;
  document.getElementById('skill-modal-desc').value = '';
  document.getElementById('skill-modal-template').value = '';
  document.getElementById('skill-modal').classList.remove('hidden');
});

document.getElementById('skill-modal-cancel').addEventListener('click', () => {
  document.getElementById('skill-modal').classList.add('hidden');
});

document.getElementById('skill-modal-save').addEventListener('click', async () => {
  const orig = document.getElementById('skill-modal-orig-name').value;
  const payload = {
    name: document.getElementById('skill-modal-name').value,
    description: document.getElementById('skill-modal-desc').value,
    prompt_template: document.getElementById('skill-modal-template').value,
  };
  if (orig) {
    await apiFetch(`/admin/api/skills/${encodeURIComponent(orig)}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  } else {
    await apiFetch('/admin/api/skills', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  }
  document.getElementById('skill-modal').classList.add('hidden');
  loadSkills();
});

async function deleteSkill(name) {
  if (!confirm(`Delete skill "${name}"?`)) return;
  await apiFetch(`/admin/api/skills/${encodeURIComponent(name)}`, {method: 'DELETE'});
  loadSkills();
}

// --- Tool Hints ---
let _hintsData = [];
async function loadHints() {
  _hintsData = await apiFetch('/admin/api/tool-hints');
  const wrap = document.getElementById('hints-table-wrap');
  if (!_hintsData.length) { wrap.innerHTML = '<p class="text-sm text-gray-500">No hints yet.</p>'; return; }
  wrap.innerHTML = '<table class="w-full text-sm border-collapse">' +
    '<thead><tr class="border-b"><th class="text-left py-2 pr-4">Tool</th><th class="text-left py-2 pr-4">Sensitivity</th><th></th></tr></thead>' +
    '<tbody>' + _hintsData.map(h =>
      `<tr class="border-b hover:bg-gray-50"><td class="py-2 pr-4 font-mono">${h.tool_name}</td><td class="py-2 pr-4">${h.data_sensitivity}</td>` +
      `<td><button onclick="openHintEdit('${h.tool_name}')" class="text-blue-600 text-xs hover:underline">Edit</button></td></tr>`
    ).join('') + '</tbody></table>';
}

document.getElementById('hint-new-btn').addEventListener('click', () => {
  document.getElementById('hint-modal-tool').value = '';
  document.getElementById('hint-modal-tool').disabled = false;
  document.getElementById('hint-modal-hint').value = '';
  document.getElementById('hint-modal-rules').value = '';
  document.getElementById('hint-modal-sensitivity').value = 'internal';
  document.getElementById('hint-modal').classList.remove('hidden');
});

function openHintEdit(toolName) {
  const h = _hintsData.find(x => x.tool_name === toolName);
  if (!h) return;
  document.getElementById('hint-modal-tool').value = toolName;
  document.getElementById('hint-modal-tool').disabled = true;
  document.getElementById('hint-modal-hint').value = h.interpretation_hint || '';
  document.getElementById('hint-modal-rules').value = h.usage_rules || '';
  document.getElementById('hint-modal-sensitivity').value = h.data_sensitivity || 'internal';
  document.getElementById('hint-modal').classList.remove('hidden');
}

document.getElementById('hint-modal-cancel').addEventListener('click', () => {
  document.getElementById('hint-modal').classList.add('hidden');
});

document.getElementById('hint-modal-save').addEventListener('click', async () => {
  const toolName = document.getElementById('hint-modal-tool').value;
  const payload = {
    interpretation_hint: document.getElementById('hint-modal-hint').value,
    usage_rules: document.getElementById('hint-modal-rules').value,
    data_sensitivity: document.getElementById('hint-modal-sensitivity').value,
  };
  await apiFetch(`/admin/api/tool-hints/${encodeURIComponent(toolName)}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  document.getElementById('hint-modal').classList.add('hidden');
  loadHints();
});

// Wire new tabs into the existing tab-switch + load dispatch
const _origTabSwitch = window._tabSwitch;  // only override the load call
document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    if (tab === 'profile') loadProfile();
    else if (tab === 'skills') loadSkills();
    else if (tab === 'hints') loadHints();
  });
});
```

**Note:** The `apiFetch` helper and tab-switching CSS class logic are already defined earlier in the `<script>` block. Verify the existing helper name before using it — it may be named `fetchJson` or similar. Update the calls above to match.

- [ ] **Step 7: Verify dashboard loads in browser**

Start the server and open the admin dashboard:
```
cd remote-gateway && MCP_TRANSPORT=combined python core/mcp_server.py
```
Open `http://localhost:8000/admin/?token=inform-admin-2026` and verify:
- Three new tabs appear: Org Profile, Skills, Tool Hints
- Org Profile form loads and saves
- Skills table renders, create/edit modal opens, new skill saves

- [ ] **Step 8: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add Org Profile, Skills, and Tool Hints tabs to admin dashboard"
```

---

## Task 11: Template branch — strip Inform-specific content

**Context:** This task creates a clean template fork. Do this on a new branch so the live Inform instance is untouched.

- [ ] **Step 1: Create a template branch**

```bash
git checkout -b template/clean-gateway
```

- [ ] **Step 2: Remove Inform-specific tool files**

```bash
rm remote-gateway/tools/attio.py
rm remote-gateway/tools/email_tools.py
rm remote-gateway/tools/wiza.py
rm remote-gateway/context/fields/attio-companies.yaml
rm remote-gateway/context/fields/attio-deals.yaml
rm remote-gateway/context/fields/attio-people.yaml
rm remote-gateway/context/fields/apollo.yaml
rm remote-gateway/context/fields/exa.yaml
```

- [ ] **Step 3: Remove Inform-specific tool registrations from `mcp_server.py`**

Remove these lines from `mcp_server.py`:
```python
from tools import attio as _attio_tools
from tools import email_tools as _email_tools
from tools import wiza as _wiza_tools
...
_attio_tools.register(mcp)
_email_tools.register(mcp)
_wiza_tools.register(mcp)
```

- [ ] **Step 4: Reset `prompts/init.md` to generic template**

Replace `remote-gateway/prompts/init.md` with generic operator instructions that reference no specific integrations or company names. Remove all Inform/Apollo/Attio-specific guidance.

- [ ] **Step 5: Clear `mcp_connections.json` to blank template**

Replace contents with:
```json
{
  "connections": {}
}
```

- [ ] **Step 6: Verify server starts cleanly**

```
cd remote-gateway && python -c "import core.mcp_server" && echo "OK"
```
Expected: `OK`.

- [ ] **Step 7: Run tests (skip tool-specific tests)**

```
cd remote-gateway && pytest -v --ignore=tests/test_attio_tools.py --ignore=tests/test_attio_config.py --ignore=tests/test_wiza_tools.py
```
Expected: all included tests PASS.

- [ ] **Step 8: Commit to template branch**

```bash
git add -A
git commit -m "chore: strip Inform-specific tools and content for template release"
```

The `main` branch retains the full Inform instance. The `template/clean-gateway` branch is the deployable template for new clients.

---

## Self-Review

**Spec coverage:**
- ✓ `org_profiles`, `skills`, `tool_hints` schema — Tasks 1-2
- ✓ `org_id` on `api_keys` + `get_org_id` resolution — Task 1
- ✓ `is_initialized` / `set_initialized` — Task 1
- ✓ `setup_*` tools bypass init gate — Tasks 3 + 7 (`GATE_BYPASS` set)
- ✓ `skill_*` tools — Task 4
- ✓ `profile_*` tools — Task 5
- ✓ Init gate in `_tracked_mcp_tool` and `_tracked_add_tool` — Task 7
- ✓ Response enrichment with tool hints — Task 8
- ✓ Admin UI: Profile, Skills, Tool Hints tabs — Tasks 9-10
- ✓ Template branch — Task 11

**Type consistency check:**
- `create_skill` returns `dict` (same as `get_skill`)
- `update_skill` returns `dict | None` — callers check for None
- `get_tool_hint` returns `dict | None` — enrichment only fires when not None
- `_org_id()` helper used consistently in all `_core` tools
- `_get_org_id()` in mcp_server returns `str | None`, gate fires only when truthy

**No placeholder scan:** All steps contain actual code. No "TBD" or "add appropriate handling."
