"""
Tests for TelemetryStore permission methods.

Run with:
    pytest remote-gateway/tests/test_telemetry_permissions.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
# Remove any stub injected by test_telemetry_async.py (which runs at collection
# time and puts a fake `telemetry` module in sys.modules before this file loads).
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(db_path=tmp_path / "test.db")


def test_has_permission_default_true(store):
    """No row in tool_permissions means the user is allowed."""
    assert store.has_permission("alice", "some_tool") is True


def test_has_permission_disabled(store):
    store.add_api_key("alice", "sk-alice")
    store.set_tool_permission("alice", "some_tool", False)
    assert store.has_permission("alice", "some_tool") is False


def test_has_permission_re_enabled(store):
    store.set_tool_permission("alice", "some_tool", False)
    store.set_tool_permission("alice", "some_tool", True)
    assert store.has_permission("alice", "some_tool") is True


def test_has_permission_other_user_unaffected(store):
    store.set_tool_permission("alice", "some_tool", False)
    assert store.has_permission("bob", "some_tool") is True


def test_list_users_returns_created_users(store):
    store.add_api_key("alice@company.com", "sk-alice")
    store.add_api_key("bob@company.com", "sk-bob")
    users = store.list_users()
    user_ids = [u["user_id"] for u in users]
    assert "alice@company.com" in user_ids
    assert "bob@company.com" in user_ids


def test_list_users_includes_call_count(store):
    store.add_api_key("alice@company.com", "sk-alice")
    store.record("health_check", 10, True, user_id="alice@company.com")
    store.record("health_check", 12, True, user_id="alice@company.com")
    users = store.list_users()
    alice = next(u for u in users if u["user_id"] == "alice@company.com")
    assert alice["call_count"] == 2


def test_list_users_empty(store):
    assert store.list_users() == []


def test_delete_user_removes_key(store):
    store.add_api_key("alice@company.com", "sk-alice")
    count = store.delete_user("alice@company.com")
    assert count == 1
    assert store.lookup_user("sk-alice") is None


def test_delete_user_removes_permissions(store):
    store.add_api_key("alice@company.com", "sk-alice")
    store.set_tool_permission("alice@company.com", "some_tool", False)
    store.delete_user("alice@company.com")
    assert store.has_permission("alice@company.com", "some_tool") is True


def test_delete_user_unknown_returns_zero(store):
    assert store.delete_user("nobody@company.com") == 0


def test_get_tool_permissions_returns_explicit_settings(store):
    store.set_tool_permission("alice", "tool_a", False)
    store.set_tool_permission("alice", "tool_b", True)
    perms = store.get_tool_permissions("alice")
    by_tool = {p["tool_name"]: p["enabled"] for p in perms}
    assert by_tool["tool_a"] is False
    assert by_tool["tool_b"] is True


def test_get_tool_permissions_empty_for_new_user(store):
    assert store.get_tool_permissions("nobody") == []


def test_record_stores_input_body(store):
    store.record("health_check", 10, True, input_body='{"q": "hello"}')
    logs = store.raw_logs(limit=1)
    assert logs[0]["input_body"] == '{"q": "hello"}'


def test_stats_includes_avg_input_size(store):
    store.record("health_check", 10, True, input_body='{"q": "hello"}')
    stats = store.stats()
    tool = next(t for t in stats["tools"] if t["name"] == "health_check")
    assert "avg_input_size" in tool
    assert tool["avg_input_size"] > 0


def test_raw_logs_returns_recent_calls(store):
    store.record("tool_a", 10, True, user_id="alice", input_body='{"x": 1}')
    store.record("tool_b", 20, False, user_id="alice", error_type="ValueError")
    logs = store.raw_logs(limit=10)
    assert len(logs) == 2
    names = {log["tool_name"] for log in logs}
    assert names == {"tool_a", "tool_b"}


def test_raw_logs_filters_by_tool(store):
    store.record("tool_a", 10, True)
    store.record("tool_b", 20, True)
    logs = store.raw_logs(tool_name="tool_a")
    assert all(log["tool_name"] == "tool_a" for log in logs)


def test_raw_logs_filters_by_user(store):
    store.record("health_check", 10, True, user_id="alice")
    store.record("health_check", 10, True, user_id="bob")
    logs = store.raw_logs(user_id="alice")
    assert all(log["user_id"] == "alice" for log in logs)


def test_raw_logs_filters_errors_only(store):
    store.record("health_check", 10, True)
    store.record("health_check", 10, False, error_type="ValueError")
    logs = store.raw_logs(success=False)
    assert all(not log["success"] for log in logs)


# ---------------------------------------------------------------------------
# daily_activity_by_user
# ---------------------------------------------------------------------------

def test_daily_activity_by_user_empty(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.daily_activity_by_user(days=30)
    assert result == {"users": [], "days": []}


def test_daily_activity_by_user_single_user(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 20, True, user_id="alice@example.com")
    result = store.daily_activity_by_user(days=30)
    assert result["users"] == ["alice@example.com"]
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert day["alice@example.com"] == 2


def test_daily_activity_by_user_multiple_users_same_day(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    result = store.daily_activity_by_user(days=30)
    assert sorted(result["users"]) == ["alice@example.com", "bob@example.com"]
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert day["alice@example.com"] == 1
    assert day["bob@example.com"] == 2


def test_daily_activity_by_user_absent_user_gets_zero(tmp_path):
    """A user who had no calls on a given day gets 0, not a missing key."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    result = store.daily_activity_by_user(days=30)
    # Both users appear in every day record
    for day in result["days"]:
        assert "alice@example.com" in day
        assert "bob@example.com" in day


def test_daily_activity_by_user_null_user_id_becomes_unknown(tmp_path):
    """Calls with no user_id are grouped under 'unknown'."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True)   # user_id=None
    result = store.daily_activity_by_user(days=30)
    assert "unknown" in result["users"]
    assert result["days"][0]["unknown"] == 1


def test_record_stores_error_message(store):
    store.record("my_tool", 10, False, error_type="ValueError", error_message="bad value: foo")
    logs = store.raw_logs(limit=1)
    assert logs[0]["error_type"] == "ValueError"
    assert logs[0]["error_message"] == "bad value: foo"


def test_record_error_message_none_on_success(store):
    store.record("my_tool", 10, True)
    logs = store.raw_logs(limit=1)
    assert logs[0]["error_message"] is None


def test_record_error_message_missing_param_defaults_none(store):
    # Calling record() without error_message (old callers) must still work.
    store.record("my_tool", 10, False, error_type="Exception")
    logs = store.raw_logs(limit=1)
    assert "error_message" in logs[0]
    assert logs[0]["error_message"] is None


def test_connect_returns_same_connection_object(store):
    """_connect() must return the cached connection — no new object per call."""
    first = store._connect()
    second = store._connect()
    assert first is second, (
        "_connect() returned a different object on the second call. "
        "The connection must be cached and reused."
    )
