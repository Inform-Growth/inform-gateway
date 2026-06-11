# Granola Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Built-in `granola__*` gateway tools (list meetings, get meeting with flattened transcript, list folders) backed by Granola's REST API.

**Architecture:** New module `remote-gateway/tools/integrations/granola.py` following the wiza pattern: plain functions calling `https://public-api.granola.ai/v1` via `httpx` with a server-side `GRANOLA_API_KEY` Bearer token, a `register(mcp)` hook wired into `core/mcp_server.py`, and responses checked against `context/fields/granola.yaml` via the field registry. All tools read-only and init-gated (the default).

**Tech Stack:** Python 3.11+, httpx, FastMCP, pytest (mocked `httpx.Client`), field registry YAML.

**Spec:** `docs/superpowers/specs/2026-06-11-granola-integration-design.md`

---

## Reference: upstream API

Base `https://public-api.granola.ai/v1`, auth `Authorization: Bearer grn_...`.

- `GET /notes` — query params `created_before`, `created_after`, `updated_after`, `folder_id`, `cursor`, `page_size` (1–30, default 10). Response: `{"notes": [{id, object, title, owner: {name, email}, created_at, updated_at}], "hasMore": bool, "cursor": str|null}`.
- `GET /notes/{id}` — optional `include=transcript`. Response adds `web_url`, `calendar_event`, `attendees`, `folder_membership`, `summary_text`, `summary_markdown` (nullable), and (when included) `transcript`: array of `{source: "microphone"|"speaker", text, start_timestamp, end_timestamp, diarization_label?}`.
- `GET /folders` — `cursor`, `page_size`. Response: `{"folders": [{id, object, name, parent_folder_id}], "hasMore": bool, "cursor": str|null}`.

Gotcha: only notes with a **finished AI summary and transcript** appear in the API.

---

### Task 1: Field registry schema

**Files:**
- Create: `remote-gateway/context/fields/granola.yaml`

The registry's `validate_response` does a flat top-level key check (unknown = response key not in YAML; missing = non-nullable YAML key absent from response). Three tools share the `granola` integration slug and return different shapes, so the YAML is the **union** of all top-level keys, every field `nullable: true` so no tool triggers `missing`.

- [ ] **Step 1: Create the schema file**

```yaml
integration: granola
source_url: https://docs.granola.ai/introduction
discovered_at: "2026-06-11"
last_drift_check: "2026-06-11"

fields:
  notes:
    display_name: Notes
    description: Array of meeting-note summaries (id, title, owner, timestamps) from granola__list_meetings.
    type: array
    notes: The API only returns notes with a finished AI summary and transcript — notes still processing or never summarized are invisible.
    nullable: true
  folders:
    display_name: Folders
    description: Array of folder objects (id, name, parent_folder_id) from granola__list_folders.
    type: array
    notes: ""
    nullable: true
  has_more:
    display_name: Has More
    description: True when additional pages exist; pass the returned cursor to fetch the next page.
    type: boolean
    notes: ""
    nullable: true
  cursor:
    display_name: Cursor
    description: Pagination cursor for the next page; null when no more results.
    type: string
    notes: ""
    nullable: true
  id:
    display_name: Note ID
    description: Granola note identifier (not_XXXXXXXXXXXXXX).
    type: string
    notes: ""
    nullable: true
  title:
    display_name: Title
    description: Meeting note title.
    type: string
    notes: May be null for untitled meetings.
    nullable: true
  owner:
    display_name: Owner
    description: Note owner as a user object with name and email.
    type: object
    notes: ""
    nullable: true
  attendees:
    display_name: Attendees
    description: Array of user objects (name, email) who attended the meeting.
    type: array
    notes: ""
    nullable: true
  calendar_event:
    display_name: Calendar Event
    description: Linked calendar event with title, organizer email, invitees, and scheduled times.
    type: object
    notes: ""
    nullable: true
  folder_membership:
    display_name: Folder Membership
    description: Array of folders this note belongs to.
    type: array
    notes: ""
    nullable: true
  summary:
    display_name: Summary
    description: AI-generated meeting summary — markdown when available, plain text otherwise.
    type: string
    notes: Sourced from summary_markdown with fallback to summary_text.
    nullable: true
  transcript:
    display_name: Transcript
    description: Full meeting transcript flattened to readable dialogue lines ("Me:" = note owner's mic, "Them:" = other participants, "Speaker A:" when diarization is available).
    type: string
    notes: Only present when include_transcript=true. Timestamps are dropped; consecutive lines from the same speaker are merged.
    nullable: true
  web_url:
    display_name: Web URL
    description: Direct link to the note in the Granola app.
    type: string
    notes: ""
    nullable: true
  created_at:
    display_name: Created At
    description: ISO 8601 creation timestamp.
    type: string
    notes: ""
    nullable: true
  updated_at:
    display_name: Updated At
    description: ISO 8601 last-update timestamp.
    type: string
    notes: ""
    nullable: true
```

