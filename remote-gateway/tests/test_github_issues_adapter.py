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
