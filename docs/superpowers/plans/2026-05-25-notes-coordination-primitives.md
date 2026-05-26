# Notes Coordination Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship epic #43 phases 1 + 2: dynamic folder structure under `notes/` and server-side filters on `list_notes` (`folder=`, `prefix=`, `since=`, `until=`, `limit=`). Migration script moves the 12 slugs that match prefix rules; the other 26 stay at root.

**Architecture:** `GitHubFilesAdapter` switches from contents-API enumeration to git-tree-API enumeration. New helpers `_tree()`, `_find_in_tree()`, `_validate_folder()`, `_parse_path()`. `read`/`write`/`delete` gain optional `folder` param (hint when provided, tree-lookup when not). `list` rewrites entirely around the tree + commit-derived dates for the filtered subset only. Tool layer adds all params and pipes them through unchanged in shape.

**Tech Stack:** Python 3.11+, httpx, FastMCP, pytest with `unittest.mock`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-25-notes-coordination-primitives-design.md`

**Closes:** #43 phases 1 + 2

---

## File Structure

**Create:**
- `scripts/migrate_notes_to_folders.py` — one-shot migration (deleted before merge)
- `remote-gateway/tests/test_notes_folders.py` — new tests for folder-aware behavior
- `remote-gateway/tests/test_migrate_notes_to_folders.py` — migration smoke tests (deleted before merge)

**Modify:**
- `remote-gateway/tools/integrations/notes/adapters/github_files.py` — add helpers + folder support on all CRUD methods + tree-based list
- `remote-gateway/tools/integrations/notes/tools.py` — folder param on all four MCP tools; filter params on list_notes
- `remote-gateway/tests/test_notes_files_adapter.py` — update existing tests for new write/list behavior + new return-shape fields (`folder`)
- `remote-gateway/CLAUDE.md` — document conventional folder names
- `CLAUDE.md` — mention list_notes filter params

Each adapter helper has one job: tree fetch, validation, path parsing, tree lookup. CRUD methods compose them. The list rewrite is large but stays in one method because filtering is its single responsibility.

---

## Conventions

- All tests use the same `_mock_resp` / `_mock_client_ctx` helpers already in `test_notes_files_adapter.py`. New test file imports them or redefines them locally (DRY across test files is fine to break — they're test fixtures).
- Mock fixtures for the tree API return the GitHub git-trees response shape: `{"sha": "...", "tree": [...], "truncated": false}`. Each tree entry has `path`, `type` ("blob"|"tree"), `sha`, `size`.
- Conventional Commit prefixes already in use: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`.
- Run tests from worktree root: `pytest remote-gateway/tests/test_notes_folders.py -xvs`. Full suite: `pytest`.
- Lint: `ruff check .`. Fix new violations before committing.

---

## Task 1: Folder validation helper

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

- [ ] **Step 1: Create the new test file with the failing tests**

Create `remote-gateway/tests/test_notes_folders.py`:

```python
"""Tests for folder-aware behavior on GitHubFilesAdapter."""
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


def _make_adapter():
    """Construct adapter with __init__'s repo-meta call mocked."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))
        return GitHubFilesAdapter()


# ---- folder validation ----

@pytest.mark.parametrize("bad", [
    "../etc",
    "manifesto.md",
    "UPPER",
    "with space",
    "trailing/",
    "/leading",
    "with.dot",
    "with/slash",
    "",
])
def test_validate_folder_rejects_bad_names(bad):
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import _validate_folder

    with pytest.raises(NotesAdapterError) as excinfo:
        _validate_folder(bad)
    assert excinfo.value.status == 400
    assert "invalid folder name" in excinfo.value.body


@pytest.mark.parametrize("good", [
    "marketing",
    "sales",
    "executive",
    "architecture",
    "shadow",
    "jaron",
    "customer-success",
    "team_42",
    "a",
    "a-b-c_d_e",
])
def test_validate_folder_accepts_good_names(good):
    from tools.integrations.notes.adapters.github_files import _validate_folder

    # Should not raise.
    _validate_folder(good)


def test_validate_folder_accepts_none():
    from tools.integrations.notes.adapters.github_files import _validate_folder

    # None means "root" — always allowed.
    _validate_folder(None)
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "validate_folder"`
Expected: FAIL — `_validate_folder` doesn't exist yet.

- [ ] **Step 3: Implement `_validate_folder`**

Edit `remote-gateway/tools/integrations/notes/adapters/github_files.py`. Add an import and module-level constant at the top of the file:

```python
import re
```

```python
# After the _HTTP_TIMEOUT_SECONDS constant:
_FOLDER_RE = re.compile(r"^[a-z0-9_-]+$")
```

Then add the module-level helper after `_FOLDER_RE`:

```python
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
```

NOTE: `NotesAdapterError` requires `repo` and `token_fingerprint`. For validation errors at the module level we don't have an adapter instance handy; pass `os.environ.get("NOTES_REPO", "")` and an empty fingerprint. Acceptable — diagnostic value is in the message, not those two fields.

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "validate_folder"`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): _validate_folder helper for folder name safety"
```

---

## Task 2: Tree fetch helper

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
def _tree_resp(paths: list[str], truncated: bool = False) -> dict:
    """Build a fake git-trees API response.

    Each path becomes a blob entry. Non-leaf path segments are implicit
    (the real API includes tree entries too, but our code filters by type='blob'
    so we only need the blobs here).
    """
    return {
        "sha": "tree-sha",
        "tree": [
            {
                "path": p,
                "type": "blob",
                "sha": f"blob-{p}",
                "size": 100,
                "url": "https://api.github.com/repos/org/test-notes/git/blobs/x",
            }
            for p in paths
        ],
        "truncated": truncated,
    }


# ---- _tree ----

def test_tree_calls_recursive_git_trees_endpoint():
    adapter = _make_adapter()
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_tree_resp([
            "notes/manifesto.md",
            "notes/marketing/competitor-watch-2026-05-25.md",
        ]))

        tree = adapter._tree()

    assert len(tree) == 2
    assert tree[0]["path"] == "notes/manifesto.md"
    # Verify the URL hit the git/trees endpoint with the branch
    call_url = client.get.call_args[0][0]
    assert "/git/trees/main" in call_url
    assert client.get.call_args[1]["params"] == {"recursive": "1"}


