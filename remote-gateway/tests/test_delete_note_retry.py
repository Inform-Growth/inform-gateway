"""
Unit tests for GitHub Issues-backed notes tools (write_note, read_note,
list_notes, delete_note).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def deployment_env(monkeypatch):
    monkeypatch.setenv("ISSUE_DEPLOYMENT_REPO", "org/test-gateway")
    monkeypatch.setenv("ISSUE_DEPLOYMENT_GITHUB_TOKEN", "ghp_test")


def _issue(number: int = 1, title: str = "my-note", body: str = "content") -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "html_url": f"https://github.com/org/test-gateway/issues/{number}",
        "labels": [{"name": "type:note"}],
    }


def _mock_resp(json_data, status_code: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock()
    return m


# ---- list_notes ----

def test_list_notes_returns_open_notes():
    from tools.notes import list_notes

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([_issue(1, "session-2026-05-19"), _issue(2, "onboarding")])

        result = list_notes()

    assert result["count"] == 2
    assert result["notes"][0]["slug"] == "session-2026-05-19"
    assert result["notes"][1]["slug"] == "onboarding"


def test_list_notes_empty():
    from tools.notes import list_notes

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([])

        result = list_notes()

    assert result["count"] == 0
    assert result["notes"] == []


# ---- read_note ----

def test_read_note_found():
    from tools.notes import read_note

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([_issue(5, "my-note", "hello world")])

        result = read_note("my-note")

    assert result["slug"] == "my-note"
    assert result["content"] == "hello world"
    assert result["issue_number"] == 5


def test_read_note_not_found():
    from tools.notes import read_note

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([])

        result = read_note("missing-note")

    assert result["status"] == "not_found"
    assert result["slug"] == "missing-note"


# ---- write_note ----

def test_write_note_creates_new_issue_when_not_found():
    from tools.notes import write_note

    created = _issue(10, "new-note", "new content")

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([])  # _find_note returns nothing
        mock_client.post.return_value = _mock_resp(created, status_code=201)

        result = write_note("new-note", "new content")

    assert result["status"] == "created"
    assert result["issue_number"] == 10
    # _ensure_label posts to /labels, then write_note posts to /issues — 2 total
    assert mock_client.post.call_count == 2
    issue_create_call = mock_client.post.call_args_list[1]
    assert issue_create_call[0][0].endswith("/issues")


def test_write_note_updates_existing_issue():
    from tools.notes import write_note

    existing = _issue(7, "existing-note", "old content")
    updated = _issue(7, "existing-note", "new content")

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([existing])
        mock_client.patch.return_value = _mock_resp(updated)

        result = write_note("existing-note", "new content")

    assert result["status"] == "updated"
    assert result["issue_number"] == 7
    mock_client.patch.assert_called_once()
    # _ensure_label posts to /labels; no issue-creation post
    assert mock_client.post.call_count == 1
    assert mock_client.post.call_args[0][0].endswith("/labels")


# ---- delete_note ----

def test_delete_note_closes_issue():
    from tools.notes import delete_note

    issue = _issue(3, "to-delete")

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([issue])
        mock_client.patch.return_value = _mock_resp({**issue, "state": "closed"})

        result = delete_note("to-delete")

    assert result["status"] == "deleted"
    assert result["issue_number"] == 3
    call_json = mock_client.patch.call_args[1]["json"]
    assert call_json["state"] == "closed"


def test_delete_note_not_found():
    from tools.notes import delete_note

    with patch("httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_resp([])

        result = delete_note("ghost-note")

    assert result["status"] == "not_found"
    assert result["slug"] == "ghost-note"
    mock_client.patch.assert_not_called()
