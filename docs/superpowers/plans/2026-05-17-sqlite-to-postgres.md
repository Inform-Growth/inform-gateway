# SQLite → PostgreSQL Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SQLite-backed `TelemetryStore` with a PostgreSQL backend using Railway Postgres, so that each gateway deployment has its own persistent, production-grade database.

**Architecture:** `telemetry.py` is a self-contained module — all changes are confined to it plus its test fixtures. The public API of `TelemetryStore` does not change (same methods, same return types). The constructor changes from `db_path: Path` to `dsn: str`. Connection management moves from a single persistent `sqlite3.Connection` to a persistent `psycopg2` connection with a `_cursor()` context manager for per-operation transactions. The test suite switches from `tmp_path`-backed SQLite fixtures to `pytest-postgresql`-backed real Postgres fixtures.

**Tech Stack:** `psycopg2-binary` (driver), `pytest-postgresql` (test Postgres), Railway Postgres (production, auto-injects `DATABASE_URL`).

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add psycopg2-binary to runtime deps and pytest-postgresql to dev deps**

Edit `pyproject.toml`:

```toml
[project]
name = "inform-gateway"
version = "0.1.0"
description = "Agentic GitOps monorepo: local R&D sandbox + centralized MCP gateway"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]",
    "fastapi",
    "uvicorn[standard]",
    "openai",
    "httpx",
    "pyyaml",
    "psycopg2-binary",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "python-dotenv",
    "ruff",
    "pytest-postgresql",
]
```

- [ ] **Step 2: Install**

Run:
```bash
pip install -e ".[dev]"
```

Expected: no errors, `psycopg2` and `pytest_postgresql` are importable.

- [ ] **Step 3: Verify**

Run:
```bash
python -c "import psycopg2; import pytest_postgresql; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add psycopg2-binary and pytest-postgresql deps"
```

---

### Task 2: Test infrastructure — conftest.py

**Files:**
- Create: `remote-gateway/tests/conftest.py`

The `store` fixture is currently defined identically in every test file as:
```python
@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")
```
We centralise it in `conftest.py` backed by a real Postgres instance.

- [ ] **Step 1: Write the failing test (verify conftest structure)**

There is no dedicated test to write here — the conftest fixture will be exercised by existing tests after we remove the per-file fixtures in Task 3. Skip to implementation.

- [ ] **Step 2: Create conftest.py**

Create `remote-gateway/tests/conftest.py`:

```python
"""Shared pytest fixtures for the remote-gateway test suite.

Provides a function-scoped ``store`` fixture backed by a real PostgreSQL
instance (via pytest-postgresql). Each test gets an isolated database.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
import pytest
from pytest_postgresql import factories

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from telemetry import TelemetryStore

postgresql_proc = factories.postgresql_proc()
postgresql = factories.postgresql("postgresql_proc")


@pytest.fixture()
def store(postgresql):
    """Function-scoped TelemetryStore backed by a fresh Postgres database."""
    params = postgresql.get_dsn_parameters()
    dsn = " ".join(f"{k}={v}" for k, v in params.items() if v)
    return TelemetryStore(dsn=dsn)
```

- [ ] **Step 3: Commit conftest**

```bash
git add remote-gateway/tests/conftest.py
git commit -m "test: add conftest.py with pytest-postgresql store fixture"
```

---

### Task 3: Update all test fixtures to use the new `dsn=` signature

**Files:**
- Modify: every test file that defines a `store` fixture with `db_path=`
- Modify: `test_telemetry_permissions.py` (inline instantiation in test bodies)
- Modify: `test_tool_visibility.py` (`_make_store` helper + disabled-state test)

After this task ALL tests will fail — that is expected. They will pass after Task 4.

#### 3a — Files where `store` fixture is the only change

For each file listed below, **delete** the `store` fixture (the `@pytest.fixture()` block that creates `TelemetryStore(db_path=...)`) so the conftest.py version is used automatically. Also remove `tmp_path` from any remaining fixtures that no longer need it, and remove any now-unused `from pathlib import Path` imports.

