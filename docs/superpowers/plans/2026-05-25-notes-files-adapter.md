# Notes Files Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the notes adapter so it reads/writes `notes/*.md` files in `NOTES_REPO` (the durable plane) instead of `type:note` GitHub Issues (the wrong plane), and surface adapter failures loudly via a typed exception. Migrate the 4 existing `type:note` issues on `Inform-Growth/inform-notes` to files in a one-shot script.

**Architecture:** New `GitHubFilesAdapter` implementing the unchanged `NotesAdapter` Protocol — backed by the GitHub contents API, top-level `notes/*.md` only, slug↔filename 1:1, direct commit to default branch with `sha` concurrency check. `GitHubIssuesAdapter` is deleted. Every adapter HTTP call wraps `httpx.HTTPStatusError` and `httpx.RequestError` into a new `NotesAdapterError(RuntimeError)` so silent empty lists never reach the agent. One-shot migration script reads `type:note` issues via raw API and writes each to `notes/{slug}.md`.

**Tech Stack:** Python 3.11+, httpx, FastMCP, pytest with `unittest.mock`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-25-notes-files-adapter-design.md`

**Closes:** #34, #35

---

## File Structure

**Create:**
- `remote-gateway/tools/integrations/notes/adapters/github_files.py` — new adapter
- `remote-gateway/tests/test_notes_files_adapter.py` — adapter unit tests
- `scripts/migrate_notes_issues_to_files.py` — one-shot migration
- `remote-gateway/tests/test_migrate_notes_issues_to_files.py` — migration smoke test

**Modify:**
- `remote-gateway/tools/integrations/notes/adapter.py` — add `NotesAdapterError`, swap registry default to `github-files`, drop `github-issues` entry
- `remote-gateway/tools/integrations/notes/__init__.py` — docstring update
- `remote-gateway/tests/test_notes_adapter.py` — update factory tests for new default
- `remote-gateway/CLAUDE.md` — env-var rows for `NOTES_ADAPTER`/`NOTES_REPO`/`NOTES_GITHUB_TOKEN`, plus the notes/issue backlog blurb
- `CLAUDE.md` — root file's notes-adapter mentions (Persistence section + Repository Structure + Tool Inventory rows)

**Delete:**
- `remote-gateway/tools/integrations/notes/adapters/github_issues.py`
- `remote-gateway/tests/test_github_issues_adapter.py`

Each adapter method is self-contained (single httpx call sequence, no shared state besides `self._repo`, `self._token`, `self._branch`). Tests stay flat — one file per adapter — matching the existing test layout.

---

## Conventions

- Mock httpx using the same `_mock_resp` / `_mock_client_ctx` pattern as `test_github_issues_adapter.py`. Copy these helpers into the new test file (DRY across adapters is fine to break — they're test fixtures).
- All commits use Conventional Commit prefixes already in use in this repo (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`).
- Run tests from repo root: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs`. Full suite: `pytest`.
- Run lint: `ruff check .`. Fix any new violations before committing.

---

## Task 1: Add `NotesAdapterError` exception

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapter.py`
- Test: `remote-gateway/tests/test_notes_adapter.py`

- [ ] **Step 1: Write the failing test**

Append to `remote-gateway/tests/test_notes_adapter.py`:

```python
def test_notes_adapter_error_carries_diagnostics():
    from tools.integrations.notes.adapter import NotesAdapterError

    err = NotesAdapterError(
        status=403,
        body="forbidden",
        repo="org/test-notes",
        token_fingerprint="ghp_…",
    )

    assert err.status == 403
    assert err.body == "forbidden"
    assert err.repo == "org/test-notes"
    assert err.token_fingerprint == "ghp_…"
    assert "403" in str(err)
    assert "org/test-notes" in str(err)
    assert "ghp_…" in str(err)
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest remote-gateway/tests/test_notes_adapter.py::test_notes_adapter_error_carries_diagnostics -xvs`
Expected: FAIL with `ImportError: cannot import name 'NotesAdapterError'`.

