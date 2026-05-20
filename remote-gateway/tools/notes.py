"""
GitHub Issues-backed notes and friction reporting tools.

All notes and issues are stored as GitHub Issues in the deployment repository.
Notes use the label "type:note"; friction issues use structured labels.

Required env vars:
    ISSUE_DEPLOYMENT_REPO          — owner/repo slug, e.g. "acme/gateway"
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
    """Return the GitHub Issues API URL for the deployment repo."""
    repo = os.environ.get("ISSUE_DEPLOYMENT_REPO", "")
    if not repo:
        raise RuntimeError(
            "ISSUE_DEPLOYMENT_REPO is not set. "
            "Set it to owner/repo where GitHub Issues should be filed."
        )
    return f"https://api.github.com/repos/{repo}/issues"


def _issue_url(number: int) -> str:
    """Return the GitHub Issues API URL for a specific issue number."""
    repo = os.environ.get("ISSUE_DEPLOYMENT_REPO", "")
    if not repo:
        raise RuntimeError(
            "ISSUE_DEPLOYMENT_REPO is not set. "
            "Set it to owner/repo where GitHub Issues should be filed."
        )
    return f"https://api.github.com/repos/{repo}/issues/{number}"


def _ensure_label(name: str, color: str = "0075ca") -> None:
    """Create a label in the deployment repo if it doesn't already exist."""
    import httpx

    repo = os.environ.get("ISSUE_DEPLOYMENT_REPO", "")
    url = f"https://api.github.com/repos/{repo}/labels"
    with httpx.Client() as client:
        client.post(url, headers=_headers(), json={"name": name, "color": color})
    # 201 = created, 422 = already exists — both are fine; errors are silently ignored


def _find_note(slug: str) -> dict | None:
    """Find the first open issue with type:note label matching the title."""
    import httpx

    with httpx.Client() as client:
        resp = client.get(
            _issues_url(),
            headers=_headers(),
            params={"labels": "type:note", "state": "open", "per_page": 100},
        )
    resp.raise_for_status()
    for issue in resp.json():
        if issue["title"] == slug:
            return issue
    return None


def list_notes() -> dict:
    """List all notes stored in the deployment repository.

    Notes are GitHub Issues with the label "type:note". They persist
    across redeployments and are shared across all agents on this gateway.

    Returns:
        Dict with 'notes' list and 'count'.
    """
    import httpx

    with httpx.Client() as client:
        resp = client.get(
            _issues_url(),
            headers=_headers(),
            params={"labels": "type:note", "state": "open", "per_page": 100},
        )
    resp.raise_for_status()
    notes = [
        {
            "slug": issue["title"],
            "issue_number": issue["number"],
            "created_at": issue["created_at"],
            "updated_at": issue["updated_at"],
            "html_url": issue["html_url"],
        }
        for issue in resp.json()
    ]
    return {"notes": notes, "count": len(notes)}


def read_note(slug: str) -> dict:
    """Read a note by its slug (title).

    Args:
        slug: The note title used when the note was written.

    Returns:
        Dict with 'slug', 'content', 'issue_number', 'html_url' on success.
        Dict with status='not_found' if no open note matches.
    """
    issue = _find_note(slug)
    if not issue:
        return {"status": "not_found", "slug": slug}
    return {
        "slug": slug,
        "content": issue.get("body", ""),
        "issue_number": issue["number"],
        "html_url": issue["html_url"],
    }


def write_note(slug: str, content: str) -> dict:
    """Create or update a note in the deployment repository.

    Notes are stored as GitHub Issues with the label "type:note".
    If a note with this slug already exists (open issue with same title),
    its body is updated in place. Otherwise a new issue is created.

    Args:
        slug: Short identifier for the note (used as the issue title).
        content: Full markdown content of the note.

    Returns:
        Dict with 'status' (created/updated), 'issue_number', 'html_url'.
    """
    import httpx

    _ensure_label("type:note")
    existing = _find_note(slug)
    with httpx.Client() as client:
        if existing:
            resp = client.patch(
                _issue_url(existing["number"]),
                headers=_headers(),
                json={"body": content},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": "updated",
                "slug": slug,
                "issue_number": data["number"],
                "html_url": data["html_url"],
            }
        else:
            resp = client.post(
                _issues_url(),
                headers=_headers(),
                json={"title": slug, "body": content, "labels": ["type:note"]},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": "created",
                "slug": slug,
                "issue_number": data["number"],
                "html_url": data["html_url"],
            }


def delete_note(slug: str) -> dict:
    """Delete (close) a note by its slug.

    Closes the GitHub Issue that backs this note. The issue remains
    visible in the closed state on GitHub but is removed from active notes.

    Args:
        slug: The note title used when the note was written.

    Returns:
        Dict with status='deleted' and 'issue_number' on success.
        Dict with status='not_found' if no open note matches.
    """
    import httpx

    issue = _find_note(slug)
    if not issue:
        return {"status": "not_found", "slug": slug}

    with httpx.Client() as client:
        resp = client.patch(
            _issue_url(issue["number"]),
            headers=_headers(),
            json={"state": "closed"},
        )
    resp.raise_for_status()
    return {
        "status": "deleted",
        "slug": slug,
        "issue_number": issue["number"],
    }


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
    """Register all notes tools on the given FastMCP server instance."""
    mcp.tool()(list_notes)
    mcp.tool()(read_note)
    mcp.tool()(write_note)
    mcp.tool()(delete_note)
    mcp.tool()(report_issue)
    mcp.tool()(list_my_issues)
