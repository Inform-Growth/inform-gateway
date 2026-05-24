# Notes Storage Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the notes tools (`write_note`/`read_note`/`list_notes`/`delete_note`) into a pluggable adapter pattern with one `GitHubIssuesAdapter` implementation pointing at `Inform-Growth/inform-notes`. Split friction tools (`report_issue`/`list_my_issues`) into a separate module since they stay gateway-internal.

**Architecture:** A `NotesAdapter` Protocol declares the storage contract; a per-invocation factory reads `NOTES_ADAPTER` and instantiates the configured adapter. The MCP tools become thin delegators. The github-issues adapter preserves today's exact GitHub Issues behavior (label `type:note`, slug-as-title, close-as-delete) but reads `NOTES_REPO`/`NOTES_GITHUB_TOKEN` instead of `ISSUE_DEPLOYMENT_REPO`/`ISSUE_DEPLOYMENT_GITHUB_TOKEN`.

**Tech Stack:** Python 3.11+, httpx, FastMCP, pytest, unittest.mock.

**Spec:** [`docs/superpowers/specs/2026-05-23-notes-adapter-design.md`](../specs/2026-05-23-notes-adapter-design.md)

**Issues:** Closes #18. Partially advances #19. Unblocks #22.

---

## Pre-flight

- [ ] **Step 0a: Confirm working tree is clean**

Run: `git status --short`
Expected: empty or only the spec file you just committed.

- [ ] **Step 0b: Confirm test baseline is green**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/ -q 2>&1 | tail -20`
Expected: all tests pass (or note any pre-existing failures so you don't blame them on this work).

---

## Task 1: Adapter Protocol + factory

**Files:**
- Create: `remote-gateway/tools/integrations/notes/__init__.py`
- Create: `remote-gateway/tools/integrations/notes/adapter.py`
- Create: `remote-gateway/tools/integrations/notes/adapters/__init__.py`
- Test: `remote-gateway/tests/test_notes_adapter.py`

- [ ] **Step 1: Create the empty package `__init__.py` files**

```bash
mkdir -p remote-gateway/tools/integrations/notes/adapters
touch remote-gateway/tools/integrations/notes/__init__.py
touch remote-gateway/tools/integrations/notes/adapters/__init__.py
```

- [ ] **Step 2: Write the failing factory tests**

Create `remote-gateway/tests/test_notes_adapter.py`:

```python
"""Tests for the NotesAdapter factory."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def notes_env(monkeypatch):
    monkeypatch.setenv("NOTES_REPO", "org/test-notes")
    monkeypatch.setenv("NOTES_GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("NOTES_ADAPTER", raising=False)


def test_get_adapter_default_is_github_issues():
    from tools.integrations.notes.adapter import get_adapter
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    adapter = get_adapter()

    assert isinstance(adapter, GitHubIssuesAdapter)


def test_get_adapter_respects_notes_adapter_env(monkeypatch):
    from tools.integrations.notes.adapter import get_adapter
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    monkeypatch.setenv("NOTES_ADAPTER", "github-issues")
    adapter = get_adapter()

    assert isinstance(adapter, GitHubIssuesAdapter)


def test_get_adapter_unknown_name_raises(monkeypatch):
    from tools.integrations.notes.adapter import get_adapter

    monkeypatch.setenv("NOTES_ADAPTER", "notion")

    with pytest.raises(RuntimeError, match="Unknown NOTES_ADAPTER"):
        get_adapter()


def test_get_adapter_returns_fresh_instance_each_call():
    from tools.integrations.notes.adapter import get_adapter

    a = get_adapter()
    b = get_adapter()

    assert a is not b  # per-invocation, not cached
```

- [ ] **Step 3: Run tests — expect ImportError**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_notes_adapter.py -v`
Expected: all four tests FAIL with `ModuleNotFoundError: No module named 'tools.integrations.notes.adapter'`.

- [ ] **Step 4: Implement adapter.py (Protocol + factory + registry — github_issues import is forward-referenced)**

Create `remote-gateway/tools/integrations/notes/adapter.py`:

```python
"""Notes storage adapter Protocol and factory.

