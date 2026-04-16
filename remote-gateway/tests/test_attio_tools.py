"""
Unit tests for tools/attio.py — Python REST overrides for broken attio-mcp tools.

Run with:
    pytest remote-gateway/tests/test_attio_tools.py -v
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.attio import attio__create_record, attio__search_records

from core.field_registry import FieldRegistry


# ---------------------------------------------------------------------------
# Helpers for pre-flight validation tests
# ---------------------------------------------------------------------------

_PEOPLE_YAML = textwrap.dedent("""\
    integration: "attio"
    object: "people"
    fields:
      name:
        display_name: "Name"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]'
      email_addresses:
        display_name: "Email Addresses"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"email_address": "jane@acme.com"}]'
      linkedin:
        display_name: "LinkedIn"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"value": "https://linkedin.com/in/handle"}]'
      job_title:
        display_name: "Job Title"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"value": "Head of Sales"}]'
      avatar_url:
        display_name: "Avatar URL"
        type: "string"
        nullable: true
        writable: false
        required_for_create: false
        write_format: null
""")


def _make_test_registry(tmp_path: Path) -> FieldRegistry:
    """Write minimal YAML fixtures and return a FieldRegistry pointed at tmp_path."""
    (tmp_path / "attio-people.yaml").write_text(_PEOPLE_YAML)
    return FieldRegistry(fields_dir=tmp_path)


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


# ---------------------------------------------------------------------------
# attio__create_record — pre-flight validation
# ---------------------------------------------------------------------------


def test_create_record_rejects_unknown_field(monkeypatch, tmp_path):
    """create_record returns a structured error when an unknown field is passed."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path))

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record(
            "people",
            {"linkedin_url": [{"value": "https://linkedin.com/in/test"}]},
        )

    assert "error" in result
    assert "linkedin_url" in result["error"]
    assert "linkedin" in result["valid_writable_fields"]
    # No HTTP call should have been made
    mock_client.post.assert_not_called()


def test_create_record_rejects_readonly_field(monkeypatch, tmp_path):
    """create_record returns a structured error when a read-only field is passed."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path))

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record(
            "people",
            {"avatar_url": [{"value": "https://example.com/photo.jpg"}]},
        )

    assert "error" in result
    assert "avatar_url" in result["error"]
    assert "avatar_url" not in result["valid_writable_fields"]
    mock_client.post.assert_not_called()


def test_create_record_valid_people_payload(monkeypatch, tmp_path):
    """create_record passes pre-flight and makes the HTTP call for a valid payload."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path))

    mock_client = _mock_client(
        post_responses=[
            _mock_response({"data": {"id": {"record_id": "rec-valid-123"}, "values": {}}})
        ]
    )

    values = {
        "name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}],
        "email_addresses": [{"email_address": "jane@acme.com"}],
        "linkedin": [{"value": "https://linkedin.com/in/janedoe"}],
        "job_title": [{"value": "Head of Sales"}],
    }

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record("people", values)

    assert result["record_id"] == "rec-valid-123"
    mock_client.post.assert_called_once()


def test_create_record_skips_validation_when_no_yaml(monkeypatch, tmp_path):
    """create_record skips validation gracefully when no YAML exists for the object type."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    # tmp_path has no YAML files — registry will return empty defs
    monkeypatch.setattr(attio_module, "registry", FieldRegistry(fields_dir=tmp_path))

    mock_client = _mock_client(
        post_responses=[
            _mock_response({"data": {"id": {"record_id": "rec-skip-456"}, "values": {}}})
        ]
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record(
            "custom_object",
            {"some_unknown_field": [{"value": "x"}]},
        )

    # No error — validation was skipped, HTTP call was made
    assert "error" not in result
    assert result["record_id"] == "rec-skip-456"
