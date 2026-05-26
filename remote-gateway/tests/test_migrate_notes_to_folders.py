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
