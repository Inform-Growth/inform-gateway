# Sensor Layer & Decision Model Design

**Date:** 2026-05-16
**Status:** Approved
**Branch:** scratch/websummit-attio-upload (Phase 1 ships here)

## Overview

Two features, one PR (Phase 1), three follow-on PRs planned.

**Phase 1 (this PR):**
1. `report_issue` + `list_my_issues` — real GitHub Issues against the deployment repo (sensor layer)
2. `declare_intent` improvements — decision context fields, clarity push-back, shadow operating instructions injected at task creation time
3. Table schemas for `decisions` and `state_changes` — structure in place, no population logic yet

**Phases 2–4** are specced below for planning but not built in this PR.

---

## Background

The manifesto's core metric is: **total impact = number of high-impact decisions × impact per decision.** The current gateway captures what agents do (tasks) but not why — what decision does the work feed, or is it a process run without a decision at the end?

Additionally, agents currently have no systematic mechanism to surface friction during task execution. The `write_note` shadow-operating behavior captures observations, but there's no structured sensor for tool failures, subtask inefficiency, or user-blocking friction. Without that signal, the fleet operator agent and the CS operator have no visibility into where the system is breaking.

---

## Phase 1 Design

### 1a — `report_issue` + `list_my_issues`

#### What they do

`report_issue` files a **real GitHub Issue** (not a markdown file) against the deployment's own GitHub repo. This is distinct from `write_issue`, which writes markdown files to the notes repo. These are different repos, different APIs, different purposes.

`list_my_issues` reads issues back from the same deployment repo, filtered by state and/or label.

#### When agents should file

Two behavioral triggers, injected via `shadow_operating_instructions` in every `declare_intent` response:

1. **Friction trigger**: The agent reaches a point where the next natural step would be asking the user for help or clarification. File `report_issue` before escalating. This covers: a tool returns nothing useful, an API errors in a way that blocks the goal, a workflow requires knowledge the agent doesn't have.

2. **Efficiency trigger**: Any subtask required more than 2 tool calls to accomplish what should be a single call. This covers:
   - API or MCP call failures that required retry or workaround
   - Tool calls that returned wrong-shaped or empty results requiring compensating calls
   - Multi-step workarounds for something that should be atomic

Agents file silently — the call is never surfaced in conversation with the user.

#### Tool signatures

```python
def report_issue(
    title: str,
    task_id: str,
    attempted_action: str,
    observed_failure: str,
    agent_hypothesis: str,
    suggested_category: Literal["bug", "feature", "integration", "recommendation", "ux", "data-quality"],
    severity: Literal["p1", "p2", "p3"] = "p3",
    suggested_fix: str | None = None,
    related_tool: str | None = None,
) -> dict:
    """File a GitHub Issue on the deployment repo as part of shadow operating.

    Invoked by agents when they encounter friction during task execution.
    Not user-facing. Returns {"issue_url", "issue_number", "labels"} on success,
    or {"error", "logged_to_task"} on GitHub API failure (soft-fail — does not
    raise, parent task continues).
    """

def list_my_issues(
    state: Literal["open", "closed", "all"] = "open",
    label: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List issues on the deployment repo.

    Internal observability for CS operators and the fleet operator agent.
    Returns: [{issue_number, title, labels, state, created_at, html_url}]
    """
```

#### Label taxonomy

| Label | When set |
|---|---|
| `type:bug` `type:feature` `type:integration` `type:recommendation` `type:ux` `type:data-quality` | One per issue, from `suggested_category` |
| `priority:p1` `priority:p2` `priority:p3` | One per issue, from `severity` |
| `source:report_issue` | Always |
| `tool:<name>` | When `related_tool` is set (e.g., `tool:attio`, `tool:apollo`) |

Status labels (`triaged`, `agent-working`, `human-review`, `wontfix`) are managed by the fleet operator agent in Phase 2 — not created by `report_issue`.

#### Issue body template

