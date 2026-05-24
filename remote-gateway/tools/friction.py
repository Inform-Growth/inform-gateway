"""GitHub Issues-backed friction-reporting tools.

report_issue files structured friction signals on the gateway deployment repo
as GitHub Issues. list_my_issues queries them. These tools are gateway-internal
and intentionally NOT pluggable — friction is always tracked as bugs against
the gateway itself.

For pluggable note storage, see tools/integrations/notes/.

Required env vars:
    ISSUE_DEPLOYMENT_REPO          — owner/repo slug, e.g. "Inform-Growth/inform-gateway"
    ISSUE_DEPLOYMENT_GITHUB_TOKEN  — fine-grained PAT with Issues: read+write
    ISSUE_REPORT_DISABLED          — set to "true" to disable report_issue (kill switch)
"""
from __future__ import annotations

import os
from typing import Any


def _headers() -> dict[str, str]:
    """Return GitHub API headers using ISSUE_DEPLOYMENT_GITHUB_TOKEN."""
    token = os.environ.get("ISSUE_DEPLOYMENT_GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "ISSUE_DEPLOYMENT_GITHUB_TOKEN is not set. "
            "Add a fine-grained GitHub PAT with Issues: read+write on ISSUE_DEPLOYMENT_REPO."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _issues_url() -> str:
    """Return the GitHub Issues API URL for the gateway deployment repo."""
    repo = os.environ.get("ISSUE_DEPLOYMENT_REPO", "")
    if not repo:
        raise RuntimeError(
            "ISSUE_DEPLOYMENT_REPO is not set. "
            "Set it to owner/repo where friction issues should be filed."
        )
    return f"https://api.github.com/repos/{repo}/issues"


def _format_issue_body(
    task_id: str,
    attempted_action: str,
    observed_failure: str,
    agent_hypothesis: str,
    suggested_fix: str | None,
    related_tool: str | None,
) -> str:
    """Render the standard friction issue body markdown."""
    return (
        f"**Task ID:** {task_id}\n"
        f"**Related tool:** {related_tool or 'n/a'}\n\n"
        f"## What the agent was trying to do\n{attempted_action}\n\n"
        f"## What actually happened\n{observed_failure}\n\n"
        f"## Agent hypothesis\n{agent_hypothesis}\n\n"
        f"## Suggested fix\n{suggested_fix or 'none'}\n\n"
        "---\n"
        "*Filed via `report_issue` after user consent. "
        "See task audit trail for full context.*"
    )


_CATEGORY_LABELS: dict[str, str] = {
    "bug": "type:bug",
    "feature": "type:feature",
    "integration": "type:integration",
    "recommendation": "type:recommendation",
    "ux": "type:ux",
    "data-quality": "type:data-quality",
}


def report_issue(
    title: str,
    task_id: str,
    attempted_action: str,
    observed_failure: str,
    agent_hypothesis: str,
    suggested_category: str,
    severity: str = "p3",
    suggested_fix: str | None = None,
    related_tool: str | None = None,
) -> dict:
    """File a GitHub Issue on the deployment repo when the agent encounters friction.

    Agents should tell the user they hit friction and ask for consent before calling
    this tool. Say: "I hit a snag with [tool] — [brief description]. Want me to log
    this as a feedback issue?" Then call this if the user agrees.

    Two triggers: (1) FRICTION — agent would otherwise ask the user for help;
    (2) EFFICIENCY — a subtask required more than 2 tool calls to accomplish
    what should be one, including retries and compensating calls.

    Args:
        title: One-line summary of the friction.
        task_id: The active task_id from declare_intent.
        attempted_action: What the agent was trying to do (1-2 sentences).
        observed_failure: What actually happened, including any error text.
        agent_hypothesis: The agent's best guess at the underlying problem.
        suggested_category: One of bug, feature, integration, recommendation, ux, data-quality.
        severity: p1 (blocked user outcome), p2 (degraded), p3 (inefficient). Default p3.
        suggested_fix: Optional concrete fix suggestion.
        related_tool: Integration name if friction is tool-specific (e.g. "attio", "apollo").

    Returns:
        Dict with issue_url, issue_number, labels on success.
        Dict with error, logged_to_task on GitHub API failure (soft-fail).
        Dict with status="disabled" when kill switch is active.
    """
    import httpx

    if os.environ.get("ISSUE_REPORT_DISABLED", "").lower() == "true":
        return {"status": "disabled", "task_id": task_id}

    labels = [
        _CATEGORY_LABELS.get(suggested_category, "type:bug"),
        f"priority:{severity}",
        "source:report_issue",
    ]
    if related_tool:
        labels.append(f"tool:{related_tool}")

    body = _format_issue_body(
        task_id=task_id,
        attempted_action=attempted_action,
        observed_failure=observed_failure,
        agent_hypothesis=agent_hypothesis,
        suggested_fix=suggested_fix,
        related_tool=related_tool,
    )

    try:
        with httpx.Client() as client:
            resp = client.post(
                _issues_url(),
                headers=_headers(),
                json={"title": title, "body": body, "labels": labels},
            )
        resp.raise_for_status()
        data = resp.json()
        return {
            "issue_number": data["number"],
            "issue_url": data["html_url"],
            "labels": labels,
        }
    except Exception as exc:
        return {"error": str(exc), "logged_to_task": task_id}


def list_my_issues(
    state: str = "open",
    label: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List friction issues on the deployment repo.

    Args:
        state: Filter by issue state — "open", "closed", or "all".
        label: Optional label name to filter by (e.g. "type:bug", "tool:attio").
        limit: Maximum number of issues to return (default 20).

    Returns:
        List of dicts with issue_number, title, labels, state, created_at, html_url.
    """
    import httpx

    params: dict = {"state": state, "per_page": limit}
    if label:
        params["labels"] = label

    with httpx.Client() as client:
        resp = client.get(
            _issues_url(),
            headers=_headers(),
            params=params,
        )
    resp.raise_for_status()
    return [
        {
            "issue_number": issue["number"],
            "title": issue["title"],
            "labels": [lb["name"] for lb in issue.get("labels", [])],
            "state": issue["state"],
            "created_at": issue["created_at"],
            "html_url": issue["html_url"],
        }
        for issue in resp.json()
    ]


def register(mcp: Any) -> None:
    """Register friction tools on the given FastMCP server instance."""
    mcp.tool()(report_issue)
    mcp.tool()(list_my_issues)