Files to update:
- `remote-gateway/tests/test_admin_api.py` (delete lines 27-28)
- `remote-gateway/tests/test_admin_routes.py` (delete lines 30-31)
- `remote-gateway/tests/test_init_gate.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_intent_overrides.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_onboarding.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_profile_manager.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_skill_manager.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_skill_permissions.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_task_gate.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_task_manager.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_telemetry_org.py` (delete the `store` fixture block)
- `remote-gateway/tests/test_tool_hints.py` (delete the `store` fixture block)

In every case, the fixture block to delete looks like:
```python
@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")
```
or the variant that adds extra setup before returning.

- [ ] **Step 1: Delete per-file `store` fixtures from the 12 files listed above**

Run after each file to catch syntax errors:
```bash
python -c "import ast; ast.parse(open('remote-gateway/tests/<filename>.py').read()); print('ok')"
```

#### 3b — `test_telemetry_permissions.py`: inline instantiation

Five test functions create `TelemetryStore` inline (not via fixture). Change each one:

```python
# BEFORE (lines 151, 157, 168, 182, 194 — same pattern):
def test_daily_activity_by_user_empty(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")

# AFTER:
def test_daily_activity_by_user_empty(store):
    # `store` is now the conftest fixture
```

Also delete the file-level `store` fixture from this file.

- [ ] **Step 2: Update test_telemetry_permissions.py**

For the five functions that take `tmp_path` and create a local store:
1. Change the function signature from `(tmp_path)` to `(store)`
2. Delete the `store = TelemetryStore(db_path=tmp_path / "test.db")` line inside the function body
3. The rest of the test body is unchanged

#### 3c — `test_tool_visibility.py`: `_make_store` helper

This file uses a local `_make_store(tmp_path)` helper and one test specifically tests the disabled (bad path) state.

- [ ] **Step 3: Update test_tool_visibility.py**

Change `_make_store` to accept a `store` fixture instead of `tmp_path`:

```python
# BEFORE:
def _make_store(tmp_path: Path) -> TelemetryStore:
    """Return a fresh TelemetryStore backed by a temp DB."""
    return TelemetryStore(db_path=tmp_path / "test.db")
```

Delete this helper entirely. In every test that called `_make_store(tmp_path)`, change:
- `def test_xxx(tmp_path):` → `def test_xxx(store):`
- `store = _make_store(tmp_path)` → (delete this line, `store` is the parameter)

For `test_filter_fails_open_when_disabled` (the disabled-state test):

```python
# BEFORE:
def test_filter_fails_open_when_disabled(tmp_path):
    """If telemetry is disabled (bad DB path), filter returns full list."""
    store = TelemetryStore(db_path=Path("/nonexistent/path/db.sqlite"))
    result = store.filter_visible_tools("user_abc", ["tool_a", "tool_b"])
    assert result == {"tool_a", "tool_b"}

# AFTER:
def test_filter_fails_open_when_disabled():
    """If telemetry is disabled (bad DSN), filter returns full list."""
    store = TelemetryStore(dsn="postgresql://invalid:5432/nodb")
    result = store.filter_visible_tools("user_abc", ["tool_a", "tool_b"])
    assert result == {"tool_a", "tool_b"}
```

- [ ] **Step 4: Run tests — confirm all fail with `TypeError: __init__() got unexpected keyword argument 'dsn'`**

```bash
cd /path/to/inform-gateway && pytest remote-gateway/tests/test_task_manager.py -x 2>&1 | head -20
```

Expected: `TypeError` or similar — TelemetryStore doesn't accept `dsn` yet.

- [ ] **Step 5: Commit test changes**

```bash
git add remote-gateway/tests/
git commit -m "test: migrate all store fixtures to pg_dsn via conftest"
```

---

### Task 4: Rewrite telemetry.py for PostgreSQL

**Files:**
- Modify: `remote-gateway/core/telemetry.py`

This is the main migration. All changes are in one file. Work top to bottom.

#### 4a — Imports and module-level constants

- [ ] **Step 1: Replace imports and `_DB_PATH`**

At the top of the file, make these changes:

```python
# REMOVE these imports:
import sqlite3
from pathlib import Path

# ADD these imports (after `import os`):
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
import psycopg2.extras
```

Replace the `_DB_PATH` constant:

```python
# REMOVE:
_DB_PATH = Path(os.environ.get("TELEMETRY_DB_PATH", "data/telemetry.db"))

# ADD:
_DSN = os.environ.get("DATABASE_URL", "")
```

