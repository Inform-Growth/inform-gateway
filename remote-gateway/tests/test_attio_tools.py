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

from core.field_registry import FieldRegistry
from tools.integrations.attio import (
    attio__create_record,
    attio__search_records,
    attio__update_record,
    attio__upsert_record,
)

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
    """search_records POSTs to /records/query with a name $contains filter.

    Regression for #55: previously sent $str_contains which Attio v2 rejects with
    "Invalid operator: $str_contains, path: ['name']". The documented operator
    on text fields (companies.name) is $contains.
    """
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        attio__search_records("people", "Jane", limit=5)

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "people/records/query" in posted_url
    assert "$str_contains" not in str(posted_body), (
        "$str_contains is not a valid Attio v2 operator (see issue #55)"
    )
    assert posted_body["filter"]["name"]["$contains"] == "Jane"
    assert posted_body["limit"] == 5


def test_search_records_companies_uses_contains_operator(monkeypatch):
    """search_records for companies uses $contains on text name field (regression #55)."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        attio__search_records("companies", "Stord")

    posted_body = mock_client.post.call_args.kwargs["json"]
    assert posted_body["filter"] == {"name": {"$contains": "Stord"}}


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


def test_create_record_returns_record_id(monkeypatch, tmp_path):
    """create_record returns record_id from Attio create response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")
    import tools.integrations.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", FieldRegistry(fields_dir=tmp_path), raising=False)

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


def test_create_record_posts_correct_payload(monkeypatch, tmp_path):
    """create_record wraps values in {"data": {"values": ...}} as Attio API requires."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")
    import tools.integrations.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", FieldRegistry(fields_dir=tmp_path), raising=False)

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


def test_create_record_uses_api_key_header(monkeypatch, tmp_path):
    """create_record sends ATTIO_API_KEY as Bearer token."""
    monkeypatch.setenv("ATTIO_API_KEY", "create-key-999")
    import tools.integrations.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", FieldRegistry(fields_dir=tmp_path), raising=False)

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

    import tools.integrations.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path), raising=False)

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
    assert "hint" in result
    assert "get_field_definitions" in result["hint"]
    # No HTTP call should have been made
    mock_client.post.assert_not_called()


def test_create_record_rejects_readonly_field(monkeypatch, tmp_path):
    """create_record returns a structured error when a read-only field is passed."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.integrations.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path), raising=False)

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
    assert "hint" in result
    assert "get_field_definitions" in result["hint"]
    mock_client.post.assert_not_called()


def test_create_record_valid_people_payload(monkeypatch, tmp_path):
    """create_record passes pre-flight and makes the HTTP call for a valid payload."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.integrations.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path), raising=False)

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
    assert result["object_type"] == "people"
    mock_client.post.assert_called_once()


def test_create_record_skips_validation_when_no_yaml(monkeypatch, tmp_path):
    """create_record skips validation gracefully when no YAML exists for the object type."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.integrations.attio as attio_module
    # tmp_path has no YAML files — registry will return empty defs
    monkeypatch.setattr(attio_module, "registry", FieldRegistry(fields_dir=tmp_path), raising=False)

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


# ---------------------------------------------------------------------------
# attio__update_record (issue #54)
# ---------------------------------------------------------------------------


