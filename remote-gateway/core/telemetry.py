"""
Gateway telemetry — SQLite-backed tool call tracking.

Records every invocation with timing, success/failure, and the user who made
the call (resolved from their API key at request time).

API key management
------------------
Each operator gets one API key, created by an admin::

    from telemetry import telemetry
    telemetry.add_api_key("sk-alice-abc123", "alice@company.com")

The key is passed in the Authorization header of every MCP connection::

    # .mcp.json
    "headers": {"Authorization": "Bearer sk-alice-abc123"}

The gateway's ASGI auth middleware resolves the key to a user_id on each
request and stores it in a ContextVar. The telemetry wrappers pick it up
automatically — no per-tool changes required.

Zero external dependencies: sqlite3 ships with the Python standard library.

Database location: TELEMETRY_DB_PATH env var (default: data/telemetry.db).
Mount a persistent volume at /data on Railway/Render and set that variable.

Telemetry is never load-bearing — all record() calls are silent no-ops if
the database is unavailable.
"""

from __future__ import annotations

import datetime
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path(os.environ.get("TELEMETRY_DB_PATH", "data/telemetry.db"))

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
    input_body    TEXT,
    response_preview TEXT
);

CREATE TABLE IF NOT EXISTS tool_permissions (
    user_id   TEXT    NOT NULL,
    tool_name TEXT    NOT NULL,
    enabled   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, tool_name)
);

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
"""

# Indexes are created after migrations so that columns added via ALTER TABLE
# are present before any index on those columns is attempted.
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls (tool_name);
CREATE INDEX IF NOT EXISTS idx_called_at ON tool_calls (called_at);
CREATE INDEX IF NOT EXISTS idx_user_id   ON tool_calls (user_id);
"""

# Columns added after initial release — applied via ALTER TABLE migration.
_MIGRATIONS = [
    ("tool_calls", "user_id",          "TEXT"),
    ("tool_calls", "request_id",       "TEXT"),
    ("tool_calls", "response_size",    "INTEGER"),
    ("tool_calls", "input_body",       "TEXT"),
    ("tool_calls", "error_message",    "TEXT"),
    ("tool_calls", "response_preview", "TEXT"),
    ("api_keys", "org_id", "TEXT"),
]


