"""MCP tool functions for notes — thin delegators to the configured NotesAdapter.

The adapter is selected per-invocation via `get_adapter()` so env-var changes
during local dev are picked up without restart. Return shapes carry slug,
content, html_url, status from the adapter. `issue_number` is present for
backward compatibility but is None under the file-based adapter.
"""
from __future__ import annotations

from tools.integrations.notes.adapter import get_adapter


def list_notes() -> dict:
    """List all notes stored in the configured notes backend.

    Notes are persistent and shared across all agents on this gateway.

    Returns:
        Dict with 'notes' list and 'count'.
    """
    notes = get_adapter().list()
    # Preserve the existing field name html_url so agents/UI keep working
    rendered = [
        {
            "slug": n["slug"],
            "issue_number": n.get("issue_number"),
            "created_at": n["created_at"],
            "updated_at": n["updated_at"],
            "html_url": n["url"],
        }
        for n in notes
    ]
    return {"notes": rendered, "count": len(rendered)}


def read_note(slug: str, folder: str | None = None) -> dict:
    """Read a note by its slug.

    With folder hint: reads notes/<folder>/<slug>.md directly. The hint is
    authoritative — if no file exists at that exact path, returns not_found
    (does not search other folders).

    Without folder: searches all folders for the slug (slugs are globally
    unique). Returns the file if found, otherwise not_found.

    Args:
        slug: The note slug used when the note was written.
        folder: Optional folder hint to skip the tree lookup.

    Returns:
        Dict with 'slug', 'content', 'folder', 'issue_number', 'html_url' on
        success. Dict with status='not_found' if no note matches.
    """
    result = get_adapter().read(slug, folder=folder)
    if result is None:
        return {"status": "not_found", "slug": slug}
    return {
        "slug": result["slug"],
        "content": result["content"],
        "folder": result.get("folder"),
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def write_note(slug: str, content: str, folder: str | None = None) -> dict:
    """Create or update a note in the configured notes backend.

    If a note with this slug already exists in the same folder, its content is
    updated in place. If the slug already exists in a DIFFERENT folder, this
    raises an error — slugs are globally unique across all folders.

    Args:
        slug: Short identifier for the note (becomes the filename: notes/<folder>/<slug>.md).
        content: Full markdown content of the note.
        folder: Optional folder under notes/ (e.g. "marketing", "sales", "executive",
            "architecture", "shadow", "jaron"). Folders are dynamic — pass any
            lowercase a-z/0-9/-/_ string; new folders materialize on first write.
            If omitted, writes to notes/<slug>.md (root, backwards-compatible).

    Returns:
        Dict with 'status' (created/updated), 'slug', 'folder', 'issue_number'
        (always None on the file-based adapter), 'html_url'.
    """
    result = get_adapter().write(slug, content, folder=folder)
    return {
        "status": result["status"],
        "slug": result["slug"],
        "folder": result.get("folder"),
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def delete_note(slug: str, folder: str | None = None) -> dict:
    """Delete a note by its slug.

    With folder hint: deletes notes/<folder>/<slug>.md directly. Hint is
    authoritative — does not fall back to a tree search on miss.

    Without folder: searches all folders for the slug, deletes if found.

    Args:
        slug: The note slug used when the note was written.
        folder: Optional folder hint.

    Returns:
        Dict with status='deleted' on success or status='not_found'.
    """
    result = get_adapter().delete(slug, folder=folder)
    return {
        "status": result["status"],
        "slug": result["slug"],
        "issue_number": result.get("issue_number"),
    }
