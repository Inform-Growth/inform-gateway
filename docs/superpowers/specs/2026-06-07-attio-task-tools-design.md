# Attio Task Tools — Design Spec

**Date:** 2026-06-07
**Issue:** [#71 — attio: no task creation tool](https://github.com/Inform-Growth/inform-gateway/issues/71)
**Approach:** A — Python `create_task` + `list_tasks`, deny `batch_records` in proxy

---

## Problem

The `attio-mcp` npm proxy exposes `batch_records` but crashes with `TypeError: Cannot read properties of undefined (reading 'toLowerCase')` when `object_type: tasks` is passed. This is because Attio tasks are a first-class resource at `/v2/tasks`, not object records at `/v2/objects/tasks/records`. No dedicated `attio__create_task` tool exists, so agents reach for `batch_records` as a workaround and hit the crash.

---

## Architecture

All changes live in two files:

- `remote-gateway/tools/integrations/attio.py` — two new Python functions added alongside existing overrides
- `remote-gateway/mcp_connections.json` — `batch_records` added to the Attio deny list

The npm proxy continues to handle all other Attio tools. The pattern mirrors the existing overrides (`search_records`, `create_record`, `update_record`, `upsert_record`): implement in Python, deny the npm version.

---

## Components

### `attio__create_task`

Calls `POST /v2/tasks`.

**Parameters:**
- `content: str` — task description (required)
- `assignee_id: str | None` — workspace member UUID; wrapped into `assignees` array internally
- `deadline_at: str | None` — ISO 8601 datetime string (e.g. `"2026-06-08T23:59:59.000Z"`)
- `linked_records: list[dict] | None` — list of `{"target_object": "companies", "target_record_id": "<uuid>"}` objects

**Request body sent to Attio:**
```json
{
  "data": {
    "content": "Follow up with Canals re: partnership",
    "assignees": [{"workspace_member_id": "24154ea2-..."}],
    "deadline_at": "2026-06-08T23:59:59.000Z",
    "linked_records": [
      {"target_object": "companies", "target_record_id": "<uuid>"}
    ],
    "is_completed": false
  }
}
```
Optional fields are omitted from the body when not provided (not sent as null).

**Returns on success:** `{"task_id": "<uuid>", "content": "...", "data": <full Attio response>}`
**Returns on error:** `{"error": "Attio API error {status}: {body}"}`

---

### `attio__list_tasks`

Calls `GET /v2/tasks` with optional query params.

**Parameters:**
- `assignee_id: str | None` — filter to tasks assigned to this workspace member UUID
- `is_completed: bool | None` — filter by completion status; omit to return all
- `limit: int` — max results, defaults to 20

**Query params sent to Attio:** `filter[assignees]`, `filter[is_completed]`, `limit`

**Returns:** `{"tasks": [...], "count": N}` where each task is the raw Attio task object.

---

### `mcp_connections.json` change

```json
"attio": {
  "tools": {
    "deny": ["search_records", "create_record", "update_record", "batch_records"]
  }
}
```

`update_record` is already denied (Python override exists). Adding `batch_records` closes the crash surface.

---

## Error Handling

Both functions use the same pattern as existing tools: non-2xx Attio responses return `{"error": "Attio API error {status}: {body}"}` with no exception raised, so agents receive a structured error they can act on.

Missing `ATTIO_API_KEY` raises `ValueError` (same as existing `_headers()` helper — shared, no change needed).

---

## Registration

Both functions added to `register(mcp)` in `attio.py`:
```python
mcp.tool()(attio__create_task)
mcp.tool()(attio__list_tasks)
```

---

## Testing

Tests added to `remote-gateway/tests/test_attio_tools.py` using the existing `_mock_client` / `_mock_response` pattern.

**`attio__create_task` tests:**
- Posts to `/v2/tasks` (not `/v2/objects/tasks/records`)
- Body wraps in `{"data": {...}}`
- Wraps `assignee_id` into `assignees` array
- Omits optional fields when not provided (no null keys sent)
- Returns `task_id` from `data.id.task_id` in response
- Returns error dict on non-2xx, does not raise

**`attio__list_tasks` tests:**
- GETs `/v2/tasks`
- Passes `filter[assignees]` when `assignee_id` provided
- Passes `filter[is_completed]` when provided
- Returns `{"tasks": [...], "count": N}`
- Handles empty response gracefully

**Friction-to-test note:** Issue #71 was an agent-contract gap — no `create_task` tool existed. These tests directly verify the gap is closed: if `attio__create_task` exists and posts to the correct endpoint, no agent needs to reach for `batch_records` as a workaround.