def test_tree_wraps_http_error():
    from tools.integrations.notes.adapter import NotesAdapterError
    adapter = _make_adapter()
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(None, status_code=500, text="boom")

        with pytest.raises(NotesAdapterError) as excinfo:
            adapter._tree()

    assert excinfo.value.status == 500
    assert "boom" in excinfo.value.body
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "_tree"`
Expected: FAIL — `_tree` method doesn't exist.

- [ ] **Step 3: Implement `_tree`**

Add inside the `GitHubFilesAdapter` class, in the helpers section after `_path_for`:

```python
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "_tree"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): _tree helper — recursive git-trees API fetch"
```

---

## Task 3: Path parsing + slug lookup helpers

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

These two pure functions translate between paths and (slug, folder) tuples and find a slug in a tree.

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- _parse_path ----

@pytest.mark.parametrize("path,expected", [
    ("notes/manifesto.md", ("manifesto", None)),
    ("notes/marketing/competitor-watch-2026-05-25.md", ("competitor-watch-2026-05-25", "marketing")),
    ("notes/shadow/shadow-2026-05-24-content-drafts.md", ("shadow-2026-05-24-content-drafts", "shadow")),
    ("notes/a/b/c.md", None),       # 3+ levels: ignored
    ("notes/issues", None),         # not a .md file: ignored
    ("other/file.md", None),        # not under notes/: ignored
    ("notes/", None),               # empty/trailing: ignored
])
def test_parse_path(path, expected):
    from tools.integrations.notes.adapters.github_files import _parse_path
    assert _parse_path(path) == expected


# ---- _find_in_tree ----

def test_find_in_tree_returns_path_when_slug_at_root():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [
        {"path": "notes/manifesto.md", "type": "blob", "sha": "s1"},
        {"path": "notes/marketing/competitor-watch-2026-05-25.md", "type": "blob", "sha": "s2"},
    ]
    assert _find_in_tree(tree, "manifesto") == ("notes/manifesto.md", None, "s1")


def test_find_in_tree_returns_path_when_slug_in_folder():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [
        {"path": "notes/manifesto.md", "type": "blob", "sha": "s1"},
        {"path": "notes/marketing/competitor-watch-2026-05-25.md", "type": "blob", "sha": "s2"},
    ]
    assert _find_in_tree(tree, "competitor-watch-2026-05-25") == (
        "notes/marketing/competitor-watch-2026-05-25.md", "marketing", "s2"
    )


def test_find_in_tree_returns_none_when_not_found():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [{"path": "notes/manifesto.md", "type": "blob", "sha": "s1"}]
    assert _find_in_tree(tree, "ghost") is None


def test_find_in_tree_ignores_non_blob_entries():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [
        {"path": "notes/marketing", "type": "tree", "sha": "t1"},
        {"path": "notes/manifesto.md", "type": "blob", "sha": "s1"},
    ]
    assert _find_in_tree(tree, "marketing") is None  # 'marketing' is a tree, not a slug
    assert _find_in_tree(tree, "manifesto") == ("notes/manifesto.md", None, "s1")
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "parse_path or find_in_tree"`
Expected: FAIL — neither helper exists.

- [ ] **Step 3: Implement both helpers**

Add module-level functions in `github_files.py` after `_validate_folder`:

```python
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "parse_path or find_in_tree"`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): _parse_path + _find_in_tree pure helpers"
```

---

## Task 4: Extend `_path_for` to support folders

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- _path_for ----

def test_path_for_root_slug():
    adapter = _make_adapter()
    assert adapter._path_for("manifesto") == "notes/manifesto.md"


def test_path_for_slug_with_folder():
    adapter = _make_adapter()
    assert adapter._path_for("competitor-watch-2026-05-25", folder="marketing") == \
        "notes/marketing/competitor-watch-2026-05-25.md"


def test_path_for_none_folder_same_as_omitting():
    adapter = _make_adapter()
    assert adapter._path_for("foo", folder=None) == "notes/foo.md"
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "path_for"`
Expected: FAIL — `_path_for` doesn't accept `folder` kwarg.

- [ ] **Step 3: Modify `_path_for`**

Edit `github_files.py`. Replace the existing `_path_for` method with:

```python
    def _path_for(self, slug: str, folder: str | None = None) -> str:
        if folder is None:
            return f"notes/{slug}.md"
        return f"notes/{folder}/{slug}.md"
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "path_for"` → 3 pass.
Then also run the existing adapter tests to confirm nothing broke (`_path_for(slug)` without folder is the existing signature):
`pytest remote-gateway/tests/test_notes_files_adapter.py -xvs`
Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): _path_for accepts optional folder"
```

---

## Task 5: `write` with folder + cross-folder collision check

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`
- Test: `remote-gateway/tests/test_notes_files_adapter.py` (existing tests need updates)

- [ ] **Step 1: Write the failing tests for folder behavior**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- write with folder ----

def _file_create_response(path: str, sha: str) -> dict:
    return {
        "content": {
            "name": path.split("/")[-1],
            "path": path,
            "sha": sha,
            "html_url": f"https://github.com/org/test-notes/blob/main/{path}",
        },
        "commit": {"sha": "commit-x"},
    }


def test_write_with_folder_creates_at_nested_path():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),          # __init__
            _mock_resp(_tree_resp([])),               # write: tree lookup, no collision
        ]
        client.put.return_value = _mock_resp(
            _file_create_response("notes/marketing/comp.md", "new-sha"),
            status_code=201,
        )

        result = GitHubFilesAdapter().write("comp", "x", folder="marketing")

    assert result["status"] == "created"
    assert result["slug"] == "comp"
    assert result["folder"] == "marketing"
    assert result["path"] == "notes/marketing/comp.md"
    assert result["id"] == "new-sha"
    # PUT went to the nested path
    put_url = client.put.call_args[0][0]
    assert put_url.endswith("/contents/notes/marketing/comp.md")
    # No sha on create
    assert "sha" not in client.put.call_args[1]["json"]


def test_write_to_same_folder_takes_update_path():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/comp.md"])),
        ]
        client.put.return_value = _mock_resp(
            _file_create_response("notes/marketing/comp.md", "updated-sha"),
        )

        result = GitHubFilesAdapter().write("comp", "new content", folder="marketing")

    assert result["status"] == "updated"
    # sha came from tree, included on PUT
    put_body = client.put.call_args[1]["json"]
    assert put_body["sha"] == "blob-notes/marketing/comp.md"


def test_write_collision_in_different_folder_raises_409():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/sales/comp.md"])),  # slug already in sales/
        ]

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("comp", "x", folder="marketing")

    assert excinfo.value.status == 409
    assert "sales" in excinfo.value.body  # mentions the folder it's in
    assert "comp" in excinfo.value.body
    client.put.assert_not_called()


def test_write_without_folder_collides_with_folder_slug():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/comp.md"])),
        ]

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("comp", "x")  # no folder

    assert excinfo.value.status == 409
    client.put.assert_not_called()


