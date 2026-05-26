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


def _dir_entry(name: str, type_: str = "file", sha: str = "x", path: str | None = None) -> dict:
    p = path or f"notes/{name}"
    return {
        "name": name,
        "path": p,
        "sha": sha,
        "type": type_,
        "html_url": f"https://github.com/org/test-notes/blob/main/{p}",
    }


# ---- list ----

def test_list_returns_md_files_with_per_file_timestamps():
    """list() makes a per-file GET /commits call to populate timestamps."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    files = [
        _dir_entry("manifesto.md", sha="s1"),
        _dir_entry("draft.md", sha="s2"),
        _dir_entry("issues", type_="dir"),         # ignored
        _dir_entry("notes-not-md.txt", sha="sX"),  # ignored
    ]
    # GitHub returns commits newest-first per file.
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
            _mock_resp(files),
            _mock_resp(manifesto_commits),
            _mock_resp(draft_commits),
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

    # Verify the per-file commits calls used the right path query param
    commits_call_urls_and_params = [
        (call.args[0], call.kwargs.get("params"))
        for call in client.get.call_args_list[2:]  # skip repo_meta + contents
    ]
    paths_queried = [params["path"] for _, params in commits_call_urls_and_params]
    assert sorted(paths_queried) == ["notes/draft.md", "notes/manifesto.md"]


def test_list_emits_empty_timestamps_when_file_has_no_commits():
    """A file with no commits returned (e.g. orphaned) gets empty timestamps, not a crash."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    files = [_dir_entry("orphan.md", sha="orph")]
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(files),
            _mock_resp([]),  # empty commits response
        ]

        result = GitHubFilesAdapter().list()

    assert len(result) == 1
    assert result[0]["slug"] == "orphan"
    assert result[0]["created_at"] == ""
    assert result[0]["updated_at"] == ""


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


# ---- timeout hardening ----

def test_httpx_client_is_constructed_with_explicit_timeout():
    """Pin the explicit timeout — httpx's 5s default got bit during smoke test."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter

    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        GitHubFilesAdapter()

    # Every httpx.Client() invocation must pass a non-default timeout.
    for call in mock_cls.call_args_list:
        assert "timeout" in call.kwargs, f"Client() called without timeout: {call}"
        assert call.kwargs["timeout"] >= 10, f"timeout too aggressive: {call.kwargs['timeout']}"


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
