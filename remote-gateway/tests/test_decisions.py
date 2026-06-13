"""Unit tests for the decisions integration — httpx fully mocked."""
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from tools.integrations import decisions  # noqa: E402


def _resp(json_data, status=200):
    r = MagicMock()
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    r.status_code = status
    return r


def _client_cm(client):
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    return cm


def test_list_open_decisions_queries_open_and_in_progress():
    client = MagicMock()
    client.get.return_value = _resp([{"id": "1", "title": "X", "status": "open"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        out = decisions.list_open_decisions()
    assert out["decisions"][0]["title"] == "X"
    _, kwargs = client.get.call_args
    assert kwargs["params"]["status"] == "in.(open,in_progress)"
    assert kwargs["params"]["order"] == "opened_at.desc"


def test_upsert_decision_dedups_existing_active_row():
    client = MagicMock()
    client.get.return_value = _resp([{"id": "1", "title": "X", "status": "open"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        out = decisions.upsert_decision("X")
    assert out["decision"]["id"] == "1"
    client.post.assert_not_called()  # no insert when an active row exists


def test_upsert_decision_inserts_when_absent():
    client = MagicMock()
    client.get.return_value = _resp([])  # nothing existing
    client.post.return_value = _resp([{"id": "2", "title": "Y", "status": "open"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        out = decisions.upsert_decision("Y", kind="task", priority="H")
    assert out["decision"]["id"] == "2"
    _, kwargs = client.post.call_args
    assert kwargs["json"]["signal_type"] == "manual"
    assert kwargs["json"]["priority"] == "H"
    assert kwargs["headers"].get("Prefer") == "return=representation"


def test_resolve_decision_patches_by_id_and_stamps_resolved_at():
    client = MagicMock()
    client.patch.return_value = _resp([{"id": "3", "status": "resolved"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        out = decisions.resolve_decision("3", resolution="done")
    assert out["decision"]["status"] == "resolved"
    _, kwargs = client.patch.call_args
    assert kwargs["params"]["id"] == "eq.3"
    assert kwargs["json"]["resolution"] == "done"
    assert "resolved_at" in kwargs["json"]


def test_register_exposes_three_tools():
    mcp = MagicMock()
    tool_decorator = MagicMock(side_effect=lambda f: f)
    mcp.tool.return_value = tool_decorator
    decisions.register(mcp)
    assert mcp.tool.call_count == 3


def test_list_open_decisions_selects_voi_fields():
    client = MagicMock()
    client.get.return_value = _resp([{"id": "1", "title": "X", "status": "open"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        decisions.list_open_decisions()
    _, kwargs = client.get.call_args
    select = kwargs["params"]["select"]
    assert "recommended_action" in select
    assert "confidence" in select
    assert "voi_rationale" in select


def test_upsert_passes_voi_fields_on_insert():
    client = MagicMock()
    client.get.return_value = _resp([])  # nothing existing
    client.post.return_value = _resp([{"id": "2", "title": "Y", "status": "open"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        decisions.upsert_decision(
            "Y",
            recommended_action="Call Leo first.",
            confidence="med",
            voi_rationale="Reaching him before the hire is what makes the play land.",
        )
    _, kwargs = client.post.call_args
    assert kwargs["json"]["recommended_action"] == "Call Leo first."
    assert kwargs["json"]["confidence"] == "med"
    assert kwargs["json"]["voi_rationale"].startswith("Reaching him")


def test_upsert_updates_voi_fields_on_existing_row():
    client = MagicMock()
    client.get.return_value = _resp([{"id": "1", "title": "X", "status": "open"}])
    client.patch.return_value = _resp([{"id": "1", "title": "X", "recommended_action": "Do the thing."}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        out = decisions.upsert_decision("X", recommended_action="Do the thing.")
    client.patch.assert_called_once()
    _, kwargs = client.patch.call_args
    assert kwargs["params"]["id"] == "eq.1"
    assert kwargs["json"]["recommended_action"] == "Do the thing."
    assert out["decision"]["recommended_action"] == "Do the thing."


def test_upsert_existing_row_no_enrichment_still_noops():
    client = MagicMock()
    client.get.return_value = _resp([{"id": "1", "title": "X", "status": "open"}])
    with patch("httpx.Client", return_value=_client_cm(client)):
        out = decisions.upsert_decision("X")  # no enrichment args
    client.post.assert_not_called()
    client.patch.assert_not_called()  # nothing to update -> pure no-op
    assert out["decision"]["id"] == "1"
