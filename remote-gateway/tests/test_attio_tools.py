"""
Unit tests for tools/attio.py — Python REST overrides for broken attio-mcp tools.

Run with:
    pytest remote-gateway/tests/test_attio_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.attio import attio__create_record, attio__search_records


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Client response."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock()
    return m


def _mock_client(post_responses=None, get_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if post_responses is not None:
        mock.post.side_effect = post_responses
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# ---------------------------------------------------------------------------
# attio__search_records
# ---------------------------------------------------------------------------


def test_search_records_returns_records(monkeypatch):
    """search_records returns count and records list from Attio query response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    records = [{"id": {"record_id": "rec-123"}, "values": {"name": [{"value": "Acme Corp"}]}}]
    mock_client = _mock_client(post_responses=[_mock_response({"data": records})])

    with patch("httpx.Client", return_value=mock_client):
        result = attio__search_records("companies", "Acme")

    assert result["count"] == 1
    assert result["records"] == records
    assert result["object_type"] == "companies"


def test_search_records_posts_correct_endpoint_and_filter(monkeypatch):
    """search_records POSTs to /records/query with a name $str_contains filter."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        attio__search_records("people", "Jane", limit=5)

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "people/records/query" in posted_url
    assert posted_body["filter"]["name"]["$str_contains"] == "Jane"
    assert posted_body["limit"] == 5


def test_search_records_uses_api_key_header(monkeypatch):
    """search_records sends ATTIO_API_KEY as Bearer token."""
    monkeypatch.setenv("ATTIO_API_KEY", "secret-key-xyz")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        attio__search_records("companies", "Test")

    posted_headers = mock_client.post.call_args.kwargs["headers"]
    assert posted_headers.get("Authorization") == "Bearer secret-key-xyz"


def test_search_records_empty_result(monkeypatch):
    """search_records with no matches returns count=0 and empty records list."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        result = attio__search_records("companies", "NonexistentCo")

    assert result["count"] == 0
    assert result["records"] == []


# ---------------------------------------------------------------------------
# attio__create_record
# ---------------------------------------------------------------------------


def test_create_record_returns_record_id(monkeypatch):
    """create_record returns record_id from Attio create response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(
        post_responses=[
            _mock_response({"data": {"id": {"record_id": "rec-new-456"}, "values": {}}})
        ]
    )
    values = {"name": [{"value": "New Corp"}], "domains": [{"domain": "newcorp.io"}]}

    with patch("httpx.Client", return_value=mock_client):
        result = attio__create_record("companies", values)

    assert result["record_id"] == "rec-new-456"
    assert result["object_type"] == "companies"
    assert result["data"]["id"]["record_id"] == "rec-new-456"


def test_create_record_posts_correct_payload(monkeypatch):
    """create_record wraps values in {"data": {"values": ...}} as Attio API requires."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )
    values = {"name": [{"value": "Corp"}]}

    with patch("httpx.Client", return_value=mock_client):
        attio__create_record("companies", values)

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "companies/records" in posted_url
    assert "query" not in posted_url  # must be create endpoint, not search
    assert posted_body == {"data": {"values": values}}


def test_create_record_uses_api_key_header(monkeypatch):
    """create_record sends ATTIO_API_KEY as Bearer token."""
    monkeypatch.setenv("ATTIO_API_KEY", "create-key-999")

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )

    with patch("httpx.Client", return_value=mock_client):
        attio__create_record("companies", {"name": [{"value": "X"}]})

    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers.get("Authorization") == "Bearer create-key-999"
