"""GitHub Issues adapter for notes.

Stores each note as an open GitHub Issue with the `type:note` label.
The slug is the issue title; the content is the issue body.

Required env vars:
    NOTES_REPO          — owner/repo slug (e.g. "Inform-Growth/inform-notes")
    NOTES_GITHUB_TOKEN  — fine-grained PAT with Issues: read+write on NOTES_REPO
"""
from __future__ import annotations

import os
from typing import Any

import httpx


class GitHubIssuesAdapter:
    """NotesAdapter backed by GitHub Issues."""

    def __init__(self) -> None:
        self._repo = os.environ.get("NOTES_REPO", "")
        if not self._repo:
            raise RuntimeError(
                "NOTES_REPO is not set. "
                "Set it to owner/repo where notes should be filed."
            )
        self._token = os.environ.get("NOTES_GITHUB_TOKEN", "")
        if not self._token:
            raise RuntimeError(
                "NOTES_GITHUB_TOKEN is not set. "
                "Add a fine-grained GitHub PAT with Issues: read+write on NOTES_REPO."
            )

    # ---- helpers ----

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _issues_url(self) -> str:
        return f"https://api.github.com/repos/{self._repo}/issues"

    def _issue_url(self, number: int) -> str:
        return f"https://api.github.com/repos/{self._repo}/issues/{number}"

    def _ensure_label(self, name: str, color: str = "0075ca") -> None:
        url = f"https://api.github.com/repos/{self._repo}/labels"
        with httpx.Client() as client:
            client.post(url, headers=self._headers(), json={"name": name, "color": color})
        # 201 = created, 422 = already exists; both fine. Errors silently ignored.

    def _find(self, slug: str) -> dict | None:
        """Find the first open type:note issue with title matching slug.

        Returns None if no match. Note: only searches the first 100 open
        notes (single API page); see TODO below.
        """
        # TODO(scale): paginate. If a deployment accumulates >100 open notes,
        # `write` will silently create a duplicate because _find won't see
        # the existing one. Acceptable for now (Inform Growth has <20 notes);
        # revisit when approaching that threshold.
        with httpx.Client() as client:
            resp = client.get(
                self._issues_url(),
                headers=self._headers(),
                params={"labels": "type:note", "state": "open", "per_page": 100},
            )
        resp.raise_for_status()
        for issue in resp.json():
            if issue["title"] == slug:
                return issue
        return None

    def _to_result(self, issue: dict, **extras: Any) -> dict:
        return {
            "slug": issue["title"],
            "id": str(issue["number"]),
            "url": issue["html_url"],
            "issue_number": issue["number"],  # adapter-specific passthrough
            **extras,
        }

    # ---- NotesAdapter contract ----

    def write(self, slug: str, content: str) -> dict:
        """Create or update a note. Returns dict with status, slug, id, url, issue_number."""
        self._ensure_label("type:note")
        existing = self._find(slug)
        with httpx.Client() as client:
            if existing:
                resp = client.patch(
                    self._issue_url(existing["number"]),
                    headers=self._headers(),
                    json={"body": content},
                )
                resp.raise_for_status()
                return self._to_result(resp.json(), status="updated")
            else:
                resp = client.post(
                    self._issues_url(),
                    headers=self._headers(),
                    json={"title": slug, "body": content, "labels": ["type:note"]},
                )
                resp.raise_for_status()
                return self._to_result(resp.json(), status="created")

    def read(self, slug: str) -> dict | None:
        """Return note dict with slug, content, id, url, issue_number, or None if not found."""
        issue = self._find(slug)
        if not issue:
            return None
        return self._to_result(issue, content=issue.get("body", ""))

    # list() and delete() in Task 3
    def list(self) -> list[dict]:  # noqa: A003 — Protocol shape
        """List all notes. Implemented in Task 3."""
        raise NotImplementedError("Implemented in Task 3")

    def delete(self, slug: str) -> dict:
        """Delete a note by slug. Implemented in Task 3."""
        raise NotImplementedError("Implemented in Task 3")
