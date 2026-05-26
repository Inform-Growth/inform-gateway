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
import re
from typing import Any

import httpx

from tools.integrations.notes.adapter import NotesAdapterError

# Default httpx timeout is 5s, which is aggressive for GitHub under load.
# Smoke-tested 2026-05-25: the GET-before-DELETE pair hit a transient
# 5s timeout. 30s matches what the migration script already uses.
_HTTP_TIMEOUT_SECONDS = 30

_FOLDER_RE = re.compile(r"^[a-z0-9_-]+$")


def _validate_folder(folder: str | None) -> None:
    """Raise NotesAdapterError(400) if folder is set and doesn't match ^[a-z0-9_-]+$.

    None is always valid (means "root").
    """
    if folder is None:
        return
    if not _FOLDER_RE.match(folder):
        raise NotesAdapterError(
            status=400,
            body=f"invalid folder name: {folder!r}",
            repo=os.environ.get("NOTES_REPO", ""),
            token_fingerprint="",
        )


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
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
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
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = client.get(self._contents_url(path), headers=self._headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
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
        """Return all top-level `notes/*.md` files with commit-derived timestamps.

        For each file, issues a per-file `GET /commits?path=notes/{slug}.md`
        to derive `created_at` (oldest commit) and `updated_at` (newest).
        Files with no commit history (e.g. orphaned via UI) get empty
        timestamps rather than failing. Listing 30 notes = ~31 API calls.
        """
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                contents = client.get(
                    self._contents_url("notes"), headers=self._headers()
                )
                if contents.status_code == 404:
                    return []
                contents.raise_for_status()

                files = [
                    entry
                    for entry in contents.json()
                    if entry["type"] == "file" and entry["name"].endswith(".md")
                ]

                result: list[dict] = []
                for entry in files:
                    path = entry["path"]
                    commits_resp = client.get(
                        f"{self._repo_url()}/commits",
                        headers=self._headers(),
                        params={"path": path, "per_page": 100},
                    )
                    commits_resp.raise_for_status()
                    commits = commits_resp.json()
                    if commits:
                        # GitHub returns newest-first.
                        updated_at = commits[0]["commit"]["committer"]["date"]
                        created_at = commits[-1]["commit"]["committer"]["date"]
                    else:
                        updated_at = ""
                        created_at = ""
                    slug = entry["name"][: -len(".md")]
                    result.append(
                        {
                            "slug": slug,
                            "id": entry["sha"],
                            "url": entry["html_url"],
                            "path": path,
                            "created_at": created_at,
                            "updated_at": updated_at,
                        }
                    )
                return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e

    def write(self, slug: str, content: str) -> dict:
        """Create or update notes/{slug}.md on the default branch."""
        path = self._path_for(slug)
        existing_sha: str | None = None
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                get_resp = client.get(self._contents_url(path), headers=self._headers())
                if get_resp.status_code != 404:
                    get_resp.raise_for_status()
                    existing_sha = get_resp.json()["sha"]

                action = "update" if existing_sha else "create"
                payload: dict[str, Any] = {
                    "message": f"notes: {action} {slug} via gateway",
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": self._branch,
                }
                if existing_sha:
                    payload["sha"] = existing_sha

                put_resp = client.put(
                    self._contents_url(path),
                    headers=self._headers(),
                    json=payload,
                )
                put_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e

        body = put_resp.json()
        return {
            "slug": slug,
            "id": body["content"]["sha"],
            "url": body["content"]["html_url"],
            "path": body["content"]["path"],
            "status": "updated" if existing_sha else "created",
        }

    def delete(self, slug: str) -> dict:
        """Delete notes/{slug}.md on the default branch."""
        path = self._path_for(slug)
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                get_resp = client.get(self._contents_url(path), headers=self._headers())
                if get_resp.status_code == 404:
                    return {"status": "not_found", "slug": slug}
                get_resp.raise_for_status()
                sha = get_resp.json()["sha"]

                del_resp = client.request(
                    "DELETE",
                    self._contents_url(path),
                    headers=self._headers(),
                    json={
                        "message": f"notes: delete {slug} via gateway",
                        "sha": sha,
                        "branch": self._branch,
                    },
                )
                del_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e

        return {"status": "deleted", "slug": slug, "path": path}
