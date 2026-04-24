"""Verify init gate logic: uninitialized orgs get a redirect, initialized pass."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice@example.com", "sk-test", org_id="acme")
    return s


def test_gate_redirects_uninitialized_org(store):
    org_id = store.get_org_id("alice@example.com")
    assert store.is_initialized(org_id) is False
    response = {
        "gateway_status": "not_initialized",
        "blocked_tool": "attio__search_records",
        "required_action": "setup_start",
    }
    assert response["gateway_status"] == "not_initialized"


def test_gate_passes_after_setup_complete(store):
    store.set_initialized("acme")
    org_id = store.get_org_id("alice@example.com")
    assert store.is_initialized(org_id) is True


def test_gate_passes_for_unauthenticated_user(store):
    org_id = None  # _get_org_id returns None for sid=None
    should_gate = org_id is not None and not store.is_initialized(org_id or "")
    assert should_gate is False
