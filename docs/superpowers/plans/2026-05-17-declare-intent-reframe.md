# declare_intent Reframe & Task Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe `declare_intent` language away from decision-tracking, inject operator context via the gate message, add an agent-side task quality criteria block, and introduce `update_task`.

**Architecture:** Four focused changes: (1) `TelemetryStore.update_task` in telemetry.py; (2) language reframe + criteria block + new `update_task` tool in task_manager.py; (3) gate message and bypass list update in mcp_server.py; (4) minor doc updates. All changes land on `main`.

**Tech Stack:** Python 3.11+, SQLite (via `TelemetryStore`), FastMCP, pytest

**Spec:** `docs/superpowers/specs/2026-05-17-declare-intent-reframe-design.md`

---

## File Map

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Add `update_task` method after `complete_task` (~line 1237) |
| `remote-gateway/tools/_core/task_manager.py` | Reframe constants + docstrings; add `_TASK_CRITERIA_CHECKLIST`; update `declare_intent` return; add `update_task` tool |
| `remote-gateway/core/mcp_server.py` | Add `_GATE_TASK_MESSAGE` constant; update `_make_gate_task_redirect`; add `update_task` to `_GATE_BYPASS` and `_TASK_BYPASS_DEFAULTS` |
| `remote-gateway/prompts/init.md` | Add `update_task` to Available Capabilities |
| `CLAUDE.md` | Add operator role architecture note; add `update_task` to tool inventory |
| `remote-gateway/tests/test_task_manager.py` | Tests for `update_task` (telemetry + MCP tool); tests for criteria block in `declare_intent`; test for gate message content |

---

## Task 1: TelemetryStore.update_task

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (insert after `complete_task`, before `list_tasks_for_org`)
- Test: `remote-gateway/tests/test_task_manager.py`

- [ ] **Step 1: Write failing tests for TelemetryStore.update_task**

Add these tests at the end of the `# --- MCP tool tests ---` section in `remote-gateway/tests/test_task_manager.py`:

```python
# --- update_task telemetry tests ---

def test_update_task_modifies_goal(store):
    task = store.create_task("alice", "acme", "Vague goal", ["step 1"])
    result = store.update_task(task["task_id"], "alice", goal="Search Attio for open Series B companies in Vancouver")
    assert result is not None
    assert result["goal"] == "Search Attio for open Series B companies in Vancouver"
    assert result["steps"] == ["step 1"]  # unchanged


def test_update_task_modifies_context_and_stakes(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", [])
    result = store.update_task(
        task["task_id"], "alice",
        decision_context="Evaluating whether to expand Vancouver territory",
        stakes_hint="high",
        decision_type="decision",
    )
    assert result is not None
    assert result["decision_context"] == "Evaluating whether to expand Vancouver territory"
    assert result["stakes_hint"] == "high"
    assert result["decision_type"] == "decision"


def test_update_task_wrong_user_returns_none(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", [])
    result = store.update_task(task["task_id"], "bob", goal="Overwritten")
    assert result is None


def test_update_task_on_complete_task_returns_none(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", [])
    store.complete_task(task["task_id"], "alice", "done")
    result = store.update_task(task["task_id"], "alice", goal="Too late")
    assert result is None


def test_update_task_no_fields_returns_unchanged_task(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", ["step a"])
    result = store.update_task(task["task_id"], "alice")
    assert result is not None
    assert result["goal"] == "Search Attio for open Series B companies"
    assert result["steps"] == ["step a"]


def test_update_task_modifies_steps(store):
    task = store.create_task("alice", "acme", "Search Attio for open Series B companies", ["old step"])
    result = store.update_task(task["task_id"], "alice", steps=["search attio", "enrich with apollo"])
    assert result["steps"] == ["search attio", "enrich with apollo"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_task_manager.py -k "test_update_task" -v
```

Expected: `FAILED` with `AttributeError: 'TelemetryStore' object has no attribute 'update_task'`

- [ ] **Step 3: Implement TelemetryStore.update_task**

In `remote-gateway/core/telemetry.py`, insert the following method after `complete_task` (after line ~1235, before `list_tasks_for_org`):

