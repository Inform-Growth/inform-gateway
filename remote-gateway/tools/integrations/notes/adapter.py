"""Notes storage adapter Protocol and factory.

Adapters implement the NotesAdapter Protocol to provide a pluggable backend
for write_note / read_note / list_notes / delete_note. The active adapter is
selected per-invocation by the NOTES_ADAPTER env var (default: github-files).

Each adapter declares its own required env vars in its docstring and raises
RuntimeError on instantiation if any are missing.
"""
from __future__ import annotations

import os
from typing import Protocol


class NotesAdapterError(RuntimeError):
    """Adapter-level failure with enough context to diagnose.

    Raised by adapters when an upstream call fails. Carries the HTTP
    status (or None for network errors), a truncated response body,
    the repo we were talking to, and a fingerprint of the token in
    use so silent empty results are no longer possible.
    """

    def __init__(
        self,
        *,
        status: int | None,
        body: str,
        repo: str,
        token_fingerprint: str,
    ) -> None:
        self.status = status
        self.body = body
        self.repo = repo
        self.token_fingerprint = token_fingerprint
        super().__init__(
            f"NotesAdapterError(status={status}, repo={repo}, "
            f"token={token_fingerprint}): {body}"
        )


class NotesAdapter(Protocol):
    """Storage backend contract for notes.

    Slugs are globally unique across folders. `folder` is an optional partition
    accepted on every CRUD operation; backends without a folder concept may
    ignore it but must accept the kwarg without raising. `write` raises
    NotesAdapterError(409) on cross-folder slug collision.
    """

    def write(self, slug: str, content: str, folder: str | None = None) -> dict:
        """Create or update a note.

        Returns {"slug": str, "id": str, "url": str, "path": str,
                 "folder": str | None, "status": "created" | "updated"}.
        Raises NotesAdapterError(409) if slug exists in a different folder.
        Adapters MAY include additional adapter-specific fields.
        """
        ...

    def read(self, slug: str, folder: str | None = None) -> dict | None:
        """Read a note by slug.

        With folder=X: hint is authoritative — returns None on miss without
        searching other folders. Without folder: searches all folders.

        Returns {"slug": str, "content": str, "id": str, "url": str,
                 "path": str, "folder": str | None, ...} or None.
        """
        ...

    def list(  # noqa: A003 — Protocol shape
        self,
        folder: str | None = None,
        prefix: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """List notes with optional server-side filters.

        - folder=X: only entries under that folder.
        - prefix=Y: only slugs starting with Y (case-sensitive).
        - since/until: ISO-8601 timestamps; filter by updated_at.
        - limit: cap results (adapter-specific clamping permitted).

        Returns [{"slug": str, "id": str, "url": str, "path": str,
                  "folder": str | None, "created_at": str, "updated_at": str}, ...].
        Returns an empty list if no notes match. Ordering is adapter-defined
        (the reference adapter sorts by updated_at descending).
        """
        ...

    def delete(self, slug: str, folder: str | None = None) -> dict:
        """Delete a note.

        With folder=X: hint is authoritative — returns not_found on miss without
        searching other folders. Without folder: searches all folders.

        Returns {"slug": str, "status": "deleted" | "not_found"}.
        """
        ...


def _registry() -> dict[str, type]:
    """Lazy-load the adapter registry to avoid circular imports."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    return {"github-files": GitHubFilesAdapter}


def get_adapter() -> NotesAdapter:
    """Return a fresh adapter instance per call. Selection is env-var driven.

    Reads NOTES_ADAPTER (default: "github-files"). Raises RuntimeError if the
    name is unknown. Any exception raised by the chosen adapter's __init__
    (e.g., RuntimeError on missing env vars) propagates as-is.
    """
    name = os.environ.get("NOTES_ADAPTER", "github-files")
    registry = _registry()
    if name not in registry:
        raise RuntimeError(
            f"Unknown NOTES_ADAPTER={name!r}. Known adapters: {sorted(registry)}"
        )
    return registry[name]()