#### 4b — Replace `_SCHEMA_TABLES` and `_SCHEMA_INDEXES` with statement lists

- [ ] **Step 2: Replace schema SQL**

Remove the entire `_SCHEMA_TABLES` string and `_SCHEMA_INDEXES` string. Replace with two lists of individual statements:

```python
_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        key         TEXT             PRIMARY KEY,
        user_id     TEXT             NOT NULL,
        created_at  DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        id            BIGSERIAL        PRIMARY KEY,
        tool_name     TEXT             NOT NULL,
        called_at     DOUBLE PRECISION NOT NULL,
        duration_ms   INTEGER          NOT NULL,
        success       INTEGER          NOT NULL,
        error_type    TEXT,
        error_message TEXT,
        user_id       TEXT,
        request_id    TEXT,
        response_size INTEGER,
        input_body    TEXT,
        response_preview TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_permissions (
        user_id   TEXT    NOT NULL,
        tool_name TEXT    NOT NULL,
        enabled   INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (user_id, tool_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS org_profiles (
        org_id       TEXT             PRIMARY KEY,
        display_name TEXT,
        profile_json TEXT             NOT NULL DEFAULT '{}',
        initialized  INTEGER          NOT NULL DEFAULT 0,
        created_at   DOUBLE PRECISION NOT NULL,
        updated_at   DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skills (
        id              TEXT             PRIMARY KEY,
        org_id          TEXT             NOT NULL,
        name            TEXT             NOT NULL,
        description     TEXT             NOT NULL,
        prompt_template TEXT             NOT NULL,
        is_active       INTEGER          NOT NULL DEFAULT 1,
        is_system       INTEGER          NOT NULL DEFAULT 0,
        created_by      TEXT,
        created_at      DOUBLE PRECISION NOT NULL,
        updated_at      DOUBLE PRECISION NOT NULL,
        UNIQUE(org_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_permissions (
        user_id    TEXT    NOT NULL,
        skill_name TEXT    NOT NULL,
        enabled    INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (user_id, skill_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_intent_overrides (
        user_id         TEXT    NOT NULL,
        tool_name       TEXT    NOT NULL,
        requires_intent INTEGER NOT NULL,
        PRIMARY KEY (user_id, tool_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_hints (
        id                  TEXT PRIMARY KEY,
        org_id              TEXT NOT NULL,
        tool_name           TEXT NOT NULL,
        interpretation_hint TEXT,
        usage_rules         TEXT,
        data_sensitivity    TEXT DEFAULT 'internal',
        is_active           INTEGER NOT NULL DEFAULT 1,
        UNIQUE(org_id, tool_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id      TEXT             PRIMARY KEY,
        user_id      TEXT             NOT NULL,
        org_id       TEXT             NOT NULL,
        goal         TEXT             NOT NULL,
        steps        TEXT             NOT NULL DEFAULT '[]',
        status       TEXT             NOT NULL DEFAULT 'active',
        outcome      TEXT,
        created_at   DOUBLE PRECISION NOT NULL,
        completed_at DOUBLE PRECISION
    )
    """,
]

_SCHEMA_INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls (tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_called_at ON tool_calls (called_at)",
    "CREATE INDEX IF NOT EXISTS idx_user_id   ON tool_calls (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_org_created ON tasks (org_id, created_at)",
]
```

Note: `_MIGRATIONS` stays exactly as-is — the `ALTER TABLE ... ADD COLUMN` syntax is identical in Postgres.

#### 4c — Replace `TelemetryStore.__init__`, `_setup`, `_migrate`, `_connect`, add `_cursor`

- [ ] **Step 3: Replace the class docstring and constructor**

```python
class TelemetryStore:
    """PostgreSQL-backed store for gateway tool call metrics and API key management."""

    def __init__(self, dsn: str = _DSN) -> None:
        self._dsn = dsn
        self._enabled = False
        self._disabled_cache: dict[str, set[str]] = {}
        self._disabled_skills_cache: dict[str, set[str]] = {}
        self._hint_cache: dict[str, dict[str, dict]] = {}
        self._conn: Any = None
        self._setup()
        self._load_disabled_cache()
        self._load_disabled_skills_cache()
```

- [ ] **Step 4: Rewrite `_setup`**

