"""GitHub Files adapter for notes.

Stores each note as a markdown file at `notes/{slug}.md` in NOTES_REPO,
committed directly to the repo's default branch. Reads, writes, and
deletes all go through the GitHub contents API.

Required env vars:
    NOTES_REPO          — owner/repo slug (e.g. "Inform-Growth/inform-notes")
    NOTES_GITHUB_TOKEN  — fine-grained PAT with Contents: read+write on NOTES_REPO
"""
from __future__ import annotations

import base64
import os

import httpx
from tools.integrations.notes.adapter import NotesAdapterError


class GitHubFilesAdapter:
    """NotesAdapter backed by markdown files under `notes/` in a GitHub repo."""

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
                "Add a fine-grained GitHub PAT with Contents: read+write on NOTES_REPO."
            )
        self._branch = self._fetch_default_branch()

    # ---- helpers ----

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _token_fingerprint(self) -> str:
        return (self._token[:4] + "…") if self._token else "…"

    def _wrap(self, exc: Exception) -> NotesAdapterError:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            body = exc.response.text[:2048]
        else:
            status = None
            body = str(exc)[:2048]
        return NotesAdapterError(
            status=status,
            body=body,
            repo=self._repo,
            token_fingerprint=self._token_fingerprint(),
        )

    def _repo_url(self) -> str:
        return f"https://api.github.com/repos/{self._repo}"

    def _contents_url(self, path: str) -> str:
        return f"{self._repo_url()}/contents/{path}"

    def _path_for(self, slug: str) -> str:
        return f"notes/{slug}.md"

    def _fetch_default_branch(self) -> str:
        try:
            with httpx.Client() as client:
                resp = client.get(self._repo_url(), headers=self._headers())
                resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            raise self._wrap(e) from e
        return resp.json()["default_branch"]

    # ---- NotesAdapter contract ----

    def read(self, slug: str) -> dict | None:
        """Return note dict with slug, content, id (sha), url, path; None if not found."""
        path = self._path_for(slug)
        try:
            with httpx.Client() as client:
                resp = client.get(self._contents_url(path), headers=self._headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e

        payload = resp.json()
        content = base64.b64decode(payload["content"]).decode()
        return {
            "slug": slug,
            "content": content,
            "id": payload["sha"],
            "url": payload["html_url"],
            "path": payload["path"],
        }

    def list(self) -> list[dict]:  # noqa: A003 — Protocol shape
        """Return all top-level `notes/*.md` files with created_at/updated_at."""
        try:
            with httpx.Client() as client:
                contents = client.get(
                    self._contents_url("notes"), headers=self._headers()
                )
                if contents.status_code == 404:
                    return []
                contents.raise_for_status()

                commits = client.get(
                    f"{self._repo_url()}/commits",
                    headers=self._headers(),
                    params={"path": "notes", "per_page": 100},
                )
                commits.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e

        files = [
            entry
            for entry in contents.json()
            if entry["type"] == "file" and entry["name"].endswith(".md")
        ]
        # Build {path: (oldest_date, newest_date)} from commits.
        # GitHub returns commits newest-first.
        dates: dict[str, tuple[str, str]] = {}
        for commit in commits.json():
            committed = commit["commit"]["committer"]["date"]
            for f in commit.get("files") or []:
                path = f["filename"]
                if path in dates:
                    oldest, _ = dates[path]
                    # newest_date stays the same (first-seen because newest-first)
                    dates[path] = (committed, dates[path][1])
                else:
                    dates[path] = (committed, committed)

        result: list[dict] = []
        for entry in files:
            path = entry["path"]
            created, updated = dates.get(path, ("", ""))
            slug = entry["name"][: -len(".md")]
            result.append(
                {
                    "slug": slug,
                    "id": entry["sha"],
                    "url": entry["html_url"],
                    "path": path,
                    "created_at": created,
                    "updated_at": updated,
                }
            )
        return result
