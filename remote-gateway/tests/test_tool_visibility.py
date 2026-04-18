"""Tests for per-user tool visibility filtering and global toggle.

All tests use a temporary SQLite DB via tmp_path — no shared state between tests.
No mcp_server import (startup side effects). The list_tools filter logic is tested
via a local simulation of _filtered_list_tools using filter_visible_tools directly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.telemetry import TelemetryStore


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal stand-in for mcp.types.Tool. Only .name is used by the filter."""

    def __init__(self, name: str) -> None:
        self.name = name


def _make_store(tmp_path: Path) -> TelemetryStore:
    """Return a fresh TelemetryStore backed by a temp DB."""
    return TelemetryStore(db_path=tmp_path / "test.db")


def _simulate_list_tools_filter(
    all_tools: list[_FakeTool],
    store: TelemetryStore,
    user_id: str | None,
) -> list[_FakeTool]:
    """Replicate the _filtered_list_tools logic from mcp_server.py.

    Tests the filtering behaviour without importing mcp_server (which has
    server-startup side effects). The logic under test is filter_visible_tools;
    this helper confirms it is wired the same way the patch will wire it.
    """
    if not store._enabled:
        return all_tools
    visible = store.filter_visible_tools(user_id, [t.name for t in all_tools])
    return [t for t in all_tools if t.name in visible]


# ---------------------------------------------------------------------------
# TelemetryStore — cache loading
# ---------------------------------------------------------------------------


def test_cache_loads_from_db(tmp_path):
    """_load_disabled_cache reads all enabled=0 rows at startup."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "tool_a", False)
    store.set_tool_permission("user_abc", "tool_b", False)
    store.set_tool_permission("user_abc", "tool_c", True)  # should NOT be in cache

    # Create a second store instance to force a fresh cache load from DB
    store2 = TelemetryStore(db_path=tmp_path / "test.db")

    assert "tool_a" in store2._disabled_cache.get("*", set())
    assert "tool_b" in store2._disabled_cache.get("user_abc", set())
    assert "tool_c" not in store2._disabled_cache.get("user_abc", set())


# ---------------------------------------------------------------------------
# TelemetryStore — filter_visible_tools
# ---------------------------------------------------------------------------


def test_filter_hides_globally_disabled(tmp_path):
    """filter_visible_tools removes '*'-disabled tools for all callers."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "hidden_tool", False)

    result = store.filter_visible_tools(None, ["hidden_tool", "visible_tool"])

    assert "hidden_tool" not in result
    assert "visible_tool" in result


def test_filter_hides_user_disabled(tmp_path):
    """filter_visible_tools removes per-user disabled tools for that user only."""
    store = _make_store(tmp_path)
    store.set_tool_permission("user_abc", "user_tool", False)

    result_abc = store.filter_visible_tools("user_abc", ["user_tool", "other_tool"])
    result_other = store.filter_visible_tools("user_xyz", ["user_tool", "other_tool"])

    assert "user_tool" not in result_abc
    assert "other_tool" in result_abc
    assert "user_tool" in result_other  # another user is unaffected


def test_filter_applies_both(tmp_path):
    """Global and per-user disables union — both sets are hidden."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "globally_hidden", False)
    store.set_tool_permission("user_abc", "user_hidden", False)

    result = store.filter_visible_tools(
        "user_abc",
        ["globally_hidden", "user_hidden", "visible"],
    )

    assert result == {"visible"}


def test_filter_shows_all_when_no_disables(tmp_path):
    """No disabled rows → full list returned."""
    store = _make_store(tmp_path)

    result = store.filter_visible_tools("user_abc", ["tool_a", "tool_b", "tool_c"])

    assert result == {"tool_a", "tool_b", "tool_c"}


def test_filter_fails_open_when_disabled(tmp_path):
    """If telemetry is disabled (bad DB path), filter returns full list."""
    store = TelemetryStore(db_path=Path("/nonexistent/path/db.sqlite"))

    result = store.filter_visible_tools("user_abc", ["tool_a", "tool_b"])

    # TelemetryStore._enabled is False, filter_visible_tools must return everything
    assert result == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# TelemetryStore — set_tool_permission cache update
# ---------------------------------------------------------------------------


def test_set_permission_updates_cache(tmp_path):
    """Cache reflects write immediately — no re-query needed."""
    store = _make_store(tmp_path)

    store.set_tool_permission("user_abc", "tool_x", False)
    assert "tool_x" in store._disabled_cache.get("user_abc", set())

    store.set_tool_permission("user_abc", "tool_x", True)
    assert "tool_x" not in store._disabled_cache.get("user_abc", set())


def test_set_global_permission_updates_cache(tmp_path):
    """set_tool_permission with user_id='*' updates the global cache entry."""
    store = _make_store(tmp_path)

    store.set_tool_permission("*", "global_tool", False)
    assert "global_tool" in store._disabled_cache.get("*", set())

    store.set_tool_permission("*", "global_tool", True)
    assert "global_tool" not in store._disabled_cache.get("*", set())


# ---------------------------------------------------------------------------
# TelemetryStore — has_permission global sentinel
# ---------------------------------------------------------------------------


def test_has_permission_blocks_global(tmp_path):
    """has_permission returns False for a '*'-disabled tool regardless of user."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "blocked_tool", False)

    assert not store.has_permission("user_abc", "blocked_tool")
    assert not store.has_permission("user_xyz", "blocked_tool")
    assert not store.has_permission("admin", "blocked_tool")


# ---------------------------------------------------------------------------
# list_tools filter simulation
# ---------------------------------------------------------------------------


def test_list_tools_filtered_by_user(tmp_path):
    """Authenticated user sees global disables + their own disables removed."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "globally_hidden", False)
    store.set_tool_permission("user_abc", "user_hidden", False)

    all_tools = [
        _FakeTool("globally_hidden"),
        _FakeTool("user_hidden"),
        _FakeTool("visible_tool"),
    ]

    result = _simulate_list_tools_filter(all_tools, store, "user_abc")

    assert len(result) == 1
    assert result[0].name == "visible_tool"


def test_list_tools_unauthenticated(tmp_path):
    """Unauthenticated (user_id=None) sees only global disables applied."""
    store = _make_store(tmp_path)
    store.set_tool_permission("*", "globally_hidden", False)
    store.set_tool_permission("user_abc", "user_hidden", False)

    all_tools = [
        _FakeTool("globally_hidden"),
        _FakeTool("user_hidden"),
        _FakeTool("visible_tool"),
    ]

    result = _simulate_list_tools_filter(all_tools, store, None)

    assert len(result) == 2
    assert {t.name for t in result} == {"user_hidden", "visible_tool"}
