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
from datetime import datetime
from typing import Any

import httpx

from tools.integrations.notes.adapter import NotesAdapterError

# Default httpx timeout is 5s, which is aggressive for GitHub under load.
# Smoke-tested 2026-05-25: the GET-before-DELETE pair hit a transient
# 5s timeout. 30s matches what the migration script already uses.
_HTTP_TIMEOUT_SECONDS = 30

_FOLDER_RE = re.compile(r"^[a-z0-9_-]+$")


def _parse_iso_or_400(value: str | None, param_name: str) -> str | None:
    """Validate an ISO-8601 string. Returns the value unchanged, or None.

    Raises NotesAdapterError(400) on invalid input.
    """
    if value is None:
        return None
    try:
        # Accept both "Z" suffix and explicit offset
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise NotesAdapterError(
            status=400,
            body=f"invalid date for {param_name}: {value!r} ({e})",
            repo=os.environ.get("NOTES_REPO", ""),
            token_fingerprint="",
        ) from e
    return value


def _iso_to_sortkey(value: str) -> float:
    """Convert ISO-8601 to a sortable float. Empty → 0.0 (sorts last via the tuple trick)."""
    if not value:
        return 0.0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


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


def _parse_path(path: str) -> tuple[str, str | None] | None:
    """Parse a tree entry path into (slug, folder).

    Accepts:
      - 'notes/foo.md'         -> ('foo', None)
      - 'notes/marketing/foo.md' -> ('foo', 'marketing')

    Rejects anything else (3+ levels deep, non-.md files, paths not under notes/).
    Returns None for rejects.
    """
    if not path.endswith(".md"):
        return None
    parts = path.split("/")
    if len(parts) < 2 or parts[0] != "notes":
        return None
    if len(parts) == 2:
        # notes/<name>.md
        slug = parts[1][: -len(".md")]
        return (slug, None) if slug else None
    if len(parts) == 3:
        # notes/<folder>/<name>.md
        folder, name = parts[1], parts[2]
        slug = name[: -len(".md")]
        return (slug, folder) if slug and folder else None
    # Deeper nesting not supported.
    return None


