from __future__ import annotations
import contextvars
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.modules.pop("telemetry", None)

from telemetry import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    s = TelemetryStore(db_path=tmp_path / "test.db")
    s.add_api_key("alice@example.com", "sk-test", org_id="acme")
    return s


@pytest.fixture()
def user_var():
    var = contextvars.ContextVar("_current_user", default=None)
    var.set("alice@example.com")
    return var


@pytest.fixture()
def tools(store, user_var):
    collected = {}
    class _MCP:
        def tool(self):
            def decorator(fn):
                collected[fn.__name__] = fn
                return fn
            return decorator
    from tools._core import skill_manager
    skill_manager.register(_MCP(), store, user_var)
    return collected


def test_skill_list_empty_initially(tools):
    assert tools["skill_list"]() == []


def test_skill_create_and_list(tools):
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    skills = tools["skill_list"]()
    assert len(skills) == 1
    assert skills[0]["name"] == "briefing"


def test_skill_update_changes_template(tools):
    tools["skill_create"]("briefing", "Morning summary", "old")
    tools["skill_update"]("briefing", prompt_template="new {var}")
    skills = tools["skill_list"]()
    assert skills[0]["prompt_template"] == "new {var}"


def test_skill_delete_removes_from_list(tools):
    tools["skill_create"]("briefing", "Morning summary", "template")
    tools["skill_delete"]("briefing")
    assert tools["skill_list"]() == []


def test_run_skill_renders_template(tools):
    tools["skill_create"]("greet", "Greeting", "Hello {name}, welcome to {place}!")
    result = tools["run_skill"]("greet", {"name": "Alice", "place": "Acme"})
    assert result == "Hello Alice, welcome to Acme!"


def test_run_skill_raises_for_unknown_skill(tools):
    with pytest.raises(ValueError, match="not found"):
        tools["run_skill"]("nonexistent", {})


def test_skill_update_raises_for_unknown_skill(tools):
    with pytest.raises(ValueError, match="not found"):
        tools["skill_update"]("nonexistent", description="new")
