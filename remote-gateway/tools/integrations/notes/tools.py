"""MCP tool functions for notes — thin delegators to the configured NotesAdapter.

The adapter is selected per-invocation via `get_adapter()` so env-var changes
during local dev are picked up without restart. Return shapes preserve the
fields existing consumers expect (slug, content, html_url, status, issue_number).
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


def read_note(slug: str) -> dict:
    """Read a note by its slug (title).

    Args:
        slug: The note title used when the note was written.

    Returns:
        Dict with 'slug', 'content', 'issue_number', 'html_url' on success.
        Dict with status='not_found' if no open note matches.
    """
    result = get_adapter().read(slug)
    if result is None:
        return {"status": "not_found", "slug": slug}
    return {
        "slug": result["slug"],
        "content": result["content"],
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def write_note(slug: str, content: str) -> dict:
    """Create or update a note in the configured notes backend.

    If a note with this slug already exists, its content is updated in place.
    Otherwise a new note is created.

    Args:
        slug: Short identifier for the note (used as the issue title).
        content: Full markdown content of the note.

    Returns:
        Dict with 'status' (created/updated), 'slug', 'issue_number', 'html_url'.
    """
    result = get_adapter().write(slug, content)
    return {
        "status": result["status"],
        "slug": result["slug"],
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def delete_note(slug: str) -> dict:
    """Delete a note by its slug.

    For issue-based backends, closes the issue. Returns not_found if absent.

    Args:
        slug: The note title used when the note was written.

    Returns:
        Dict with status='deleted' on success or status='not_found'.
    """
    return get_adapter().delete(slug)