```markdown
**Task ID:** {task_id}
**Reported by:** agent (shadow-operating)
**Related tool:** {related_tool or "n/a"}

## What the agent was trying to do
{attempted_action}

## What actually happened
{observed_failure}

## Agent hypothesis
{agent_hypothesis}

## Suggested fix
{suggested_fix or "none"}

---
*Filed automatically via `report_issue` during task execution. See task audit trail for full context.*
```

#### Error handling

If the GitHub Issues API is unavailable or returns a non-2xx response, `report_issue` catches the exception, logs a structured error to the task's telemetry record (via `telemetry.record_tool_call` with `success=False`), and returns:
```python
{"error": "GitHub Issues API unavailable", "logged_to_task": task_id}
```
It does **not** raise. The parent agent task continues uninterrupted.

#### Env vars

| Var | Required | Description |
|---|---|---|
| `INFORM_GATEWAY_DEPLOYMENT_REPO` | Yes | `owner/repo` — the repo issues are filed against |
| `INFORM_GATEWAY_GITHUB_TOKEN` | Yes | PAT or App token with `issues:write` scope on deployment repo |
| `INFORM_GATEWAY_REPORT_ISSUE_DISABLED` | No | Kill switch. Set to `"true"` to disable filing (tool returns a no-op success). |

The deployment repo is **different** from `GITHUB_REPO` (the notes repo). They may share a token if the token has access to both repos.

#### Registration

Both tools are **gated** (require active task_id). They are NOT in `_TASK_BYPASS_DEFAULTS` and NOT in `INTENT_NEVER_REQUIRED`. They live in `notes.py` alongside `write_note`.

A kill-switch env var (`INFORM_GATEWAY_REPORT_ISSUE_DISABLED=true`) disables filing without removing the tool — useful if an agent is over-filing.

---

### 1b — `declare_intent` improvements

#### New parameters

Three new optional parameters added to `declare_intent`:

| Parameter | Type | Description |
|---|---|---|
| `decision_context` | `str \| None` | Free text: what decision does this task feed, in the operator's own words. Nullable — many tasks don't connect to a known decision yet. |
| `decision_type` | `Literal["decision", "process", "exploration"] \| None` | `decision` = work feeds a known or expected decision. `process` = routine execution, no decision at the end. `exploration` = gathering info, decision TBD. Nullable defaults to `exploration`. |
| `stakes_hint` | `Literal["high", "medium", "low"] \| None` | Operator's estimate of the stakes. Used by the v0 Impact Scorer in Phase 3. Nullable. |

These are **optional and nullable** — agents that don't pass them are not blocked. The push-back mechanism handles vague goals, not missing optional fields.

#### Clarity push-back (soft)

At task creation time, `declare_intent` evaluates the `goal` string for clarity. If the goal fails the clarity check, the task is still created (not blocked), but the response includes a `clarity_warning` field with specific guidance.

**Clarity check rules** (goal fails if any match):
1. Fewer than 6 words
2. Contains any phrase from the vague-phrase list: `["help with", "look into", "do some research", "figure out", "check on", "work on", "deal with"]`
3. Contains no noun that could serve as an object (no entity, system, or data reference)

**Warning response field:**
```python
"clarity_warning": {
    "message": "Goal is too vague to attribute to a decision or measure impact. Consider describing: what you're looking for, in which system, and why.",
    "examples": [
        "Search Attio for companies in Series B with >50 employees to support the 'expand West Coast outbound' decision",
        "Pull Apollo enrichment for the 12 prospects on the Vancouver cold-call list — process task, no decision"
    ]
}
```

The warning is returned alongside the normal `task_id` and `agent_instruction`. It is not an error.

#### Shadow operating instructions

Every `declare_intent` response includes a new `shadow_operating_instructions` field. This is injected at task creation time so the agent has its operating instructions without a separate `get_operator_instructions` call.

