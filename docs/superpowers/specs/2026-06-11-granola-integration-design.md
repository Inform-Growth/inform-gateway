# Granola Integration — Design

**Date:** 2026-06-11
**Status:** Approved
**Scope:** `main` (dogfood) only — not distributed to the template/clients.

## Goal

Let gateway agents query Granola meeting notes — list meetings, read AI summaries, and
pull transcripts — so sessions can ground work in meeting context (e.g. draft Attio notes
from sales calls, extract action items).

## Decision

Built-in Python tool module (the wiza/apollo pattern), **not** a proxied MCP connection.
Rationale: Granola's hosted MCP (`mcp.granola.ai/mcp`) is designed for interactive OAuth and
is unverified for headless bearer-key auth, while the REST API is tiny (3 endpoints),
key-authenticated, and transcripts are exactly the payload we want to shape server-side
rather than letting a third-party MCP dump raw utterance arrays into agent context.

## API surface (upstream)

Base URL: `https://public-api.granola.ai/v1`
Auth: `Authorization: Bearer grn_...` (personal API key; Business/Enterprise plans).

| Endpoint | Notes |
|---|---|
| `GET /v1/notes` | Filters: `created_before`, `created_after`, `updated_after`, `folder_id`; pagination: `cursor`, `page_size` (1–30, default 10). Returns note summaries + `hasMore`/`cursor`. |
| `GET /v1/notes/{id}` | `include=transcript` query param adds the transcript array. Returns title, owner, attendees, `calendar_event`, `folder_membership`, `summary_text`, `summary_markdown`, `web_url`. |
| `GET /v1/folders` | `cursor`, `page_size`. Returns `id`, `name`, `parent_folder_id`. |

**Gotcha:** the API only returns notes that have a finished AI summary and transcript;
notes still processing or never summarized are invisible.

## Module

`remote-gateway/tools/integrations/granola.py`

- Plain functions + `register(mcp)` hook called from `core/mcp_server.py` (after wiza/apollo).
- `httpx.Client` for synchronous GETs; no retries (fast reads).
- Env var: `GRANOLA_API_KEY` — read at call time; missing key raises `ValueError`.
- All tools **read-only** and **gated** by the init gate (the default — no allowlist entry).

## Tools

### `granola__list_meetings(created_after=None, created_before=None, updated_after=None, folder_id=None, cursor=None, page_size=10)`

Maps 1:1 to `GET /v1/notes`. Only non-None params are sent. `page_size` clamped to 1–30.
Returns `{notes: [{id, title, owner, created_at, updated_at}], has_more, cursor}`.

### `granola__get_meeting(note_id, include_transcript=False)`

`GET /v1/notes/{note_id}` (with `include=transcript` when requested). Returns the note's
metadata, attendees, calendar event, folder membership, and `summary_markdown` (falling
back to `summary_text` when markdown is null).

**Transcript flattening** (the token-shaping win): the raw transcript array (per-utterance
objects with `source`, `text`, start/end timestamps, optional `diarization_label`) is
flattened server-side into readable dialogue lines, one per utterance:

- `diarization_label` present → `Speaker A: <text>`
- else `source == "microphone"` → `Me: <text>`
- else (`source == "speaker"`) → `Them: <text>`

Consecutive lines from the same speaker are merged. Timestamps are dropped. The flattened
transcript is returned as a single `transcript` string field.

### `granola__list_folders(cursor=None, page_size=30)`

`GET /v1/folders`. Returns `{folders: [{id, name, parent_folder_id}], has_more, cursor}`
so agents can discover `folder_id`s for filtering `list_meetings`.

## Field registry

Responses pass through `registry.validate_response("granola", result)`; failures attach
`_field_validation` (same as wiza). New schema `remote-gateway/context/fields/granola.yaml`
documenting note fields, with a note about the finished-summary visibility gotcha.

## Error handling

| Condition | Behavior |
|---|---|
| `GRANOLA_API_KEY` unset | `ValueError` with setup hint |
| HTTP 401 | `PermissionError` — "invalid or expired GRANOLA_API_KEY" |
| HTTP 404 (get_meeting) | `RuntimeError` — "note not found: {note_id}" |
| HTTP 400 | `RuntimeError` with response body (bad filter/param) |
| Other ≥400 | `RuntimeError` with status + body |

## Testing

`remote-gateway/tests/test_granola_tools.py`, mirroring `test_wiza_tools.py`
(mocked `httpx.Client`):

- Happy path for each of the three tools.
- Filter/pagination params passed through correctly; None params omitted; `page_size` clamp.
- Transcript flattening: diarization labels, mic/speaker fallback, same-speaker merging,
  `include_transcript=False` sends no `include` param.
- `summary_markdown` → `summary_text` fallback.
- 401 → `PermissionError`; 404 → "note not found"; missing env var → `ValueError`.

## Docs & config

- `GRANOLA_API_KEY` row added to the env-var table in `remote-gateway/CLAUDE.md`.
- Tool inventory rows added to root `CLAUDE.md`.
- Marked `[custom]` — dogfood only; not synced by `distribute.yml`.

## Out of scope

- Webhook/ingestion path (Phase-3 state-change pattern).
- Granola enterprise API / team context.
- Proxying Granola's hosted MCP.