- [ ] **Step 3: Add the exception class**

Edit `remote-gateway/tools/integrations/notes/adapter.py`. Add this class above the `NotesAdapter` Protocol:

```python
class NotesAdapterError(RuntimeError):
    """Adapter-level failure with enough context to diagnose.

    Raised by adapters when an upstream call fails. Carries the HTTP
    status (or None for network errors), a truncated response body,
    the repo we were talking to, and a fingerprint of the token in
    use so silent empty results are no longer possible.
    """

    def __init__(
        self,
        *,
        status: int | None,
        body: str,
        repo: str,
        token_fingerprint: str,
    ) -> None:
        self.status = status
        self.body = body
        self.repo = repo
        self.token_fingerprint = token_fingerprint
        super().__init__(
            f"NotesAdapterError(status={status}, repo={repo}, "
            f"token={token_fingerprint}): {body}"
        )
```

- [ ] **Step 4: Run test, confirm it passes**

Run: `pytest remote-gateway/tests/test_notes_adapter.py::test_notes_adapter_error_carries_diagnostics -xvs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapter.py remote-gateway/tests/test_notes_adapter.py
git commit -m "feat(notes): add NotesAdapterError for loud failure surfacing"
```

---

## Task 2: `GitHubFilesAdapter.__init__` and env validation

**Files:**
- Create: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `remote-gateway/tests/test_notes_files_adapter.py`:

```python
"""Unit tests for GitHubFilesAdapter."""
from __future__ import annotations

import base64
import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def notes_env(monkeypatch):
    monkeypatch.setenv("NOTES_REPO", "org/test-notes")
    monkeypatch.setenv("NOTES_GITHUB_TOKEN", "ghp_test1234")


def _mock_resp(json_data=None, status_code: int = 200, text: str = "") -> MagicMock:
    m = MagicMock(spec=httpx.Response)
    m.status_code = status_code
    m.text = text or ("" if json_data is None else str(json_data))
    m.json = MagicMock(return_value=json_data)
    if status_code >= 400:
        request = httpx.Request("GET", "https://api.github.com/test")
        m.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status_code}", request=request, response=m
            )
        )
    else:
        m.raise_for_status = MagicMock()
    return m


def _mock_client_ctx(mock_cls):
    mock_client = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


def _repo_meta(default_branch: str = "main") -> dict:
    return {"default_branch": default_branch}


# ---- __init__ ----

def test_init_raises_without_repo(monkeypatch):
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    monkeypatch.delenv("NOTES_REPO")
    with pytest.raises(RuntimeError, match="NOTES_REPO"):
        GitHubFilesAdapter()


def test_init_raises_without_token(monkeypatch):
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    monkeypatch.delenv("NOTES_GITHUB_TOKEN")
    with pytest.raises(RuntimeError, match="NOTES_GITHUB_TOKEN"):
        GitHubFilesAdapter()


def test_init_fetches_default_branch():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("trunk"))

        adapter = GitHubFilesAdapter()

    assert adapter._branch == "trunk"
    # First call is GET /repos/{repo}
    first_call_url = client.get.call_args_list[0][0][0]
    assert first_call_url.endswith("/repos/org/test-notes")
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.integrations.notes.adapters.github_files'`.

- [ ] **Step 3: Create the adapter file with __init__ only**

Create `remote-gateway/tools/integrations/notes/adapters/github_files.py`:

```python
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
from typing import Any

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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): GitHubFilesAdapter init + default-branch discovery"
```

---

## Task 3: `read(slug)` — hit and miss

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Modify: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_files_adapter.py`:

```python
def _file_payload(content: str, sha: str = "abc123", path: str = "notes/my-note.md") -> dict:
    return {
        "name": path.split("/")[-1],
        "path": path,
        "sha": sha,
        "content": base64.b64encode(content.encode()).decode(),
        "encoding": "base64",
        "html_url": f"https://github.com/org/test-notes/blob/main/{path}",
    }