```python
def _setup(self) -> None:
    """Connect to Postgres, create schema, run migrations. Disables on any failure."""
    if not self._dsn:
        print("[telemetry] disabled — DATABASE_URL not set", flush=True)
        return
    try:
        conn = psycopg2.connect(self._dsn)
        with conn.cursor() as cur:
            for stmt in _SCHEMA_STATEMENTS:
                cur.execute(stmt)
            self._migrate_pg(cur)
            for stmt in _SCHEMA_INDEX_STATEMENTS:
                cur.execute(stmt)
        conn.commit()
        self._conn = conn
        self._enabled = True
    except Exception as exc:
        print(f"[telemetry] disabled — could not connect: {exc}", flush=True)
```

- [ ] **Step 5: Replace `_migrate` with `_migrate_pg`**

Delete the old `_migrate` method entirely. Add:

```python
def _migrate_pg(self, cur: Any) -> None:
    """Add any columns that were introduced after the initial schema."""
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    existing_tables = {row[0] for row in cur.fetchall()}
    for table, column, col_type in _MIGRATIONS:
        if table not in existing_tables:
            continue
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        existing_cols = {row[0] for row in cur.fetchall()}
        if column not in existing_cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
```

- [ ] **Step 6: Rewrite `_connect` and add `_cursor`**

Replace `_connect`:

```python
def _connect(self) -> Any:
    """Return the shared persistent connection."""
    return self._conn
```

Add `_cursor` immediately after:

```python
@contextmanager
def _cursor(self) -> Generator[Any, None, None]:
    """Context manager that yields a RealDictCursor and commits on exit.

    Rolls back automatically on exception. All query methods use this instead
    of calling conn.execute() directly.
    """
    conn = self._conn
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
```

- [ ] **Step 7: Run a quick smoke test (expect failures but not import errors)**

```bash
cd remote-gateway && python -c "
import sys; sys.path.insert(0, 'core')
from telemetry import TelemetryStore
print('import ok')
"
```

Expected: `import ok` (no DATABASE_URL → disabled, but no crash).

#### 4d — Migrate all query methods

This is the largest step. Work through the file top to bottom. For every method that calls `conn.execute(...)`:

**Rule 1**: Replace `conn = self._connect()` + `conn.execute("...", params)` + `conn.commit()` with:
```python
with self._cursor() as cur:
    cur.execute("...", params)
```

**Rule 2**: Replace `conn = self._connect()` + `rows = conn.execute("...", params).fetchall()` with:
```python
with self._cursor() as cur:
    cur.execute("...", params)
    rows = cur.fetchall()
```

**Rule 3**: Replace `conn = self._connect()` + `row = conn.execute("...", params).fetchone()` with:
```python
with self._cursor() as cur:
    cur.execute("...", params)
    row = cur.fetchone()
```

**Rule 4**: Replace every `?` placeholder with `%s` in all SQL strings.

**Rule 5**: Replace `date(called_at, 'unixepoch')` with `to_char(to_timestamp(called_at), 'YYYY-MM-DD')` in `daily_activity` and `daily_activity_by_user`.

**Rule 6**: Replace dynamic `f"{k} = ?"` patterns with `f"{k} = %s"` in `update_skill` and `"goal = ?"` etc. with `"goal = %s"` in `update_task`.

- [ ] **Step 8: Apply rules to every method in order**

Methods to update (in file order):

