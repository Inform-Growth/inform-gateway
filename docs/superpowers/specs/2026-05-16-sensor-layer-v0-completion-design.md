# Sensor Layer v0 Completion Design

**Date:** 2026-05-16
**Status:** Approved
**Branch:** scratch/websummit-attio-upload

## Overview

Phase 1 of the sensor layer added `decision_context`, `decision_type`, and `stakes_hint` to the `tasks` table and updated `declare_intent` to capture them. However, the existing `list_tasks_for_org` method and the `GET /api/tasks` endpoint were never updated to read or return these fields. The loom also needs to filter tasks by time window and exclude process tasks before clustering them into decisions.

This spec covers the minimal changes needed to make the gateway's task data loom-readable:
1. Update `list_tasks_for_org` to include the three decision fields and support time-window + decision_type filtering
2. Expose those filters on `GET /api/tasks`
3. Add a compound index for efficient org + time-window queries

No new tables, no new authentication, no new endpoints.

---

## What the Loom Needs

The loom's Decision Assembler (Phase 2, external) clusters tasks into decisions by:
- Same `org_id`
- `decision_type != 'process'` (process tasks never roll up)
- Within a ±2h time window
- Overlapping `decision_context` keywords

To do this, the loom calls `GET /admin/api/tasks?org_id=<org>&from=<ts>&to=<ts>&exclude_process=true`. The response must include `decision_context`, `decision_type`, and `stakes_hint` on each task row.

---

## Changes

### 1. `remote-gateway/core/telemetry.py` — `list_tasks_for_org`

**New signature:**
```python
def list_tasks_for_org(
    self,
    org_id: str,
    status: str | None = None,
    limit: int = 100,
    from_ts: float | None = None,
    to_ts: float | None = None,
    exclude_process: bool = False,
) -> list[dict]:
```

**Changes:**
- SELECT now includes `decision_context, decision_type, stakes_hint`
- Returned dict includes all three fields
- When `from_ts` is set: `AND created_at >= from_ts`
- When `to_ts` is set: `AND created_at <= to_ts`
- When `exclude_process=True`: `AND decision_type != 'process'` — NULL decision_type rows are kept (they are not process tasks; the loom treats NULL as `exploration`)

### 2. `remote-gateway/core/admin_api.py` — `GET /api/tasks`

**New query params:**
| Param | Type | Description |
|---|---|---|
| `from` | float (unix ts) | Include tasks created at or after this timestamp |
| `to` | float (unix ts) | Include tasks created at or before this timestamp |
| `exclude_process` | `"true"` | Exclude tasks where `decision_type = 'process'` |

These are parsed and passed through to `list_tasks_for_org`. Existing `org_id`, `status`, `limit` params are unchanged.

### 3. `remote-gateway/core/telemetry.py` — compound index

Add to `_SCHEMA_INDEXES`:
```sql
CREATE INDEX IF NOT EXISTS idx_tasks_org_created ON tasks (org_id, created_at);
```

This makes `WHERE org_id = ? AND created_at BETWEEN ? AND ?` fast at scale.

---

## Response Shape

`GET /admin/api/tasks?org_id=acme&from=1747400000&to=1747407200&exclude_process=true`

```json
{
  "org_id": "acme",
  "tasks": [
    {
      "task_id": "task-abc123",
      "user_id": "alice",
      "org_id": "acme",
      "goal": "Evaluate whether to expand Acme account to enterprise tier",
      "steps": ["pull usage data", "check deal history"],
      "status": "complete",
      "outcome": "Usage data pulled. Recommended expansion.",
      "created_at": 1747401234.5,
      "completed_at": 1747401890.2,
      "decision_context": "Should we upgrade Acme to enterprise",
      "decision_type": "decision",
      "stakes_hint": "high"
    }
  ],
  "count": 1
}
```

---

## Tests

Three new tests appended to `remote-gateway/tests/test_task_manager.py`:

**`test_list_tasks_for_org_includes_decision_fields`**
Create a task with all three decision fields. Call `list_tasks_for_org`. Assert the returned dict includes `decision_context`, `decision_type`, `stakes_hint`.

**`test_list_tasks_for_org_time_window`**
Create three tasks at different timestamps. Call `list_tasks_for_org` with `from_ts`/`to_ts` spanning only the middle task. Assert only one task is returned.

**`test_list_tasks_for_org_exclude_process`**
Create one task with `decision_type="process"` and one with `decision_type="decision"`. Call with `exclude_process=True`. Assert only the decision task is returned.

---

## Out of scope

- New tables (`decisions`, `state_changes`) — these belong to the loom
- Pagination cursors — `limit` is sufficient for v0
- Write-back from loom into gateway — gateway is read-only for the loom
- Supabase migration — separate spec/plan