def test_write_without_folder_to_existing_root_slug_updates():
    """No folder + slug exists at root → update path (no collision)."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/manifesto.md"])),
        ]
        client.put.return_value = _mock_resp(
            _file_create_response("notes/manifesto.md", "new"),
        )

        result = GitHubFilesAdapter().write("manifesto", "v2")

    assert result["status"] == "updated"
    assert result["folder"] is None


def test_write_validates_folder_name():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("foo", "x", folder="../etc")

    assert excinfo.value.status == 400
    # No tree call, no put call
    # client.get was called once (in __init__); subsequent should not happen
    assert client.get.call_count == 1
    client.put.assert_not_called()
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "write"`
Expected: FAIL — `write` doesn't accept `folder` kwarg.

- [ ] **Step 3: Update existing `test_notes_files_adapter.py` write tests**

The existing tests `test_write_creates_when_file_does_not_exist`, `test_write_updates_when_file_exists`, `test_write_raises_on_sha_conflict` are written against the old `GET-then-PUT` flow. They must be updated for the new tree-based flow.

Open `remote-gateway/tests/test_notes_files_adapter.py` and replace those three tests (find the `# ---- write ----` section) with:

```python
# ---- write ----

def _tree_resp(paths: list[str]) -> dict:
    """Build a fake git-trees API response with the given blob paths."""
    return {
        "sha": "tree-sha",
        "tree": [
            {"path": p, "type": "blob", "sha": f"blob-{p}", "size": 100}
            for p in paths
        ],
        "truncated": False,
    }


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
            _mock_resp(_tree_resp([])),  # empty tree
        ]
        client.put.return_value = _mock_resp(created_payload, status_code=201)

        result = GitHubFilesAdapter().write("new-note", "hello")

    assert result["status"] == "created"
    assert result["slug"] == "new-note"
    assert result["id"] == "new-sha"
    assert result["path"] == "notes/new-note.md"
    assert result["folder"] is None
    put_body = client.put.call_args[1]["json"]
    assert put_body["message"] == "notes: create new-note via gateway"
    assert base64.b64decode(put_body["content"]).decode() == "hello"
    assert put_body["branch"] == "main"
    assert "sha" not in put_body


def test_write_updates_when_file_exists():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    updated_payload = {
        "content": _file_payload("new", sha="updated-sha", path="notes/existing.md"),
        "commit": {"sha": "commit2"},
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/existing.md"])),
        ]
        client.put.return_value = _mock_resp(updated_payload)

        result = GitHubFilesAdapter().write("existing", "new")

    assert result["status"] == "updated"
    assert result["id"] == "updated-sha"
    put_body = client.put.call_args[1]["json"]
    assert put_body["sha"] == "blob-notes/existing.md"  # sha from tree
    assert put_body["message"] == "notes: update existing via gateway"


def test_write_raises_on_sha_conflict():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/conflict.md"])),
        ]
        client.put.return_value = _mock_resp(
            None, status_code=409, text="sha mismatch"
        )

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("conflict", "new")

    assert excinfo.value.status == 409
    assert "sha mismatch" in excinfo.value.body
```

- [ ] **Step 4: Rewrite `write` in the adapter**

Replace the existing `write` method in `github_files.py` with:

```python
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
```

- [ ] **Step 5: Run all write tests**

Run: `pytest remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py -xvs -k "write"`
Expected: PASS — all old write tests pass (now with tree-based flow) + 6 new folder-aware tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): write() takes folder; uses tree for cross-folder collision check"
```

---

## Task 6: `read` with folder hint

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`
- Test: `remote-gateway/tests/test_notes_files_adapter.py` (existing tests stay valid; we add `folder` field assertion)

- [ ] **Step 1: Write the failing tests for folder behavior**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- read with folder hint ----

def _file_payload(content: str, sha: str = "abc123", path: str = "notes/my-note.md") -> dict:
    return {
        "name": path.split("/")[-1],
        "path": path,
        "sha": sha,
        "content": base64.b64encode(content.encode()).decode(),
        "encoding": "base64",
        "html_url": f"https://github.com/org/test-notes/blob/main/{path}",
    }


def test_read_with_folder_hint_hits_path_directly():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_file_payload("hi", sha="s1", path="notes/marketing/foo.md")),
        ]

        result = GitHubFilesAdapter().read("foo", folder="marketing")

    assert result is not None
    assert result["content"] == "hi"
    assert result["folder"] == "marketing"
    assert result["path"] == "notes/marketing/foo.md"
    # Second GET (after init) went directly to nested path, no tree call
    second_url = client.get.call_args_list[1][0][0]
    assert second_url.endswith("/contents/notes/marketing/foo.md")


def test_read_with_folder_hint_returns_none_on_404_no_fallthrough():
    """Hint is authoritative — 404 returns None, does NOT search the tree."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().read("foo", folder="marketing")

    assert result is None
    # Only init + one read call, no tree call
    assert client.get.call_count == 2


def test_read_without_folder_uses_tree_to_locate():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/foo.md"])),
            _mock_resp(_file_payload("hi", sha="s1", path="notes/marketing/foo.md")),
        ]

        result = GitHubFilesAdapter().read("foo")

    assert result is not None
    assert result["folder"] == "marketing"
    assert result["content"] == "hi"
    # Third GET hit the resolved path
    third_url = client.get.call_args_list[2][0][0]
    assert third_url.endswith("/contents/notes/marketing/foo.md")


def test_read_without_folder_returns_none_when_tree_misses():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().read("ghost")

    assert result is None
    assert client.get.call_count == 2  # init + tree, no contents fetch


def test_read_validates_folder_name():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().read("foo", folder="../etc")

    assert excinfo.value.status == 400
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "read"`
Expected: FAIL — `read` doesn't accept `folder` kwarg.

- [ ] **Step 3: Update existing `read` tests in `test_notes_files_adapter.py`**

In `remote-gateway/tests/test_notes_files_adapter.py`, find `test_read_returns_content_when_file_exists` and the helper `_file_payload` etc. Update `test_read_returns_content_when_file_exists` to assert the new `folder` field:

```python
def test_read_returns_content_when_file_exists():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/my-note.md"])),
            _mock_resp(_file_payload("hello world", sha="sha-5", path="notes/my-note.md")),
        ]

        result = GitHubFilesAdapter().read("my-note")

    assert result is not None
    assert result["slug"] == "my-note"
    assert result["content"] == "hello world"
    assert result["id"] == "sha-5"
    assert result["path"] == "notes/my-note.md"
    assert result["folder"] is None
    assert "github.com/org/test-notes/blob/main/notes/my-note.md" in result["url"]
```

Update `test_read_returns_none_when_missing` to mock the tree call instead of the direct contents 404:

```python
def test_read_returns_none_when_missing():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),  # empty tree → not found
        ]

        result = GitHubFilesAdapter().read("ghost")

    assert result is None
```

- [ ] **Step 4: Rewrite `read` in the adapter**

Replace the existing `read` method in `github_files.py` with:

```python
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
```

- [ ] **Step 5: Run all read tests**

Run: `pytest remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py -xvs -k "read"`
Expected: PASS — 5 new folder-aware tests + 2 updated existing tests.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): read() takes optional folder hint; tree-resolves otherwise"
```

---

## Task 7: `delete` with folder hint

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`
- Test: `remote-gateway/tests/test_notes_files_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- delete with folder hint ----

def test_delete_with_folder_hint_deletes_at_nested_path():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    existing = _file_payload("bye", sha="del-sha", path="notes/marketing/comp.md")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(existing),
        ]
        client.request.return_value = _mock_resp({"commit": {"sha": "c1"}})

        result = GitHubFilesAdapter().delete("comp", folder="marketing")

    assert result["status"] == "deleted"
    assert result["path"] == "notes/marketing/comp.md"
    assert client.request.call_args[0][0] == "DELETE"
    assert client.request.call_args[1]["json"]["sha"] == "del-sha"


