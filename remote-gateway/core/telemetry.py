"""
Gateway telemetry — SQLite-backed tool call tracking.

Records every invocation with timing and success/failure status.
Zero external dependencies: sqlite3 ships with the Python standard library.

Database location is controlled by the TELEMETRY_DB_PATH environment variable
(default: data/telemetry.db relative to the working directory).

Railway / Render setup:
    Mount a persistent volume at /data and set:
        TELEMETRY_DB_PATH=/data/telemetry.db

If the path is not writable the store silently disables itself — telemetry is
never load-bearing for the gateway. All record() calls become no-ops; stats()
returns an explanatory error key.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path(os.environ.get("TELEMETRY_DB_PATH", "data/telemetry.db"))

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name   TEXT    NOT NULL,
    called_at   REAL    NOT NULL,
    duration_ms INTEGER NOT NULL,
    success     INTEGER NOT NULL,
    error_type  TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls (tool_name);
CREATE INDEX IF NOT EXISTS idx_called_at ON tool_calls (called_at);
"""


class TelemetryStore:
    """Lightweight SQLite store for gateway tool call metrics."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = db_path
        self._enabled = False
        self._setup()

    def _setup(self) -> None:
        """Create the database file and schema. Disables itself on any failure."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path)
            conn.executescript(_SCHEMA)
            conn.close()
            self._enabled = True
        except Exception as exc:
            print(f"[telemetry] disabled — could not open {self._path}: {exc}", flush=True)

    def _connect(self) -> sqlite3.Connection:
        """Return a new WAL-mode connection with row_factory set."""
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def record(
        self,
        tool_name: str,
        duration_ms: int,
        success: bool,
        error_type: str | None = None,
    ) -> None:
        """Record a single tool invocation. Silent no-op if disabled.

        Args:
            tool_name: Name of the tool function that was called.
            duration_ms: Wall-clock time in milliseconds.
            success: True if the tool returned normally, False if it raised.
            error_type: Exception class name on failure, otherwise None.
        """
        if not self._enabled:
            return
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO tool_calls (tool_name, called_at, duration_ms, success, error_type)"
                " VALUES (?, ?, ?, ?, ?)",
                (tool_name, time.time(), duration_ms, int(success), error_type),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # telemetry must never break the gateway

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
                datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime(
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
