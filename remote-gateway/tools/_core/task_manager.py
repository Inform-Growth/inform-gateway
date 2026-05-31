"""
Gateway task management tools.

Agents must tell us what they're working on before using gateway tools. Each
declared intent creates a task with a unique task_id. Tool calls are attributed
to the active task in telemetry, enabling per-task audit trails.

Bypasses the init gate — safe to call after initialization.
"""
from __future__ import annotations

import contextvars
from collections.abc import Callable
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

_SKILL_SUGGESTION_INSTRUCTION: str = (
    "Review `suggested_skills` — each entry has a `name`, `description`, and `score`. "
    "If any are relevant to this task, tell the user which skills are available "
    "(name + one-line description) and ask if they'd like to run one before you proceed. "
    "Do not run a skill without the user's confirmation."
)

_SHADOW_OPERATING_INSTRUCTIONS: str = (
    "As you work, notice when something takes longer than it should or breaks unexpectedly. "
    "When either trigger applies, tell the user briefly and ask if they'd like to log it:\n\n"
    "1. FRICTION: You reach a point where the next natural step would be asking the user "
    "for help, clarification, or a workaround. Say: 'I hit a snag with [tool/step] — "
    "[one sentence]. Want me to log this as a feedback issue?' File if they agree.\n\n"
    "2. EFFICIENCY: A single subtask required more than 2 tool calls to accomplish what "
    "should be one — including retries after failures, compensating calls for "
    "empty/wrong-shaped results, and multi-step workarounds. Say: 'That took more steps "
    "than it should — [brief description]. Want me to file a friction report?' "
    "File once per affected subtask if they agree.\n\n"
    "When filing: pass the active task_id, describe what you attempted and what happened, "
    "set related_tool when the friction is tool-specific, and use severity p1 only if the "
    "issue blocked the user-visible outcome.\n\n"
    "SUBAGENTS: If you were dispatched as a subagent by another agent, do NOT call "
    "declare_intent. Use the task_id passed to you by the caller and include it on every "
    "tool call. Only the top-level agent owns the task lifecycle."
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


def register(
    mcp: Any,
    telemetry: Any,
    current_user_var: contextvars.ContextVar,
    embed_fn: Callable[[str], list[float] | None] | None = None,
) -> None:
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

    def _suggest_skills(org_id: str, goal: str) -> list[dict]:
        """Return top-k skill suggestions for goal. Always returns a list; never raises."""
        if embed_fn is None:
            return []
        try:
            import embeddings as _emb  # noqa: PLC0415
            vec = embed_fn(goal)
            if vec is None:
                return []
            matches = telemetry.search_skills_by_embedding(org_id, vec)
            results = []
            for m in matches:
                skill_text = _emb.skill_embed_source(m["name"], m["description"])
                score = _emb.hybrid_score(float(m["cosine"]), goal, skill_text)
                if score >= _emb.SCORE_FLOOR:
                    results.append({"name": m["name"], "description": m["description"], "score": round(score, 3)})
            return results
        except Exception:
            return []  # fail open — never let suggestions block task creation

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
            "if lost, call get_tasks to recover it before calling complete_task. "
            "You MUST call complete_task when the work is done — do not leave tasks open. "
            "If you spawn subagents, pass the task_id to them; subagents must NOT call "
            "declare_intent."
        )
        task["task_criteria"] = {
            "checklist": _TASK_CRITERIA_CHECKLIST,
            "instruction": _TASK_CRITERIA_INSTRUCTION,
        }
        task["shadow_operating_instructions"] = _SHADOW_OPERATING_INSTRUCTIONS
        suggested = _suggest_skills(org_id, goal)
        task["suggested_skills"] = suggested
        if suggested:
            task["skill_suggestion_instruction"] = _SKILL_SUGGESTION_INSTRUCTION

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
            Updated task dict, or an error dict if task not found, not owned by you,
            or already complete.
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
