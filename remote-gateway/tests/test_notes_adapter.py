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
