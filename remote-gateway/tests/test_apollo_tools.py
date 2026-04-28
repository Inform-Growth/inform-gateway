"""Unit tests for tools/apollo.py — Apollo REST API tools."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_response(
    json_data: dict, status_code: int = 200, headers: dict | None = None
) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.headers = headers or {}
    m.raise_for_status = MagicMock()
    m.is_success = status_code < 300
    return m


def _mock_client(post_responses=None, get_responses=None) -> MagicMock:
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if post_responses is not None:
        mock.post.side_effect = post_responses
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------

def test_headers_raises_without_key(monkeypatch):
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    from tools.apollo import _headers

    with pytest.raises(ValueError, match="APOLLO_API_KEY"):
        _headers()


def test_headers_returns_api_key_header(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-apollo-key")
    from tools.apollo import _headers
    h = _headers()
    assert h["X-Api-Key"] == "test-apollo-key"
    assert h["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# _strip_nulls
# ---------------------------------------------------------------------------

def test_strip_nulls_removes_none_empty_string_and_empty_list():
    from tools.apollo import _strip_nulls
    result = _strip_nulls({
        "a": "hello", "b": None, "c": "", "d": [], "e": 0, "f": False, "g": ["x"]
    })
    assert result == {"a": "hello", "e": 0, "f": False, "g": ["x"]}


# ---------------------------------------------------------------------------
# _map_to_attio_values — person
# ---------------------------------------------------------------------------

def test_map_person_maps_name_email_title_linkedin(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": "VP of Sales",
        "linkedin_url": "https://linkedin.com/in/janedoe",
    }
    result = _map_to_attio_values(person, "person")
    assert result["name"] == [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]
    assert result["email_addresses"] == [{"email_address": "jane@acme.com"}]
    assert result["job_title"] == [{"value": "VP of Sales"}]
    assert result["linkedin"] == [{"value": "https://linkedin.com/in/janedoe"}]


def test_map_person_maps_phone_from_raw_number(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "phone_numbers": [{"raw_number": "+1-555-0100", "type": "work"}],
    }
    result = _map_to_attio_values(person, "person")
    assert result["phone_numbers"] == [{"phone_number": "+1-555-0100"}]


def test_map_person_maps_location_from_city_and_state(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "city": "San Francisco", "state": "California",
    }
    result = _map_to_attio_values(person, "person")
    assert result["primary_location"] == [{"value": "San Francisco, California"}]


def test_map_person_omits_fields_with_no_data(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {"first_name": "Jane", "last_name": "Doe", "name": "Jane Doe"}
    result = _map_to_attio_values(person, "person")
    assert "email_addresses" not in result
    assert "job_title" not in result
    assert "linkedin" not in result
    assert "phone_numbers" not in result
    assert "primary_location" not in result


def test_map_person_does_not_include_organization_name(monkeypatch):
    from tools.apollo import _map_to_attio_values
    person = {
        "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "organization_name": "Acme Inc",
    }
    result = _map_to_attio_values(person, "person")
    assert "company" not in result


# ---------------------------------------------------------------------------
# _map_to_attio_values — organization
# ---------------------------------------------------------------------------

def test_map_org_maps_name_domain_location(monkeypatch):
    from tools.apollo import _map_to_attio_values
    org = {
        "name": "Acme Inc", "domain": "acme.com",
        "city": "San Francisco", "state": "California",
    }
    result = _map_to_attio_values(org, "organization")
    assert result["name"] == [{"value": "Acme Inc"}]
    assert result["domains"] == [{"domain": "acme.com"}]
    assert result["primary_location"] == [{"value": "San Francisco, California"}]


def test_map_org_falls_back_to_primary_domain(monkeypatch):
    from tools.apollo import _map_to_attio_values
    org = {"name": "Acme Inc", "primary_domain": "acme.com"}
    result = _map_to_attio_values(org, "organization")
    assert result["domains"] == [{"domain": "acme.com"}]


# ---------------------------------------------------------------------------
# apollo__search_people
# ---------------------------------------------------------------------------

def test_search_people_posts_to_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people()
    url = mock_client.post.call_args.args[0]
    assert "mixed_people/api_search" in url


def test_search_people_accepts_contacts_key_in_response(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "contacts": [{"id": "p1", "name": "Jane Doe", "email": "jane@acme.com"}],
        "pagination": {"total_entries": 1}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people()
    assert len(result["people"]) == 1
    assert result["people"][0]["email"] == "jane@acme.com"


def test_search_people_sends_api_key_header(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "my-secret-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people()
    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers["X-Api-Key"] == "my-secret-key"


def test_search_people_includes_filters_in_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people(
            person_titles=["VP of Sales"],
            person_seniorities=["vp"],
            funding_stage=["series_b"],
            per_page=10,
        )
    body = mock_client.post.call_args.kwargs["json"]
    assert body["person_titles"] == ["VP of Sales"]
    assert body["person_seniorities"] == ["vp"]
    assert body["funding_stage"] == ["series_b"]
    assert body["per_page"] == 10


def test_search_people_omits_none_filters_from_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_people()
    body = mock_client.post.call_args.kwargs["json"]
    assert "person_titles" not in body
    assert "funding_stage" not in body


def test_search_people_strips_nulls_from_results(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    raw_person = {
        "id": "p1", "name": "Jane Doe", "first_name": "Jane", "last_name": "Doe",
        "title": None, "email": "jane@acme.com", "linkedin_url": None,
        "city": "SF", "state": "CA", "country": "US",
        "organization_name": "Acme", "organization_id": "o1",
        "funding_stage": None, "estimated_num_employees": 200,
    }
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [raw_person], "pagination": {"total_entries": 1}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people()
    person = result["people"][0]
    assert "title" not in person
    assert "linkedin_url" not in person
    assert "funding_stage" not in person
    assert person["email"] == "jane@acme.com"


def test_search_people_returns_pagination_and_agent_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({
        "people": [{"id": "p1", "name": "Jane"}],
        "pagination": {"total_entries": 500}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people(page=1, per_page=25)
    assert result["pagination"]["total"] == 500
    assert result["pagination"]["has_more"] is True
    assert "500" in result["pagination"]["summary"]
    assert "agent_hint" in result


def test_search_people_raises_permission_error_on_401(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "bad-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[_mock_response({}, status_code=401)])
    with (
        patch("httpx.Client", return_value=mock_client),
        pytest.raises(PermissionError, match="APOLLO_API_KEY"),
    ):
        apollo__search_people()


def test_search_people_returns_error_dict_on_422(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    mock_client = _mock_client(post_responses=[
        _mock_response({"error": "invalid seniority"}, status_code=422)
    ])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_people(person_seniorities=["bogus"])
    assert "error" in result
    assert "detail" in result


def test_search_people_raises_runtime_error_on_429(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_people
    resp = _mock_response({}, status_code=429, headers={"Retry-After": "30"})
    mock_client = _mock_client(post_responses=[resp])
    with patch("httpx.Client", return_value=mock_client), pytest.raises(RuntimeError, match="30"):
        apollo__search_people()


# ---------------------------------------------------------------------------
# apollo__search_companies
# ---------------------------------------------------------------------------

def test_search_companies_posts_to_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_companies()
    url = mock_client.post.call_args.args[0]
    assert "mixed_companies/search" in url


def test_search_companies_includes_filters_in_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [], "pagination": {"total_entries": 0}
    })])
    with patch("httpx.Client", return_value=mock_client):
        apollo__search_companies(
            q_organization_name="Acme",
            organization_num_employees_ranges=["51,200"],
            funding_stage=["series_a"],
            organization_latest_funding_amount_min=1000000,
        )
    body = mock_client.post.call_args.kwargs["json"]
    assert body["q_organization_name"] == "Acme"
    assert body["organization_num_employees_ranges"] == ["51,200"]
    assert body["funding_stage"] == ["series_a"]
    assert body["organization_latest_funding_amount_min"] == 1000000


def test_search_companies_strips_nulls_from_results(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    raw_org = {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
        "industry": None, "city": "SF", "state": "CA",
        "num_employees": 200, "estimated_annual_revenue": None,
        "funding_stage": "series_b", "latest_funding_amount": 25000000,
        "latest_funding_date": None,
    }
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [raw_org], "pagination": {"total_entries": 1}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_companies()
    org = result["companies"][0]
    assert "industry" not in org
    assert "estimated_annual_revenue" not in org
    assert "latest_funding_date" not in org
    assert org["name"] == "Acme Inc"


def test_search_companies_returns_pagination_and_agent_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__search_companies
    mock_client = _mock_client(post_responses=[_mock_response({
        "organizations": [], "pagination": {"total_entries": 250}
    })])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__search_companies(page=1, per_page=25)
    assert result["pagination"]["total"] == 250
    assert result["pagination"]["has_more"] is True
    assert "agent_hint" in result


# ---------------------------------------------------------------------------
# apollo__enrich_person
# ---------------------------------------------------------------------------

def test_enrich_person_raises_without_identifier(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    with pytest.raises(ValueError, match="id, email, linkedin_url"):
        apollo__enrich_person()


def test_enrich_person_posts_to_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    mock_client = _mock_client(post_responses=[_mock_response({"person": {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": "VP of Sales",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_person(email="jane@acme.com")
    url = mock_client.post.call_args.args[0]
    assert "people/match" in url


def test_enrich_person_posts_identifier_in_body(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    mock_client = _mock_client(post_responses=[_mock_response({"person": {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_person(id="p1", reveal_phone_number=True)
    body = mock_client.post.call_args.kwargs["json"]
    assert body["id"] == "p1"
    assert body["reveal_phone_number"] is True


def test_enrich_person_returns_person_attio_values_and_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    apollo_person = {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": "VP of Sales",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "phone_numbers": [{"raw_number": "+1-555-0100", "type": "work"}],
        "city": "San Francisco", "state": "California",
        "employment_history": None,
    }
    mock_client = _mock_client(post_responses=[_mock_response({"person": apollo_person})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_person(email="jane@acme.com")
    assert "person" in result
    assert "attio_values" in result
    assert "agent_hint" in result
    # attio_values should be pre-mapped
    av = result["attio_values"]
    assert av["email_addresses"] == [{"email_address": "jane@acme.com"}]
    assert av["job_title"] == [{"value": "VP of Sales"}]
    assert av["phone_numbers"] == [{"phone_number": "+1-555-0100"}]


def test_enrich_person_strips_nulls_from_person(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_person
    apollo_person = {
        "id": "p1", "first_name": "Jane", "last_name": "Doe", "name": "Jane Doe",
        "email": "jane@acme.com", "title": None, "linkedin_url": None,
        "employment_history": None,
    }
    mock_client = _mock_client(post_responses=[_mock_response({"person": apollo_person})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_person(email="jane@acme.com")
    assert "title" not in result["person"]
    assert "linkedin_url" not in result["person"]
    assert "employment_history" not in result["person"]


# ---------------------------------------------------------------------------
# apollo__enrich_organization
# ---------------------------------------------------------------------------

def test_enrich_organization_gets_correct_url(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    mock_client = _mock_client(get_responses=[_mock_response({"organization": {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_organization(domain="acme.com")
    url = mock_client.get.call_args.args[0]
    assert "organizations/enrich" in url


def test_enrich_organization_passes_domain_as_param(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    mock_client = _mock_client(get_responses=[_mock_response({"organization": {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
    }})])
    with patch("httpx.Client", return_value=mock_client):
        apollo__enrich_organization(domain="acme.com")
    params = mock_client.get.call_args.kwargs.get("params", {})
    assert params.get("domain") == "acme.com"


def test_enrich_organization_returns_org_attio_values_and_hint(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    apollo_org = {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
        "industry": "Software", "city": "San Francisco", "state": "California",
        "num_employees": 250, "funding_stage": "series_b",
        "latest_funding_amount": 25000000, "annual_revenue": None,
    }
    mock_client = _mock_client(get_responses=[_mock_response({"organization": apollo_org})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_organization(domain="acme.com")
    assert "organization" in result
    assert "attio_values" in result
    assert "agent_hint" in result
    av = result["attio_values"]
    assert av["name"] == [{"value": "Acme Inc"}]
    assert av["domains"] == [{"domain": "acme.com"}]
    assert av["primary_location"] == [{"value": "San Francisco, California"}]


def test_enrich_organization_strips_nulls(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    from tools.apollo import apollo__enrich_organization
    apollo_org = {
        "id": "o1", "name": "Acme Inc", "domain": "acme.com",
        "annual_revenue": None, "latest_funding_date": None,
    }
    mock_client = _mock_client(get_responses=[_mock_response({"organization": apollo_org})])
    with patch("httpx.Client", return_value=mock_client):
        result = apollo__enrich_organization(domain="acme.com")
    assert "annual_revenue" not in result["organization"]
    assert "latest_funding_date" not in result["organization"]