- [ ] **Step 2: Verify the registry loads it**

Run: `cd /Users/jaronsander/main/inform/inform-gateway/remote-gateway && python -c "import sys; sys.path.insert(0, '.'); from core.field_registry import registry; fields = registry.get_all('granola'); print(sorted(fields.keys()))"`
Expected: prints the 15 field names including `notes`, `summary`, `transcript`.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/context/fields/granola.yaml
git commit -m "feat(granola): field registry schema"
```

---

### Task 2: Module skeleton — `_headers` and `_get`

**Files:**
- Create: `remote-gateway/tools/integrations/granola.py`
- Create: `remote-gateway/tests/test_granola_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `remote-gateway/tests/test_granola_tools.py`:

```python
"""
Unit tests for tools/integrations/granola.py — Granola meeting notes tools.

Run with:
    pytest remote-gateway/tests/test_granola_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx response."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.text = str(json_data)
    m.is_success = status_code < 400

    def raise_for_status():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")

    m.raise_for_status = raise_for_status
    return m


def _mock_client(get_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# ---------------------------------------------------------------------------
# Auth / transport (_headers, _get)
# ---------------------------------------------------------------------------

def test_get_raises_without_api_key(monkeypatch):
    """_get raises ValueError when GRANOLA_API_KEY is not set."""
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)

    from tools.integrations.granola import _get
    with pytest.raises(ValueError, match="GRANOLA_API_KEY"):
        _get("/notes")


def test_get_sends_bearer_token(monkeypatch):
    """_get sends GRANOLA_API_KEY as a Bearer token."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response({"notes": []})])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        _get("/notes")

    headers = mock_client.get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer grn_testkey"


def test_get_401_raises_permission_error(monkeypatch):
    """_get raises PermissionError on HTTP 401."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_bad")
    mock_client = _mock_client(get_responses=[_mock_response({}, status_code=401)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        with pytest.raises(PermissionError, match="GRANOLA_API_KEY"):
            _get("/notes")


def test_get_404_raises_not_found(monkeypatch):
    """_get raises RuntimeError naming the path on HTTP 404."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response({}, status_code=404)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        with pytest.raises(RuntimeError, match="not_doesNotExist00"):
            _get("/notes/not_doesNotExist00")


def test_get_400_raises_bad_request(monkeypatch):
    """_get raises RuntimeError with the response body on HTTP 400."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(
        get_responses=[_mock_response({"error": "bad folder_id"}, status_code=400)]
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        with pytest.raises(RuntimeError, match="bad folder_id"):
            _get("/notes")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_granola_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.integrations.granola'`

- [ ] **Step 3: Write the implementation**

Create `remote-gateway/tools/integrations/granola.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_granola_tools.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py
git commit -m "feat(granola): module skeleton with auth and error handling"
```

---

### Task 3: Transcript flattening

**Files:**
- Modify: `remote-gateway/tools/integrations/granola.py` (add `_flatten_transcript` after `_validated`)
- Modify: `remote-gateway/tests/test_granola_tools.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_granola_tools.py`:

