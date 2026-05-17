"""Tests for report_issue and list_my_issues in tools/notes.py."""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


@pytest.fixture(autouse=True)
def deployment_env(monkeypatch):
    monkeypatch.setenv("INFORM_GATEWAY_DEPLOYMENT_REPO", "Inform-Growth/test-deployment")
    monkeypatch.setenv("INFORM_GATEWAY_GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("INFORM_GATEWAY_REPORT_ISSUE_DISABLED", raising=False)


def _make_issue_response(number: int = 42, title: str = "Test issue") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {
        "number": number,
        "html_url": f"https://github.com/Inform-Growth/test-deployment/issues/{number}",
    }
    resp.raise_for_status = MagicMock()
    return resp


def test_report_issue_returns_issue_url():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response(number=42)

        result = report_issue(
            title="Apollo returns empty for happy-path query",
            task_id="task-abc123",
            attempted_action="Search Apollo for VP Engineering at Series B companies",
            observed_failure="apollo__search_people returned empty results for a query that should match 50+ contacts",
            agent_hypothesis="The seniority filter may be case-sensitive; tried 'VP' but API may expect 'vp'",
            suggested_category="bug",
            severity="p2",
            related_tool="apollo",
        )

    assert result["issue_number"] == 42
    assert "github.com" in result["issue_url"]
    assert "type:bug" in result["labels"]
    assert "priority:p2" in result["labels"]
    assert "source:report_issue" in result["labels"]
    assert "tool:apollo" in result["labels"]


def test_report_issue_posts_to_correct_repo():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response()

        report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="bug",
        )

        call_args = mock_client.post.call_args
        url = call_args[0][0]
        assert "Inform-Growth/test-deployment" in url
        assert url.endswith("/issues")


def test_report_issue_body_contains_task_id():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response()

        report_issue(
            title="Test",
            task_id="task-xyz999",
            attempted_action="looked up contact",
            observed_failure="got 400",
            agent_hypothesis="bad field name",
            suggested_category="bug",
        )

        payload = mock_client.post.call_args[1]["json"]
        assert "task-xyz999" in payload["body"]


def test_report_issue_soft_fails_on_github_error():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("GitHub is down")

        result = report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="bug",
        )

    assert "error" in result
    assert result.get("logged_to_task") == "task-abc"


def test_report_issue_kill_switch(monkeypatch):
    monkeypatch.setenv("INFORM_GATEWAY_REPORT_ISSUE_DISABLED", "true")
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        result = report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="bug",
        )
        mock_client_cls.assert_not_called()

    assert result.get("status") == "disabled"


def test_report_issue_no_tool_label_when_related_tool_absent():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response()

        result = report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="ux",
        )

    assert not any(l.startswith("tool:") for l in result["labels"])


def test_list_my_issues_returns_open_issues():
    from tools.notes import list_my_issues

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "number": 7,
            "title": "Apollo empty results",
            "labels": [{"name": "type:bug"}, {"name": "priority:p2"}],
            "state": "open",
            "created_at": "2026-05-16T10:00:00Z",
            "html_url": "https://github.com/Inform-Growth/test-deployment/issues/7",
        }
    ]
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        result = list_my_issues(state="open", limit=20)

    assert len(result) == 1
    assert result[0]["issue_number"] == 7
    assert result[0]["title"] == "Apollo empty results"
    assert "type:bug" in result[0]["labels"]


def test_list_my_issues_passes_state_and_label_params():
    from tools.notes import list_my_issues

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        list_my_issues(state="closed", label="type:bug", limit=5)

        params = mock_client.get.call_args[1]["params"]
        assert params["state"] == "closed"
        assert params["labels"] == "type:bug"
        assert params["per_page"] == 5
