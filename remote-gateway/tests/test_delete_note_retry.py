"""
Unit tests for delete_note SHA conflict retry (Fix 4).

The GitHub Contents API returns 409/422 when the SHA used in a DELETE
is stale (another write happened between the GET and DELETE). delete_note
must re-fetch the SHA and retry once.

Run with:
    pytest remote-gateway/tests/test_delete_note_retry.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.notes import delete_note


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx response with raise_for_status as a no-op by default."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock()
    return m


def _mock_client(get_responses=None, request_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if get_responses is not None:
        mock.get.side_effect = get_responses
    if request_responses is not None:
        mock.request.side_effect = request_responses
    return mock


def test_delete_note_retries_on_409(monkeypatch):
    """409 conflict triggers a re-fetch of the SHA and a second DELETE attempt."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-stale", "name": "_test.md"})
    second_get = _mock_response({"sha": "sha-fresh", "name": "_test.md"})

    conflict_resp = _mock_response({}, status_code=409)
    success_resp = _mock_response({
        "commit": {"sha": "commit-abc", "html_url": "https://github.com/org/repo/commit/abc"}
    })

    mock_client = _mock_client(
        get_responses=[first_get, second_get],
        request_responses=[conflict_resp, success_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "deleted"
    assert mock_client.request.call_count == 2, "Expected exactly 2 DELETE attempts"

    # Second DELETE must use the freshly fetched SHA
    second_call_body = mock_client.request.call_args_list[1].kwargs["json"]
    assert second_call_body["sha"] == "sha-fresh", (
        f"Expected sha-fresh in second DELETE, got: {second_call_body['sha']}"
    )


def test_delete_note_retries_on_422(monkeypatch):
    """422 conflict also triggers retry (GitHub uses both 409 and 422 for SHA mismatch)."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-old", "name": "_test.md"})
    second_get = _mock_response({"sha": "sha-new", "name": "_test.md"})

    conflict_resp = _mock_response({}, status_code=422)
    success_resp = _mock_response({
        "commit": {"sha": "commit-xyz", "html_url": "https://github.com/org/repo/commit/xyz"}
    })

    mock_client = _mock_client(
        get_responses=[first_get, second_get],
        request_responses=[conflict_resp, success_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "deleted"
    assert mock_client.request.call_count == 2


def test_delete_note_no_retry_on_success(monkeypatch):
    """When first DELETE succeeds (200), no retry is issued."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-ok", "name": "_test.md"})
    success_resp = _mock_response({
        "commit": {"sha": "commit-ok", "html_url": "https://github.com/org/repo/commit/ok"}
    })

    mock_client = _mock_client(
        get_responses=[first_get],
        request_responses=[success_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "deleted"
    assert mock_client.request.call_count == 1, (
        "Expected exactly 1 DELETE attempt (no retry needed)"
    )
    assert mock_client.get.call_count == 1, "Expected exactly 1 GET (no re-fetch)"


def test_delete_note_returns_not_found_when_file_gone_during_retry(monkeypatch):
    """If file disappears between first and retry GET, return not_found gracefully."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-stale", "name": "_test.md"})
    not_found_get = _mock_response({}, status_code=404)

    conflict_resp = _mock_response({}, status_code=409)

    mock_client = _mock_client(
        get_responses=[first_get, not_found_get],
        request_responses=[conflict_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "not_found"