class TelemetryStore:
    """Lightweight SQLite store for gateway tool call metrics and API key management."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = db_path
        self._enabled = False
        self._disabled_cache: dict[str, set[str]] = {}
        self._conn: sqlite3.Connection | None = None
        self._setup()
        self._load_disabled_cache()

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
            self._conn = conn          # store; do NOT close
            self._enabled = True
        except Exception as exc:
            print(f"[telemetry] disabled — could not open {self._path}: {exc}", flush=True)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add any columns that were introduced after the initial schema."""
        existing_tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table, column, col_type in _MIGRATIONS:
            if table not in existing_tables:
                continue
            existing_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing_cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Return the shared persistent WAL-mode connection.

        The connection is created once in _setup() and lives for the process
        lifetime. Callers must NOT call conn.close().
        """
        return self._conn  # type: ignore[return-value]

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
            for row in rows:
                self._disabled_cache.setdefault(row["user_id"], set()).add(row["tool_name"])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

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

    def revoke_api_key(self, key: str) -> None:
        """Remove an API key. The user can no longer authenticate with it.

        Args:
            key: The key to revoke.
        """
        if not self._enabled:
            return
        try:
            conn = self._connect()
            conn.execute("DELETE FROM api_keys WHERE key = ?", (key,))
            conn.commit()
        except Exception:
            pass

    def list_users(self) -> list[dict]:
        """Return all API key records with per-user call counts."""
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
                    COUNT(tc.id)      AS call_count,
                    MAX(tc.called_at) AS last_active
                FROM api_keys ak
                LEFT JOIN tool_calls tc ON ak.user_id = tc.user_id
                GROUP BY ak.user_id, ak.key
                ORDER BY ak.created_at DESC
                """
            ).fetchall()
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
        """Delete all API keys and permissions for user_id. Returns rows deleted."""
        if not self._enabled:
            return 0
        try:
            conn = self._connect()
            cursor = conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
            deleted = cursor.rowcount
            conn.execute("DELETE FROM tool_permissions WHERE user_id = ?", (user_id,))
            conn.commit()
            return deleted
        except Exception:
            return 0

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
            return row is None or bool(row["enabled"])
        except Exception:
            return True  # never block on DB failure

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
        if not self._enabled:
            return set(tool_names)
        globally_disabled = self._disabled_cache.get("*", set())
        user_disabled = self._disabled_cache.get(user_id, set()) if user_id else set()
        hidden = globally_disabled | user_disabled
        return {name for name in tool_names if name not in hidden}

    def get_tool_permissions(self, user_id: str) -> list[dict]:
        """Return explicit permission rows for a user."""
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            rows = conn.execute(
                "SELECT tool_name, enabled FROM tool_permissions"
                " WHERE user_id = ? ORDER BY tool_name",
                (user_id,),
            ).fetchall()
        except Exception:
            return []
        return [{"tool_name": row["tool_name"], "enabled": bool(row["enabled"])} for row in rows]

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
        except Exception:
            pass
        # Keep cache consistent regardless of DB success/failure
        if enabled:
            if user_id in self._disabled_cache:
                self._disabled_cache[user_id].discard(tool_name)
        else:
            self._disabled_cache.setdefault(user_id, set()).add(tool_name)

    def lookup_user(self, key: str) -> str | None:
        """Return the user_id for an API key, or None if the key is invalid.

        Args:
            key: The Bearer token extracted from the Authorization header.

        Returns:
            The associated user_id, or None if the key is not recognized.
        """
        if not self._enabled:
            return None
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT user_id FROM api_keys WHERE key = ?", (key,)
            ).fetchone()
            return row["user_id"] if row else None
        except Exception:
            return None

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

    def get_org_profile(self, org_id: str) -> dict:
        """Return the org's profile_json as a dict. Returns {} if not found.

        Args:
            org_id: Organization identifier.
        """
        if not self._enabled:
            return {}
        try:
            import json as _json
            conn = self._connect()
            row = conn.execute(
                "SELECT profile_json FROM org_profiles WHERE org_id = ?", (org_id,)
            ).fetchone()
            if row:
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
        import json as _json
        if not self._enabled:
            return fields
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

    # ------------------------------------------------------------------
    # Call recording
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self, tool_name: str | None = None) -> dict[str, Any]:
        """Return aggregated call statistics, optionally for a single tool.

        Args:
            tool_name: Limit results to this tool, or None for all tools.

        Returns:
            Dict with:
              - tools: list of per-tool stat dicts (call_count, error_count,
                error_rate, last_called, avg_duration_ms, max_duration_ms,
                avg_response_size, max_response_size,
                avg_input_size, max_input_size)
              - summary: total_calls, total_tools_seen, high_error_rate list
                (tools with ≥5% error rate across ≥10 calls)
        """
        if not self._enabled:
            return {
                "error": "telemetry disabled — check startup logs for the reason",
                "tools": [],
            }

        try:
            conn = self._connect()
            where = "WHERE tool_name = ?" if tool_name else ""
            params: tuple = (tool_name,) if tool_name else ()

            rows = conn.execute(
                f"""
                SELECT
                    tool_name,
                    COUNT(*)                                       AS call_count,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END)  AS error_count,
                    MAX(called_at)                                 AS last_called_ts,
                    AVG(duration_ms)                               AS avg_ms,
                    MAX(duration_ms)                               AS max_ms,
                    AVG(response_size)                             AS avg_size,
                    MAX(response_size)                             AS max_size,
                    AVG(LENGTH(input_body))                        AS avg_input_size,
                    MAX(LENGTH(input_body))                        AS max_input_size
                FROM tool_calls
                {where}
                GROUP BY tool_name
                ORDER BY call_count DESC
                """,
                params,
            ).fetchall()
        except Exception as exc:
            return {"error": str(exc), "tools": []}

        tools: list[dict[str, Any]] = []
        high_error: list[str] = []

        for row in rows:
            call_count: int = row["call_count"]
            error_count: int = row["error_count"]
            error_rate = error_count / call_count if call_count else 0.0
            ts = row["last_called_ts"]
            last_called = (
                datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).strftime(
                    "%Y-%m-%dT%H:%MZ"
                )
                if ts
                else None
            )

            tools.append(
                {
                    "name": row["tool_name"],
                    "call_count": call_count,
                    "error_count": error_count,
                    "error_rate": f"{error_rate:.1%}",
                    "last_called": last_called,
                    "avg_duration_ms": round(row["avg_ms"] or 0),
                    "max_duration_ms": row["max_ms"] or 0,
                    "avg_response_size": round(row["avg_size"] or 0),
                    "max_response_size": row["max_size"] or 0,
                    "avg_input_size": round(row["avg_input_size"] or 0),
                    "max_input_size": row["max_input_size"] or 0,
                }
            )

            if error_rate >= 0.05 and call_count >= 10:
                high_error.append(row["tool_name"])

        return {
            "tools": tools,
            "summary": {
                "total_calls": sum(t["call_count"] for t in tools),
                "total_tools_seen": len(tools),
                "high_error_rate": high_error,
            },
        }

    def session_usage(self, limit: int = 100) -> dict[str, Any]:
        """Return a sequence of recent tool calls grouped by user and request.

        Args:
            limit: Maximum number of recent calls to analyze.

        Returns:
            Dict with 'recent_sequences' (call sequences) and
            'user_breakdown' (total calls per user).
        """
        if not self._enabled:
            return {"error": "telemetry disabled"}

        try:
            conn = self._connect()
            
            # 1. Get raw sequence of recent calls
            rows = conn.execute(
                """
                SELECT tool_name, called_at, success, user_id, request_id, response_size
                FROM tool_calls
                ORDER BY called_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            
            # 2. Get breakdown by user (all time)
            user_rows = conn.execute(
                """
                SELECT user_id, COUNT(*) as call_count
                FROM tool_calls
                GROUP BY user_id
                ORDER BY call_count DESC
                """
            ).fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        # Group calls by user_id
        user_history: dict[str, list[dict]] = {}
        for row in rows:
            uid = row["user_id"] or "anonymous"
            if uid not in user_history:
                user_history[uid] = []
            
            ts = datetime.datetime.fromtimestamp(
                row["called_at"], tz=datetime.UTC
            ).strftime("%H:%M:%S")
            user_history[uid].append({
                "tool": row["tool_name"],
                "time": ts,
                "success": bool(row["success"]),
                "request_id": row["request_id"],
                "response_size": row["response_size"],
            })

        return {
            "recent_sequences": user_history,
            "user_breakdown": {
                row["user_id"] or "anonymous": row["call_count"] 
                for row in user_rows
            }
        }

    def user_flow_analysis(self, limit: int = 500) -> dict[str, Any]:
        """Analyze common sequences of tool calls (flows) across all users.

        Args:
            limit: Number of recent calls to analyze.

        Returns:
            Dict with 'common_flows' (list of tool sequences and their frequencies).
        """
        if not self._enabled:
            return {"error": "telemetry disabled"}

        try:
            conn = self._connect()
            # Get calls ordered by user and time to reconstruct flows
            rows = conn.execute(
                """
                SELECT user_id, request_id, tool_name, called_at
                FROM tool_calls
                WHERE success = 1
                ORDER BY user_id, called_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        # Reconstruct flows (sequences of tools) per session/user
        # For simplicity, we define a flow as tools called within a 10-minute window
        # or sharing the same request_id if available.
        flows: list[list[str]] = []
        current_flow: list[str] = []
        last_user = None
        last_time = 0

        for row in rows:
            user = row["user_id"]
            time_ts = row["called_at"]
            tool = row["tool_name"]

            # Start new flow if user changes or more than 10 minutes pass
            if user != last_user or (time_ts - last_time) > 600:
                if current_flow:
                    flows.append(current_flow)
                current_flow = [tool]
            else:
                current_flow.append(tool)
            
            last_user = user
            last_time = time_ts
        
        if current_flow:
            flows.append(current_flow)

        # Count frequencies of sequences (length 2 and 3)
        sequences: dict[str, int] = {}
        for flow in flows:
            # Pairs
            for i in range(len(flow) - 1):
                seq = f"{flow[i]} -> {flow[i+1]}"
                sequences[seq] = sequences.get(seq, 0) + 1
            # Triplets
            for i in range(len(flow) - 2):
                seq = f"{flow[i]} -> {flow[i+1]} -> {flow[i+2]}"
                sequences[seq] = sequences.get(seq, 0) + 1

        # Sort by frequency
        sorted_sequences = sorted(sequences.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "common_flows": [
                {"sequence": seq, "count": count}
                for seq, count in sorted_sequences[:20]
            ]
        }


    def daily_activity(self, days: int = 30) -> list[dict[str, Any]]:
        """Return per-day call and unique-user counts for the last N calendar days.

        Args:
            days: How many days back to include (default: 30).

        Returns:
            List of dicts with 'day' (YYYY-MM-DD), 'calls', 'users', ordered
            ascending. Days with zero activity are omitted.
        """
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            cutoff = time.time() - days * 86400
            rows = conn.execute(
                """
                SELECT
                    date(called_at, 'unixepoch') AS day,
                    COUNT(*)                     AS calls,
                    COUNT(DISTINCT user_id)      AS users
                FROM tool_calls
                WHERE called_at >= ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (cutoff,),
            ).fetchall()
        except Exception:
            return []
        return [
            {"day": row["day"], "calls": row["calls"], "users": row["users"]}
            for row in rows
        ]

    def daily_activity_by_user(self, days: int = 30) -> dict[str, Any]:
        """Return per-user, per-day call counts for the last N calendar days.

        Args:
            days: How many days back to include (default: 30).

        Returns:
            Dict with:
              - ``users``: sorted list of distinct user_id strings seen in the period
              - ``days``: list of dicts ordered ascending by date, each with a
                ``'day'`` key (YYYY-MM-DD) and one key per user_id containing that
                user's call count (0 for users absent on that day).
            Days with zero activity across ALL users are omitted.
        """
        if not self._enabled:
            return {"users": [], "days": []}
        try:
            conn = self._connect()
            cutoff = time.time() - days * 86400
            rows = conn.execute(
                """
                SELECT
                    date(called_at, 'unixepoch') AS day,
                    COALESCE(user_id, 'unknown') AS user_id,
                    COUNT(*)                     AS calls
                FROM tool_calls
                WHERE called_at >= ?
                GROUP BY day, user_id
                ORDER BY day ASC
                """,
                (cutoff,),
            ).fetchall()
        except Exception:
            return {"users": [], "days": []}

        # Pivot rows into {day -> {user_id -> calls}}
        days_map: dict[str, dict[str, int]] = {}
        users_seen: set[str] = set()
        for row in rows:
            day = row["day"]
            uid = row["user_id"]
            users_seen.add(uid)
            if day not in days_map:
                days_map[day] = {}
            days_map[day][uid] = row["calls"]

        users = sorted(users_seen)
        day_records = []
        for day in sorted(days_map):
            record: dict[str, Any] = {"day": day}
            for uid in users:
                record[uid] = days_map[day].get(uid, 0)
            day_records.append(record)

        return {"users": users, "days": day_records}

    def raw_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        tool_name: str | None = None,
        user_id: str | None = None,
        success: bool | None = None,
        error_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent raw tool call rows, newest first.

        Args:
            limit: Max rows to return.
            offset: Rows to skip for pagination.
            tool_name: Filter to an exact tool name.
            user_id: Filter to an exact user_id.
            success: If True, only successful calls; if False, only errors.
            error_type: Filter to an exact error_type (e.g. "PermissionError").

        Returns:
            List of dicts with id, tool_name, called_at, duration_ms, success,
            error_type, error_message, user_id, request_id, response_size, input_size, input_body.
        """
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            filters: list[str] = []
            params: list[Any] = []
            if tool_name is not None:
                filters.append("tool_name = ?")
                params.append(tool_name)
            if user_id is not None:
                filters.append("user_id = ?")
                params.append(user_id)
            if success is not None:
                filters.append("success = ?")
                params.append(int(success))
            if error_type is not None:
                filters.append("error_type = ?")
                params.append(error_type)
            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            params.extend([limit, offset])
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
        except Exception:
            return []
        result = []
        for row in rows:
            ts = row["called_at"]
            called_at_str = (
                datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                if ts
                else None
            )
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
        return result


# Module-level singleton — imported by mcp_server.py
telemetry = TelemetryStore()
