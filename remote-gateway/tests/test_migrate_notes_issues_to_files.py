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
