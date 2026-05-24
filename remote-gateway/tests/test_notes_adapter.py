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