Adapters implement the NotesAdapter Protocol to provide a pluggable backend
for write_note / read_note / list_notes / delete_note. The active adapter is
selected per-invocation by the NOTES_ADAPTER env var (default: github-issues).

Each adapter declares its own required env vars in its docstring and raises
RuntimeError on instantiation if any are missing.
"""
from __future__ import annotations

import os
from typing import Protocol


class NotesAdapter(Protocol):
    """Storage backend contract for notes."""

    def write(self, slug: str, content: str) -> dict:
        """Create or update a note.

        Returns {"slug": str, "id": str, "url": str, "status": "created" | "updated"}.
        Adapters MAY include additional adapter-specific fields.
        """
        ...

    def read(self, slug: str) -> dict | None:
        """Read a note by slug.

        Returns {"slug": str, "content": str, "id": str, "url": str, ...} or None.
        """
        ...

    def list(self) -> list[dict]:
        """List all notes.

        Returns [{"slug": str, "id": str, "url": str, "created_at": str, "updated_at": str}, ...].
        Ordering is adapter-defined.
        """
        ...

    def delete(self, slug: str) -> dict:
        """Delete (or close) a note.

        Returns {"slug": str, "status": "deleted" | "not_found"}.
        """
        ...


def _registry() -> dict[str, type]:
    """Lazy-load the adapter registry to avoid circular imports."""
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    return {"github-issues": GitHubIssuesAdapter}


def get_adapter() -> NotesAdapter:
    """Return a fresh adapter instance per call. Selection is env-var driven.

    Reads NOTES_ADAPTER (default: "github-issues"). Raises RuntimeError if the
    name is unknown or if the chosen adapter's __init__ raises (missing env, etc.).
    """
    name = os.environ.get("NOTES_ADAPTER", "github-issues")
    registry = _registry()
    if name not in registry:
        raise RuntimeError(
            f"Unknown NOTES_ADAPTER={name!r}. Known adapters: {sorted(registry)}"
        )
    return registry[name]()
```

- [ ] **Step 5: Create a stub `github_issues.py` so the factory import resolves**

Create `remote-gateway/tools/integrations/notes/adapters/github_issues.py`:

```python
"""GitHub Issues adapter for notes — stub (implemented in Task 2)."""
from __future__ import annotations


class GitHubIssuesAdapter:
    """Stub. Real implementation lands in Task 2."""

    def __init__(self) -> None:
        pass
```

- [ ] **Step 6: Run tests — expect PASS**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_notes_adapter.py -v`
Expected: all four tests PASS.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/tools/integrations/notes/ remote-gateway/tests/test_notes_adapter.py
git commit -m "$(cat <<'EOF'
feat(notes): add NotesAdapter Protocol and factory

First slice of the notes-storage-adapter refactor (spec
2026-05-23-notes-adapter-design.md). Adds the pluggable interface and
env-var-driven factory; the github-issues adapter is a stub filled in by
the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: GitHubIssuesAdapter — write + read

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_issues.py` (replace stub)
- Test: `remote-gateway/tests/test_github_issues_adapter.py`

- [ ] **Step 1: Write failing tests for __init__ validation, write, and read**

Create `remote-gateway/tests/test_github_issues_adapter.py`:

```python
"""Unit tests for GitHubIssuesAdapter (write, read; list/delete in next task)."""
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


def _issue(number: int = 1, title: str = "my-note", body: str = "content") -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "html_url": f"https://github.com/org/test-notes/issues/{number}",
        "labels": [{"name": "type:note"}],
    }


def _mock_resp(json_data, status_code: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock()
    return m


def _mock_client_ctx(mock_cls):
    mock_client = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


# ---- __init__ validation ----

def test_init_raises_without_repo(monkeypatch):
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    monkeypatch.delenv("NOTES_REPO")
    with pytest.raises(RuntimeError, match="NOTES_REPO"):
        GitHubIssuesAdapter()


def test_init_raises_without_token(monkeypatch):
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    monkeypatch.delenv("NOTES_GITHUB_TOKEN")
    with pytest.raises(RuntimeError, match="NOTES_GITHUB_TOKEN"):
        GitHubIssuesAdapter()


# ---- write ----

def test_write_creates_new_when_not_found():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    created = _issue(10, "new-note", "new content")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([])  # _find returns nothing
        client.post.return_value = _mock_resp(created, status_code=201)

        result = GitHubIssuesAdapter().write("new-note", "new content")

    assert result["status"] == "created"
    assert result["slug"] == "new-note"
    assert result["id"] == "10"
    assert result["issue_number"] == 10  # preserved passthrough
    assert "github.com/org/test-notes/issues/10" in result["url"]
    # _ensure_label posts to /labels, write posts to /issues — 2 total
    assert client.post.call_count == 2
    issue_create_call = client.post.call_args_list[1]
    assert issue_create_call[0][0].endswith("/issues")
    payload = issue_create_call[1]["json"]
    assert payload["title"] == "new-note"
    assert payload["body"] == "new content"
    assert payload["labels"] == ["type:note"]


def test_write_updates_when_slug_exists():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    existing = _issue(7, "existing-note", "old")
    updated = _issue(7, "existing-note", "new")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([existing])
        client.patch.return_value = _mock_resp(updated)

        result = GitHubIssuesAdapter().write("existing-note", "new")

    assert result["status"] == "updated"
    assert result["issue_number"] == 7
    client.patch.assert_called_once()
    # _ensure_label posts to /labels only (no issue creation)
    assert client.post.call_count == 1
    assert client.post.call_args[0][0].endswith("/labels")


# ---- read ----

def test_read_found_returns_content():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([_issue(5, "my-note", "hello world")])

        result = GitHubIssuesAdapter().read("my-note")

    assert result is not None
    assert result["slug"] == "my-note"
    assert result["content"] == "hello world"
    assert result["issue_number"] == 5
    assert result["id"] == "5"


def test_read_missing_returns_none():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([])

        result = GitHubIssuesAdapter().read("ghost")

    assert result is None
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_github_issues_adapter.py -v`
Expected: all tests FAIL (the stub adapter doesn't implement these methods yet).

- [ ] **Step 3: Implement the adapter (write + read; list/delete come in Task 3)**

Replace `remote-gateway/tools/integrations/notes/adapters/github_issues.py` with:

```python
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
        issue = self._find(slug)
        if not issue:
            return None
        return self._to_result(issue, content=issue.get("body", ""))

    # list() and delete() in Task 3
    def list(self) -> list[dict]:  # noqa: A003 — Protocol shape
        raise NotImplementedError("Implemented in Task 3")

    def delete(self, slug: str) -> dict:
        raise NotImplementedError("Implemented in Task 3")
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_github_issues_adapter.py -v`
Expected: all 6 tests PASS. Also re-run Task 1 tests to confirm no regression: `pytest remote-gateway/tests/test_notes_adapter.py -v`.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_issues.py remote-gateway/tests/test_github_issues_adapter.py
git commit -m "$(cat <<'EOF'
feat(notes): implement GitHubIssuesAdapter write + read

Reads NOTES_REPO and NOTES_GITHUB_TOKEN. Slug-as-title, body-as-content,
auto-creates the type:note label. Preserves issue_number as an
adapter-specific passthrough so existing consumers don't break.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: GitHubIssuesAdapter — list + delete

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_issues.py` (replace `list()` and `delete()` stubs)
- Modify: `remote-gateway/tests/test_github_issues_adapter.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `remote-gateway/tests/test_github_issues_adapter.py`:

```python
# ---- list ----

def test_list_returns_open_notes():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(
            [_issue(1, "session-2026-05-19"), _issue(2, "onboarding")]
        )

        result = GitHubIssuesAdapter().list()

    assert len(result) == 2
    assert result[0]["slug"] == "session-2026-05-19"
    assert result[1]["slug"] == "onboarding"
    assert result[0]["created_at"] == "2026-01-01T00:00:00Z"
    assert result[0]["updated_at"] == "2026-01-02T00:00:00Z"
    assert result[0]["id"] == "1"


def test_list_empty():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([])

        result = GitHubIssuesAdapter().list()

    assert result == []


# ---- delete ----

def test_delete_closes_issue():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    issue = _issue(3, "to-delete")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([issue])
        client.patch.return_value = _mock_resp({**issue, "state": "closed"})

        result = GitHubIssuesAdapter().delete("to-delete")

    assert result["status"] == "deleted"
    assert result["slug"] == "to-delete"
    assert result["issue_number"] == 3
    call_json = client.patch.call_args[1]["json"]
    assert call_json["state"] == "closed"


def test_delete_not_found():
    from tools.integrations.notes.adapters.github_issues import GitHubIssuesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp([])

        result = GitHubIssuesAdapter().delete("ghost")

    assert result["status"] == "not_found"
    assert result["slug"] == "ghost"
    client.patch.assert_not_called()
```

- [ ] **Step 2: Run tests — expect FAIL (NotImplementedError)**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_github_issues_adapter.py -v`
Expected: 4 new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement list + delete**

In `remote-gateway/tools/integrations/notes/adapters/github_issues.py`, replace the two `NotImplementedError` stubs with:

```python
    def list(self) -> list[dict]:  # noqa: A003 — Protocol shape
        with httpx.Client() as client:
            resp = client.get(
                self._issues_url(),
                headers=self._headers(),
                params={"labels": "type:note", "state": "open", "per_page": 100},
            )
        resp.raise_for_status()
        return [
            {
                "slug": issue["title"],
                "id": str(issue["number"]),
                "url": issue["html_url"],
                "issue_number": issue["number"],
                "created_at": issue["created_at"],
                "updated_at": issue["updated_at"],
            }
            for issue in resp.json()
        ]

    def delete(self, slug: str) -> dict:
        issue = self._find(slug)
        if not issue:
            return {"status": "not_found", "slug": slug}
        with httpx.Client() as client:
            resp = client.patch(
                self._issue_url(issue["number"]),
                headers=self._headers(),
                json={"state": "closed"},
            )
        resp.raise_for_status()
        return {
            "status": "deleted",
            "slug": slug,
            "issue_number": issue["number"],
        }
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_github_issues_adapter.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_issues.py remote-gateway/tests/test_github_issues_adapter.py
git commit -m "$(cat <<'EOF'
feat(notes): GitHubIssuesAdapter list + delete

Completes the adapter CRUD surface. Delete closes the issue (matches
prior delete_note behavior).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: MCP tool layer (delegators)

**Files:**
- Create: `remote-gateway/tools/integrations/notes/tools.py`
- Modify: `remote-gateway/tools/integrations/notes/__init__.py` (registration)

This task wires the four MCP tools to the adapter. The tools themselves contain no GitHub-specific code — they call `get_adapter()` and forward. Return shapes match what agents currently see.

- [ ] **Step 1: Write the tools module**

Create `remote-gateway/tools/integrations/notes/tools.py`:

```python
"""MCP tool functions for notes — thin delegators to the configured NotesAdapter.