# ---- read ----

def test_read_returns_content_when_file_exists():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_file_payload("hello world", sha="sha-5", path="notes/my-note.md")),
        ]

        result = GitHubFilesAdapter().read("my-note")

    assert result is not None
    assert result["slug"] == "my-note"
    assert result["content"] == "hello world"
    assert result["id"] == "sha-5"
    assert result["path"] == "notes/my-note.md"
    assert "github.com/org/test-notes/blob/main/notes/my-note.md" in result["url"]


def test_read_returns_none_when_missing():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().read("ghost")

    assert result is None
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "read"`
Expected: FAIL with `AttributeError: 'GitHubFilesAdapter' object has no attribute 'read'`.

- [ ] **Step 3: Implement `read`**

Append to `remote-gateway/tools/integrations/notes/adapters/github_files.py` (inside the class):

```python
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "read"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): GitHubFilesAdapter.read via contents API"
```

---

## Task 4: `list()` — happy path and empty

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Modify: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_files_adapter.py`:

```python
def _dir_entry(name: str, type_: str = "file", sha: str = "x", path: str | None = None) -> dict:
    p = path or f"notes/{name}"
    return {
        "name": name,
        "path": p,
        "sha": sha,
        "type": type_,
        "html_url": f"https://github.com/org/test-notes/blob/main/{p}",
    }


def _commit(path: str, date_committed: str, date_authored: str | None = None) -> dict:
    return {
        "sha": f"commit-{path}-{date_committed}",
        "commit": {
            "committer": {"date": date_committed},
            "author": {"date": date_authored or date_committed},
        },
        "files": [{"filename": path}],
    }


# ---- list ----

def test_list_returns_md_files_with_dates():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    files = [
        _dir_entry("manifesto.md", sha="s1"),
        _dir_entry("draft.md", sha="s2"),
        _dir_entry("issues", type_="dir"),         # ignored
        _dir_entry("notes-not-md.txt", sha="sX"),  # ignored
    ]
    # Newest-first commits per the contract; list builds {oldest, newest} per path
    commits = [
        _commit("notes/manifesto.md", "2026-05-20T00:00:00Z"),
        _commit("notes/manifesto.md", "2026-05-10T00:00:00Z"),
        _commit("notes/draft.md", "2026-05-15T00:00:00Z"),
    ]
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(files),
            _mock_resp(commits),
        ]

        result = GitHubFilesAdapter().list()

    assert len(result) == 2
    by_slug = {n["slug"]: n for n in result}
    assert by_slug["manifesto"]["id"] == "s1"
    assert by_slug["manifesto"]["path"] == "notes/manifesto.md"
    assert by_slug["manifesto"]["created_at"] == "2026-05-10T00:00:00Z"
    assert by_slug["manifesto"]["updated_at"] == "2026-05-20T00:00:00Z"
    assert by_slug["draft"]["created_at"] == "2026-05-15T00:00:00Z"
    assert by_slug["draft"]["updated_at"] == "2026-05-15T00:00:00Z"


def test_list_returns_empty_when_notes_dir_missing():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().list()

    assert result == []
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "list"`
Expected: FAIL with `AttributeError: 'GitHubFilesAdapter' object has no attribute 'list'`.

- [ ] **Step 3: Implement `list`**

Append to `github_files.py` (inside the class):

```python
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "list"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): GitHubFilesAdapter.list with commit-derived timestamps"
```

---

## Task 5: `write(slug, content)` — create, update, conflict

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Modify: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_files_adapter.py`:

```python
# ---- write ----

def test_write_creates_when_file_does_not_exist():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    created_payload = {
        "content": _file_payload("hello", sha="new-sha", path="notes/new-note.md"),
        "commit": {"sha": "commit1"},
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),  # GET file → miss
        ]
        client.put.return_value = _mock_resp(created_payload, status_code=201)

        result = GitHubFilesAdapter().write("new-note", "hello")

    assert result["status"] == "created"
    assert result["slug"] == "new-note"
    assert result["id"] == "new-sha"
    assert result["path"] == "notes/new-note.md"
    # PUT payload
    put_body = client.put.call_args[1]["json"]
    assert put_body["message"] == "notes: create new-note via gateway"
    assert base64.b64decode(put_body["content"]).decode() == "hello"
    assert put_body["branch"] == "main"
    assert "sha" not in put_body  # no sha on create