def test_delete_with_folder_hint_returns_not_found_on_404_no_fallthrough():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().delete("ghost", folder="marketing")

    assert result["status"] == "not_found"
    client.request.assert_not_called()


def test_delete_without_folder_uses_tree_to_locate():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/comp.md"])),
        ]
        client.request.return_value = _mock_resp({"commit": {"sha": "c1"}})

        result = GitHubFilesAdapter().delete("comp")

    assert result["status"] == "deleted"
    assert result["path"] == "notes/marketing/comp.md"
    # No content-API GET — tree gave us the sha
    assert client.get.call_count == 2  # init + tree only


def test_delete_without_folder_returns_not_found_when_tree_misses():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().delete("ghost")

    assert result["status"] == "not_found"
    client.request.assert_not_called()
```

- [ ] **Step 2: Update existing delete tests in `test_notes_files_adapter.py`**

In `test_notes_files_adapter.py`, replace `test_delete_removes_existing_file` and `test_delete_missing_returns_not_found` with versions that use tree-based lookup:

```python
def test_delete_removes_existing_file():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/to-delete.md"])),
        ]
        client.request.return_value = _mock_resp({"commit": {"sha": "c3"}})

        result = GitHubFilesAdapter().delete("to-delete")

    assert result["status"] == "deleted"
    assert result["slug"] == "to-delete"
    assert result["path"] == "notes/to-delete.md"
    assert client.request.call_args[0][0] == "DELETE"
    del_body = client.request.call_args[1]["json"]
    assert del_body["sha"] == "blob-notes/to-delete.md"
    assert del_body["message"] == "notes: delete to-delete via gateway"
    assert del_body["branch"] == "main"


def test_delete_missing_returns_not_found():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().delete("ghost")

    assert result["status"] == "not_found"
    assert result["slug"] == "ghost"
    client.request.assert_not_called()
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py -xvs -k "delete"`
Expected: FAIL — `delete` doesn't accept `folder` kwarg.

- [ ] **Step 4: Rewrite `delete` in the adapter**

Replace the existing `delete` method in `github_files.py` with:

```python
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
```

- [ ] **Step 5: Run all delete tests**

Run: `pytest remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py -xvs -k "delete"`
Expected: PASS — 4 new + 2 updated.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): delete() takes optional folder hint"
```

---

## Task 8: `list` rewrite with tree-based discovery and filters

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- Test: `remote-gateway/tests/test_notes_folders.py`
- Test: `remote-gateway/tests/test_notes_files_adapter.py` (existing list tests need updates)

This is the largest task. The existing `list()` uses the contents API and only sees top-level `notes/*.md`. The new `list()` uses the tree API (recursive) and applies server-side filters.

- [ ] **Step 1: Write the failing tests for filter behavior**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- list with filters ----

def _commit_resp(date: str, sha: str = "c1") -> dict:
    return {"sha": sha, "commit": {"committer": {"date": date}}}


def test_list_recursive_default_returns_all_md_under_notes():
    """No filters: returns every .md file recursively, including root and folders."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/manifesto.md",
                "notes/marketing/comp.md",
                "notes/sales/lead.md",
                "notes/issues",  # directory entry — ignored even though no .md
                "other/file.md",  # not under notes/ — ignored
                "notes/issues/foo/bar.md",  # too deep — ignored
            ])),
            # One per-file commits call (3 .md files)
            _mock_resp([_commit_resp("2026-05-20T00:00:00Z", sha="cm")]),
            _mock_resp([_commit_resp("2026-05-22T00:00:00Z", sha="cmkt")]),
            _mock_resp([_commit_resp("2026-05-18T00:00:00Z", sha="cs")]),
        ]

        result = GitHubFilesAdapter().list()

    assert len(result) == 3
    slugs = [n["slug"] for n in result]
    # Sorted by updated_at descending
    assert slugs == ["comp", "manifesto", "lead"]
    by_slug = {n["slug"]: n for n in result}
    assert by_slug["manifesto"]["folder"] is None
    assert by_slug["comp"]["folder"] == "marketing"
    assert by_slug["lead"]["folder"] == "sales"


def test_list_folder_filter_returns_only_that_folder():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/manifesto.md",
                "notes/marketing/comp-1.md",
                "notes/marketing/comp-2.md",
                "notes/sales/lead.md",
            ])),
            _mock_resp([_commit_resp("2026-05-22T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-21T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(folder="marketing")

    assert len(result) == 2
    assert all(n["folder"] == "marketing" for n in result)


def test_list_prefix_filter_returns_starts_with_slug():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/marketing/competitor-watch-2026-05-25.md",
                "notes/marketing/competitor-watch-2026-05-24.md",
                "notes/marketing/content-drafts-2026-05-25.md",
            ])),
            _mock_resp([_commit_resp("2026-05-25T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-24T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(prefix="competitor-watch-")

    assert len(result) == 2
    assert all(n["slug"].startswith("competitor-watch-") for n in result)


def test_list_since_until_filters_by_updated_at():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/a.md",  # old
                "notes/b.md",  # in window
                "notes/c.md",  # future
            ])),
            _mock_resp([_commit_resp("2026-05-01T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-15T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-06-01T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(
            since="2026-05-10T00:00:00Z",
            until="2026-05-20T00:00:00Z",
        )

    assert len(result) == 1
    assert result[0]["slug"] == "b"


def test_list_limit_caps_results():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/a.md", "notes/b.md", "notes/c.md"])),
            _mock_resp([_commit_resp("2026-05-01T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-02T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-03T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(limit=2)

    assert len(result) == 2


def test_list_limit_clamped_to_range():
    """limit=0 and limit>100 are clamped to [1, 100]."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    paths = [f"notes/n{i}.md" for i in range(5)]
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(paths)),
            *[_mock_resp([_commit_resp(f"2026-05-0{i+1}T00:00:00Z")]) for i in range(5)],
        ]

        result = GitHubFilesAdapter().list(limit=0)  # clamped up to 1

    assert len(result) == 1