def _find_in_tree(tree: list[dict], slug: str) -> tuple[str, str | None, str] | None:
    """Find a blob entry matching the slug. Returns (path, folder, sha) or None.

    Only inspects type='blob' entries. Folder is None for root-level slugs.
    """
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        parsed = _parse_path(entry["path"])
        if parsed is None:
            continue
        s, folder = parsed
        if s == slug:
            return entry["path"], folder, entry["sha"]
    return None


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

    def _path_for(self, slug: str, folder: str | None = None) -> str:
        if folder is None:
            return f"notes/{slug}.md"
        return f"notes/{folder}/{slug}.md"

    def _tree(self) -> list[dict]:
        """Fetch the recursive git tree for the default branch.

        Returns the list of tree entries (each with path, type, sha, size).
        Wraps HTTP errors as NotesAdapterError. No caching in v1.
        """
        url = f"{self._repo_url()}/git/trees/{self._branch}"
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = client.get(
                    url, headers=self._headers(), params={"recursive": "1"}
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e
        return resp.json().get("tree", [])

    def _fetch_default_branch(self) -> str:
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = client.get(self._repo_url(), headers=self._headers())
                resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            raise self._wrap(e) from e
        return resp.json()["default_branch"]

    # ---- NotesAdapter contract ----

    def read(self, slug: str, folder: str | None = None) -> dict | None:
        """Return note dict with slug, content, id, url, path, folder; None if not found.

        With folder=X: hits notes/X/{slug}.md directly. 404 → None (authoritative).
        Without folder: tree lookup finds the unique path, then contents fetch.
        """
        _validate_folder(folder)

        if folder is not None:
            path = self._path_for(slug, folder=folder)
            resolved_folder: str | None = folder
        else:
            found = _find_in_tree(self._tree(), slug)
            if found is None:
                return None
            path, resolved_folder, _ = found

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
        return {
            "slug": slug,
            "content": base64.b64decode(payload["content"]).decode(),
            "id": payload["sha"],
            "url": payload["html_url"],
            "path": payload["path"],
            "folder": resolved_folder,
        }

    def list(  # noqa: A003 — Protocol shape
        self,
        folder: str | None = None,
        prefix: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return notes under notes/, with optional server-side filters.

        - folder=X: only entries under notes/X/
        - prefix=Y: only slugs starting with Y (case-sensitive)
        - since/until: ISO-8601 timestamps; filter by updated_at (commit-derived)
        - limit: cap results (clamped to [1, 100])

        Results sorted by updated_at descending. Orphans (no commit history)
        sort last with empty timestamps.
        """
        _validate_folder(folder)
        since_str = _parse_iso_or_400(since, "since")
        until_str = _parse_iso_or_400(until, "until")

        tree = self._tree()
        # Filter to .md files under notes/ at the supported levels.
        entries: list[tuple[dict, str, str | None]] = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            parsed = _parse_path(entry["path"])
            if parsed is None:
                continue
            slug, slug_folder = parsed
            if folder is not None and slug_folder != folder:
                continue
            if prefix is not None and not slug.startswith(prefix):
                continue
            entries.append((entry, slug, slug_folder))

        # Fetch commits for the post-filter set only.
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                results: list[dict] = []
                for entry, slug, slug_folder in entries:
                    path = entry["path"]
                    commits_resp = client.get(
                        f"{self._repo_url()}/commits",
                        headers=self._headers(),
                        params={"path": path, "per_page": 100},
                    )
                    commits_resp.raise_for_status()
                    commits = commits_resp.json()
                    if commits:
                        updated_at = commits[0]["commit"]["committer"]["date"]
                        created_at = commits[-1]["commit"]["committer"]["date"]
                    else:
                        updated_at = ""
                        created_at = ""

                    # since/until window filter (string compare works for ISO-8601 Z form)
                    if since_str and (not updated_at or updated_at < since_str):
                        continue
                    if until_str and (updated_at and updated_at > until_str):
                        continue

                    results.append({
                        "slug": slug,
                        "id": entry["sha"],
                        "url": f"https://github.com/{self._repo}/blob/{self._branch}/{path}",
                        "path": path,
                        "folder": slug_folder,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    })
        except httpx.HTTPStatusError as e:
            raise self._wrap(e) from e
        except httpx.RequestError as e:
            raise self._wrap(e) from e

        # Sort by updated_at desc; orphans (empty) sort last.
        results.sort(key=lambda n: (n["updated_at"] == "", -_iso_to_sortkey(n["updated_at"])))

        # Limit (clamp to [1, 100])
        if limit is not None:
            effective_limit = max(1, min(100, limit))
            results = results[:effective_limit]

        return results

    def write(self, slug: str, content: str, folder: str | None = None) -> dict:
        """Create or update notes/{folder}/{slug}.md (or notes/{slug}.md if folder is None).

        Looks up the slug across the full tree first. Cross-folder collisions
        raise NotesAdapterError(409). Same-folder writes update via sha.
        """
        _validate_folder(folder)
        existing = _find_in_tree(self._tree(), slug)
        target_folder = folder
        action = "create"
        existing_sha: str | None = None

        if existing is not None:
            existing_path, existing_folder, existing_sha = existing
            if existing_folder != folder:
                raise NotesAdapterError(
                    status=409,
                    body=(
                        f"slug {slug!r} exists in folder "
                        f"{existing_folder!r}; folder param mismatch"
                    ),
                    repo=self._repo,
                    token_fingerprint=self._token_fingerprint(),
                )
            action = "update"
            target_folder = existing_folder

        path = self._path_for(slug, folder=target_folder)
        payload: dict[str, Any] = {
            "message": f"notes: {action} {slug} via gateway",
            "content": base64.b64encode(content.encode()).decode(),
            "branch": self._branch,
        }
        if existing_sha is not None:
            payload["sha"] = existing_sha

        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
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
            "folder": target_folder,
            "status": "updated" if existing_sha else "created",
        }

    def delete(self, slug: str, folder: str | None = None) -> dict:
        """Delete a note. With folder hint: direct path. Without: tree lookup.

        404 (either path) returns {status: not_found, slug}.
        """
        _validate_folder(folder)

        path: str
        sha: str

        if folder is not None:
            # Direct contents GET to fetch sha + verify existence.
            path = self._path_for(slug, folder=folder)
            try:
                with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                    get_resp = client.get(
                        self._contents_url(path), headers=self._headers()
                    )
                if get_resp.status_code == 404:
                    return {"status": "not_found", "slug": slug}
                get_resp.raise_for_status()
                sha = get_resp.json()["sha"]
            except httpx.HTTPStatusError as e:
                raise self._wrap(e) from e
            except httpx.RequestError as e:
                raise self._wrap(e) from e
        else:
            found = _find_in_tree(self._tree(), slug)
            if found is None:
                return {"status": "not_found", "slug": slug}
            path, _resolved_folder, sha = found

        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
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