def test_write_updates_when_file_exists():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    existing = _file_payload("old", sha="old-sha", path="notes/existing.md")
    updated_payload = {
        "content": _file_payload("new", sha="updated-sha", path="notes/existing.md"),
        "commit": {"sha": "commit2"},
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(existing),
        ]
        client.put.return_value = _mock_resp(updated_payload)

        result = GitHubFilesAdapter().write("existing", "new")

    assert result["status"] == "updated"
    assert result["id"] == "updated-sha"
    put_body = client.put.call_args[1]["json"]
    assert put_body["sha"] == "old-sha"
    assert put_body["message"] == "notes: update existing via gateway"


def test_write_raises_on_sha_conflict():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    existing = _file_payload("old", sha="old-sha", path="notes/conflict.md")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(existing),
        ]
        client.put.return_value = _mock_resp(
            None, status_code=409, text="sha mismatch"
        )

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("conflict", "new")

    assert excinfo.value.status == 409
    assert "sha mismatch" in excinfo.value.body
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "write"`
Expected: FAIL with `AttributeError: 'GitHubFilesAdapter' object has no attribute 'write'`.

- [ ] **Step 3: Implement `write`**

Append to `github_files.py` (inside the class):

```python
    def write(self, slug: str, content: str) -> dict:
        """Create or update notes/{slug}.md on the default branch."""
        path = self._path_for(slug)
        existing_sha: str | None = None
        try:
            with httpx.Client() as client:
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "write"`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): GitHubFilesAdapter.write with sha concurrency check"
```

---

## Task 6: `delete(slug)` — exists, missing

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Modify: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_files_adapter.py`:

```python
# ---- delete ----

def test_delete_removes_existing_file():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    existing = _file_payload("bye", sha="del-sha", path="notes/to-delete.md")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(existing),
        ]
        # Impl uses client.request("DELETE", ...) because the GH contents API
        # requires a body on DELETE and httpx.Client.delete() doesn't accept json=.
        client.request.return_value = _mock_resp({"commit": {"sha": "c3"}})

        result = GitHubFilesAdapter().delete("to-delete")

    assert result["status"] == "deleted"
    assert result["slug"] == "to-delete"
    assert result["path"] == "notes/to-delete.md"
    assert client.request.call_args[0][0] == "DELETE"
    del_body = client.request.call_args[1]["json"]
    assert del_body["sha"] == "del-sha"
    assert del_body["message"] == "notes: delete to-delete via gateway"
    assert del_body["branch"] == "main"


def test_delete_missing_returns_not_found():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().delete("ghost")

    assert result["status"] == "not_found"
    assert result["slug"] == "ghost"
    client.request.assert_not_called()
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "delete"`
Expected: FAIL with `AttributeError: 'GitHubFilesAdapter' object has no attribute 'delete'`.

- [ ] **Step 3: Implement `delete`**

Append to `github_files.py` (inside the class):

```python
    def delete(self, slug: str) -> dict:
        """Delete notes/{slug}.md on the default branch."""
        path = self._path_for(slug)
        try:
            with httpx.Client() as client:
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "delete"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): GitHubFilesAdapter.delete"
```

---

## Task 7: Loud failure on upstream errors (#35's fix)

The wrapping logic is already present in tasks 2-6 (via `_wrap` and the try/except blocks). This task adds explicit tests confirming that 5xx and `RequestError` propagate as `NotesAdapterError` — the regression net for #35.

**Files:**
- Modify: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_files_adapter.py`:

```python
# ---- error surfacing (#35) ----

def test_list_raises_on_500_from_contents():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=500, text="upstream boom"),
        ]

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().list()

    assert excinfo.value.status == 500
    assert excinfo.value.repo == "org/test-notes"
    assert excinfo.value.token_fingerprint == "ghp_…"
    assert "upstream boom" in excinfo.value.body


def test_read_raises_on_403_from_contents():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=403, text="forbidden"),
        ]

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().read("any-note")

    assert excinfo.value.status == 403


def test_init_raises_on_network_error_to_repo():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = httpx.ConnectError("dns fail")

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter()

    assert excinfo.value.status is None
    assert "dns fail" in excinfo.value.body
```

- [ ] **Step 2: Run tests, confirm they pass immediately**

The wrapping was implemented in tasks 2-6, so these regression tests should pass on first run.

Run: `pytest remote-gateway/tests/test_notes_files_adapter.py -xvs -k "raises"`
Expected: PASS (3 tests).

If any fail, fix the corresponding adapter method's exception handling. Do not commit until they pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tests/test_notes_files_adapter.py
git commit -m "test(notes): regression tests for loud failure surfacing"
```

---

## Task 8: Swap factory default and drop the issues adapter from the registry

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapter.py`
- Modify: `remote-gateway/tests/test_notes_adapter.py`

- [ ] **Step 1: Update the factory tests**

Replace the existing tests in `remote-gateway/tests/test_notes_adapter.py` (keep imports, `notes_env` fixture, and `test_notes_adapter_error_carries_diagnostics` from Task 1):

```python
"""Tests for the NotesAdapter factory."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def notes_env(monkeypatch):
    monkeypatch.setenv("NOTES_REPO", "org/test-notes")
    monkeypatch.setenv("NOTES_GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("NOTES_ADAPTER", raising=False)


def _mock_repo_get():
    """Patch httpx so GitHubFilesAdapter.__init__ does not call the network."""
    ctx = patch("httpx.Client")
    mock_cls = ctx.start()
    mock_client = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"default_branch": "main"})
    mock_client.get.return_value = resp
    return ctx


def test_get_adapter_default_is_github_files():
    from tools.integrations.notes.adapter import get_adapter
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    ctx = _mock_repo_get()
    try:
        adapter = get_adapter()
    finally:
        ctx.stop()

    assert isinstance(adapter, GitHubFilesAdapter)


def test_get_adapter_respects_notes_adapter_env(monkeypatch):
    from tools.integrations.notes.adapter import get_adapter
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    monkeypatch.setenv("NOTES_ADAPTER", "github-files")
    ctx = _mock_repo_get()
    try:
        adapter = get_adapter()
    finally:
        ctx.stop()

    assert isinstance(adapter, GitHubFilesAdapter)


def test_get_adapter_unknown_name_raises(monkeypatch):
    from tools.integrations.notes.adapter import get_adapter

    monkeypatch.setenv("NOTES_ADAPTER", "notion")

    with pytest.raises(RuntimeError, match="Unknown NOTES_ADAPTER"):
        get_adapter()


def test_get_adapter_github_issues_alias_is_no_longer_registered(monkeypatch):
    from tools.integrations.notes.adapter import get_adapter

    monkeypatch.setenv("NOTES_ADAPTER", "github-issues")

    with pytest.raises(RuntimeError, match="Unknown NOTES_ADAPTER"):
        get_adapter()


def test_get_adapter_returns_fresh_instance_each_call():
    from tools.integrations.notes.adapter import get_adapter

    ctx = _mock_repo_get()
    try:
        a = get_adapter()
        b = get_adapter()
    finally:
        ctx.stop()

    assert a is not b


def test_notes_adapter_error_carries_diagnostics():
    from tools.integrations.notes.adapter import NotesAdapterError

    err = NotesAdapterError(
        status=403,
        body="forbidden",
        repo="org/test-notes",
        token_fingerprint="ghp_…",
    )

    assert err.status == 403
    assert err.body == "forbidden"
    assert err.repo == "org/test-notes"
    assert err.token_fingerprint == "ghp_…"
    assert "403" in str(err)
    assert "org/test-notes" in str(err)
    assert "ghp_…" in str(err)
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_adapter.py -xvs`
Expected: FAIL (registry still defaults to `github-issues`).