The adapter is selected per-invocation via `get_adapter()` so env-var changes
during local dev are picked up without restart. Return shapes preserve the
fields existing consumers expect (slug, content, html_url, status, issue_number).
"""
from __future__ import annotations

from tools.integrations.notes.adapter import get_adapter


def list_notes() -> dict:
    """List all notes stored in the configured notes backend.

    Notes are persistent and shared across all agents on this gateway.

    Returns:
        Dict with 'notes' list and 'count'.
    """
    notes = get_adapter().list()
    # Preserve the existing field name html_url so agents/UI keep working
    rendered = [
        {
            "slug": n["slug"],
            "issue_number": n.get("issue_number"),
            "created_at": n["created_at"],
            "updated_at": n["updated_at"],
            "html_url": n["url"],
        }
        for n in notes
    ]
    return {"notes": rendered, "count": len(rendered)}


def read_note(slug: str) -> dict:
    """Read a note by its slug (title).

    Args:
        slug: The note title used when the note was written.

    Returns:
        Dict with 'slug', 'content', 'issue_number', 'html_url' on success.
        Dict with status='not_found' if no open note matches.
    """
    result = get_adapter().read(slug)
    if result is None:
        return {"status": "not_found", "slug": slug}
    return {
        "slug": result["slug"],
        "content": result["content"],
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def write_note(slug: str, content: str) -> dict:
    """Create or update a note in the configured notes backend.

    If a note with this slug already exists, its content is updated in place.
    Otherwise a new note is created.

    Args:
        slug: Short identifier for the note (used as the issue title).
        content: Full markdown content of the note.

    Returns:
        Dict with 'status' (created/updated), 'slug', 'issue_number', 'html_url'.
    """
    result = get_adapter().write(slug, content)
    return {
        "status": result["status"],
        "slug": result["slug"],
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def delete_note(slug: str) -> dict:
    """Delete a note by its slug.

    For issue-based backends, closes the issue. Returns not_found if absent.

    Args:
        slug: The note title used when the note was written.

    Returns:
        Dict with status='deleted' on success or status='not_found'.
    """
    return get_adapter().delete(slug)
```

- [ ] **Step 2: Wire registration in `__init__.py`**

Replace `remote-gateway/tools/integrations/notes/__init__.py` with:

```python
"""Notes integration — pluggable storage backend.