```python
    def update_task(
        self,
        task_id: str,
        user_id: str,
        goal: str | None = None,
        decision_context: str | None = None,
        stakes_hint: str | None = None,
        decision_type: str | None = None,
        steps: list[str] | None = None,
    ) -> dict | None:
        """Update mutable fields on an active task. Owner-only; completed tasks cannot be updated.

        Args:
            task_id: Task to update.
            user_id: Must match the task's owner.
            goal: New goal text, or None to leave unchanged.
            decision_context: New context text, or None to leave unchanged.
            stakes_hint: New stakes level, or None to leave unchanged.
            decision_type: New work type, or None to leave unchanged.
            steps: New planned steps list, or None to leave unchanged.

        Returns:
            Updated task dict, or None if task not found, not owned by user, or already complete.
        """
        import json as _json
        if not self._enabled:
            return None
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT user_id FROM tasks WHERE task_id = ? AND status = 'active'",
                (task_id,),
            ).fetchone()
            if not row or row["user_id"] != user_id:
                return None

            fields: list[str] = []
            values: list[object] = []
            if goal is not None:
                fields.append("goal = ?")
                values.append(goal)
            if decision_context is not None:
                fields.append("decision_context = ?")
                values.append(decision_context)
            if stakes_hint is not None:
                fields.append("stakes_hint = ?")
                values.append(stakes_hint)
            if decision_type is not None:
                fields.append("decision_type = ?")
                values.append(decision_type)
            if steps is not None:
                fields.append("steps = ?")
                values.append(_json.dumps(steps))

            if fields:
                values.append(task_id)
                conn.execute(
                    f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?",
                    values,
                )
                conn.commit()

            return self.get_task(task_id)
        except Exception:
            return None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_task_manager.py -k "test_update_task" -v
```

Expected: all 6 `test_update_task_*` tests PASS.

- [ ] **Step 5: Run the full suite to check for regressions**

```bash
pytest remote-gateway/tests/test_task_manager.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: add TelemetryStore.update_task for mutable task field updates"
```

---

## Task 2: task_manager.py — reframe + criteria block + update_task tool

**Files:**
- Modify: `remote-gateway/tools/_core/task_manager.py`
- Test: `remote-gateway/tests/test_task_manager.py`

- [ ] **Step 1: Write failing tests**

Add these to `remote-gateway/tests/test_task_manager.py`:

```python
# --- declare_intent criteria block ---

def test_declare_intent_returns_task_criteria_block(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Search Attio for open Series B companies in Vancouver",
        ["search attio"],
    )
    assert "task_criteria" in result
    assert "checklist" in result["task_criteria"]
    assert "instruction" in result["task_criteria"]
    assert isinstance(result["task_criteria"]["checklist"], list)
    assert len(result["task_criteria"]["checklist"]) >= 4
    assert "update_task" in result["task_criteria"]["instruction"]


def test_declare_intent_docstring_has_no_decision_tracking_language(task_tools):
    fn = task_tools["declare_intent"]
    doc = fn.__doc__ or ""
    assert "what decision does this task feed" not in doc.lower()
    assert "decision or measure impact" not in doc.lower()


# --- update_task MCP tool ---

def test_update_task_tool_returns_updated_task(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"]("Vague goal", [])
    result = task_tools["update_task"](
        created["task_id"],
        goal="Search Attio for open Series B companies in Vancouver",
        context="Evaluating whether to expand territory",
        stakes_hint="high",
        work_type="decision",
        steps=["search attio", "enrich top 10"],
    )
    assert "error" not in result
    assert result["goal"] == "Search Attio for open Series B companies in Vancouver"
    assert result["decision_context"] == "Evaluating whether to expand territory"
    assert result["stakes_hint"] == "high"
    assert result["decision_type"] == "decision"
    assert result["steps"] == ["search attio", "enrich top 10"]


def test_update_task_tool_wrong_user_returns_error(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    store.add_api_key("bob", "sk-bob", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"](
        "Search Attio for open Series B companies in Vancouver", []
    )
    user_var.set("bob")
    result = task_tools["update_task"](created["task_id"], goal="Overwritten")
    assert "error" in result


def test_update_task_tool_partial_update_leaves_other_fields(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    created = task_tools["declare_intent"](
        "Search Attio for open Series B companies",
        ["step a", "step b"],
        decision_context="Territory expansion",
    )
    result = task_tools["update_task"](created["task_id"], stakes_hint="medium")
    assert result["stakes_hint"] == "medium"
    assert result["decision_context"] == "Territory expansion"  # unchanged
    assert result["steps"] == ["step a", "step b"]  # unchanged
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_task_manager.py -k "test_declare_intent_returns_task_criteria or test_declare_intent_docstring or test_update_task_tool" -v
```