1. **`_load_disabled_cache`**: Rule 1+3 (read rows, no commit needed — wrap in `_cursor` anyway)
2. **`_load_disabled_skills_cache`**: same pattern
3. **`get_primary_initialized_org`**: Rule 3 + Rule 4
4. **`add_api_key`**: Rule 1 + Rule 4
5. **`revoke_api_key`**: Rule 1 + Rule 4
6. **`list_users`**: Rule 2 + Rule 4 (complex SELECT with JOIN — replace `?` in WHERE clause if any)
7. **`delete_user`**: Rule 2 + Rule 4
8. **`set_tool_permission`**: Rule 1 + Rule 4
9. **`get_tool_permissions`**: Rule 2 + Rule 4
10. **`filter_visible_tools`**: Rule 2 + Rule 4
11. **`set_skill_permission`**: Rule 1 + Rule 4
12. **`is_skill_enabled`**: Rule 3 + Rule 4
13. **`get_skill_permissions`**: Rule 2 + Rule 4
14. **`set_tool_intent_override`**: Rule 1 + Rule 4
15. **`clear_tool_intent_override`**: Rule 1 + Rule 4
16. **`get_tool_intent_overrides`**: Rule 2 + Rule 4
17. **`lookup_user`**: Rule 3 + Rule 4
18. **`get_org_id`**: Rule 3 + Rule 4
19. **`set_user_org_id`**: Rule 1 + Rule 4
20. **`get_org_profile`**: Rule 3 + Rule 4
21. **`update_org_profile`**: Rule 1+3 + Rule 4 (read then write in same method — use two `with self._cursor()` blocks)
22. **`is_initialized`**: Rule 3 + Rule 4
23. **`set_initialized`**: Rule 1 + Rule 4
24. **`create_skill`**: Rule 1 + Rule 4
25. **`get_skill`**: Rule 3 + Rule 4
26. **`list_skills`**: Rule 2 + Rule 4
27. **`update_skill`**: Rule 1+3 + Rule 4 + Rule 6 (`f"{k} = ?"` → `f"{k} = %s"`)
28. **`delete_skill`**: Rule 1+3 + Rule 4
29. **`_load_hint_cache`**: Rule 2 + Rule 4
30. **`upsert_tool_hint`**: Rule 1 + Rule 4
31. **`list_tool_hints`**: Rule 2 + Rule 4
32. **`create_task`**: Rule 1 + Rule 4
33. **`get_task`**: Rule 3 + Rule 4
34. **`complete_task`**: Rule 1+3 + Rule 4
35. **`update_task`**: Rule 1+3 + Rule 4 + Rule 6 (`"goal = ?"` → `"goal = %s"`, `"WHERE task_id = ?"` → `"WHERE task_id = %s"`)
36. **`list_tasks_for_org`**: Rule 2 + Rule 4 (`"org_id = ?"` → `"org_id = %s"`, `"status = ?"` → `"status = %s"`, etc., `"LIMIT ?"` → `"LIMIT %s"`)
37. **`list_active_tasks`**: Rule 2 + Rule 4
38. **`record`**: Rule 1 + Rule 4
39. **`stats`**: Rule 2 + Rule 4 (WHERE clause, if any)
40. **`get_session_usage`**: Rule 2 + Rule 4
41. **`user_flow_analysis`**: Rule 2 + Rule 4
42. **`daily_activity`**: Rule 2 + Rule 4 + **Rule 5** (`date(called_at, 'unixepoch')` → `to_char(to_timestamp(called_at), 'YYYY-MM-DD')`)
43. **`daily_activity_by_user`**: Rule 2 + Rule 4 + **Rule 5**
44. **`raw_logs`**: Rule 2 + Rule 4 (dynamic WHERE with `"tool_name = ?"` → `"tool_name = %s"` etc., `"LIMIT ? OFFSET ?"` → `"LIMIT %s OFFSET %s"`)

For `update_org_profile`, which reads then writes, use two separate cursor blocks:

```python
def update_org_profile(self, org_id: str, fields: dict) -> dict:
    import json as _json
    if not self._enabled:
        return fields
    try:
        now = time.time()
        with self._cursor() as cur:
            cur.execute(
                "SELECT profile_json FROM org_profiles WHERE org_id = %s", (org_id,)
            )
            row = cur.fetchone()
        current = _json.loads(row["profile_json"] or "{}") if row else {}
        current.update(fields)
        merged = _json.dumps(current)
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO org_profiles (org_id, profile_json, initialized, created_at, updated_at)
                VALUES (%s, %s, 0, %s, %s)
                ON CONFLICT(org_id) DO UPDATE SET profile_json = excluded.profile_json,
                                                  updated_at = excluded.updated_at
                """,
                (org_id, merged, now, now),
            )
        return current
    except Exception:
        return fields
```

For `update_skill`, the key change to the dynamic SET clause:
```python
# BEFORE:
set_clause = ", ".join(f"{k} = ?" for k in updates)
values = list(updates.values()) + [time.time(), org_id, name]

# AFTER:
set_clause = ", ".join(f"{k} = %s" for k in updates)
values = list(updates.values()) + [time.time(), org_id, name]
```
And the queries in that method use `%s`.