See adapter.py for the NotesAdapter Protocol and the env-var-driven factory.
The adapter is currently routed to GitHub Issues by default (see adapters/github_issues.py).
"""
from __future__ import annotations

from typing import Any

from tools.integrations.notes.tools import (
    delete_note,
    list_notes,
    read_note,
    write_note,
)


def register(mcp: Any) -> None:
    """Register the four notes MCP tools on the given FastMCP server."""
    mcp.tool()(list_notes)
    mcp.tool()(read_note)
    mcp.tool()(write_note)
    mcp.tool()(delete_note)
```

- [ ] **Step 3: Smoke-test the imports**

Run: `cd /Users/jaronsander/main/inform/inform-gateway/remote-gateway && python -c "from tools.integrations.notes import register, list_notes, read_note, write_note, delete_note; print('imports OK')"`
Expected: `imports OK`.

- [ ] **Step 4: Re-run all notes-related tests to confirm no regression**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_notes_adapter.py remote-gateway/tests/test_github_issues_adapter.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/
git commit -m "$(cat <<'EOF'
feat(notes): add MCP tool delegators

write_note / read_note / list_notes / delete_note now delegate to the
configured NotesAdapter. Return shapes preserve the fields existing
consumers expect (slug, content, html_url, issue_number, status).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Extract friction module

Split `report_issue` + `list_my_issues` out of the old `notes.py` into their own top-level `tools/friction.py`. These tools stay gateway-internal (read `ISSUE_DEPLOYMENT_REPO`) — they are bugs about the gateway itself, not notes.

**Files:**
- Create: `remote-gateway/tools/friction.py`
- Modify: `remote-gateway/tests/test_report_issue.py` (update import path)

- [ ] **Step 1: Create `friction.py` with the report_issue + list_my_issues code**

This code is **lifted verbatim** from `remote-gateway/tools/notes.py` lines 1-80 (helpers), 217-374 (report_issue, list_my_issues, _format_issue_body, _CATEGORY_LABELS, register), with the docstring updated to reflect the friction-only scope. Create `remote-gateway/tools/friction.py`:

```python
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
```

- [ ] **Step 2: Update test imports in `test_report_issue.py`**

In `remote-gateway/tests/test_report_issue.py`, replace **every occurrence** of `from tools.notes import` with `from tools.friction import`. Concretely, search-and-replace these lines:

| Old (current) | New |
|---|---|
| `from tools.notes import report_issue` | `from tools.friction import report_issue` |
| `from tools.notes import list_my_issues` | `from tools.friction import list_my_issues` |

Use:

```bash
sed -i '' 's|from tools.notes import|from tools.friction import|g' remote-gateway/tests/test_report_issue.py
```

- [ ] **Step 3: Run friction tests — expect PASS**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_report_issue.py -v`
Expected: all tests PASS (the old `tools/notes.py` still exists at this point — both imports resolve; the new `tools/friction.py` is what the tests now hit).

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/tools/friction.py remote-gateway/tests/test_report_issue.py
git commit -m "$(cat <<'EOF'
feat: extract friction tools into tools/friction.py

report_issue and list_my_issues split out of notes.py — they're
gateway-internal (bugs about the gateway itself), not pluggable notes.
Behavior unchanged; reads ISSUE_DEPLOYMENT_REPO as before.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire imports in mcp_server.py

**Files:**
- Modify: `remote-gateway/core/mcp_server.py` (lines ~865 and ~905)

- [ ] **Step 1: Locate the current notes import + registration**

Run: `grep -n "tools import notes\|notes_tools.register" remote-gateway/core/mcp_server.py`
Expected: matches at the two lines noted earlier (865 and 905).

- [ ] **Step 2: Update the import line**

In `remote-gateway/core/mcp_server.py`, replace:

```python
from tools import notes as _notes_tools  # noqa: E402
```

with:

```python
from tools import friction as _friction_tools  # noqa: E402
from tools.integrations import notes as _notes_tools  # noqa: E402
```

- [ ] **Step 3: Update the registration block**

Find:

```python
_notes_tools.register(mcp)
```

Replace with:

```python
_notes_tools.register(mcp)
_friction_tools.register(mcp)
```

- [ ] **Step 4: Smoke-test the server boots**

Run: `cd /Users/jaronsander/main/inform/inform-gateway/remote-gateway && python -c "import core.mcp_server; print('server module imports OK')"`
Expected: `server module imports OK` (no ImportError, no missing-env-var crash at import time).

- [ ] **Step 5: Run the full notes + friction test surface**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/test_notes_adapter.py remote-gateway/tests/test_github_issues_adapter.py remote-gateway/tests/test_report_issue.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/mcp_server.py
git commit -m "$(cat <<'EOF'
refactor(mcp_server): register notes from integrations/, friction separately

Imports the new notes package and the extracted friction module. Tool
names registered on the MCP server are unchanged, so no agent prompts break.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Delete legacy notes.py and test_notes.py

**Files:**
- Delete: `remote-gateway/tools/notes.py`
- Delete: `remote-gateway/tests/test_notes.py`
- Delete: `remote-gateway/tests/test_delete_note_retry.py` (it tests the legacy module; its coverage moved to `test_github_issues_adapter.py`)

- [ ] **Step 1: Confirm no live references remain**

Run: `grep -rn "from tools.notes\|tools\.notes" --include="*.py" remote-gateway/ 2>/dev/null | grep -v "tools.integrations.notes"`
Expected: empty output. If anything matches, fix it before deleting the file.

- [ ] **Step 2: Delete the three files**

```bash
git rm remote-gateway/tools/notes.py remote-gateway/tests/test_notes.py remote-gateway/tests/test_delete_note_retry.py
```

- [ ] **Step 3: Run the full test suite to confirm nothing else broke**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && pytest remote-gateway/tests/ -q 2>&1 | tail -15`
Expected: all tests pass; no ImportError mentioning `tools.notes`.

- [ ] **Step 4: Lint**

Run: `cd /Users/jaronsander/main/inform/inform-gateway && ruff check remote-gateway/`
Expected: clean (or only pre-existing warnings unrelated to this work).

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: remove legacy tools/notes.py and its tests

Replaced by tools/integrations/notes/ (pluggable adapter) and
tools/friction.py (gateway-internal friction reporting). Coverage of the
github-issues backend moved to test_github_issues_adapter.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Update env files and docs

**Files:**
- Modify: `.env.example` (root)
- Modify: `remote-gateway/.env.example`
- Modify: `remote-gateway/CLAUDE.md` (env-vars table)
- Modify: `CLAUDE.md` (root — tool inventory + repo structure)

- [ ] **Step 1: Update root `.env.example`**

Read the current file: `cat .env.example`. Add the NOTES_* block, remove the file-based-era GITHUB_* block. Result should contain (replacing the existing GITHUB_REPO/TOKEN/BRANCH section):

```
# Notes storage adapter
# Selects the backend that write_note/read_note/list_notes/delete_note use.
NOTES_ADAPTER=github-issues
NOTES_REPO=Inform-Growth/inform-notes
NOTES_GITHUB_TOKEN=ghp_replace_me  # fine-grained PAT with Issues:read+write on NOTES_REPO

# Friction issues (bugs about the gateway itself) — kept separate from notes
ISSUE_DEPLOYMENT_REPO=Inform-Growth/inform-gateway
ISSUE_DEPLOYMENT_GITHUB_TOKEN=ghp_replace_me  # fine-grained PAT with Issues:read+write on this repo
```

Use Edit (not sed) so you can verify the result. Delete the lines:

```
GITHUB_TOKEN=...
GITHUB_REPO=...
GITHUB_BRANCH=...
```

- [ ] **Step 2: Mirror in `remote-gateway/.env.example`**

Same edits as Step 1, applied to `remote-gateway/.env.example`. Confirm both files agree.

- [ ] **Step 3: Update `remote-gateway/CLAUDE.md` env-vars table**

Find the env-vars table (currently around the "Environment Variables" section). Add three rows for `NOTES_ADAPTER`, `NOTES_REPO`, `NOTES_GITHUB_TOKEN`. Update the description on `ISSUE_DEPLOYMENT_REPO` and `ISSUE_DEPLOYMENT_GITHUB_TOKEN` to clarify scope:

| Variable | Required | Description |
|---|---|---|
| `NOTES_ADAPTER` | No | Notes storage backend (default: `github-issues`). |
| `NOTES_REPO` | Yes (when adapter=github-issues) | `owner/repo` for notes (e.g. `Inform-Growth/inform-notes`). |
| `NOTES_GITHUB_TOKEN` | Yes (when adapter=github-issues) | Fine-grained PAT with `Issues: read+write` on `NOTES_REPO`. |
| `ISSUE_DEPLOYMENT_REPO` | Yes | `owner/repo` for friction issues (bugs about the gateway). |
| `ISSUE_DEPLOYMENT_GITHUB_TOKEN` | Yes | Fine-grained PAT with `Issues: read+write` on the gateway repo. |

- [ ] **Step 4: Update root `CLAUDE.md` tool inventory + repo structure**

In `CLAUDE.md`, find the "Repository Structure" section. The current bullet for `notes.py` reads:

> `notes.py` **[custom]** — GitHub Issues-backed notes (`write_note`, `read_note`, `list_notes`, `delete_note`, `report_issue`, `list_my_issues`). **Inform-Growth dogfood only**; downstream deployments use DB-backed notes instead, so this file is excluded from sync.

Replace with two bullets:

> - `friction.py` **[custom]** — `report_issue` / `list_my_issues`. Gateway-internal friction reporting; reads `ISSUE_DEPLOYMENT_REPO`.
> - `integrations/notes/` **[custom]** — pluggable notes storage (`write_note` / `read_note` / `list_notes` / `delete_note`). `NotesAdapter` Protocol + `GitHubIssuesAdapter` backend (reads `NOTES_REPO`). Stays `[custom]` until a second adapter (e.g. SQLite-backed for downstream clients) is added.

In the Tool Inventory table, update the `write_note / read_note / list_notes / delete_note` row description to mention "configured via `NOTES_ADAPTER` (default github-issues)." Update the `report_issue` row to clarify it lands on `ISSUE_DEPLOYMENT_REPO`.

- [ ] **Step 5: Verify nothing was left in a half-edited state**

Run: `grep -n "GITHUB_REPO\|GITHUB_BRANCH" CLAUDE.md remote-gateway/CLAUDE.md .env.example remote-gateway/.env.example 2>/dev/null`
Expected: empty output (these vars should be fully removed from docs and examples).

- [ ] **Step 6: Commit**

```bash
git add .env.example remote-gateway/.env.example CLAUDE.md remote-gateway/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: env vars + CLAUDE.md for the notes adapter split

Adds NOTES_ADAPTER / NOTES_REPO / NOTES_GITHUB_TOKEN; documents that
ISSUE_DEPLOYMENT_* is now friction-only. Removes orphaned
GITHUB_REPO/TOKEN/BRANCH leftover from the file-based-notes era.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Post-deploy operational steps (manual checks)

This task is run **after deploy** by the operator. It's not code — it's the cutover.

- [ ] **Step 1: Set NOTES_* env vars in Railway**

In the Railway dashboard for the `inform-gateway` service, add:

- `NOTES_ADAPTER=github-issues`
- `NOTES_REPO=Inform-Growth/inform-notes`
- `NOTES_GITHUB_TOKEN=<existing PAT scoped to inform-notes, or a new one>`

The token may need re-issuing if the existing `GITHUB_TOKEN` is scoped only to `inform-notes` — verify scope before reusing.

- [ ] **Step 2: Remove orphaned Railway vars**

Delete `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH` from Railway. These were file-based-era leftovers, no code reads them anymore.

- [ ] **Step 3: Update local `.env` files**

Apply the same changes to `/Users/jaronsander/main/inform/inform-gateway/.env` (root) and `/Users/jaronsander/main/inform/inform-gateway/remote-gateway/.env`: add NOTES_*, remove GITHUB_*.

Do NOT commit `.env`. Verify with: `grep -E "^(NOTES|GITHUB)" .env remote-gateway/.env`.

- [ ] **Step 4: Smoke-test against the deployed gateway**

From any MCP client connected to the gateway, run:

```
write_note(slug="adapter-smoke-test-2026-05-23", content="hello from the new adapter")
read_note(slug="adapter-smoke-test-2026-05-23")
delete_note(slug="adapter-smoke-test-2026-05-23")
```

Expected: `write_note` returns `status=created` and an `html_url` containing `Inform-Growth/inform-notes`. `read_note` returns the content. `delete_note` returns `status=deleted`. Confirm a closed issue exists in `Inform-Growth/inform-notes` via `gh issue list --repo Inform-Growth/inform-notes --state closed --search "adapter-smoke-test"`.

Also smoke-test friction: any `report_issue` call should still land in `Inform-Growth/inform-gateway` (unchanged). No code path should be hitting the wrong repo.

- [ ] **Step 5: Add cutover-marker comments to legacy notes**

The three existing notes (#16, #17, #20) remain in `Inform-Growth/inform-gateway`. Add an explanatory comment to each so future readers understand the cutover:

```bash
for n in 16 17 20; do
  gh issue comment "$n" --repo Inform-Growth/inform-gateway \
    --body "_As of 2026-05-23, new notes route to \`Inform-Growth/inform-notes\` (see [#19](https://github.com/Inform-Growth/inform-gateway/issues/19) and spec [\`2026-05-23-notes-adapter-design.md\`](https://github.com/Inform-Growth/inform-gateway/blob/main/docs/superpowers/specs/2026-05-23-notes-adapter-design.md)). This note remains here as a pre-cutover legacy artifact._"
done
```

- [ ] **Step 6: Close issue #18 and comment on #19**

```bash
gh issue close 18 --repo Inform-Growth/inform-gateway --reason completed \
  --comment "Fixed by the notes-storage-adapter refactor. New notes now route to \`Inform-Growth/inform-notes\` via the NOTES_REPO env var. See plan: docs/superpowers/plans/2026-05-23-notes-adapter.md"

gh issue comment 19 --repo Inform-Growth/inform-gateway \
  --body "Progress: the adapter pattern landed (see [plan](../blob/main/docs/superpowers/plans/2026-05-23-notes-adapter.md) and [spec](../blob/main/docs/superpowers/specs/2026-05-23-notes-adapter-design.md)). \`NotesAdapter\` Protocol + factory + \`GitHubIssuesAdapter\` shipped. Epic closes when a second adapter (e.g. SqliteAdapter for downstream clients) is added, proving the abstraction."
```

---

## Self-Review checklist (for the implementer)

After Task 7, before Task 8:

- [ ] `git log --oneline | head -8` shows the 7 commits in order: adapter Protocol, adapter write+read, adapter list+delete, MCP delegators, friction split, mcp_server wiring, legacy delete.
- [ ] `pytest remote-gateway/tests/ -q` is green.
- [ ] `ruff check remote-gateway/` is clean (or shows only pre-existing warnings unrelated to this work).
- [ ] `grep -rn "from tools.notes" remote-gateway/` returns nothing (all references should now be `tools.integrations.notes` or `tools.friction`).
- [ ] `mcp_server.py` registers both `_notes_tools.register(mcp)` and `_friction_tools.register(mcp)`.
- [ ] No file in this changeset still references `ISSUE_DEPLOYMENT_REPO` for notes purposes (only for friction).

If any check fails, stop and fix before continuing to docs and the operational cutover.