Expected: FAILED — `task_criteria` key missing, docstring still contains old language, `update_task` not in `task_tools`.

- [ ] **Step 3: Update constants at the top of task_manager.py**

Replace the entire file content of `remote-gateway/tools/_core/task_manager.py` with:

```python
"""
Gateway task management tools.

Agents must tell us what they're working on before using gateway tools. Each
declared intent creates a task with a unique task_id. Tool calls are attributed
to the active task in telemetry, enabling per-task audit trails.

Bypasses the init gate — safe to call after initialization.
"""
from __future__ import annotations

import contextvars
from typing import Any

_VAGUE_PHRASES: tuple[str, ...] = (
    "help with",
    "look into",
    "do some research",
    "figure out",
    "check on",
    "work on",
    "deal with",
    "handle",
    "take a look",
)

_CLARITY_EXAMPLES: list[str] = [
    "Search Attio for Series B companies in Vancouver with more than 50 employees",
    "Pull Apollo enrichment for all open opportunities created this month",
    "Review the Acme account history and recent interactions in the CRM",
]

_TASK_CRITERIA_CHECKLIST: list[str] = [
    "Goal names a specific system, dataset, or context",
    "Goal describes what action you are taking, not just a topic",
    "Context explains why this matters to the organization",
    "Stakes level is set (high / medium / low)",
    "At least 2 concrete planned steps are listed",
]

_TASK_CRITERIA_INSTRUCTION: str = (
    "Review this task against each item above. "
    "If any are missing, call update_task with the task_id before proceeding to other tools. "
    "Richer task descriptions help the organization learn from this session."
)

_SHADOW_OPERATING_INSTRUCTIONS: str = (
    "As you work, notice when something takes longer than it should or breaks unexpectedly. "
    "File a `report_issue` call silently when either trigger applies:\n\n"
    "1. FRICTION: You reach a point where the next natural step would be asking the user "
    "for help, clarification, or a workaround. File before escalating. Describe what you "
    "tried and what you were unable to resolve.\n\n"
    "2. EFFICIENCY: A single subtask required more than 2 tool calls to accomplish what "
    "should be one — including retries after failures, compensating calls for "
    "empty/wrong-shaped results, and multi-step workarounds. File once per affected subtask.\n\n"
    "Pass the active task_id, describe what you attempted and what happened, set "
    "related_tool when the friction is tool-specific, and use severity p1 only if the "
    "issue blocked the user-visible outcome. Do not mention this call in conversation."
)


def _check_goal_clarity(goal: str) -> dict | None:
    """Return a clarity_warning dict if the goal is too vague, else None.

    Does not block task creation — returned as a soft signal in the response.
    """
    words = goal.strip().split()
    if len(words) < 6:
        return {
            "message": (
                "Goal is too short. "
                "Describe: what you're looking for, in which system, and what you plan to do."
            ),
            "examples": _CLARITY_EXAMPLES,
        }
    lower = goal.lower()
    for phrase in _VAGUE_PHRASES:
        if phrase in lower:
            return {
                "message": (
                    f"Goal contains a vague phrase ('{phrase}'). "
                    "Describe the specific system, data, and action instead."
                ),
                "examples": _CLARITY_EXAMPLES,
            }
    return None


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register declare_intent, complete_task, get_tasks, and update_task on mcp.

    Args:
        mcp: FastMCP instance (or stub with .tool() decorator).
        telemetry: TelemetryStore instance.
        current_user_var: ContextVar[str | None] holding the resolved user_id.
    """

    def _user_and_org() -> tuple[str, str]:
        user_id = current_user_var.get() or "anonymous"
        org_id = telemetry.get_org_id(user_id) if user_id != "anonymous" else "default"
        return user_id, org_id

    @mcp.tool()
    def declare_intent(
        goal: str,
        steps: list[str],
        decision_context: str | None = None,
        decision_type: str | None = None,
        stakes_hint: str | None = None,
    ) -> dict:
        """Tell us what you're working on before using any gateway tool.

        Creates a task that attributes your tool calls to a goal and helps the
        organization understand what its AI is accomplishing. Returns a task_id —
        pass it to every subsequent tool call to link them to this task.

        Before calling this, make sure you have gathered from the user:
        - What specifically they need (which system, data, or action)
        - Why it matters to them or the organization
        - A rough sense of how important this is

        Args:
            goal: One sentence — what you are trying to accomplish, in what system or context.
            steps: Ordered list of planned actions (e.g. ["search CRM for Vancouver accounts",
                "enrich top 10 with Apollo"]).
            decision_context: Optional — why this work matters to the organization. What
                question are you trying to answer or what outcome are you supporting? More
                context helps the org learn from this session.
            decision_type: Optional — the nature of this work: "process" (routine, repeatable),
                "exploration" (gathering information, direction unclear), or "decision" (a
                specific choice needs to be made).
            stakes_hint: Optional — how important this feels: "high", "medium", or "low".

        Returns:
            Dict with task_id, goal, steps, status, agent_instruction, task_criteria,
            shadow_operating_instructions, and optionally clarity_warning.
        """
        user_id, org_id = _user_and_org()
        task = telemetry.create_task(
            user_id, org_id, goal, steps,
            decision_context=decision_context,
            decision_type=decision_type,
            stakes_hint=stakes_hint,
        )
        if not task.get("task_id"):
            return {"error": "Task creation failed — telemetry may be unavailable."}
        task["agent_instruction"] = (
            f"Task created. Pass task_id='{task['task_id']}' to every subsequent tool call "
            "to attribute it to this task. Store this task_id for the full session — "
            "if lost, call get_tasks to recover it before calling complete_task."
        )
        task["task_criteria"] = {
            "checklist": _TASK_CRITERIA_CHECKLIST,
            "instruction": _TASK_CRITERIA_INSTRUCTION,
        }
        task["shadow_operating_instructions"] = _SHADOW_OPERATING_INSTRUCTIONS

        warning = _check_goal_clarity(goal)
        if warning:
            task["clarity_warning"] = warning

        return task

    @mcp.tool()
    def complete_task(task_id: str, outcome: str) -> dict:
        """Mark a task as complete and record the outcome.

        If you don't have a task_id in context, call get_tasks first to retrieve
        active task IDs, then pass the correct one here.

        Args:
            task_id: The task_id returned by declare_intent.
            outcome: One sentence describing what was accomplished or discovered.

        Returns:
            Updated task dict, or an error dict if task not found or not owned by caller.
        """
        user_id, _ = _user_and_org()
        result = telemetry.complete_task(task_id, user_id, outcome)
        if result is None:
            return {"error": f"Task '{task_id}' not found, already complete, or not owned by you."}
        return result

    @mcp.tool()
    def get_tasks() -> dict:
        """Return your currently active tasks and their task_ids.

        Use this to retrieve task_ids if you need to continue a previous task.

        Returns:
            Dict with a list of active tasks for the current user.
        """
        user_id, _ = _user_and_org()
        tasks = telemetry.list_active_tasks(user_id)
        return {"tasks": tasks, "count": len(tasks)}

    @mcp.tool()
    def update_task(
        task_id: str,
        goal: str | None = None,
        context: str | None = None,
        stakes_hint: str | None = None,
        work_type: str | None = None,
        steps: list[str] | None = None,
    ) -> dict:
        """Add or correct information on an active task before proceeding to other tools.

        Use this after declare_intent if the task description is incomplete — for example,
        after the user provides more context about why this work matters or how important it is.
        Only the task owner can update a task, and only while it is still active.

        Args:
            task_id: The task_id returned by declare_intent.
            goal: Updated goal sentence, or omit to leave unchanged.
            context: Why this work matters to the organization, or omit to leave unchanged.
            stakes_hint: Importance level — "high", "medium", or "low" — or omit to leave unchanged.
            work_type: Nature of the work — "process", "exploration", or "decision" — or omit.
            steps: Updated planned steps list, or omit to leave unchanged.

        Returns:
            Updated task dict, or an error dict if task not found, not owned by you, or already complete.
        """
        user_id, _ = _user_and_org()
        result = telemetry.update_task(
            task_id,
            user_id,
            goal=goal,
            decision_context=context,
            stakes_hint=stakes_hint,
            decision_type=work_type,
            steps=steps,
        )
        if result is None:
            return {"error": f"Task '{task_id}' not found, already complete, or not owned by you."}
        return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_task_manager.py -k "test_declare_intent_returns_task_criteria or test_declare_intent_docstring or test_update_task_tool" -v
```

