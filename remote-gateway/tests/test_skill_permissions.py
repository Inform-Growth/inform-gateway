"""Tests for skill_permissions table and TelemetryStore methods."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


def test_skill_permissions_table_exists(store):
    """skill_permissions table must be created on init."""
    conn = store._connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_permissions'"
    ).fetchone()
    assert row is not None


def test_is_skill_enabled_default_true(store):
    """No row means the skill is allowed."""
    assert store.is_skill_enabled("alice", "briefing") is True


def test_is_skill_enabled_user_disabled(store):
    store.set_skill_permission("alice", "briefing", False)
    assert store.is_skill_enabled("alice", "briefing") is False


def test_is_skill_enabled_other_user_unaffected(store):
    store.set_skill_permission("alice", "briefing", False)
    assert store.is_skill_enabled("bob", "briefing") is True


def test_is_skill_enabled_global_star_disabled(store):
    store.set_skill_permission("*", "briefing", False)
    assert store.is_skill_enabled("alice", "briefing") is False
    assert store.is_skill_enabled("bob", "briefing") is False


def test_is_skill_enabled_user_override_beats_global(store):
    store.set_skill_permission("*", "briefing", False)
    store.set_skill_permission("alice", "briefing", True)
    assert store.is_skill_enabled("alice", "briefing") is True
    assert store.is_skill_enabled("bob", "briefing") is False
