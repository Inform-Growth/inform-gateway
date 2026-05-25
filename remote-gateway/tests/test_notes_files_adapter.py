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
