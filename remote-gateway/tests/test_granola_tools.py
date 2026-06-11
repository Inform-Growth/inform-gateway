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


def test_get_forwards_params(monkeypatch):
    """_get forwards query params to the underlying client.get call."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response({"notes": []})])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import _get
        _get("/notes", params={"page_size": 5, "cursor": "abc"})

    assert mock_client.get.call_args.kwargs["params"] == {"page_size": 5, "cursor": "abc"}


# ---------------------------------------------------------------------------
# Transcript flattening
# ---------------------------------------------------------------------------

def test_flatten_transcript_mic_and_speaker():
    """Mic utterances become 'Me:', speaker utterances become 'Them:'."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "Hi there.", "start_timestamp": "0"},
        {"source": "speaker", "text": "Hello!", "start_timestamp": "1"},
    ])
    assert out == "Me: Hi there.\nThem: Hello!"


def test_flatten_transcript_prefers_diarization_label():
    """diarization_label wins over the mic/speaker fallback."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "speaker", "text": "First point.", "diarization_label": "Speaker A"},
        {"source": "speaker", "text": "Reply.", "diarization_label": "Speaker B"},
    ])
    assert out == "Speaker A: First point.\nSpeaker B: Reply."


def test_flatten_transcript_merges_consecutive_same_speaker():
    """Consecutive utterances from the same speaker merge into one line."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "So the plan"},
        {"source": "microphone", "text": "is to ship Friday."},
        {"source": "speaker", "text": "Sounds good."},
    ])
    assert out == "Me: So the plan is to ship Friday.\nThem: Sounds good."


def test_flatten_transcript_skips_empty_text():
    """Utterances with empty or whitespace-only text are dropped."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "  "},
        {"source": "speaker", "text": "Real content."},
        {"source": "speaker", "text": ""},
    ])
    assert out == "Them: Real content."


def test_flatten_transcript_empty_list():
    """An empty transcript flattens to an empty string."""
    from tools.integrations.granola import _flatten_transcript
    assert _flatten_transcript([]) == ""


def test_flatten_transcript_blank_diarization_label_falls_back():
    """A whitespace-only diarization_label is treated as absent."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([
        {"source": "microphone", "text": "Hello.", "diarization_label": "   "},
    ])
    assert out == "Me: Hello."


def test_flatten_transcript_missing_source_defaults_to_them():
    """An utterance with no source key is attributed to 'Them'."""
    from tools.integrations.granola import _flatten_transcript
    out = _flatten_transcript([{"text": "System note."}])
    assert out == "Them: System note."


# ---------------------------------------------------------------------------
# granola__list_meetings
# ---------------------------------------------------------------------------

_LIST_NOTES_RESPONSE = {
    "notes": [
        {
            "id": "not_1d3tmYTlCICgjy",
            "object": "note",
            "title": "Weekly sync",
            "owner": {"name": "Jaron Sander", "email": "jaron@informgrowth.com"},
            "created_at": "2026-06-10T15:00:00Z",
            "updated_at": "2026-06-10T16:00:00Z",
        }
    ],
    "hasMore": True,
    "cursor": "eyJjcmVkZW50aWFsfQ==",
}


def test_list_meetings_returns_notes_and_pagination(monkeypatch):
    """granola__list_meetings returns note summaries with has_more and cursor."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_NOTES_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        result = granola__list_meetings()

    assert result["notes"][0]["id"] == "not_1d3tmYTlCICgjy"
    assert result["notes"][0]["title"] == "Weekly sync"
    assert result["notes"][0]["owner"]["email"] == "jaron@informgrowth.com"
    assert result["has_more"] is True
    assert result["cursor"] == "eyJjcmVkZW50aWFsfQ=="


def test_list_meetings_omits_none_params(monkeypatch):
    """Only non-None filters are sent; defaults send just page_size."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_NOTES_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        granola__list_meetings()

    params = mock_client.get.call_args.kwargs["params"]
    assert params == {"page_size": 10}


def test_list_meetings_passes_filters(monkeypatch):
    """All provided filters are passed through as query params."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(get_responses=[_mock_response(_LIST_NOTES_RESPONSE)])

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        granola__list_meetings(
            created_after="2026-06-01",
            created_before="2026-06-10",
            updated_after="2026-06-05",
            folder_id="fol_AAAABBBBCCCCdd",
            cursor="abc",
            page_size=25,
        )

    params = mock_client.get.call_args.kwargs["params"]
    assert params == {
        "page_size": 25,
        "created_after": "2026-06-01",
        "created_before": "2026-06-10",
        "updated_after": "2026-06-05",
        "folder_id": "fol_AAAABBBBCCCCdd",
        "cursor": "abc",
    }


def test_list_meetings_clamps_page_size(monkeypatch):
    """page_size is clamped to the API's 1-30 range."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_testkey")
    mock_client = _mock_client(
        get_responses=[
            _mock_response(_LIST_NOTES_RESPONSE),
            _mock_response(_LIST_NOTES_RESPONSE),
        ]
    )

    with patch("httpx.Client", return_value=mock_client):
        from tools.integrations.granola import granola__list_meetings
        granola__list_meetings(page_size=100)
        assert mock_client.get.call_args.kwargs["params"]["page_size"] == 30
        granola__list_meetings(page_size=0)
        assert mock_client.get.call_args.kwargs["params"]["page_size"] == 1
