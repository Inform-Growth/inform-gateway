"""Tests for skill embedding behavior in skill_create and skill_update."""
from __future__ import annotations

import contextvars
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.modules.pop("telemetry", None)


@pytest.fixture()
def user_var():
    var = contextvars.ContextVar("_current_user", default=None)
    var.set("alice@example.com")
    return var


def _make_tools(store, user_var, embed_fn=None):
    collected = {}

    class _MCP:
        def tool(self):
            def decorator(fn):
                collected[fn.__name__] = fn
                return fn
            return decorator

    from tools._core import skill_manager
    skill_manager.register(_MCP(), store, user_var, embed_fn=embed_fn)
    return collected


def test_skill_create_calls_embed_fn_with_name_and_description(store, user_var):
    calls = []

    def fake_embed(text):
        calls.append(text)
        return [0.1] * 1536

    tools = _make_tools(store, user_var, embed_fn=fake_embed)
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    assert len(calls) == 1
    assert "briefing" in calls[0]
    assert "Morning summary" in calls[0]


def test_skill_create_without_embed_fn_still_works(store, user_var):
    tools = _make_tools(store, user_var, embed_fn=None)
    result = tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    assert result["name"] == "briefing"


def test_skill_update_re_embeds_when_description_changes(store, user_var):
    calls = []

    def fake_embed(text):
        calls.append(text)
        return [0.1] * 1536

    tools = _make_tools(store, user_var, embed_fn=fake_embed)
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    calls.clear()

    tools["skill_update"]("briefing", description="Evening recap")
    assert len(calls) == 1
    assert "Evening recap" in calls[0]


def test_skill_update_skips_embed_when_description_unchanged(store, user_var):
    """No re-embed when description is identical — hash-gate."""
    calls = []

    def fake_embed(text):
        calls.append(text)
        return [0.1] * 1536

    tools = _make_tools(store, user_var, embed_fn=fake_embed)
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    calls.clear()

    tools["skill_update"]("briefing", description="Morning summary")  # same
    assert len(calls) == 0


def test_skill_update_skips_embed_when_only_template_changes(store, user_var):
    """No re-embed when only prompt_template changes."""
    calls = []

    def fake_embed(text):
        calls.append(text)
        return [0.1] * 1536

    tools = _make_tools(store, user_var, embed_fn=fake_embed)
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    calls.clear()

    tools["skill_update"]("briefing", prompt_template="New template {x}")
    assert len(calls) == 0


def test_skill_create_embed_failure_does_not_raise(store, user_var):
    """Embed failure is silently ignored — skill is still created."""

    def failing_embed(text):
        raise RuntimeError("OpenAI unavailable")

    tools = _make_tools(store, user_var, embed_fn=failing_embed)
    result = tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")
    assert result["name"] == "briefing"


def test_skill_update_embed_failure_does_not_raise(store, user_var):
    """Embed failure during update is silently ignored."""

    def failing_embed(text):
        raise RuntimeError("OpenAI unavailable")

    tools = _make_tools(store, user_var, embed_fn=failing_embed)
    tools["skill_create"]("briefing", "Morning summary", "Summarize {topic}")

    # Should not raise even though embed_fn throws
    result = tools["skill_update"]("briefing", description="Evening recap")
    assert result["name"] == "briefing"