```python
# ---------------------------------------------------------------------------
# Transcript flattening
# ---------------------------------------------------------------------------

def test_flatten_transcript_mic_and_speaker():
    """Mic utterances become 'Me:', speaker utterances become 'Them:'."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "Hi there.", "start_timestamp": "0"},
        {"source": "speaker", "text": "Hello!", "start_timestamp": "1"},
    ])
    assert out == "Me: Hi there.\nThem: Hello!"


def test_flatten_transcript_prefers_diarization_label():
    """diarization_label wins over the mic/speaker fallback."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "speaker", "text": "First point.", "diarization_label": "Speaker A"},
        {"source": "speaker", "text": "Reply.", "diarization_label": "Speaker B"},
    ])
    assert out == "Speaker A: First point.\nSpeaker B: Reply."


def test_flatten_transcript_merges_consecutive_same_speaker():
    """Consecutive utterances from the same speaker merge into one line."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "So the plan"},
        {"source": "microphone", "text": "is to ship Friday."},
        {"source": "speaker", "text": "Sounds good."},
    ])
    assert out == "Me: So the plan is to ship Friday.\nThem: Sounds good."


def test_flatten_transcript_skips_empty_text():
    """Utterances with empty or whitespace-only text are dropped."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "  "},
        {"source": "speaker", "text": "Real content."},
        {"source": "speaker", "text": ""},
    ])
    assert out == "Them: Real content."


def test_flatten_transcript_empty_list():
    """An empty transcript flattens to an empty string."""
    from tools.integrations.granola import _flatten_transcript
    assert _flatten_transcript([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k flatten -v`
Expected: FAIL — `ImportError: cannot import name '_flatten_transcript'`

- [ ] **Step 3: Write the implementation**

Add to `remote-gateway/tools/integrations/granola.py` (after `_validated`):

```python
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
        label = utterance.get("diarization_label") or (
            "Me" if utterance.get("source") == "microphone" else "Them"
        )
        if merged and merged[-1][0] == label:
            merged[-1] = (label, f"{merged[-1][1]} {text}")
        else:
            merged.append((label, text))
    return "\n".join(f"{speaker}: {text}" for speaker, text in merged)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k flatten -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py
git commit -m "feat(granola): flatten transcripts into dialogue lines"
```

---

### Task 4: `granola__list_meetings`

**Files:**
- Modify: `remote-gateway/tools/integrations/granola.py`
- Modify: `remote-gateway/tests/test_granola_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_granola_tools.py`:

```python
# ---------------------------------------------------------------------------
# granola__list_meetings
# ---------------------------------------------------------------------------

_LIST_NOTES_RESPONSE = {
    "notes": [
        {
            "id": "not_1d3tmYTlCICgjy",
            "object": "note",
            "title": "Weekly sync",
            "owner": {"name": "Jaron Sander", "email": "jaron@informgrowth.com"},
            "created_at": "2026-06-10T15:00:00Z",
            "updated_at": "2026-06-10T16:00:00Z",
        }
    ],
    "hasMore": True,
    "cursor": "eyJjcmVkZW50aWFsfQ==",
}


def test_list_meetings_returns_notes_and_pagination(monkeypatch):
    """granola__list_meetings returns note summaries with has_more and cursor."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_NOTES_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        result = granola__list_meetings()

    assert result["notes"][0]["id"] == "not_1d3tmYTlCICgjy"
    assert result["notes"][0]["title"] == "Weekly sync"
    assert result["notes"][0]["owner"]["email"] == "jaron@informgrowth.com"
    assert result["has_more"] is True
    assert result["cursor"] == "eyJjcmVkZW50aWFsfQ=="


def test_list_meetings_omits_none_params(monkeypatch):
    """Only non-None filters are sent; defaults send just page_size."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_NOTES_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        granola__list_meetings()

    params = mock_client.get.call_args.kwargs["params"]
    assert params == {"page_size": 10}


def test_list_meetings_passes_filters(monkeypatch):
    """All provided filters are passed through as query params."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_NOTES_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        granola__list_meetings(
            created_after="2026-06-01",
            created_before="2026-06-10",
            updated_after="2026-06-05",
            folder_id="fol_AAAABBBBCCCCdd",
            cursor="abc",
            page_size=25,
        )

    params = mock_client.get.call_args.kwargs["params"]
    assert params == {
        "page_size": 25,
        "created_after": "2026-06-01",
        "created_before": "2026-06-10",
        "updated_after": "2026-06-05",
        "folder_id": "fol_AAAABBBBCCCCdd",
        "cursor": "abc",
    }


def test_list_meetings_clamps_page_size(monkeypatch):
    """page_size is clamped to the API's 1-30 range."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(
        get_responses=[
            _mock_response(_LIST_NOTES_RESPONSE),
            _mock_response(_LIST_NOTES_RESPONSE),
        ]
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        granola__list_meetings(page_size=100)
        assert mock_client.get.call_args.kwargs["params"]["page_size"] == 30
        granola__list_meetings(page_size=0)
        assert mock_client.get.call_args.kwargs["params"]["page_size"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k list_meetings -v`
