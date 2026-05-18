"""Tests for skill_permissions table and TelemetryStore methods."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))



def test_skill_permissions_table_exists(store):
    """skill_permissions table must be created on init."""
    with store._cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'skill_permissions'"
        )
        row = cur.fetchone()
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


def test_get_skill_permissions_returns_explicit_rows(store):
    store.set_skill_permission("alice", "briefing", False)
    store.set_skill_permission("alice", "summary", True)
    rows = store.get_skill_permissions("alice")
    by_name = {r["skill_name"]: r["enabled"] for r in rows}
    assert by_name == {"briefing": False, "summary": True}


def test_get_skill_permissions_empty_for_unknown_user(store):
    assert store.get_skill_permissions("nobody") == []


def test_filter_visible_skills_hides_globally_disabled(store):
    store.set_skill_permission("*", "briefing", False)
    visible = store.filter_visible_skills("alice", ["briefing", "summary"])
    assert visible == {"summary"}


def test_filter_visible_skills_hides_user_disabled(store):
    store.set_skill_permission("alice", "briefing", False)
    visible = store.filter_visible_skills("alice", ["briefing", "summary"])
    assert visible == {"summary"}


def test_filter_visible_skills_other_user_unaffected(store):
    store.set_skill_permission("alice", "briefing", False)
    visible = store.filter_visible_skills("bob", ["briefing", "summary"])
    assert visible == {"briefing", "summary"}
