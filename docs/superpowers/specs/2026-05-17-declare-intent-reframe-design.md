# Design: declare_intent Reframe & Task Quality Gate

**Date:** 2026-05-17
**Status:** Approved

## Overview

This change updates the `declare_intent` tool, the init gate message, and adds `update_task` to reflect the correct sensor/loom architecture. The gateway (Camber core) is the sensor — it captures raw signal from agent sessions. The loom is the thing that figures out what decisions tasks support. Agents should not see "decision tracking" language; they should see "tell us what you're working on."

Scope:
- Option B language reframe on `declare_intent` and the gate message
- Operator context injected automatically via the gate (no reliance on `get_operator_instructions`)
- Agent-side self-check returned with task creation (no server-side blocking)
- New `update_task` tool
- All changes apply to `main`; template migration is a separate pass

---

## Architecture Context

The gateway operates in two layers:

**Camber core (this repo) — the sensor:**
Captures raw signal from every agent session via tasks (`declare_intent` / `complete_task`), tool-call telemetry, and friction issues (`report_issue`). Tasks hold three hint fields (`decision_context`, `decision_type`, `stakes_hint`) that the loom uses as signal — agents provide these as natural context about their work, not as explicit decision labels.

**The loom (separate repo) — the decision layer:**
Reads task records from `/admin/api/tasks`, clusters them into decisions by org, time window, and overlapping context, and scores impact. The loom is read-only against the gateway schema. It figures out what decision a task supports — the agent never needs to know this is happening.

**Operator roles (future):**
Each operator will get a role (autonomous agent vs. human operator). Human operators will go through role onboarding; the loom will infer role responsibilities from task/tool patterns over time. Role routing (analogous to org routing) ships later. The language in this design is written to stay consistent when roles ship.

---

## Section 1 — Language Reframe (Option B)

### declare_intent docstring

Replace all decision-tracking framing with goal/context framing:

- **Tool description:** "Tell us what you're working on before using any gateway tool. Creates a task that attributes your tool calls to a goal and helps the organization understand what its AI is accomplishing."
- **`goal`:** "One sentence: what are you trying to accomplish, in what system or context."
- **`steps`:** "Ordered list of planned actions (e.g. `['search CRM for Vancouver accounts', 'enrich top 10 with Apollo']`)."
- **`decision_context`:** "Optional — why this work matters to the organization. What question are you trying to answer or what outcome are you supporting? More context helps the org learn from this session."
- **`decision_type`:** "Optional — the nature of this work: `process` (routine, repeatable), `exploration` (gathering information, direction unclear), or `decision` (a specific choice needs to be made)."
- **`stakes_hint`:** "Optional — how important this feels: `high`, `medium`, or `low`."

DB column names are unchanged. The language hides the loom's purpose entirely.

### Gate message (_make_gate_task_redirect)

Replace the terse "no task_id provided" message. The gate response becomes the operator briefing — automatically delivered the first time any tool is called without an active task. See Section 2 for full content.

---

## Section 2 — Gate Message as Operator Context Injection

`_make_gate_task_redirect` is the automatic injection point for operator context. It fires on any tool call without an active task. Autonomous agents (N8N, etc.) with intent disabled via `tool_intent_overrides` never see this.

The gate response includes:

```python
{
    "gateway_status": "no_active_task",
    "blocked_tool": tool_name,
    "required_action": "declare_intent",
    "message": (
        "GATEWAY: No active task for this session. Before using tools, "
        "tell us what you're working on by calling declare_intent.\n\n"
        "AGENT INSTRUCTION: Before calling declare_intent, make sure you have "
        "gathered the following from the user:\n"
        "1. What specifically they need — which system, data, or action\n"
        "2. Why it matters — what question they're trying to answer or outcome they're supporting\n"
        "3. How important this is — high, medium, or low\n\n"
        "Then call declare_intent with a goal, planned steps, and as much of "
        "the above context as the user has provided."
    ),
}
```

`get_operator_instructions` is unchanged — it remains available for agents that call it manually, but is no longer load-bearing for the gate flow.

---

## Section 3 — Post-Creation Self-Check (Agent-Side)

The server stays non-blocking. `declare_intent` always creates the task. The clarity check (`_check_goal_clarity`) continues to run on the goal text for vague phrases and word count, but the bigger change is that every `declare_intent` response includes a `task_criteria` block:

```python
_TASK_CRITERIA_CHECKLIST = [
    "Goal names a specific system, dataset, or context",
    "Goal describes what action you are taking, not just a topic",
    "Context explains why this matters to the organization",
    "Stakes level is set (high / medium / low)",
    "At least 2 concrete planned steps are listed",
]

_TASK_CRITERIA_INSTRUCTION = (
    "Review this task against each item above. "
    "If any are missing, call update_task with the task_id before proceeding to other tools. "
    "Richer task descriptions help the organization learn from this session."
)
```

The agent reads this after task creation, self-checks, and calls `update_task` to fill gaps. The server does not block on missing fields.

The existing `clarity_warning` return (for vague phrases / short goals) is kept as-is — it is one signal among others, not a gate.

---

## Section 4 — update_task Tool

New tool registered in `task_manager.py`. Added to `_GATE_BYPASS` in `mcp_server.py` — it is a task lifecycle tool (like `declare_intent`, `complete_task`, `get_tasks`) and must not require an active task to call, since its purpose is to update the task that was just created. Owner-only, active-tasks-only.

**Signature:**
```python
def update_task(
    task_id: str,
    goal: str | None = None,
    context: str | None = None,
    stakes_hint: str | None = None,
    work_type: str | None = None,
    steps: list[str] | None = None,
) -> dict:
```

Note: parameter names use agent-friendly language (`context`, `work_type`) mapped to DB columns (`decision_context`, `decision_type`) inside the implementation.

**Behavior:**
- Any field left `None` is unchanged
- Updates the task record in telemetry
- Returns the full updated task dict
- Returns an error dict if task not found, not owned by caller, or already complete

**Telemetry change:**
Add `update_task` telemetry method to `TelemetryStore`:
```python
def update_task(
    self,
    task_id: str,
    user_id: str,
    goal: str | None,
    decision_context: str | None,
    stakes_hint: str | None,
    decision_type: str | None,
    steps: list[str] | None,
) -> dict | None
```

---

## Files Changed

| File | Change |
|---|---|
| `remote-gateway/tools/_core/task_manager.py` | Reframe docstrings; add `_TASK_CRITERIA_CHECKLIST`; update `declare_intent` return; add `update_task` tool |
| `remote-gateway/core/mcp_server.py` | Update `_make_gate_task_redirect` with operator context injection; add `update_task` to `_GATE_BYPASS` |
| `remote-gateway/core/telemetry.py` | Add `update_task` method to `TelemetryStore` |
| `remote-gateway/prompts/init.md` | Minor: note that gate handles auto-injection; update issue tool references |
| `remote-gateway/tests/test_task_manager.py` | Tests for `update_task`; updated assertions for new gate message and criteria block |
| `CLAUDE.md` | Note operator role architecture (future), update tool inventory |

---

## Out of Scope

- Operator role field (future — loom-driven inference)
- Role onboarding flow (future)
- Role routing (future — analogous to org routing)
- Template branch migration (separate pass after this lands on main)
- Any changes to `get_operator_instructions` behavior
- Any server-side blocking on task quality