Expected: FAIL — `ImportError: cannot import name 'granola__list_meetings'`

- [ ] **Step 3: Write the implementation**

Add to `remote-gateway/tools/integrations/granola.py` (after `_flatten_transcript`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k list_meetings -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py
git commit -m "feat(granola): granola__list_meetings"
```

---

### Task 5: `granola__get_meeting`

**Files:**
- Modify: `remote-gateway/tools/integrations/granola.py`
- Modify: `remote-gateway/tests/test_granola_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_granola_tools.py`:

```python
# ---------------------------------------------------------------------------
# granola__get_meeting
# ---------------------------------------------------------------------------

_NOTE_RESPONSE = {
    "id": "not_1d3tmYTlCICgjy",
    "object": "note",
    "title": "Weekly sync",
    "owner": {"name": "Jaron Sander", "email": "jaron@informgrowth.com"},
    "attendees": [{"name": "Jane Smith", "email": "jane@example.com"}],
    "calendar_event": {"title": "Weekly sync", "organizer_email": "jaron@informgrowth.com"},
    "folder_membership": [{"id": "fol_AAAABBBBCCCCdd", "name": "Sales"}],
    "summary_text": "Plain summary.",
    "summary_markdown": "## Summary\n- Ship Friday",
    "web_url": "https://app.granola.ai/notes/not_1d3tmYTlCICgjy",
    "created_at": "2026-06-10T15:00:00Z",
    "updated_at": "2026-06-10T16:00:00Z",
}


def test_get_meeting_returns_note_fields(monkeypatch):
    """granola__get_meeting returns metadata and the markdown summary."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_NOTE_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__get_meeting
        result = granola__get_meeting("not_1d3tmYTlCICgjy")

    assert result["id"] == "not_1d3tmYTlCICgjy"
    assert result["title"] == "Weekly sync"
    assert result["summary"] == "## Summary\n- Ship Friday"
    assert result["attendees"][0]["email"] == "jane@example.com"
    assert result["web_url"] == "https://app.granola.ai/notes/not_1d3tmYTlCICgjy"
    assert "transcript" not in result

    requested_url = mock_client.get.call_args.args[0]
    assert requested_url.endswith("/notes/not_1d3tmYTlCICgjy")
    assert mock_client.get.call_args.kwargs["params"] == {}


def test_get_meeting_falls_back_to_summary_text(monkeypatch):
    """When summary_markdown is null, summary falls back to summary_text."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    note = dict(_NOTE_RESPONSE, summary_markdown=None)
    mock_client = _mock_client(get_responses=[_mock_response(note)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__get_meeting
        result = granola__get_meeting("not_1d3tmYTlCICgjy")

    assert result["summary"] == "Plain summary."


def test_get_meeting_includes_flattened_transcript(monkeypatch):
    """include_transcript=True sends include=transcript and flattens the result."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    note = dict(
        _NOTE_RESPONSE,
        transcript=[
            {"source": "microphone", "text": "Let's start."},
            {"source": "speaker", "text": "Ready."},
        ],
    )
    mock_client = _mock_client(get_responses=[_mock_response(note)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__get_meeting
        result = granola__get_meeting("not_1d3tmYTlCICgjy", include_transcript=True)

    assert mock_client.get.call_args.kwargs["params"] == {"include": "transcript"}
    assert result["transcript"] == "Me: Let's start.\nThem: Ready."


def test_get_meeting_not_found(monkeypatch):
    """A 404 surfaces as RuntimeError naming the note id."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response({}, status_code=404)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__get_meeting
        with pytest.raises(RuntimeError, match="not_doesNotExist00"):
            granola__get_meeting("not_doesNotExist00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k get_meeting -v`
Expected: FAIL — `ImportError: cannot import name 'granola__get_meeting'`

- [ ] **Step 3: Write the implementation**

Add to `remote-gateway/tools/integrations/granola.py` (after `granola__list_meetings`):

```python
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
        "summary": payload.get("summary_markdown") or payload.get("summary_text"),
        "web_url": payload.get("web_url"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }
    if include_transcript:
        result["transcript"] = _flatten_transcript(payload.get("transcript") or [])
    return _validated(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k get_meeting -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py
git commit -m "feat(granola): granola__get_meeting with flattened transcript"
```

---

### Task 6: `granola__list_folders`

**Files:**
- Modify: `remote-gateway/tools/integrations/granola.py`
- Modify: `remote-gateway/tests/test_granola_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_granola_tools.py`:

```python
# ---------------------------------------------------------------------------
# granola__list_folders
# ---------------------------------------------------------------------------

_LIST_FOLDERS_RESPONSE = {
    "folders": [
        {"id": "fol_AAAABBBBCCCCdd", "object": "folder", "name": "Sales", "parent_folder_id": None}
    ],
    "hasMore": False,
    "cursor": None,
}


def test_list_folders_returns_folders(monkeypatch):
    """granola__list_folders returns folder id/name/parent and pagination."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_FOLDERS_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_folders
        result = granola__list_folders()

    assert result["folders"] == [
        {"id": "fol_AAAABBBBCCCCdd", "name": "Sales", "parent_folder_id": None}
    ]
    assert result["has_more"] is False
    assert result["cursor"] is None

    requested_url = mock_client.get.call_args.args[0]
    assert requested_url.endswith("/folders")
    assert mock_client.get.call_args.kwargs["params"] == {"page_size": 30}


def test_list_folders_passes_cursor(monkeypatch):
    """A cursor is passed through as a query param."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_FOLDERS_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_folders
        granola__list_folders(cursor="abc")

    assert mock_client.get.call_args.kwargs["params"] == {"page_size": 30, "cursor": "abc"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k list_folders -v`
Expected: FAIL — `ImportError: cannot import name 'granola__list_folders'`

- [ ] **Step 3: Write the implementation**

Add to `remote-gateway/tools/integrations/granola.py` (after `granola__get_meeting`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest remote-gateway/tests/test_granola_tools.py -k list_folders -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py
git commit -m "feat(granola): granola__list_folders"
```

---

### Task 7: Register on the server

**Files:**
- Modify: `remote-gateway/tools/integrations/granola.py` (add `register` at end)
- Modify: `remote-gateway/core/mcp_server.py` (import block ~line 929-933; registration block ~line 966-970)

- [ ] **Step 1: Add the register hook**

Append to `remote-gateway/tools/integrations/granola.py`:

```python
def register(mcp: Any) -> None:
    """Register Granola tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(granola__list_meetings)
    mcp.tool()(granola__get_meeting)
    mcp.tool()(granola__list_folders)
```

- [ ] **Step 2: Wire into mcp_server.py**

In `remote-gateway/core/mcp_server.py`, the import block currently reads:

```python
from tools.integrations import apollo as _apollo_tools  # noqa: E402
from tools.integrations import attio as _attio_tools  # noqa: E402
from tools.integrations import email_tools as _email_tools  # noqa: E402
from tools.integrations import notes as _notes_tools  # noqa: E402
from tools.integrations import wiza as _wiza_tools  # noqa: E402
```

Add the granola import in alphabetical position (after `email_tools`):

```python
from tools.integrations import granola as _granola_tools  # noqa: E402
```

The registration block currently reads:

```python
_wiza_tools.register(mcp)
_apollo_tools.register(mcp)
```

Add after `_apollo_tools.register(mcp)`:

```python
_granola_tools.register(mcp)
```

- [ ] **Step 3: Verify the server imports cleanly and lint passes**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && ruff check remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py remote-gateway/core/mcp_server.py`
Expected: `All checks passed!`

Run: `pytest remote-gateway/tests/ -x -q`
Expected: full suite PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/tools/integrations/granola.py remote-gateway/core/mcp_server.py
git commit -m "feat(granola): register granola tools on the gateway"
```

---

### Task 8: Documentation

**Files:**
- Modify: `remote-gateway/CLAUDE.md` (env var table)
- Modify: `CLAUDE.md` (built-in tool inventory table)

- [ ] **Step 1: Add GRANOLA_API_KEY to the env table**

In `remote-gateway/CLAUDE.md`, after the `GOOGLE_APPLICATION_CREDENTIALS` row, add:

```markdown
| `GRANOLA_API_KEY` | Granola | Personal API key (`grn_...`) for the `granola__*` meeting-notes tools. Generate in the Granola desktop app: Settings > API (Business/Enterprise plans). |
```

- [ ] **Step 2: Add the tools to the root CLAUDE.md inventory**

In `CLAUDE.md`, in the "Built-in tools" table, after the `check_field_drift / ...` field-registry row, add:

```markdown
| `granola__list_meetings` / `granola__get_meeting` / `granola__list_folders` | Granola meeting notes — list meetings with date/folder filters, fetch a meeting's AI summary and flattened transcript, list folders. Requires `GRANOLA_API_KEY`. Only meetings with a finished AI summary are visible. |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md
git commit -m "docs(granola): env var and tool inventory entries"
```

---

### Task 9: Live smoke test

**Files:** none (verification only). `GRANOLA_API_KEY` is in `remote-gateway/.env`.

- [ ] **Step 1: Confirm the key variable name**

Run: `grep -o "^GRANOLA[A-Z_]*" remote-gateway/.env`
Expected: `GRANOLA_API_KEY` (if named differently, export accordingly below).

- [ ] **Step 2: List real meetings**

Run:
```bash
cd /Users/jaronsander/main/inform/inform-gateway/remote-gateway && \
set -a && source .env && set +a && \
python -c "
import sys, json
sys.path.insert(0, '.')
from tools.integrations.granola import granola__list_meetings
result = granola__list_meetings(page_size=3)
print(json.dumps(result, indent=2)[:2000])
"
```
Expected: JSON with up to 3 real notes, `has_more`, `cursor`, and **no** `_field_validation` key. If `_field_validation` appears, the real API shape drifted from the docs — update `granola.yaml` and/or the result mapping to match reality before proceeding.

- [ ] **Step 3: Fetch one meeting with transcript**

Run (substitute a real note id from step 2):
```bash
cd /Users/jaronsander/main/inform/inform-gateway/remote-gateway && \
set -a && source .env && set +a && \
python -c "
import sys
sys.path.insert(0, '.')
from tools.integrations.granola import granola__get_meeting
result = granola__get_meeting('<note_id_from_step_2>', include_transcript=True)
print('summary:', (result['summary'] or '')[:300])
print('transcript head:', (result.get('transcript') or '')[:500])
"
```
Expected: a real summary and dialogue-formatted transcript lines (`Me:` / `Them:` / `Speaker A:`). If the API returns transcript fields not matching the documented shape (e.g. different key names), fix `_flatten_transcript` and its tests to match reality.

- [ ] **Step 4: Final full suite + lint**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && ruff check . && pytest remote-gateway/tests/ -q`
Expected: both PASS. Commit any smoke-test-driven fixes:

```bash
git add -A remote-gateway/tools/integrations/granola.py remote-gateway/tests/test_granola_tools.py remote-gateway/context/fields/granola.yaml
git commit -m "fix(granola): align with live API shape"  # only if fixes were needed
```
