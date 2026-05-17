"""
GitHub-backed markdown notes tools.

Reads and writes .md files in a GitHub repository, providing a
persistent notes store that survives gateway redeployments.

Required env vars:
    GITHUB_TOKEN  — fine-grained PAT with Contents read+write on the repo
    GITHUB_REPO   — owner/repo slug, e.g. "acme/inform-notes"
    GITHUB_BRANCH — branch to read/write (default: "main")
    NOTES_PATH    — folder inside GITHUB_REPO (default: "notes")
"""
from __future__ import annotations

import base64
import os
from typing import Any


def _github_headers() -> dict[str, str]:
    """Return GitHub API request headers using GITHUB_TOKEN from env."""
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_file_url(path: str) -> str:
    """Return the GitHub Contents API URL for a file path."""
    repo = os.environ.get("GITHUB_REPO", "")
    return f"https://api.github.com/repos/{repo}/contents/{path}"


def _notes_path(filename: str) -> str:
    """Resolve a filename to its full repo path under the notes folder."""
    notes_base = os.environ.get("NOTES_PATH", "notes")
    safe = os.path.basename(filename)
    if not safe.endswith(".md"):
        safe = safe + ".md"
    return f"{notes_base}/{safe}"


def _issue_path(slug: str) -> str:
    """Resolve a slug to its full repo path under the issues subfolder.

    Unlike _notes_path, this preserves the issues/ directory level.
    """
    notes_base = os.environ.get("NOTES_PATH", "notes")
    safe = os.path.basename(slug)
    if not safe.endswith(".md"):
        safe = safe + ".md"
    return f"{notes_base}/issues/{safe}"


def list_notes() -> dict:
    """List all markdown notes stored in the gateway's notes folder.

    Notes are stored in the GitHub repository and persist across redeployments.

    Returns:
        Dict with 'notes' list of filenames and their last-commit message.
    """
    import httpx

    notes_base = os.environ.get("NOTES_PATH", "notes")
    repo = os.environ.get("GITHUB_REPO", "")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    url = _github_file_url(notes_base)

    with httpx.Client() as client:
        resp = client.get(url, headers=_github_headers(), params={"ref": branch})

    if resp.status_code == 404:
        return {"notes": [], "message": "No notes found — notes folder does not exist yet."}

    resp.raise_for_status()
    entries = resp.json()
    notes = [
        {"name": e["name"], "path": e["path"], "sha": e["sha"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".md")
    ]
    return {"notes": notes, "count": len(notes), "repo": repo, "branch": branch}


def read_note(filename: str) -> dict:
    """Read a markdown note from the gateway's notes folder.

    Args:
        filename: Note filename, with or without .md extension (e.g. "onboarding").

    Returns:
        Dict with 'filename', 'content' (decoded markdown text), and 'sha'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)

    with httpx.Client() as client:
        resp = client.get(url, headers=_github_headers(), params={"ref": branch})

    if resp.status_code == 404:
        return {"status": "not_found", "filename": os.path.basename(path)}

    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return {
        "filename": data["name"],
        "path": data["path"],
        "content": content,
        "sha": data["sha"],
    }


def write_note(filename: str, content: str, commit_message: str = "") -> dict:
    """Create or update a markdown note in the gateway's notes folder.

    The note is committed directly to the repository and persists across redeployments.
    To update an existing note you do not need the SHA — it is fetched automatically.

    Args:
        filename: Note filename, with or without .md extension (e.g. "onboarding").
        content: Full markdown content to write.
        commit_message: Optional git commit message. Defaults to "chore: update <filename>".

    Returns:
        Dict confirming the commit with 'sha', 'filename', and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)
    base_name = os.path.basename(path)
    message = commit_message or f"chore: update {base_name}"

    sha: str | None = None
    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 200:
            sha = check.json()["sha"]

        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = client.put(url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "ok",
        "filename": base_name,
        "path": path,
        "sha": commit.get("sha", ""),
        "commit_url": commit.get("html_url", ""),
        "action": "updated" if sha else "created",
    }


