"""Test that tool hint enrichment attaches meta to successful responses."""
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
    s.set_initialized("acme")
    return s


def test_enrich_wraps_result_when_hint_exists(store):
    store.upsert_tool_hint(
        "acme", "health_check",
        interpretation_hint="Server is live",
        usage_rules="Call to verify connectivity",
        data_sensitivity="public",
    )
    result = {"status": "ok"}
    hint = store.get_tool_hint("acme", "health_check")
    if hint:
        enriched = {
            "data": result,
            "meta": {
                "interpretation_hint": hint.get("interpretation_hint"),
                "usage_rules": hint.get("usage_rules"),
                "data_sensitivity": hint.get("data_sensitivity"),
            }
        }
    else:
        enriched = result
    assert enriched["data"] == {"status": "ok"}
    assert enriched["meta"]["interpretation_hint"] == "Server is live"


def test_enrich_passes_through_when_no_hint(store):
    result = {"status": "ok"}
    hint = store.get_tool_hint("acme", "no_hint_tool")
    enriched = {"data": result, "meta": {}} if hint else result
    assert enriched == {"status": "ok"}


def test_hint_cache_invalidated_on_upsert(store):
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v1")
    _ = store.get_tool_hint("acme", "health_check")  # loads cache
    store.upsert_tool_hint("acme", "health_check", interpretation_hint="v2")
    assert store.get_tool_hint("acme", "health_check")["interpretation_hint"] == "v2"