def test_list_combines_filters():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/marketing/competitor-watch-2026-05-25.md",
                "notes/marketing/competitor-watch-2026-05-20.md",  # too old
                "notes/marketing/content-drafts-2026-05-25.md",    # wrong prefix
                "notes/sales/competitor-watch-2026-05-25.md",      # wrong folder
            ])),
            _mock_resp([_commit_resp("2026-05-25T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(
            folder="marketing",
            prefix="competitor-watch-",
            since="2026-05-24T00:00:00Z",
        )

    assert len(result) == 1
    assert result[0]["slug"] == "competitor-watch-2026-05-25"


def test_list_empty_when_no_matches():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().list(folder="marketing")

    assert result == []


def test_list_invalid_since_raises_400():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().list(since="not-a-date")

    assert excinfo.value.status == 400
    assert "invalid date" in excinfo.value.body


def test_list_orphans_sort_last():
    """Files with no commit history get empty timestamps and sort after dated ones."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/dated.md", "notes/orphan.md"])),
            _mock_resp([_commit_resp("2026-05-25T00:00:00Z")]),
            _mock_resp([]),  # no commits for orphan
        ]

        result = GitHubFilesAdapter().list()

    assert [n["slug"] for n in result] == ["dated", "orphan"]
    assert result[1]["updated_at"] == ""
```

- [ ] **Step 2: Update existing list tests in `test_notes_files_adapter.py`**

The existing `test_list_returns_md_files_with_per_file_timestamps` and `test_list_emits_empty_timestamps_when_file_has_no_commits` use the old contents-API flow. Replace them with versions that mock the tree call:

```python
def test_list_returns_md_files_with_per_file_timestamps():
    """list() uses the tree API and per-file commit calls for timestamps."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    manifesto_commits = [
        {"sha": "m2", "commit": {"committer": {"date": "2026-05-20T00:00:00Z"}}},
        {"sha": "m1", "commit": {"committer": {"date": "2026-05-10T00:00:00Z"}}},
    ]
    draft_commits = [
        {"sha": "d1", "commit": {"committer": {"date": "2026-05-15T00:00:00Z"}}},
    ]
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/manifesto.md", "notes/draft.md"])),
            _mock_resp(manifesto_commits),
            _mock_resp(draft_commits),
        ]

        result = GitHubFilesAdapter().list()

    assert len(result) == 2
    by_slug = {n["slug"]: n for n in result}
    assert by_slug["manifesto"]["folder"] is None
    assert by_slug["manifesto"]["created_at"] == "2026-05-10T00:00:00Z"
    assert by_slug["manifesto"]["updated_at"] == "2026-05-20T00:00:00Z"
    assert by_slug["draft"]["created_at"] == "2026-05-15T00:00:00Z"
    assert by_slug["draft"]["updated_at"] == "2026-05-15T00:00:00Z"


def test_list_emits_empty_timestamps_when_file_has_no_commits():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/orphan.md"])),
            _mock_resp([]),
        ]

        result = GitHubFilesAdapter().list()

    assert len(result) == 1
    assert result[0]["slug"] == "orphan"
    assert result[0]["created_at"] == ""
    assert result[0]["updated_at"] == ""
```

The 500-error test in `test_notes_files_adapter.py::test_list_raises_on_500_from_contents` needs updating too — the contents call is gone. Rename to `test_list_raises_on_500_from_tree` and rewrite:

```python
def test_list_raises_on_500_from_tree():
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
    assert "upstream boom" in excinfo.value.body
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py -xvs -k "list"`
Expected: FAIL — `list()` doesn't accept new filter kwargs.

- [ ] **Step 4: Rewrite `list` in the adapter**

Replace the existing `list` method in `github_files.py` with:

```python
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
```

Add the `datetime` import at the top of `github_files.py` alongside other imports:

```python
from datetime import datetime
```

Then add two module-level helpers (above `_validate_folder`):

```python
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
```

- [ ] **Step 5: Run all list tests**

Run: `pytest remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py -xvs -k "list"`
Expected: PASS — all new filter tests + updated existing tests.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/integrations/notes/adapters/github_files.py remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_notes_files_adapter.py
git commit -m "feat(notes): list() tree-based + server-side filters (folder, prefix, since, until, limit)"
```

---

## Task 9: Tool layer — `write_note(folder=...)`

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/tools.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

The tool layer is a thin delegator. Need to add `folder` to the signature, pass it through, and surface `folder` in the response.

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- tool-layer: write_note ----

def test_write_note_tool_passes_folder_through():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.write.return_value = {
        "slug": "comp",
        "id": "sha",
        "url": "https://example/blob/main/notes/marketing/comp.md",
        "path": "notes/marketing/comp.md",
        "folder": "marketing",
        "status": "created",
    }
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        result = notes_tools.write_note("comp", "content", folder="marketing")

    fake_adapter.write.assert_called_once_with("comp", "content", folder="marketing")
    assert result["status"] == "created"
    assert result["slug"] == "comp"
    assert result["folder"] == "marketing"
    assert result["html_url"].endswith("notes/marketing/comp.md")


def test_write_note_tool_omits_folder_when_none():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.write.return_value = {
        "slug": "x", "id": "s", "url": "u", "path": "notes/x.md",
        "folder": None, "status": "created",
    }
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        result = notes_tools.write_note("x", "c")

    fake_adapter.write.assert_called_once_with("x", "c", folder=None)
    assert result["folder"] is None
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "write_note_tool"`
Expected: FAIL.

- [ ] **Step 3: Update `tools.py`**

Open `remote-gateway/tools/integrations/notes/tools.py`. Replace `write_note` with:

```python
def write_note(slug: str, content: str, folder: str | None = None) -> dict:
    """Create or update a note in the configured notes backend.

    If a note with this slug already exists in the same folder, its content is
    updated in place. If the slug already exists in a DIFFERENT folder, this
    raises an error — slugs are globally unique across all folders.

    Args:
        slug: Short identifier for the note (becomes the filename: notes/<folder>/<slug>.md).
        content: Full markdown content of the note.
        folder: Optional folder under notes/ (e.g. "marketing", "sales", "executive",
            "architecture", "shadow", "jaron"). Folders are dynamic — pass any
            lowercase a-z/0-9/-/_ string; new folders materialize on first write.
            If omitted, writes to notes/<slug>.md (root, backwards-compatible).

    Returns:
        Dict with 'status' (created/updated), 'slug', 'folder', 'issue_number'
        (always None on the file-based adapter), 'html_url'.
    """
    result = get_adapter().write(slug, content, folder=folder)
    return {
        "status": result["status"],
        "slug": result["slug"],
        "folder": result.get("folder"),
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "write_note_tool"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/tools.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): write_note tool accepts folder kwarg"
```

---

## Task 10: Tool layer — `read_note(folder=...)` and `delete_note(folder=...)`

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/tools.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- tool-layer: read_note + delete_note ----

def test_read_note_tool_passes_folder_through():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.read.return_value = {
        "slug": "comp", "content": "hi", "id": "s",
        "url": "https://example/blob/main/notes/marketing/comp.md",
        "path": "notes/marketing/comp.md", "folder": "marketing",
    }
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        result = notes_tools.read_note("comp", folder="marketing")

    fake_adapter.read.assert_called_once_with("comp", folder="marketing")
    assert result["content"] == "hi"
    assert result["folder"] == "marketing"
    assert result["html_url"].endswith("notes/marketing/comp.md")


def test_read_note_tool_missing_returns_not_found():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.read.return_value = None
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        result = notes_tools.read_note("ghost", folder="marketing")

    assert result["status"] == "not_found"
    assert result["slug"] == "ghost"


def test_delete_note_tool_passes_folder_through():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.delete.return_value = {
        "status": "deleted", "slug": "comp", "path": "notes/marketing/comp.md",
    }
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        result = notes_tools.delete_note("comp", folder="marketing")

    fake_adapter.delete.assert_called_once_with("comp", folder="marketing")
    assert result["status"] == "deleted"
    assert result["slug"] == "comp"
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "read_note_tool or delete_note_tool"`
Expected: FAIL.

