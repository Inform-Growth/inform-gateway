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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name   TEXT    NOT NULL,
    called_at   REAL    NOT NULL,
    duration_ms INTEGER NOT NULL,
    success     INTEGER NOT NULL,
    error_type  TEXT,
    user_id     TEXT,
    request_id  TEXT
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
    ("tool_calls", "user_id",    "TEXT"),
    ("tool_calls", "request_id", "TEXT"),
]


class TelemetryStore:
    """Lightweight SQLite store for gateway tool call metrics and API key management."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = db_path
        self._enabled = False
        self._setup()

    def _setup(self) -> None:
        """Create the database file and schema. Disables itself on any failure."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path)
            conn.executescript(_SCHEMA_TABLES)
            self._migrate(conn)
            conn.executescript(_SCHEMA_INDEXES)
            conn.close()
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
        """Return a new WAL-mode connection with row_factory set."""
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    def add_api_key(self, user_id: str, key: str | None = None) -> str:
        """Create an API key for a user and store it. Returns the key.

        Args:
            user_id: Opaque user identifier (email, username, UUID, etc.).
            key: The key value to store. Generated securely if omitted.

        Returns:
            The API key string (``sk-<32 random hex chars>``).
        """
        if key is None:
            key = f"sk-{secrets.token_hex(16)}"
        if not self._enabled:
            return key
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO api_keys (key, user_id, created_at) VALUES (?, ?, ?)",
                (key, user_id, time.time()),
            )
            conn.commit()
            conn.close()
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
            conn.close()
        except Exception:
            pass

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
            conn.close()
            return row["user_id"] if row else None
        except Exception:
            return None

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
        """
        if not self._enabled:
            return
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO tool_calls"
                " (tool_name, called_at, duration_ms, success, error_type, user_id, request_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tool_name, time.time(), duration_ms, int(success),
                    error_type, user_id, request_id,
                ),
            )
            conn.commit()
            conn.close()
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
                error_rate, last_called, avg_duration_ms, max_duration_ms)
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
                    MAX(duration_ms)                               AS max_ms
                FROM tool_calls
                {where}
                GROUP BY tool_name
                ORDER BY call_count DESC
                """,
                params,
            ).fetchall()
            conn.close()
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


# Module-level singleton — imported by mcp_server.py
telemetry = TelemetryStore()
