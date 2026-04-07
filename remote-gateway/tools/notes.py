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

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "deleted",
        "filename": base_name,
        "commit_url": commit.get("html_url", ""),
    }


def write_issue(slug: str, content: str, commit_message: str = "") -> dict:
    """Create or update an issue note in the gateway's issues folder.

    Use this during gateway health checks to record problems found: authentication
    failures, missing field documentation, schema drift, or tool errors. Issues
    persist in {NOTES_PATH}/issues/ across redeployments.

    Args:
        slug: Short kebab-case identifier for the issue, without .md extension
            (e.g., "attio-auth-failure-2026-04-07", "exa-missing-docs").
        content: Full markdown content describing the issue, including context
            and recommended action.
        commit_message: Optional git commit message. Defaults to
            "chore: record issue <slug>".

    Returns:
        Dict confirming the commit with 'sha', 'slug', 'path', and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _issue_path(slug)
    url = _github_file_url(path)
    base_name = os.path.basename(path)
    message = commit_message or f"chore: record issue {base_name}"

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
    """List all open issue notes in the gateway's issues folder.

    Issues are written by the gateway-health-check skill when problems are
    found (auth failures, missing documentation, schema drift, tool errors).
    Use this to audit the current open issue backlog.

    Returns:
        Dict with 'issues' list (each entry has name, path, sha) and 'count'.
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
    mcp.tool()(write_issue)
    mcp.tool()(list_issues)