For `update_task`, the dynamic SET clause:
```python
# BEFORE:
fields.append("goal = ?")
# ...
conn.execute(
    f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?",
    values,
)

# AFTER:
fields.append("goal = %s")
# ...
with self._cursor() as cur:
    cur.execute(
        f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = %s",
        values,
    )
```

- [ ] **Step 9: Update the module docstring**

Replace:
```
Zero external dependencies: sqlite3 ships with the Python standard library.
Database location: TELEMETRY_DB_PATH env var (default: data/telemetry.db).
Mount a persistent volume at /data on Railway/Render and set that variable.
```

With:
```
Requires psycopg2-binary. Connection string from DATABASE_URL env var.
On Railway, add a Postgres plugin to your service — Railway auto-injects DATABASE_URL.
```

- [ ] **Step 10: Run the full test suite**

```bash
pytest remote-gateway/tests/ -x -v 2>&1 | tail -30
```

Expected: all tests pass (315+). If tests fail:
- `psycopg2.ProgrammingError: syntax error` → check for remaining `?` placeholders (grep: `grep -n "= ?"`)
- `psycopg2.errors.UndefinedFunction: function date(double precision, unknown) does not exist` → check `daily_activity` and `daily_activity_by_user` for remaining SQLite date function
- `AttributeError: 'RealDictRow' object has no attribute 'X'` → check row access patterns (`row["field"]` should work with RealDictCursor)
- `TypeError: 'NoneType' object is not subscriptable` → check `fetchone()` null check patterns

- [ ] **Step 11: Commit**

```bash
git add remote-gateway/core/telemetry.py
git commit -m "feat: migrate TelemetryStore from SQLite to PostgreSQL"
```

---

### Task 5: Update docs and env var references

**Files:**
- Modify: `CLAUDE.md`
- Modify: `remote-gateway/CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md telemetry section**

Find the telemetry table in `CLAUDE.md`. Update the `TELEMETRY_DB_PATH` row:

```markdown
| `DATABASE_URL` | Yes (prod) | PostgreSQL DSN. Railway auto-injects this when you add a Postgres plugin. |
```

Remove the `TELEMETRY_DB_PATH` row (it no longer exists).

In the "Telemetry" section, update the storage line:
```markdown
- **Storage**: PostgreSQL at `DATABASE_URL`. Add a Postgres plugin in Railway — the DSN is injected automatically.
```

- [ ] **Step 2: Update remote-gateway/CLAUDE.md env var table**

In the environment variables table, change:
```markdown
| `TELEMETRY_DB_PATH` | No | Path to SQLite telemetry file (default: `data/telemetry.db`) |
```
To:
```markdown
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string. Railway injects this automatically when a Postgres plugin is added to the service. |
```

- [ ] **Step 3: Run tests one more time to confirm nothing broke**

```bash
pytest remote-gateway/tests/ -q 2>&1 | tail -5
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md
git commit -m "docs: update env var refs from TELEMETRY_DB_PATH to DATABASE_URL"
```

---

## Self-Review

**Spec coverage:**
- ✅ psycopg2-binary added (Task 1)
- ✅ pytest-postgresql added (Task 1)
- ✅ `db_path: Path` → `dsn: str` constructor (Task 4c)
- ✅ Schema types updated (BIGSERIAL, DOUBLE PRECISION) (Task 4b)
- ✅ PRAGMA/sqlite_master removed (Task 4b/4c)
- ✅ executescript removed (Task 4c/4d)
- ✅ All `?` → `%s` (Task 4d)
- ✅ `date(called_at, 'unixepoch')` → Postgres equivalent (Task 4d Rule 5)
- ✅ All test fixtures migrated to real Postgres (Tasks 2+3)
- ✅ Disabled-state test updated (Task 3c)
- ✅ Docs updated (Task 5)

**Placeholder scan:** No TBDs, no "similar to Task N" references, every SQL change shown with concrete before/after.

**Type consistency:** `_cursor()` yields `Any` typed as `psycopg2.extras.RealDictCursor` — `row["field"]` access works identically to `sqlite3.Row`. The `_conn` type annotation changes from `sqlite3.Connection | None` to `Any` — this is intentional to avoid importing psycopg2 types at the annotation level.