Expected: all 5 new tests PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
pytest remote-gateway/tests/test_task_manager.py -v
```

Expected: all tests pass, including all existing `test_declare_intent_*`, `test_complete_task_*`, `test_clarity_check_*`.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/_core/task_manager.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: reframe declare_intent language, add task_criteria block, add update_task tool"
```

---

## Task 3: Gate message and _GATE_BYPASS in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`
- Test: `remote-gateway/tests/test_task_manager.py`

- [ ] **Step 1: Write failing test for gate message content**

Add to `remote-gateway/tests/test_task_manager.py`:

```python
# --- gate message content ---

def test_gate_task_redirect_contains_operator_instructions(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    sys.modules.pop("mcp_server", None)
    from mcp_server import _make_gate_task_redirect
    result = _make_gate_task_redirect("attio__search_records")
    assert result["gateway_status"] == "no_active_task"
    assert result["blocked_tool"] == "attio__search_records"
    assert result["required_action"] == "declare_intent"
    msg = result["message"]
    assert "AGENT INSTRUCTION" in msg
    assert "declare_intent" in msg
    # must contain the three context prompts
    assert "system" in msg.lower()
    assert "matters" in msg.lower()
    assert "important" in msg.lower()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest remote-gateway/tests/test_task_manager.py -k "test_gate_task_redirect_contains_operator_instructions" -v
```