- [ ] **Step 3: Update `tools.py`**

Replace `read_note` and `delete_note` in `remote-gateway/tools/integrations/notes/tools.py`:

```python
def read_note(slug: str, folder: str | None = None) -> dict:
    """Read a note by its slug.

    With folder hint: reads notes/<folder>/<slug>.md directly. The hint is
    authoritative — if no file exists at that exact path, returns not_found
    (does not search other folders).

    Without folder: searches all folders for the slug (slugs are globally
    unique). Returns the file if found, otherwise not_found.

    Args:
        slug: The note slug used when the note was written.
        folder: Optional folder hint to skip the tree lookup.

    Returns:
        Dict with 'slug', 'content', 'folder', 'issue_number', 'html_url' on
        success. Dict with status='not_found' if no note matches.
    """
    result = get_adapter().read(slug, folder=folder)
    if result is None:
        return {"status": "not_found", "slug": slug}
    return {
        "slug": result["slug"],
        "content": result["content"],
        "folder": result.get("folder"),
        "issue_number": result.get("issue_number"),
        "html_url": result["url"],
    }


def delete_note(slug: str, folder: str | None = None) -> dict:
    """Delete a note by its slug.

    With folder hint: deletes notes/<folder>/<slug>.md directly. Hint is
    authoritative — does not fall back to a tree search on miss.

    Without folder: searches all folders for the slug, deletes if found.

    Args:
        slug: The note slug used when the note was written.
        folder: Optional folder hint.

    Returns:
        Dict with status='deleted' on success or status='not_found'.
    """
    result = get_adapter().delete(slug, folder=folder)
    return {
        "status": result["status"],
        "slug": result["slug"],
        "issue_number": result.get("issue_number"),
    }
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "read_note_tool or delete_note_tool"`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/tools.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): read_note + delete_note tools accept folder kwarg"
```

---

## Task 11: Tool layer — `list_notes` with filter params

**Files:**
- Modify: `remote-gateway/tools/integrations/notes/tools.py`
- Test: `remote-gateway/tests/test_notes_folders.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_notes_folders.py`:

```python
# ---- tool-layer: list_notes ----

def test_list_notes_tool_passes_filters_through():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.list.return_value = [
        {
            "slug": "comp", "id": "s", "url": "u",
            "path": "notes/marketing/comp.md", "folder": "marketing",
            "created_at": "2026-05-20T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
        }
    ]
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        result = notes_tools.list_notes(
            folder="marketing",
            prefix="comp",
            since="2026-05-20T00:00:00Z",
            until="2026-05-26T00:00:00Z",
            limit=10,
        )

    fake_adapter.list.assert_called_once_with(
        folder="marketing", prefix="comp",
        since="2026-05-20T00:00:00Z", until="2026-05-26T00:00:00Z",
        limit=10,
    )
    assert result["count"] == 1
    assert result["notes"][0]["folder"] == "marketing"
    assert result["notes"][0]["html_url"] == "u"


