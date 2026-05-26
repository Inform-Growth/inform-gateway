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