Expected: FAILED — current message does not contain `"AGENT INSTRUCTION"` or the context prompts.

- [ ] **Step 3: Update mcp_server.py — gate message constant and function**

In `remote-gateway/core/mcp_server.py`, add the constant `_GATE_TASK_MESSAGE` just before `_make_gate_task_redirect` (currently at line ~255), then update the function:

```python
_GATE_TASK_MESSAGE: str = (
    "GATEWAY: No active task for this session. Before using tools, tell us what "
    "you're working on by calling declare_intent.\n\n"
    "AGENT INSTRUCTION: Before calling declare_intent, make sure you have gathered "
    "the following from the user:\n"
    "1. What specifically they need — which system, data, or action\n"
    "2. Why it matters — what question they're trying to answer or outcome they're supporting\n"
    "3. How important this is — high, medium, or low\n\n"
    "Then call declare_intent with a goal, planned steps, and as much of "
    "the above context as the user has provided."
)


def _make_gate_task_redirect(tool_name: str) -> dict:
    return {
        "gateway_status": "no_active_task",
        "message": _GATE_TASK_MESSAGE,
        "blocked_tool": tool_name,
        "required_action": "declare_intent",
    }
```

- [ ] **Step 4: Add `update_task` to `_GATE_BYPASS` and `_TASK_BYPASS_DEFAULTS`**

In `remote-gateway/core/mcp_server.py`, add `"update_task"` to both frozensets:

`_GATE_BYPASS` (currently at line ~194):
```python
_GATE_BYPASS: frozenset[str] = frozenset({
    "setup_start",
    "setup_save_profile",
    "setup_complete",
    "health_check",
    "skill_create",
    "skill_update",
    "skill_list",
    "run_skill",
    "profile_get",
    "profile_update",
    "create_user",
    "get_operator_instructions",
    "list_prompts",
    "get_prompt",
    "declare_intent",
    "complete_task",
    "get_tasks",
    "update_task",
})
```

