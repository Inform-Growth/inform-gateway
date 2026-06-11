"""
Granola meeting notes tools — read-only access to the Granola REST API.

Lists meetings, fetches AI summaries, and pulls transcripts (flattened
server-side into readable dialogue lines) so agents can ground work in
meeting context.

Note: the Granola API only returns notes that have a finished AI summary
and transcript — notes still processing or never summarized are invisible.

Required env vars:
    GRANOLA_API_KEY — Granola personal API key (Bearer token, starts with grn_)
"""
from __future__ import annotations

import os
from typing import Any

from core.field_registry import registry

_GRANOLA_BASE = "https://public-api.granola.ai/v1"
_MAX_PAGE_SIZE = 30


def _headers() -> dict[str, str]:
    """Return Granola API request headers using GRANOLA_API_KEY from env."""
    api_key = os.environ.get("GRANOLA_API_KEY")
    if not api_key:
        raise ValueError(
            "GRANOLA_API_KEY environment variable is not set "
            "(generate a personal key in the Granola desktop app: Settings > API)"
        )
    return {
        "Authorization": f"Bearer {api_key}",
        # Accept (not Content-Type) — this integration only sends GETs with no body.
        "Accept": "application/json",
    }


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET a Granola API path and return the parsed JSON body.

    Args:
        path: API path starting with "/" (e.g. "/notes").
        params: Optional query parameters.

    Returns:
        Parsed JSON response dict.

    Raises:
        ValueError: If GRANOLA_API_KEY is not set.
        PermissionError: On 401 invalid/expired API key.
        RuntimeError: On 400 bad request or 404 not found.
    """
    import httpx

    with httpx.Client() as client:
        resp = client.get(
            f"{_GRANOLA_BASE}{path}",
            headers=_headers(),
            params=params or {},
        )

    if resp.status_code == 400:
        raise RuntimeError(f"Granola bad request: {resp.text}")
    if resp.status_code == 401:
        raise PermissionError("GRANOLA_API_KEY is invalid or expired")
    if resp.status_code == 404:
        raise RuntimeError(f"Granola resource not found: {path}")
    resp.raise_for_status()
    return resp.json()


def _validated(result: dict[str, Any]) -> dict[str, Any]:
    """Attach _field_validation when the result drifts from the granola schema."""
    validation = registry.validate_response("granola", result)
    if not validation.valid:
        result["_field_validation"] = validation.summary()
    return result


def granola__list_meetings(
    created_after: str | None = None,
    created_before: str | None = None,
    updated_after: str | None = None,
    folder_id: str | None = None,
    cursor: str | None = None,
    page_size: int = 10,
) -> dict[str, Any]:
    """List Granola meeting notes, newest first, with optional filters.

    Returns lightweight summaries (id, title, owner, timestamps) — call
    granola__get_meeting with a note id for the AI summary and transcript.
    Only meetings with a finished AI summary appear; notes still processing
    or never summarized are not returned by the Granola API.

    Args:
        created_after: Only notes created after this date/datetime
            (e.g. "2026-06-01" or "2026-06-01T15:30:00Z").
        created_before: Only notes created before this date/datetime.
        updated_after: Only notes modified after this date/datetime.
        folder_id: Scope to a Granola folder and its children
            (fol_... id from granola__list_folders).
        cursor: Pagination cursor from a previous response.
        page_size: Results per page, 1-30 (default 10).

    Returns:
        Dict with notes (list of {id, title, owner, created_at, updated_at}),
        has_more (bool), and cursor (str or None) for the next page.

    Raises:
        ValueError: If GRANOLA_API_KEY is not set.
        PermissionError: If the API key is invalid or expired.
        RuntimeError: On bad request (e.g. malformed folder_id).
    """
    params: dict[str, Any] = {"page_size": max(1, min(int(page_size), _MAX_PAGE_SIZE))}
    for key, val in (
        ("created_after", created_after),
        ("created_before", created_before),
        ("updated_after", updated_after),
        ("folder_id", folder_id),
        ("cursor", cursor),
    ):
        if val is not None:
            params[key] = val

    payload = _get("/notes", params)

    result: dict[str, Any] = {
        "notes": [
            {
                "id": n.get("id"),
                "title": n.get("title"),
                "owner": n.get("owner"),
                "created_at": n.get("created_at"),
                "updated_at": n.get("updated_at"),
            }
            for n in payload.get("notes", [])
        ],
        "has_more": payload.get("hasMore", False),
        "cursor": payload.get("cursor"),
    }
    return _validated(result)


def granola__get_meeting(note_id: str, include_transcript: bool = False) -> dict[str, Any]:
    """Fetch a Granola meeting note: AI summary, attendees, and optional transcript.

    Returns the meeting's metadata and AI-generated summary (markdown when
    available). With include_transcript=True the full transcript is returned
    as readable dialogue lines — "Me:" is the note owner's microphone,
    "Them:" is other participants, "Speaker A/B/..." when diarization is
    available. Transcripts can be long; only request them when needed.

    Args:
        note_id: Granola note id (not_..., from granola__list_meetings).
        include_transcript: Include the flattened meeting transcript.

    Returns:
        Dict with id, title, owner, attendees, calendar_event,
        folder_membership, summary, web_url, created_at, updated_at,
        and transcript (only when include_transcript=True).

    Raises:
        ValueError: If GRANOLA_API_KEY is not set.
        PermissionError: If the API key is invalid or expired.
        RuntimeError: If the note does not exist.
    """
    params = {"include": "transcript"} if include_transcript else None
    payload = _get(f"/notes/{note_id}", params)

    result: dict[str, Any] = {
        "id": payload.get("id"),
        "title": payload.get("title"),
        "owner": payload.get("owner"),
        "attendees": payload.get("attendees"),
        "calendar_event": payload.get("calendar_event"),
        "folder_membership": payload.get("folder_membership"),
        # Empty-string markdown is treated as absent — falls back to plain text.
        "summary": payload.get("summary_markdown") or payload.get("summary_text"),
        "web_url": payload.get("web_url"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }
    if include_transcript:
        result["transcript"] = _flatten_transcript(payload.get("transcript") or [])
    return _validated(result)


def granola__list_folders(cursor: str | None = None, page_size: int = 30) -> dict[str, Any]:
    """List Granola folders so meetings can be filtered by folder.

    Use the returned folder ids as the folder_id argument to
    granola__list_meetings (a folder filter includes its child folders).

    Args:
        cursor: Pagination cursor from a previous response.
        page_size: Results per page, 1-30 (default 30).

    Returns:
        Dict with folders (list of {id, name, parent_folder_id}),
        has_more (bool), and cursor (str or None) for the next page.

    Raises:
        ValueError: If GRANOLA_API_KEY is not set.
        PermissionError: If the API key is invalid or expired.
    """
    params: dict[str, Any] = {"page_size": max(1, min(int(page_size), _MAX_PAGE_SIZE))}
    if cursor is not None:
        params["cursor"] = cursor

    payload = _get("/folders", params)

    result: dict[str, Any] = {
        "folders": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "parent_folder_id": f.get("parent_folder_id"),
            }
            for f in payload.get("folders", [])
        ],
        "has_more": payload.get("hasMore", False),
        "cursor": payload.get("cursor"),
    }
    return _validated(result)


def register(mcp: Any) -> None:
    """Register Granola tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(granola__list_meetings)
    mcp.tool()(granola__get_meeting)
    mcp.tool()(granola__list_folders)


def _flatten_transcript(transcript: list[dict[str, Any]]) -> str:
    """Flatten Granola's per-utterance transcript array into dialogue lines.

    Speaker labels: diarization_label when present (e.g. "Speaker A"),
    otherwise "Me" for source=="microphone" and "Them" for source=="speaker".
    Consecutive utterances from the same speaker are merged into one line;
    timestamps are dropped.

    Args:
        transcript: Raw transcript array from GET /notes/{id}?include=transcript.

    Returns:
        Newline-joined dialogue lines ("<speaker>: <text>"), or "" when empty.
    """
    merged: list[tuple[str, str]] = []
    for utterance in transcript:
        text = (utterance.get("text") or "").strip()
        if not text:
            continue
        raw_label = (utterance.get("diarization_label") or "").strip()
        label = raw_label or ("Me" if utterance.get("source") == "microphone" else "Them")
        if merged and merged[-1][0] == label:
            merged[-1] = (label, f"{merged[-1][1]} {text}")
        else:
            merged.append((label, text))
    return "\n".join(f"{speaker}: {text}" for speaker, text in merged)
