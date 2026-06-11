"""
Unit tests for tools/integrations/granola.py — Granola meeting notes tools.

Run with:
    pytest remote-gateway/tests/test_granola_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx response."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.text = str(json_data)
    m.is_success = status_code < 400

    def raise_for_status():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")

    m.raise_for_status = raise_for_status
    return m


def _mock_client(get_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# ---------------------------------------------------------------------------
# Auth / transport (_headers, _get)
# ---------------------------------------------------------------------------

def test_get_raises_without_api_key(monkeypatch):
    """_get raises ValueError when GRANOLA_API_KEY is not set."""
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)

    from tools.integrations.granola import _get
    with pytest.raises(ValueError, match="GRANOLA_API_KEY"):
        _get("/notes")


def test_get_sends_bearer_token(monkeypatch):
    """_get sends GRANOLA_API_KEY as a Bearer token."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response({"notes": []})])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        _get("/notes")

    headers = mock_client.get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer grn_testkey"


def test_get_401_raises_permission_error(monkeypatch):
    """_get raises PermissionError on HTTP 401."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_bad")
    mock_client = _mock_client(get_responses=[_mock_response({}, status_code=401)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        with pytest.raises(PermissionError, match="GRANOLA_API_KEY"):
            _get("/notes")


def test_get_404_raises_not_found(monkeypatch):
    """_get raises RuntimeError naming the path on HTTP 404."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response({}, status_code=404)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        with pytest.raises(RuntimeError, match="not_doesNotExist00"):
            _get("/notes/not_doesNotExist00")


def test_get_400_raises_bad_request(monkeypatch):
    """_get raises RuntimeError with the response body on HTTP 400."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(
        get_responses=[_mock_response({"error": "bad folder_id"}, status_code=400)]
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        with pytest.raises(RuntimeError, match="bad folder_id"):
            _get("/notes")
