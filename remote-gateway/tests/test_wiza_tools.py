"""
Unit tests for tools/wiza.py — Wiza Individual Reveal person enrichment.

Run with:
    pytest remote-gateway/tests/test_wiza_tools.py -v
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


# Canonical start and finished responses for reuse across tests
_START_RESPONSE = {"data": {"id": "rev-abc-123", "status": "queued", "is_complete": False}}

_FINISHED_RESPONSE = {
    "data": {
        "id": "rev-abc-123",
        "status": "finished",
        "is_complete": True,
        "name": "Jane Smith",
        "title": "VP of Engineering",
        "linkedin_profile_url": "https://www.linkedin.com/in/janesmith",
        "email": "jane@example.com",
        "email_status": "valid",
        "mobile_phone": "+14155551234",
        "company": "Acme Corp",
        "credits": {
            "email_credits": 2,
            "phone_credits": 5,
            "api_credits": {"total": 1, "email_credits": 0, "phone_credits": 0, "scrape_credits": 1},
        },
    }
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_enrich_person_returns_all_fields(monkeypatch):
    """wiza__enrich_person returns name, title, email, phone, linkedin, company, credits."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        result = wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert result["name"] == "Jane Smith"
    assert result["title"] == "VP of Engineering"
    assert result["email"] == "jane@example.com"
    assert result["email_status"] == "valid"
    assert result["mobile_phone"] == "+14155551234"
    assert result["linkedin_profile_url"] == "https://www.linkedin.com/in/janesmith"
    assert result["company_name"] == "Acme Corp"
    assert result["credits_used"]["email"] == 2
    assert result["credits_used"]["phone"] == 5
    assert result["credits_used"]["api"] == 1


def test_enrich_person_posts_correct_payload(monkeypatch):
    """wiza__enrich_person POSTs enrichment_level=full and the linkedin URL."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "individual_reveals" in posted_url
    assert posted_body["individual_reveal"]["profile_url"] == "https://www.linkedin.com/in/janesmith"
    assert posted_body["individual_reveal"]["enrichment_level"] == "full"


def test_enrich_person_sends_bearer_token(monkeypatch):
    """wiza__enrich_person sends WIZA_API_KEY as Bearer token on both POST and GET."""
    monkeypatch.setenv("WIZA_API_KEY", "my-secret-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    post_headers = mock_client.post.call_args.kwargs["headers"]
    get_headers = mock_client.get.call_args.kwargs["headers"]

    assert post_headers["Authorization"] == "Bearer my-secret-key"
    assert get_headers["Authorization"] == "Bearer my-secret-key"


def test_enrich_person_polls_correct_url(monkeypatch):
    """wiza__enrich_person GETs /individual_reveals/{id} using the ID from the POST response."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(_FINISHED_RESPONSE)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    polled_url = mock_client.get.call_args.args[0]
    assert "individual_reveals/rev-abc-123" in polled_url


def test_enrich_person_retries_while_resolving(monkeypatch):
    """wiza__enrich_person keeps polling through 'resolving' status until 'finished'."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    resolving = {"data": {"id": "rev-abc-123", "status": "resolving", "is_complete": False}}

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[
            _mock_response(resolving),
            _mock_response(resolving),
            _mock_response(_FINISHED_RESPONSE),
        ],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        result = wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert result["name"] == "Jane Smith"
    assert mock_client.get.call_count == 3


def test_enrich_person_omits_absent_fields(monkeypatch):
    """wiza__enrich_person omits fields not present in the Wiza response."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    sparse_finished = {
        "data": {
            "id": "rev-abc-123",
            "status": "finished",
            "is_complete": True,
            "name": "Jane Smith",
            "email": "jane@example.com",
            "email_status": "valid",
            # no title, mobile_phone, company, linkedin_profile_url
            "credits": {"email_credits": 2, "phone_credits": 0, "api_credits": None},
        }
    }

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(sparse_finished)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        result = wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert "title" not in result
    assert "mobile_phone" not in result
    assert "company_name" not in result
    assert "linkedin_profile_url" not in result
    assert result["name"] == "Jane Smith"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_enrich_person_raises_value_error_when_no_api_key(monkeypatch):
    """wiza__enrich_person raises ValueError if WIZA_API_KEY is not set."""
    monkeypatch.delenv("WIZA_API_KEY", raising=False)

    from tools.wiza import wiza__enrich_person
    with pytest.raises(ValueError, match="WIZA_API_KEY"):
        wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_permission_error_on_401(monkeypatch):
    """wiza__enrich_person raises PermissionError on 401 from Wiza."""
    monkeypatch.setenv("WIZA_API_KEY", "bad-key")

    mock_client = _mock_client(
        post_responses=[_mock_response({}, status_code=401)],
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(PermissionError, match="WIZA_API_KEY"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_runtime_error_on_400(monkeypatch):
    """wiza__enrich_person raises RuntimeError on 400 from Wiza."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response({"error": "invalid input"}, status_code=400)],
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(RuntimeError, match="bad request"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_runtime_error_on_429(monkeypatch):
    """wiza__enrich_person raises RuntimeError on 429 queue full from Wiza."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    mock_client = _mock_client(
        post_responses=[_mock_response({}, status_code=429)],
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(RuntimeError, match="queue full"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_runtime_error_on_failed_reveal(monkeypatch):
    """wiza__enrich_person raises RuntimeError when reveal status is 'failed'."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    failed = {"data": {"id": "rev-abc-123", "status": "failed", "is_complete": True}}

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(failed)],
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(RuntimeError, match="failed"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")


def test_enrich_person_raises_timeout_error_after_max_polls(monkeypatch):
    """wiza__enrich_person raises TimeoutError if still queued after 10 polls."""
    monkeypatch.setenv("WIZA_API_KEY", "test-key")

    still_queued = {"data": {"id": "rev-abc-123", "status": "queued", "is_complete": False}}

    mock_client = _mock_client(
        post_responses=[_mock_response(_START_RESPONSE)],
        get_responses=[_mock_response(still_queued)] * 10,
    )

    with patch("httpx.Client", return_value=mock_client), \
         patch("time.sleep"):
        from tools.wiza import wiza__enrich_person
        with pytest.raises(TimeoutError, match="rev-abc-123"):
            wiza__enrich_person("https://www.linkedin.com/in/janesmith")

    assert mock_client.get.call_count == 10