def test_list_notes_tool_no_args_passes_all_none():
    from tools.integrations.notes import tools as notes_tools

    fake_adapter = MagicMock()
    fake_adapter.list.return_value = []
    with patch("tools.integrations.notes.tools.get_adapter", return_value=fake_adapter):
        notes_tools.list_notes()

    fake_adapter.list.assert_called_once_with(
        folder=None, prefix=None, since=None, until=None, limit=None,
    )
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "list_notes_tool"`
Expected: FAIL.

- [ ] **Step 3: Update `list_notes` in `tools.py`**

Replace the existing `list_notes` function with:

```python
def list_notes(
    folder: str | None = None,
    prefix: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> dict:
    """List notes stored in the configured notes backend, with optional filters.

    All filters are server-side — combine them to drop your token cost. Results
    are sorted by updated_at descending.

    Args:
        folder: Filter to a specific folder (e.g. "marketing", "sales",
            "executive", "architecture", "shadow", "jaron"). Folders are dynamic
            and case-sensitive lowercase a-z/0-9/-/_; new folders materialize
            on first write_note(folder=X) call.
        prefix: Case-sensitive slug starts-with filter (e.g. "competitor-watch-").
        since: ISO-8601 timestamp. Return only notes updated at or after this
            time (e.g. "2026-05-24T00:00:00Z").
        until: ISO-8601 timestamp. Return only notes updated at or before this
            time.
        limit: Cap the number of results returned (clamped to [1, 100]).

    Returns:
        Dict with 'notes' list and 'count'. Each note has slug, folder
        (None for root-level notes), created_at, updated_at, issue_number
        (always None on the file-based adapter), html_url.
    """
    notes = get_adapter().list(
        folder=folder, prefix=prefix, since=since, until=until, limit=limit,
    )
    rendered = [
        {
            "slug": n["slug"],
            "folder": n.get("folder"),
            "issue_number": n.get("issue_number"),
            "created_at": n["created_at"],
            "updated_at": n["updated_at"],
            "html_url": n["url"],
        }
        for n in notes
    ]
    return {"notes": rendered, "count": len(rendered)}
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_notes_folders.py -xvs -k "list_notes_tool"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/integrations/notes/tools.py remote-gateway/tests/test_notes_folders.py
git commit -m "feat(notes): list_notes tool accepts folder/prefix/since/until/limit filters"
```

---

## Task 12: Migration script

**Files:**
- Create: `scripts/migrate_notes_to_folders.py`
- Create: `remote-gateway/tests/test_migrate_notes_to_folders.py`

The migration script reads slugs matching the prefix rules, copies them to the new folder location, then deletes the originals. Idempotent: skip if target exists with matching content; warn if different content.

- [ ] **Step 1: Write the failing smoke tests**

Create `remote-gateway/tests/test_migrate_notes_to_folders.py`:

```python
"""Smoke tests for the one-shot folder migration script."""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _load_script():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "scripts" / "migrate_notes_to_folders.py"
    spec = importlib.util.spec_from_file_location("migrate_notes_to_folders", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def notes_env(monkeypatch):
    monkeypatch.setenv("NOTES_REPO", "org/test-notes")
    monkeypatch.setenv("NOTES_GITHUB_TOKEN", "ghp_test")


def _mock_resp(json_data=None, status_code=200, text=""):
    m = MagicMock(spec=httpx.Response)
    m.status_code = status_code
    m.text = text
    m.json = MagicMock(return_value=json_data)
    if status_code >= 400:
        request = httpx.Request("GET", "https://api.github.com/test")
        m.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(f"{status_code}", request=request, response=m)
        )
    else:
        m.raise_for_status = MagicMock()
    return m


def _mock_client_ctx(mock_cls):
    mock_client = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


def _root_file(slug: str, content: str = "x") -> dict:
    return {
        "name": f"{slug}.md",
        "path": f"notes/{slug}.md",
        "sha": f"sha-{slug}",
        "content": base64.b64encode(content.encode()).decode(),
        "encoding": "base64",
        "html_url": f"https://github.com/org/test-notes/blob/main/notes/{slug}.md",
    }


def test_target_folder_for_known_prefixes():
    script = _load_script()
    assert script.target_folder("competitor-watch-2026-05-25") == "marketing"
    assert script.target_folder("content-drafts-2026-05-24") == "marketing"
    assert script.target_folder("marketing-research-2026-05-25") == "marketing"
    assert script.target_folder("marketing-weekly-2026-05-25") == "marketing"
    assert script.target_folder("signal-scout-2026-05-25") == "sales"
    assert script.target_folder("lead-research-2026-05-25") == "sales"
    assert script.target_folder("sales-weekly-2026-05-25") == "sales"
    assert script.target_folder("sales-strategy-v1") == "sales"
    assert script.target_folder("shadow-2026-05-25-content-drafts") == "shadow"
    assert script.target_folder("manifesto") is None  # stays at root
    assert script.target_folder("execution-path-v1") is None
    assert script.target_folder("conference-contact") is None


def test_migrates_matching_slug():
    script = _load_script()
    contents_path = "notes/competitor-watch-2026-05-25.md"
    target_path = "notes/marketing/competitor-watch-2026-05-25.md"

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        # List root contents -> one matching file (and ignore subdirs)
        client.get.side_effect = [
            _mock_resp([{
                "name": "competitor-watch-2026-05-25.md",
                "path": contents_path, "type": "file",
                "sha": "src-sha",
            }]),
            _mock_resp(_root_file("competitor-watch-2026-05-25", "the body")),  # source content
            _mock_resp(None, status_code=404, text="not found"),  # target does not exist
        ]
        client.put.return_value = _mock_resp({
            "content": {"sha": "dst-sha", "path": target_path,
                        "html_url": f"https://github.com/org/test-notes/blob/main/{target_path}"},
            "commit": {"sha": "abc"},
        }, status_code=201)
        client.request.return_value = _mock_resp({"commit": {"sha": "def"}})

        summary = script.run()

    assert summary["migrated"] == 1
    assert summary["skipped"] == 0
    assert summary["errors"] == 0
    # PUT body
    put_body = client.put.call_args[1]["json"]
    assert "move competitor-watch-2026-05-25 to marketing" in put_body["message"]
    assert base64.b64decode(put_body["content"]).decode() == "the body"
    # DELETE used src-sha
    del_body = client.request.call_args[1]["json"]
    assert del_body["sha"] == "src-sha"


def test_skips_when_target_exists_with_same_content():
    script = _load_script()
    body = "same"
    target_existing = {
        "content": base64.b64encode(body.encode()).decode(),
        "sha": "tgt-sha",
        "path": "notes/marketing/competitor-watch-2026-05-25.md",
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp([{
                "name": "competitor-watch-2026-05-25.md",
                "path": "notes/competitor-watch-2026-05-25.md",
                "type": "file", "sha": "src-sha",
            }]),
            _mock_resp(_root_file("competitor-watch-2026-05-25", body)),
            _mock_resp(target_existing),  # target exists with same content
        ]

        summary = script.run()

    assert summary["migrated"] == 0
    assert summary["skipped"] == 1
    client.put.assert_not_called()
    client.request.assert_not_called()


def test_warns_and_skips_on_content_divergence():
    script = _load_script()
    target_existing = {
        "content": base64.b64encode(b"different").decode(),
        "sha": "tgt-sha",
        "path": "notes/marketing/competitor-watch-2026-05-25.md",
    }
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp([{
                "name": "competitor-watch-2026-05-25.md",
                "path": "notes/competitor-watch-2026-05-25.md",
                "type": "file", "sha": "src-sha",
            }]),
            _mock_resp(_root_file("competitor-watch-2026-05-25", "source")),
            _mock_resp(target_existing),
        ]

        summary = script.run()

    assert summary["migrated"] == 0
    assert summary["skipped"] == 1
    assert summary["warnings"] == 1
    client.put.assert_not_called()


def test_root_only_slug_not_touched():
    script = _load_script()
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp([{
                "name": "manifesto.md", "path": "notes/manifesto.md",
                "type": "file", "sha": "x",
            }]),
        ]

        summary = script.run()

    assert summary["migrated"] == 0
    assert summary["skipped"] == 1  # counted as skipped (no prefix match)
    client.put.assert_not_called()
    client.request.assert_not_called()
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest remote-gateway/tests/test_migrate_notes_to_folders.py -xvs`
Expected: FAIL — script doesn't exist.

- [ ] **Step 3: Create the migration script**

Create `scripts/migrate_notes_to_folders.py`:

```python
"""One-shot migration: move root-level notes/*.md into folder by prefix rule.

Prefix → folder:
  competitor-watch-*, content-drafts-*, marketing-research-*, marketing-weekly-* → marketing/
  signal-scout-*, lead-research-*, sales-weekly-*, sales-strategy-*              → sales/
  shadow-*                                                                       → shadow/
  (everything else)                                                              → stays at root

For each match:
  1. GET source file from notes/{slug}.md.
  2. Check if target exists; if same content, skip; if different, warn + skip.
  3. PUT target file at notes/{folder}/{slug}.md.
  4. DELETE source file.

Idempotent. Delete this script after Inform-Growth's deployment has run it once.

Required env vars:
    NOTES_REPO          — owner/repo (e.g. "Inform-Growth/inform-notes")
    NOTES_GITHUB_TOKEN  — fine-grained PAT with Contents: read+write on NOTES_REPO.
"""
from __future__ import annotations

import base64
import os
import sys

import httpx


_PREFIX_RULES: list[tuple[str, str]] = [
    ("competitor-watch-", "marketing"),
    ("content-drafts-", "marketing"),
    ("marketing-research-", "marketing"),
    ("marketing-weekly-", "marketing"),
    ("signal-scout-", "sales"),
    ("lead-research-", "sales"),
    ("sales-weekly-", "sales"),
    ("sales-strategy-", "sales"),
    ("shadow-", "shadow"),
]


def target_folder(slug: str) -> str | None:
    """Return the folder this slug should live in, or None if it stays at root."""
    for prefix, folder in _PREFIX_RULES:
        if slug.startswith(prefix):
            return folder
    return None


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _list_root_md(client: httpx.Client, repo: str, token: str) -> list[dict]:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/contents/notes",
        headers=_headers(token),
    )
    resp.raise_for_status()
    return [
        e for e in resp.json()
        if e.get("type") == "file" and e["name"].endswith(".md")
    ]


def _get_file(client: httpx.Client, repo: str, token: str, path: str) -> dict | None:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _put_file(
    client: httpx.Client, repo: str, token: str,
    path: str, content: str, slug: str, folder: str,
) -> dict:
    resp = client.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json={
            "message": f"notes: move {slug} to {folder}/",
            "content": base64.b64encode(content.encode()).decode(),
        },
    )
    resp.raise_for_status()
    return resp.json()