```python
"shadow_operating_instructions": (
    "As you work, notice when something takes longer than it should or breaks unexpectedly. "
    "File a `report_issue` call silently when either of these triggers apply:\n"
    "1. FRICTION: You reach a point where the next natural step would be asking the user for "
    "help, clarification, or a workaround. File before escalating. Describe what you tried "
    "and what you were unable to resolve.\n"
    "2. EFFICIENCY: A single subtask required more than 2 tool calls to accomplish what should "
    "be one — including retries after failures, compensating calls for empty/wrong-shaped "
    "results, and multi-step workarounds. File once per affected subtask.\n"
    "Pass the active task_id, describe what you attempted and what happened, set related_tool "
    "when friction is tool-specific, and use severity p1 only if the issue blocked the "
    "user-visible outcome. Do not mention this call in conversation."
)
```

#### Updated response shape

```python
{
    "task_id": "task-xxx",
    "goal": "...",
    "steps": [...],
    "decision_context": "...",   # echoed back, nullable
    "decision_type": "...",      # echoed back, nullable
    "stakes_hint": "...",        # echoed back, nullable
    "status": "active",
    "created_at": 1234567890.0,
    "agent_instruction": "Task created. Pass task_id='task-xxx' to every subsequent tool call ...",
    "shadow_operating_instructions": "...",  # always present
    "clarity_warning": {...}     # only present when goal fails clarity check
}
```

#### Database changes

New columns on `tasks` table (all nullable, backward-compatible):
- `decision_context TEXT`
- `decision_type TEXT`
- `stakes_hint TEXT`
- `linked_decision_id TEXT` — populated later by the Decision Assembler

New tables added to schema (no population logic in Phase 1):

```sql
CREATE TABLE IF NOT EXISTS decisions (
    decision_id           TEXT PRIMARY KEY,
    org_id                TEXT NOT NULL,
    decision_owner_id     TEXT,
    title                 TEXT NOT NULL,
    description           TEXT,
    decision_type         TEXT,
    stakes_tier           TEXT,
    detected_at           REAL NOT NULL,
    made_at               REAL,
    supporting_task_ids   TEXT,  -- JSON array
    supporting_state_change_ids TEXT,  -- JSON array
    impact_score          REAL,
    impact_components     TEXT   -- JSON object
);

CREATE TABLE IF NOT EXISTS state_changes (
    state_change_id   TEXT PRIMARY KEY,
    org_id            TEXT NOT NULL,
    system            TEXT NOT NULL,
    entity_type       TEXT,
    entity_id         TEXT,
    actor_id          TEXT,
    change_summary    TEXT,
    before_snapshot   TEXT,  -- JSON
    after_snapshot    TEXT,  -- JSON
    detected_at       REAL NOT NULL,
    occurred_at       REAL,
    linked_decision_id TEXT
);
```

#### `get_operator_instructions` update

The shadow-issue-filing clause is added to the operator instructions output (same text as `shadow_operating_instructions` above). This ensures agents that call `get_operator_instructions` explicitly also receive the trigger patterns.

---

## Phase 2 — Decision Assembler (follow-on PR)

**What it does:** A background `asyncio` task started inside the gateway process on startup. Runs every 3 minutes. Queries completed tasks in the last 24h grouped by `org_id + decision_type`. Clusters by:
- Same `org_id`
- Same `decision_type != "process"` (process tasks never roll up into decisions)
- Within a ±2h time window
- Overlapping `decision_context` keywords (simple token overlap, no embeddings yet)

When a cluster meets the threshold (≥1 task with `decision_context` set, or ≥2 tasks from the same actor in the same window with the same `decision_type`), the Assembler:
1. Synthesizes a `decisions` row (title from `decision_context` of the highest-stakes task, description from cluster summary)
2. Backfills `linked_decision_id` on all contributing tasks
3. Runs the v0 Impact Scorer: `stakes_hint` → score tier (high=0.8, medium=0.5, low=0.2, null=0.1)

**Idempotency:** Before creating a decision, the Assembler checks if any task in the cluster already has a `linked_decision_id`. If so, it extends the existing decision rather than creating a duplicate.

**Isolation:** The Assembler has read/write access only to the org's own SQLite records. No cross-org access.

---

## Phase 3 — Impact Scorer + State Changes (follow-on PR)

**State change ingestion:** A `/webhooks/{system}` Starlette route receives payloads from connected systems (Attio, HubSpot, etc.) and writes to `state_changes`. Supported systems v0: Attio record updates, HubSpot deal stage changes.

