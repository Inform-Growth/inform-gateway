"""Notes storage adapter Protocol and factory.

Adapters implement the NotesAdapter Protocol to provide a pluggable backend
for write_note / read_note / list_notes / delete_note. The active adapter is
selected per-invocation by the NOTES_ADAPTER env var (default: github-issues).

Each adapter declares its own required env vars in its docstring and raises
RuntimeError on instantiation if any are missing.
"""
from __future__ import annotations

import os
from typing import Protocol


class NotesAdapter(Protocol):
    """Storage backend contract for notes."""

    def write(self, slug: str, content: str) -> dict:
        """Create or update a note.

        Returns {"slug": str, "id": str, "url": str, "status": "created" | "updated"}.
        Adapters MAY include additional adapter-specific fields.
        """
        ...

    def read(self, slug: str) -> dict | None:
        """Read a note by slug.

        Returns {"slug": str, "content": str, "id": str, "url": str, ...} or None.
        """
        ...

    def list(self) -> list[dict]:
        """List all notes.

        Returns [{"slug": str, "id": str, "url": str, "created_at": str, "updated_at": str}, ...].
        Returns an empty list if no notes exist. Ordering is adapter-defined.
        """
        ...

    def delete(self, slug: str) -> dict:
        """Delete (or close) a note.

        Returns {"slug": str, "status": "deleted" | "not_found"}.
        """
        ...


def _registry() -> dict[str, type]:
    """Lazy-load the adapter registry to avoid circular imports."""
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    return {"github-issues": GitHubIssuesAdapter}


def get_adapter() -> NotesAdapter:
    """Return a fresh adapter instance per call. Selection is env-var driven.

    Reads NOTES_ADAPTER (default: "github-issues"). Raises RuntimeError if the
    name is unknown. Any exception raised by the chosen adapter's __init__
    (e.g., RuntimeError on missing env vars) propagates as-is.
    """
    name = os.environ.get("NOTES_ADAPTER", "github-issues")
    registry = _registry()
    if name not in registry:
        raise RuntimeError(
            f"Unknown NOTES_ADAPTER={name!r}. Known adapters: {sorted(registry)}"
        )
    return registry[name]()