def _mock_patch_client(responses):
    """Return a context-manager mock for httpx.Client with .patch responses."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.patch.side_effect = responses
    return mock


def _stub_empty_registry(monkeypatch, tmp_path):
    """Point the module-level registry at an empty dir so pre-flight validation is skipped."""
    import tools.integrations.attio as attio_module
    monkeypatch.setattr(
        attio_module, "registry", FieldRegistry(fields_dir=tmp_path), raising=False,
    )


def test_update_record_patches_correct_url_with_plural_resource(monkeypatch, tmp_path):
    """update_record PATCHes /objects/people/records/{id} — always plural (regression #54)."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    _stub_empty_registry(monkeypatch, tmp_path)

    record_id = "2b2b1e2d-07c0-44ff-bffa-83562292351c"
    mock_client = _mock_patch_client([
        _mock_response({"data": {"id": {"record_id": record_id}, "values": {}}})
    ])

    with patch("httpx.Client", return_value=mock_client):
        attio__update_record(
            "people",
            record_id,
            {"job_title": [{"value": "VP of Ops"}]},
        )

    url = mock_client.patch.call_args.args[0]
    assert f"/objects/people/records/{record_id}" in url, (
        "must use plural 'people' not singular 'person' (issue #54)"
    )
    assert "/person/" not in url


def test_update_record_wraps_values_correctly(monkeypatch, tmp_path):
    """update_record sends {data: {values: ...}} payload shape."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    _stub_empty_registry(monkeypatch, tmp_path)

    mock_client = _mock_patch_client([
        _mock_response({"data": {"id": {"record_id": "rec-1"}, "values": {}}})
    ])
    values = {"icp_rationale": [{"value": "Strategic fit on procurement"}]}

    with patch("httpx.Client", return_value=mock_client):
        attio__update_record("people", "rec-1", values)

    body = mock_client.patch.call_args.kwargs["json"]
    assert body == {"data": {"values": values}}


def test_update_record_surfaces_full_attio_error_body(monkeypatch, tmp_path):
    """update_record surfaces the underlying Attio error body, not a generic 400 (regression #54).

    The previous npm-proxied tool returned only "An error occurred while
    processing your request" — agents couldn't tell which field was invalid.
    """
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    _stub_empty_registry(monkeypatch, tmp_path)

    attio_error_body = (
        '{"status_code":400,"type":"invalid_request_error",'
        '"code":"value_not_writable","message":"Field icp_rationale is read-only"}'
    )
    failed = _mock_response({}, status_code=400)
    failed.is_success = False
    failed.text = attio_error_body
    mock_client = _mock_patch_client([failed])

    with patch("httpx.Client", return_value=mock_client):
        result = attio__update_record(
            "people",
            "rec-1",
            {"icp_rationale": [{"value": "..."}]},
        )

    assert "error" in result
    assert "400" in result["error"]
    assert "icp_rationale" in result["error"], (
        "must include the underlying Attio body so agents can see which field failed"
    )
    assert result["object_type"] == "people"
    assert result["record_id"] == "rec-1"


def test_update_record_returns_updated_record_id(monkeypatch, tmp_path):
    """update_record returns the updated record id and data on success."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    _stub_empty_registry(monkeypatch, tmp_path)

    mock_client = _mock_patch_client([_mock_response({
        "data": {
            "id": {"record_id": "rec-42"},
            "values": {"job_title": [{"value": "VP of Ops"}]},
        }
    })])

    with patch("httpx.Client", return_value=mock_client):
        result = attio__update_record(
            "people", "rec-42", {"job_title": [{"value": "VP of Ops"}]},
        )

    assert result["record_id"] == "rec-42"
    assert result["object_type"] == "people"
    assert result["data"]["values"]["job_title"] == [{"value": "VP of Ops"}]


# ---------------------------------------------------------------------------
# attio__upsert_record
# ---------------------------------------------------------------------------


def test_upsert_record_raises_for_invalid_matching_attribute(monkeypatch):
    """upsert_record raises ValueError for unsupported matching_attribute."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    import pytest
    with pytest.raises(ValueError, match="matching_attribute"):
        attio__upsert_record("people", {}, matching_attribute="bogus_field")


def test_upsert_record_posts_with_matching_attribute(monkeypatch):
    """upsert_record includes matching_attribute in the POST body."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    mock_client = _mock_client(
        post_responses=[_mock_response(
            {"data": {"id": {"record_id": "rec-upserted"}, "values": {}}},
            status_code=200,
        )]
    )
    values = {"email_addresses": [{"email_address": "jane@acme.com"}]}
    with patch("httpx.Client", return_value=mock_client):
        attio__upsert_record("people", values, matching_attribute="email_addresses")
    posted_body = mock_client.post.call_args.kwargs["json"]
    assert posted_body["matching_attribute"] == "email_addresses"
    assert posted_body["data"]["values"] == values


def test_upsert_record_returns_upserted_true_on_200(monkeypatch):
    """upsert_record returns upserted=True when Attio returns 200 (existing record updated)."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    mock_client = _mock_client(
        post_responses=[_mock_response(
            {"data": {"id": {"record_id": "rec-existing"}, "values": {}}},
            status_code=200,
        )]
    )
    with patch("httpx.Client", return_value=mock_client):
        result = attio__upsert_record(
            "people",
            {"email_addresses": [{"email_address": "jane@acme.com"}]},
            matching_attribute="email_addresses",
        )
    assert result["upserted"] is True
    assert result["record_id"] == "rec-existing"


def test_upsert_record_returns_upserted_false_on_201(monkeypatch):
    """upsert_record returns upserted=False when Attio returns 201 (new record created)."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    mock_client = _mock_client(
        post_responses=[_mock_response(
            {"data": {"id": {"record_id": "rec-new"}, "values": {}}},
            status_code=201,
        )]
    )
    with patch("httpx.Client", return_value=mock_client):
        result = attio__upsert_record(
            "companies",
            {"domains": [{"domain": "acme.com"}]},
            matching_attribute="domains",
        )
    assert result["upserted"] is False
    assert result["record_id"] == "rec-new"


def test_upsert_record_returns_error_on_attio_failure(monkeypatch):
    """upsert_record returns error dict on non-2xx Attio response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    resp = _mock_response({"message": "bad request"}, status_code=400)
    resp.is_success = False
    resp.text = '{"message": "bad request"}'
    mock_client = _mock_client(post_responses=[resp])
    with patch("httpx.Client", return_value=mock_client):
        result = attio__upsert_record(
            "people",
            {"email_addresses": [{"email_address": "x@y.com"}]},
            matching_attribute="email_addresses",
        )
    assert "error" in result
