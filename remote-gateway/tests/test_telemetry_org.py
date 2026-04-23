from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)
from telemetry import TelemetryStore

@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")

def test_get_org_id_falls_back_to_user_id(store):
    store.add_api_key("alice@example.com", "sk-test")
    assert store.get_org_id("alice@example.com") == "alice@example.com"

def test_get_org_id_returns_explicit_org(store):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    assert store.get_org_id("alice@example.com") == "acme"

def test_is_initialized_false_by_default(store):
    assert store.is_initialized("acme") is False

def test_is_initialized_true_after_set(store):
    store.set_initialized("acme")
    assert store.is_initialized("acme") is True

def test_get_org_profile_empty_for_unknown(store):
    assert store.get_org_profile("acme") == {}

def test_update_org_profile_creates_and_patches(store):
    store.update_org_profile("acme", {"tone": "professional", "icp": "SaaS"})
    profile = store.get_org_profile("acme")
    assert profile["tone"] == "professional"
    assert profile["icp"] == "SaaS"

def test_update_org_profile_merges_not_replaces(store):
    store.update_org_profile("acme", {"tone": "professional"})
    store.update_org_profile("acme", {"icp": "SaaS"})
    profile = store.get_org_profile("acme")
    assert profile["tone"] == "professional"
    assert profile["icp"] == "SaaS"