- [ ] **Step 3: Update the factory**

Edit `remote-gateway/tools/integrations/notes/adapter.py`. Replace the `_registry` and `get_adapter` functions and the module docstring:

```python
"""Notes storage adapter Protocol and factory.

Adapters implement the NotesAdapter Protocol to provide a pluggable backend
for write_note / read_note / list_notes / delete_note. The active adapter is
selected per-invocation by the NOTES_ADAPTER env var (default: github-files).

Each adapter declares its own required env vars in its docstring and raises
RuntimeError on instantiation if any are missing.
"""
```

```python
def _registry() -> dict[str, type]:
    """Lazy-load the adapter registry to avoid circular imports."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    return {"github-files": GitHubFilesAdapter}


def get_adapter() -> NotesAdapter:
    """Return a fresh adapter instance per call. Selection is env-var driven.

    Reads NOTES_ADAPTER (default: "github-files"). Raises RuntimeError if the
    name is unknown. Any exception raised by the chosen adapter's __init__
    (e.g., RuntimeError on missing env vars) propagates as-is.
    """
    name = os.environ.get("NOTES_ADAPTER", "github-files")
    registry = _registry()
    if name not in registry:
        raise RuntimeError(
            f"Unknown NOTES_ADAPTER={name!r}. Known adapters: {sorted(registry)}"
        )
    return registry[name]()
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_adapter.py -xvs`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapter.py remote-gateway/tests/test_notes_adapter.py
git commit -m "refactor(notes): default NOTES_ADAPTER to github-files, drop github-issues from registry"
```

---

## Task 9: Delete the old `GitHubIssuesAdapter`

**Files:**
- Delete: `remote-gateway/tools/integrations/notes/adapters/github_issues.py`
- Delete: `remote-gateway/tests/test_github_issues_adapter.py`
- Modify: `remote-gateway/tools/integrations/notes/__init__.py`

- [ ] **Step 1: Delete the old adapter and its tests**

```bash
git rm remote-gateway/tools/integrations/notes/adapters/github_issues.py
git rm remote-gateway/tests/test_github_issues_adapter.py
```

- [ ] **Step 2: Update the notes integration docstring**

Edit `remote-gateway/tools/integrations/notes/__init__.py`. Replace the module docstring:

```python
"""Notes integration — pluggable storage backend.

See adapter.py for the NotesAdapter Protocol and the env-var-driven factory.
The default adapter routes to markdown files at notes/*.md in NOTES_REPO
(see adapters/github_files.py).
"""
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest`
Expected: PASS (no failures, no import errors from the removed adapter).

If any test still imports `GitHubIssuesAdapter`, remove or update it. There should be none left after Task 8.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/tools/integrations/notes/__init__.py
git commit -m "chore(notes): remove GitHubIssuesAdapter, files-backed adapter is now the only backend"
```

---

## Task 10: Migration script for the 4 existing `type:note` issues

**Files:**
- Create: `scripts/migrate_notes_issues_to_files.py`
- Create: `remote-gateway/tests/test_migrate_notes_issues_to_files.py`

The script uses raw GitHub API calls (not the new adapter) because:
1. It needs custom commit messages (`"notes: migrate from issue #N (slug)"`) the adapter doesn't expose.
2. It is one-shot — coupling it to the adapter creates unnecessary churn if the adapter changes.
3. It needs `Issues: read+write` during the migration window, which the adapter no longer requires.

- [ ] **Step 1: Write the failing smoke test**

Create `remote-gateway/tests/test_migrate_notes_issues_to_files.py`:

```python
"""Smoke tests for the one-shot notes migration script."""
from __future__ import annotations

import base64
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _load_script():
    """Load the script as a module (it's not a package import)."""
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "scripts" / "migrate_notes_issues_to_files.py"
    spec = importlib.util.spec_from_file_location("migrate_notes", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def notes_env(monkeypatch):
    monkeypatch.setenv("NOTES_REPO", "org/test-notes")
    monkeypatch.setenv("NOTES_GITHUB_TOKEN", "ghp_test")


def _mock_resp(json_data=None, status_code: int = 200, text: str = ""):
    m = MagicMock(spec=httpx.Response)
    m.status_code = status_code
    m.text = text
    m.json = MagicMock(return_value=json_data)
    if status_code >= 400:
        request = httpx.Request("GET", "https://api.github.com/test")
        m.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status_code}", request=request, response=m
            )
        )
    else:
        m.raise_for_status = MagicMock()
    return m


def _mock_client_ctx(mock_cls):
    mock_client = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_migrates_one_issue_to_file_and_closes_it():
    script = _load_script()

    issue = {
        "number": 4,
        "title": "content-drafts-2026-05-24",
        "body": "drafts go here",
        "html_url": "https://github.com/org/test-notes/issues/4",
    }
    file_create_response = {
        "content": {
            "sha": "new-file-sha",
            "html_url": "https://github.com/org/test-notes/blob/main/notes/content-drafts-2026-05-24.md",
            "path": "notes/content-drafts-2026-05-24.md",
        },
        "commit": {"sha": "abc"},
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp([issue]),                                     # list issues
            _mock_resp(None, status_code=404, text="not found"),     # file does not exist
        ]
        client.put.return_value = _mock_resp(file_create_response, status_code=201)
        client.post.return_value = _mock_resp({})                    # issue comment
        client.patch.return_value = _mock_resp({"state": "closed"})  # close issue

        summary = script.run()

    assert summary["migrated"] == 1
    assert summary["skipped"] == 0
    assert summary["errors"] == 0
    # PUT call
    put_kwargs = client.put.call_args[1]["json"]
    assert "migrate from issue #4" in put_kwargs["message"]
    assert base64.b64decode(put_kwargs["content"]).decode() == "drafts go here"
    # PATCH closes the issue
    patch_kwargs = client.patch.call_args[1]["json"]
    assert patch_kwargs["state"] == "closed"


def test_skips_when_target_file_already_exists_with_same_content():
    script = _load_script()

    issue = {
        "number": 5,
        "title": "already-migrated",
        "body": "same body",
        "html_url": "https://github.com/org/test-notes/issues/5",
    }
    existing_file = {
        "content": base64.b64encode(b"same body").decode(),
        "sha": "sha-existing",
        "html_url": "https://github.com/org/test-notes/blob/main/notes/already-migrated.md",
        "path": "notes/already-migrated.md",
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp([issue]),
            _mock_resp(existing_file),
        ]

        summary = script.run()

    assert summary["migrated"] == 0
    assert summary["skipped"] == 1
    client.put.assert_not_called()
    client.patch.assert_not_called()


def test_warns_and_skips_when_target_exists_with_different_content():
    script = _load_script()

    issue = {
        "number": 6,
        "title": "diverged",
        "body": "issue body",
        "html_url": "https://github.com/org/test-notes/issues/6",
    }
    existing_file = {
        "content": base64.b64encode(b"different body in repo").decode(),
        "sha": "sha-x",
        "html_url": "https://github.com/org/test-notes/blob/main/notes/diverged.md",
        "path": "notes/diverged.md",
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp([issue]),
            _mock_resp(existing_file),
        ]

        summary = script.run()

    assert summary["migrated"] == 0
    assert summary["skipped"] == 1
    assert summary["warnings"] == 1
    client.put.assert_not_called()
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_migrate_notes_issues_to_files.py -xvs`
Expected: FAIL with `FileNotFoundError` or similar (script does not exist yet).

- [ ] **Step 3: Create the migration script**

Create `scripts/migrate_notes_issues_to_files.py`:

```python
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_migrate_notes_issues_to_files.py -xvs`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_notes_issues_to_files.py remote-gateway/tests/test_migrate_notes_issues_to_files.py
git commit -m "feat(notes): one-shot migration script for type:note issues → files"
```

---

## Task 11: Update documentation

**Files:**
- Modify: `remote-gateway/CLAUDE.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `remote-gateway/CLAUDE.md` env-var table**

Open `remote-gateway/CLAUDE.md`. Replace the three `NOTES_*` rows in the env vars table (lines around 41-43):

```
| `NOTES_ADAPTER` | No | Notes storage backend (default: `github-files`). |
| `NOTES_REPO` | Yes (when adapter=github-files) | `owner/repo` for notes (e.g. `Inform-Growth/inform-notes`). |
| `NOTES_GITHUB_TOKEN` | Yes (when adapter=github-files) | Fine-grained PAT with `Contents: read+write` on `NOTES_REPO`. |
```

Then update the "Notes & Issue Backlog" line (around line 105):

```
- **Notes & Issue Backlog**: Monitor two repos — `NOTES_REPO/notes/*.md` for durable session notes (via the configured notes adapter), and `ISSUE_DEPLOYMENT_REPO` for `source:report_issue` friction signals. Review both regularly to understand user goals and stay ahead of integration failures.
```

- [ ] **Step 2: Update root `CLAUDE.md`**

Open `CLAUDE.md`. Update the Persistence line (around line 112):

```
- **Persistence**: Notes are stored via the adapter selected by `NOTES_ADAPTER` (default `github-files`, backed by markdown files under `notes/*.md` in `NOTES_REPO`). They are NOT in `ISSUE_DEPLOYMENT_REPO` — that's friction issues only.
```

Update the Repository Structure line (around line 127):

```
    - `integrations/notes/` **[custom]** — pluggable notes storage (`write_note` / `read_note` / `list_notes` / `delete_note`). `NotesAdapter` Protocol + `GitHubFilesAdapter` backend (markdown files under `notes/*.md` in `NOTES_REPO`). Stays `[custom]` until a second adapter (e.g. SQLite-backed for downstream clients) is added.
```

Update the Tool Inventory row (around line 166):

```
| `write_note` / `read_note` / `list_notes` / `delete_note` | Notes stored via the adapter configured by `NOTES_ADAPTER` (default: `github-files`, backed by `notes/*.md` in `NOTES_REPO`). |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md
git commit -m "docs(notes): document new files-backed adapter and Contents token scope"
```

---

## Task 12: Full test suite + lint

- [ ] **Step 1: Run the whole test suite**

Run: `pytest`
Expected: PASS (all tests). Pay attention to any test that previously imported `GitHubIssuesAdapter`.

- [ ] **Step 2: Run lint**

Run: `ruff check .`
Expected: clean (no new violations).

If anything fails, fix it in a follow-up commit (`fix(notes): …`).

---

## Deployment Notes (out of scope for this plan, but the engineer should surface them to the user)

After this plan is merged:

1. Rotate `NOTES_GITHUB_TOKEN` on the Inform Growth Railway service. New scope: `Contents: read+write` on `Inform-Growth/inform-notes`. **Add `Issues: read+write` temporarily** so the migration script can comment-and-close.
2. Run the migration script once against the deployment env:
   ```
   NOTES_REPO=Inform-Growth/inform-notes NOTES_GITHUB_TOKEN=<pat> \
     python scripts/migrate_notes_issues_to_files.py
   ```
3. Verify summary shows 4 migrated, 0 errors. Spot-check the 4 new files on `Inform-Growth/inform-notes/tree/main/notes`.
4. Drop the `Issues` scope from the PAT.
5. Deploy.
6. In a follow-up PR, delete `scripts/migrate_notes_issues_to_files.py` and `remote-gateway/tests/test_migrate_notes_issues_to_files.py` (one-shot script, no longer needed).

The agent implementing this plan should leave the script + its test in place and surface steps 1-6 to the user in the PR description.
