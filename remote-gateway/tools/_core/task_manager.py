"""
Gateway task management tools.

Agents must declare intent before using gateway tools. Each declared intent
creates a task with a unique task_id. Tool calls are attributed to the active
task in telemetry, enabling per-task audit trails.

Bypasses the init gate — safe to call after initialization.
"""
from __future__ import annotations

import contextvars
from typing import Any


def register(mcp: Any, telemetry: Any, current_user_var: contextvars.ContextVar) -> None:
    """Register declare_intent, complete_task, and get_tasks on mcp.

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
    def declare_intent(goal: str, steps: list[str]) -> dict:
        """Declare what you are about to accomplish. Required before using any gateway tool.

        Creates a task and returns a task_id. Pass this task_id to subsequent tool
        calls to attribute them to this task. Multiple tasks can be active at once.

        Args:
            goal: One sentence describing what you are trying to accomplish.
            steps: Ordered list of planned tool calls or actions (e.g. ["search CRM", "enrich with Apollo"]).

        Returns:
            Dict with task_id, goal, steps, status, and agent_instruction.
        """
        user_id, org_id = _user_and_org()
        task = telemetry.create_task(user_id, org_id, goal, steps)
        if not task.get("task_id"):
            return {"error": "Task creation failed — telemetry may be unavailable."}
        task["agent_instruction"] = (
            f"Task created. Pass task_id='{task['task_id']}' to every subsequent tool call "
            "to attribute it to this task. Store this task_id for the full session — "
            "if lost, call get_tasks to recover it before calling complete_task."
        )
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