def _delete_file(client: httpx.Client, repo: str, token: str, path: str, sha: str) -> None:
    resp = client.request(
        "DELETE",
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json={"message": f"notes: remove {path} after move", "sha": sha},
    )
    resp.raise_for_status()


def run() -> dict:
    repo = os.environ.get("NOTES_REPO", "")
    token = os.environ.get("NOTES_GITHUB_TOKEN", "")
    if not repo or not token:
        raise RuntimeError("NOTES_REPO and NOTES_GITHUB_TOKEN must be set.")

    summary = {"migrated": 0, "skipped": 0, "warnings": 0, "errors": 0}
    with httpx.Client(timeout=30) as client:
        root_files = _list_root_md(client, repo, token)
        for entry in root_files:
            slug = entry["name"][: -len(".md")]
            folder = target_folder(slug)
            if folder is None:
                print(f"skip (no rule match): {slug}")
                summary["skipped"] += 1
                continue

            target_path = f"notes/{folder}/{slug}.md"
            source_path = entry["path"]
            try:
                source = _get_file(client, repo, token, source_path)
                if source is None:
                    print(f"ERROR source disappeared: {source_path}", file=sys.stderr)
                    summary["errors"] += 1
                    continue
                body = base64.b64decode(source["content"]).decode()

                existing = _get_file(client, repo, token, target_path)
                if existing is not None:
                    existing_body = base64.b64decode(existing["content"]).decode()
                    if existing_body == body:
                        print(f"skip (already migrated): {slug} → {folder}/")
                    else:
                        print(
                            f"WARNING skip (target diverges): {slug} → {folder}/",
                            file=sys.stderr,
                        )
                        summary["warnings"] += 1
                    summary["skipped"] += 1
                    continue

                _put_file(client, repo, token, target_path, body, slug, folder)
                _delete_file(client, repo, token, source_path, source["sha"])
                print(f"migrated: {slug} → {folder}/")
                summary["migrated"] += 1
            except Exception as e:  # noqa: BLE001 — surface and continue
                print(f"ERROR migrating {slug}: {e}", file=sys.stderr)
                summary["errors"] += 1
    return summary


if __name__ == "__main__":
    result = run()
    print(f"\nSummary: {result}")
    sys.exit(1 if result["errors"] else 0)
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest remote-gateway/tests/test_migrate_notes_to_folders.py -xvs`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_notes_to_folders.py remote-gateway/tests/test_migrate_notes_to_folders.py
git commit -m "feat(notes): one-shot migration script for root → folder layout"
```

---

## Task 13: Documentation

**Files:**
- Modify: `remote-gateway/CLAUDE.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `remote-gateway/CLAUDE.md`**

Open `remote-gateway/CLAUDE.md`. Find the section "Admin Guardrails" and the "Notes & Issue Backlog" bullet (around line 105). Add a new subsection right after the existing "Notes & Issue Backlog" line:

Insert before `### Admin role`:

```markdown
### Notes folder convention

The notes plane (`NOTES_REPO/notes/`) supports a flat-or-folder layout. The adapter accepts any folder name matching `^[a-z0-9_-]+$`; folders are dynamic and materialize on first write.

Conventional folders (start with these; add more as agents and departments grow):

- `marketing/` — competitor-watch, content-drafts, marketing-research, marketing-weekly
- `sales/` — signal-scout, lead-research, sales-weekly, sales-strategy
- `executive/` — chief-of-staff briefs
- `architecture/` — strategy and architecture docs (manifesto, execution-path, gateway-template-plan)
- `shadow/` — gateway shadow notes
- `jaron/` — Jaron's working notes

`list_notes` takes optional server-side filters: `folder=`, `prefix=`, `since=`, `until=`, `limit=`. Use these to drop token cost on routine reads (e.g. chief_of_staff's "what changed in the last 24h" query becomes `list_notes(folder="executive", since="<yesterday>")`).

Slugs are globally unique across folders. `write_note(slug, content, folder=X)` raises `NotesAdapterError(409)` if the slug already exists in a different folder.
```

- [ ] **Step 2: Update root `CLAUDE.md`**

Open `CLAUDE.md`. Find the Tool Inventory section (around line 166) and the `write_note / read_note / list_notes / delete_note` row. Replace it with:

```markdown
| `write_note` / `read_note` / `list_notes` / `delete_note` | Notes stored via the adapter configured by `NOTES_ADAPTER` (default: `github-files`, backed by `notes/<folder>/<slug>.md` in `NOTES_REPO`). `write_note(slug, content, folder=)` supports dynamic folders. `list_notes(folder=, prefix=, since=, until=, limit=)` supports server-side filters. |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md
git commit -m "docs(notes): document folder convention and list_notes filter params"
```

---

## Task 14: Full pytest + ruff

- [ ] **Step 1: Run the full notes-related test suite**

Run: `pytest remote-gateway/tests/test_notes_adapter.py remote-gateway/tests/test_notes_files_adapter.py remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_migrate_notes_to_folders.py -xvs`
Expected: PASS (counts: 6 + ~22 + ~40 + 5 = ~73 tests).

- [ ] **Step 2: Run the full suite**

Run: `pytest --ignore=remote-gateway/tests/test_attio_tools.py`
Expected: notes tests pass. Apollo/wiza/tool_name_length pre-existing failures remain — confirm count matches the base SHA (`9427d77`) — should be ~49 failures, none of them in notes modules.

- [ ] **Step 3: Run lint on touched files**

Run: `ruff check remote-gateway/tools/integrations/notes/ remote-gateway/tests/test_notes_folders.py remote-gateway/tests/test_migrate_notes_to_folders.py scripts/migrate_notes_to_folders.py`
Expected: clean (no new violations).

- [ ] **Step 4: If anything fails, fix it in a new commit**

Use `fix(notes): …` prefix.

---

## Deployment Notes (out of scope for this plan, but surface to the user)

After this plan merges:

1. **Run the migration script** against the live `Inform-Growth/inform-notes`:
   ```bash
   NOTES_REPO=Inform-Growth/inform-notes \
   NOTES_GITHUB_TOKEN=<existing PAT, already has Contents:read+write> \
   python scripts/migrate_notes_to_folders.py
   ```
   Expect ~12 files moved (the prefix-matching slugs).

2. Verify on `https://github.com/Inform-Growth/inform-notes/tree/main/notes`:
   - `marketing/`, `sales/`, `shadow/` folders exist
   - root still contains the ~26 ambiguous notes (manifesto, execution-path-*, etc.)

3. Railway auto-deploys on merge. Smoke test on the live gateway:
   - `list_notes(folder="marketing", since="2026-05-24T00:00:00Z")` → ~6 marketing notes
   - `list_notes()` → all ~38 notes with `folder` populated

4. Update agent role prompts (separate PR / configuration change) to pass `folder=` on `write_note`. Existing agent code keeps working until updated — folder is optional and defaults to root.

5. Delete the migration script in a small follow-up PR (one-shot, no longer needed).