`_TASK_BYPASS_DEFAULTS` (currently at line ~218):
```python
_TASK_BYPASS_DEFAULTS: frozenset[str] = frozenset({
    "setup_start",
    "setup_save_profile",
    "setup_complete",
    "health_check",
    "skill_create",
    "skill_update",
    "skill_list",
    "run_skill",
    "profile_get",
    "profile_update",
    "create_user",
    "get_operator_instructions",
    "list_prompts",
    "get_prompt",
    "declare_intent",
    "complete_task",
    "get_tasks",
    "update_task",
})
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest remote-gateway/tests/test_task_manager.py -k "test_gate_task_redirect" -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: inject operator context into gate message, add update_task to bypass lists"
```

---

## Task 4: Docs — prompts/init.md and CLAUDE.md

**Files:**
- Modify: `remote-gateway/prompts/init.md`
- Modify: `CLAUDE.md`

No tests needed for doc changes.

- [ ] **Step 1: Update prompts/init.md — add update_task to Available Capabilities**

In `remote-gateway/prompts/init.md`, update the Tasks line:

```markdown
- **Tasks**: `declare_intent`, `complete_task`, `get_tasks`, `update_task`
```

- [ ] **Step 2: Update CLAUDE.md — operator role architecture note**

In `CLAUDE.md`, in the section **"What's next in this repo (Phases 3–4)"**, add a note about future operator roles after the existing bullet list:

```markdown
### Operator Roles (future — post-loom)

Each operator will carry a role: **autonomous agent** (e.g. N8N workflow) or **human operator** (using Claude/Gemini). Human operators will go through a role onboarding flow to capture their responsibilities. The loom will infer and update roles over time from task/tool patterns — analogous to how the loom clusters tasks into decisions. Role routing (directing tasks to the right operator context) will ship once the loom is operational.
```

- [ ] **Step 3: Update CLAUDE.md — tool inventory**

In the tool inventory table under **Built-in tools**, add `update_task`:

```markdown
| `update_task` | Update goal, context, stakes, work type, or steps on an active task |
```

Place it after the `get_tasks` row:
```markdown
| `declare_intent` / `complete_task` / `get_tasks` | Task lifecycle — `declare_intent` opens the **init gate** and captures `decision_context`, `decision_type`, `stakes_hint` for the loom |
| `update_task` | Update goal, context, stakes, work type, or steps on an active task before proceeding to tools |
```

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/prompts/init.md CLAUDE.md
git commit -m "docs: add update_task to init prompt and CLAUDE.md; note operator role architecture"
```

---

## Task 5: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest remote-gateway/tests/ -v
```

Expected: all tests pass with no failures or errors.

- [ ] **Step 2: Run the linter**

```bash
ruff check remote-gateway/tools/_core/task_manager.py remote-gateway/core/telemetry.py remote-gateway/core/mcp_server.py
```

Expected: no lint errors.

- [ ] **Step 3: Smoke test the gate message manually**

```bash
cd remote-gateway && python -c "
import sys; sys.path.insert(0, 'core')
from mcp_server import _make_gate_task_redirect
import json
print(json.dumps(_make_gate_task_redirect('attio__search_records'), indent=2))
"
```

Expected output contains `gateway_status`, `AGENT INSTRUCTION`, and the three numbered context prompts.

- [ ] **Step 4: Smoke test declare_intent returns criteria block**

```bash
cd remote-gateway && python -c "
import sys, contextvars, json, tempfile
from pathlib import Path
sys.path.insert(0, 'core'); sys.path.insert(0, '.')
from telemetry import TelemetryStore
with tempfile.TemporaryDirectory() as tmp:
    store = TelemetryStore(db_path=Path(tmp) / 'smoke.db')
    store.add_api_key('alice', 'sk-test', org_id='acme')
    store.set_initialized('acme')
    uv = contextvars.ContextVar('u', default='alice')
    tools = {}
    class M:
        def tool(self):
            def d(fn): tools[fn.__name__] = fn; return fn
            return d
    from tools._core import task_manager
    task_manager.register(M(), store, uv)
    r = tools['declare_intent']('Search Attio for open Series B companies in Vancouver', ['search attio'])
    print(json.dumps(list(r.keys()), indent=2))
    assert 'task_criteria' in r
    assert 'shadow_operating_instructions' in r
    assert 'update_task' in r['task_criteria']['instruction']
    print('OK')
"
```

Expected: prints key list including `task_criteria`, `shadow_operating_instructions`, `agent_instruction`. Prints `OK`.