def delete_note(filename: str, commit_message: str = "") -> dict:
    """Delete a markdown note from the gateway's notes folder.

    Args:
        filename: Note filename, with or without .md extension.
        commit_message: Optional git commit message. Defaults to "chore: delete <filename>".

    Returns:
        Dict confirming deletion with 'filename' and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)
    base_name = os.path.basename(path)

    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 404:
            return {"status": "not_found", "filename": base_name}
        check.raise_for_status()
        sha = check.json()["sha"]

        body = {
            "message": commit_message or f"chore: delete {base_name}",
            "sha": sha,
            "branch": branch,
        }
        resp = client.request("DELETE", url, headers=_github_headers(), json=body)

        if resp.status_code in (409, 422):
            # SHA is stale — a concurrent write changed the file between our GET and DELETE.
            # Re-fetch the current SHA and retry once.
            recheck = client.get(url, headers=_github_headers(), params={"ref": branch})
            if recheck.status_code == 404:
                return {"status": "not_found", "filename": base_name}
            recheck.raise_for_status()
            body["sha"] = recheck.json()["sha"]
            resp = client.request("DELETE", url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "deleted",
        "filename": base_name,
        "commit_url": commit.get("html_url", ""),
    }


def _deployment_repo_headers() -> dict[str, str]:
    """Return GitHub API headers using INFORM_GATEWAY_GITHUB_TOKEN."""
    token = os.environ.get("INFORM_GATEWAY_GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _deployment_issue_url() -> str:
    """Return the GitHub Issues API URL for the deployment repo."""
    repo = os.environ.get("INFORM_GATEWAY_DEPLOYMENT_REPO", "")
    return f"https://api.github.com/repos/{repo}/issues"


def _format_issue_body(
    task_id: str,
    attempted_action: str,
    observed_failure: str,
    agent_hypothesis: str,
    suggested_fix: str | None,
    related_tool: str | None,
) -> str:
    """Render the standard issue body markdown."""
    return (
        f"**Task ID:** {task_id}\n"
        f"**Reported by:** agent (shadow-operating)\n"
        f"**Related tool:** {related_tool or 'n/a'}\n\n"
        f"## What the agent was trying to do\n{attempted_action}\n\n"
        f"## What actually happened\n{observed_failure}\n\n"
        f"## Agent hypothesis\n{agent_hypothesis}\n\n"
        f"## Suggested fix\n{suggested_fix or 'none'}\n\n"
        "---\n"
        "*Filed automatically via `report_issue` during task execution. "
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
    """File a GitHub Issue on the deployment repo as part of shadow operating.

    Invoked by agents during task execution when they encounter friction.
    Not user-facing — the user never sees this call in conversation.

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

    if os.environ.get("INFORM_GATEWAY_REPORT_ISSUE_DISABLED", "").lower() == "true":
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
                _deployment_issue_url(),
                headers=_deployment_repo_headers(),
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


def write_issue(slug: str, content: str, commit_message: str = "") -> dict:
    """DEPRECATED. Use report_issue instead.

    write_issue wrote markdown files to the notes repo under notes/issues/.
    All issue creation now goes to real GitHub Issues on the deployment repo
    via report_issue. This function is unregistered and kept temporarily
    for reference until existing notes/issues/ files are archived.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _issue_path(slug)
    url = _github_file_url(path)
    message = commit_message or f"chore: record issue {slug}"

    sha: str | None = None
    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 200:
            sha = check.json()["sha"]

        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = client.put(url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "ok",
        "slug": slug,
        "path": path,
        "sha": commit.get("sha", ""),
        "commit_url": commit.get("html_url", ""),
        "action": "updated" if sha else "created",
    }


def list_issues() -> dict:
    """DEPRECATED. Use list_my_issues instead.

    list_issues listed markdown files from the notes repo issues folder.
    All issue listing now goes through list_my_issues, which reads real
    GitHub Issues from the deployment repo. This function is unregistered.
    """
    import httpx

    notes_base = os.environ.get("NOTES_PATH", "notes")
    repo = os.environ.get("GITHUB_REPO", "")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    url = _github_file_url(f"{notes_base}/issues")

    with httpx.Client() as client:
        resp = client.get(url, headers=_github_headers(), params={"ref": branch})

    if resp.status_code == 404:
        return {"issues": [], "count": 0, "message": "No issues folder yet — none recorded."}

    resp.raise_for_status()
    entries = resp.json()
    issues = [
        {"name": e["name"], "path": e["path"], "sha": e["sha"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".md")
    ]
    return {"issues": issues, "count": len(issues), "repo": repo, "branch": branch}


def register(mcp: Any) -> None:
    """Register all notes tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(list_notes)
    mcp.tool()(read_note)
    mcp.tool()(write_note)
    mcp.tool()(delete_note)
    # write_issue and list_issues are intentionally NOT registered here.
    # They are deprecated — use report_issue and list_my_issues instead.