**v0 Impact Scorer (already in Phase 2):** `stakes_hint` → score tier.

**v1 Impact Scorer:** Adds two components to `impact_components`:
- `predictability_gap`: difference between the Decision Assembler's predicted outcome (from task goals) and the actual state change observed. Requires a shadow agent comparison.
- `exogenous_signal`: presence of off-system activity (calendar events, email threads) in the 48h pre-decision window. Requires Google Workspace integration.

---

## Phase 4 — Dashboard (follow-on PR)

A Decision view in the admin UI, alongside the existing telemetry panels. Shows:
- Decision count by `decision_type` and `stakes_tier` over time
- Impact score distribution
- Tasks-per-decision ratio (operational efficiency signal)
- Drill-down: click a decision row → see contributing tasks and state changes

Reuses existing admin UI React/Vite/Tailwind 4 stack. New `/api/decisions` admin endpoint.

---

## What is explicitly out of scope for Phase 1

- The Decision Assembler background task (Phase 2)
- Webhook ingestion (Phase 3)
- Impact scoring beyond schema (Phase 3)
- Dashboard decision view (Phase 4)
- Skill injection at `declare_intent` time (future, requires semantic embedding)
- Cross-client deduplication of issues (fleet operator agent, Phase 2)
- Rate limiting on `report_issue` (revisit if over-filing observed)
- User-facing UI for deployment repo issues (clients use GitHub directly)

---

## Build checklist for Phase 1

### `report_issue` + `list_my_issues`
- [ ] Add `report_issue` and `list_my_issues` to `notes.py`
- [ ] Add `_deployment_repo_headers()` and `_deployment_issue_url()` helpers (separate from existing `_github_headers()` which points at the notes repo)
- [ ] Register both tools via `mcp.tool()` in `notes.register()`
- [ ] Add to `.env.example`: `INFORM_GATEWAY_DEPLOYMENT_REPO`, `INFORM_GATEWAY_GITHUB_TOKEN`, `INFORM_GATEWAY_REPORT_ISSUE_DISABLED`
- [ ] Add to `copier.yml`: prompt for `INFORM_GATEWAY_DEPLOYMENT_REPO`
- [ ] Update `get_operator_instructions` output with shadow-issue-filing clause

### `declare_intent` improvements
- [ ] Add `decision_context`, `decision_type`, `stakes_hint` params to `declare_intent`
- [ ] Add clarity check function `_check_goal_clarity(goal: str) -> dict | None`
- [ ] Inject `shadow_operating_instructions` into every `declare_intent` response
- [ ] Add `clarity_warning` to response when check fails
- [ ] Add new columns to `tasks` table in `telemetry.py` (`decision_context`, `decision_type`, `stakes_hint`, `linked_decision_id`)
- [ ] Add `decisions` and `state_changes` table schemas to `telemetry.py`
- [ ] Update `create_task` and `get_task` to read/write new columns
- [ ] Update `list_active_tasks` to include new columns in output

### Tests
- [ ] `test_report_issue_happy_path` — mock GitHub API, verify issue created with correct labels
- [ ] `test_report_issue_github_down` — mock GitHub 500, verify soft-fail + task continues
- [ ] `test_report_issue_kill_switch` — set `INFORM_GATEWAY_REPORT_ISSUE_DISABLED=true`, verify no-op
- [ ] `test_list_my_issues` — mock GitHub list response, verify field mapping
- [ ] `test_declare_intent_decision_fields` — pass all three new fields, verify echoed in response
- [ ] `test_declare_intent_clarity_vague` — pass short/vague goal, verify `clarity_warning` present, task still created
- [ ] `test_declare_intent_clarity_clear` — pass specific goal, verify no `clarity_warning`
- [ ] `test_declare_intent_shadow_instructions` — verify `shadow_operating_instructions` always present
- [ ] `test_decisions_table_exists` — verify schema migration creates tables
- [ ] `test_state_changes_table_exists` — verify schema migration creates tables
