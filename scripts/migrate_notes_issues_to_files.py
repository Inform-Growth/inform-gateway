"""One-shot migration: type:note GitHub Issues → notes/*.md files.

Reads open type:note issues from NOTES_REPO, writes each as
notes/{title}.md (using the issue body as content), comments on the
issue with the new file location, and closes the issue.

Idempotent — re-runs skip issues whose target file already exists with
matching content. Delete this script after Inform Growth's deployment
has run it once.

Required env vars:
    NOTES_REPO          — owner/repo (e.g. "Inform-Growth/inform-notes")
    NOTES_GITHUB_TOKEN  — fine-grained PAT with Contents AND Issues read+write
                          on NOTES_REPO. Drop the Issues scope after migration.
"""
from __future__ import annotations

import base64
import os
import sys

import httpx


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _file_path(slug: str) -> str:
    return f"notes/{slug}.md"


def _list_note_issues(client: httpx.Client, repo: str, token: str) -> list[dict]:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/issues",
        headers=_headers(token),
        params={"labels": "type:note", "state": "open", "per_page": 100},
    )
    resp.raise_for_status()
    return resp.json()


def _get_existing_file(client: httpx.Client, repo: str, token: str, path: str) -> dict | None:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _write_file(
    client: httpx.Client,
    repo: str,
    token: str,
    path: str,
    content: str,
    issue_number: int,
    slug: str,
) -> dict:
    resp = client.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json={
            "message": f"notes: migrate from issue #{issue_number} ({slug})",
            "content": base64.b64encode(content.encode()).decode(),
        },
    )
    resp.raise_for_status()
    return resp.json()


def _close_issue_with_comment(
    client: httpx.Client,
    repo: str,
    token: str,
    issue_number: int,
    new_path: str,
    commit_sha: str,
) -> None:
    client.post(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        headers=_headers(token),
        json={
            "body": (
                f"Migrated to `{new_path}` (commit `{commit_sha}`). "
                f"Closing — notes now live in the file-based plane."
            )
        },
    ).raise_for_status()
    client.patch(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers=_headers(token),
        json={"state": "closed"},
    ).raise_for_status()


def run() -> dict:
    """Migrate all open type:note issues to notes/*.md files. Returns a summary."""
    repo = os.environ.get("NOTES_REPO", "")
    token = os.environ.get("NOTES_GITHUB_TOKEN", "")
    if not repo or not token:
        raise RuntimeError("NOTES_REPO and NOTES_GITHUB_TOKEN must be set.")

    summary = {"migrated": 0, "skipped": 0, "warnings": 0, "errors": 0}
    with httpx.Client(timeout=30) as client:
        issues = _list_note_issues(client, repo, token)
        for issue in issues:
            slug = issue["title"]
            body = issue.get("body") or ""
            path = _file_path(slug)
            try:
                existing = _get_existing_file(client, repo, token, path)
                if existing is not None:
                    existing_content = base64.b64decode(existing["content"]).decode()
                    if existing_content == body:
                        print(f"skip (already migrated): #{issue['number']} → {path}")
                    else:
                        print(
                            f"WARNING skip (file diverges from issue): "
                            f"#{issue['number']} → {path}"
                        )
                        summary["warnings"] += 1
                    summary["skipped"] += 1
                    continue

                created = _write_file(client, repo, token, path, body, issue["number"], slug)
                commit_sha = created["commit"]["sha"]
                _close_issue_with_comment(
                    client, repo, token, issue["number"], path, commit_sha
                )
                print(f"migrated: #{issue['number']} → {path} ({commit_sha[:7]})")
                summary["migrated"] += 1
            except Exception as e:  # noqa: BLE001 — surface and continue
                print(f"ERROR migrating #{issue['number']} ({slug}): {e}", file=sys.stderr)
                summary["errors"] += 1
    return summary


if __name__ == "__main__":
    result = run()
    print(f"\nSummary: {result}")
    sys.exit(1 if result["errors"] else 0)
