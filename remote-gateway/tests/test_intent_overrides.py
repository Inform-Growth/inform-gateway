"""Tests for tool_intent_overrides table and TelemetryStore methods."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore, INTENT_NEVER_REQUIRED  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


def test_intent_overrides_table_exists(store):
    conn = store._connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_intent_overrides'"
    ).fetchone()
    assert row is not None


def test_intent_never_required_contains_bootstrap_tools():
    """The hard-block list must include every bootstrap tool."""
    expected = {
        "setup_start", "setup_save_profile", "setup_complete",
        "health_check",
        "declare_intent", "complete_task", "get_tasks",
        "get_operator_instructions", "create_user",
        "profile_get", "profile_update",
        "list_prompts", "get_prompt",
    }
    assert expected.issubset(INTENT_NEVER_REQUIRED)
