"""Notes integration — pluggable storage backend.

See adapter.py for the NotesAdapter Protocol and the env-var-driven factory.
The adapter is currently routed to GitHub Issues by default (see adapters/github_issues.py).
"""
from __future__ import annotations

from typing import Any

from tools.integrations.notes.tools import (
    delete_note,
    list_notes,
    read_note,
    write_note,
)


def register(mcp: Any) -> None:
    """Register the four notes MCP tools on the given FastMCP server."""
    mcp.tool()(list_notes)
    mcp.tool()(read_note)
    mcp.tool()(write_note)
    mcp.tool()(delete_note)
