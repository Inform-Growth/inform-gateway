"""Tests for suggested_skills in declare_intent response."""
from __future__ import annotations
import contextvars
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.modules.pop("telemetry", None)


@pytest.fixture()
def user_var():
    var = contextvars.ContextVar("_current_user", default=None)
    var.set("alice@example.com")
    return var


def _make_task_tools(store, user_var, embed_fn=None):
    collected = {}

    class _MCP:
        def tool(self):
            def decorator(fn):
                collected[fn.__name__] = fn
                return fn
            return decorator

    from tools._core import task_manager
    task_manager.register(_MCP(), store, user_var, embed_fn=embed_fn)
    return collected


def _declare(tools, goal="Search Attio for top accounts in Vancouver", steps=None):
    return tools["declare_intent"](
        goal=goal,
        steps=steps or ["search attio", "export results"],
    )


def test_declare_intent_always_has_suggested_skills_field(store, user_var):
    tools = _make_task_tools(store, user_var)
    result = _declare(tools)
    assert "suggested_skills" in result


def test_declare_intent_suggested_skills_empty_without_embed_fn(store, user_var):
    tools = _make_task_tools(store, user_var)
    result = _declare(tools)
    assert result["suggested_skills"] == []


def test_declare_intent_suggested_skills_empty_when_embed_returns_none(store, user_var):
    tools = _make_task_tools(store, user_var, embed_fn=lambda _: None)
    result = _declare(tools)
    assert result["suggested_skills"] == []


def test_declare_intent_returns_skill_matches_above_floor(store, user_var):
    """Search results with high cosine appear in suggested_skills."""
    embed_fn = lambda _: [0.1] * 1536  # noqa: E731
    fake_match = {"name": "crm_search", "description": "Search CRM records", "cosine": 0.9}

    tools = _make_task_tools(store, user_var, embed_fn=embed_fn)
    with patch.object(store, "search_skills_by_embedding", return_value=[fake_match]):
        result = _declare(tools, goal="Search CRM for accounts in Vancouver")

    assert len(result["suggested_skills"]) == 1
    assert result["suggested_skills"][0]["name"] == "crm_search"
    assert "score" in result["suggested_skills"][0]
    score = result["suggested_skills"][0]["score"]
    assert 0.0 < score <= 1.0


def test_declare_intent_filters_skills_below_floor(store, user_var):
    """Skills with hybrid score below floor are excluded."""
    embed_fn = lambda _: [0.1] * 1536  # noqa: E731
    # cosine=0.1, disjoint words → hybrid ≈ 0.08, well below 0.35 floor
    fake_match = {"name": "irrelevant_skill", "description": "xyz abc foo", "cosine": 0.1}

    tools = _make_task_tools(store, user_var, embed_fn=embed_fn)
    with patch.object(store, "search_skills_by_embedding", return_value=[fake_match]):
        result = _declare(tools, goal="research leads attio search")

    assert result["suggested_skills"] == []


def test_declare_intent_suggested_skills_empty_on_embed_error(store, user_var):
    """Embed failure never blocks task creation — suggested_skills is empty."""
    def failing_embed(_):
        raise RuntimeError("API unavailable")

    tools = _make_task_tools(store, user_var, embed_fn=failing_embed)
    result = _declare(tools)
    assert result.get("task_id")  # task was created
    assert result["suggested_skills"] == []


def test_declare_intent_task_still_created_when_search_fails(store, user_var):
    """DB search failure never blocks task creation."""
    embed_fn = lambda _: [0.1] * 1536  # noqa: E731

    tools = _make_task_tools(store, user_var, embed_fn=embed_fn)
    with patch.object(store, "search_skills_by_embedding", side_effect=RuntimeError("DB down")):
        result = _declare(tools)

    assert result.get("task_id")
    assert result["suggested_skills"] == []


def test_declare_intent_suggested_skills_scores_are_rounded(store, user_var):
    """Scores are rounded to 3 decimal places."""
    embed_fn = lambda _: [0.1] * 1536  # noqa: E731
    fake_match = {"name": "crm_search", "description": "Search CRM records", "cosine": 0.87654321}

    tools = _make_task_tools(store, user_var, embed_fn=embed_fn)
    with patch.object(store, "search_skills_by_embedding", return_value=[fake_match]):
        result = _declare(tools, goal="Search CRM for accounts")

    if result["suggested_skills"]:
        score = result["suggested_skills"][0]["score"]
        assert score == round(score, 3)


def test_suggested_skills_includes_description(store, user_var):
    """Each suggested skill entry includes the skill description."""
    embed_fn = lambda _: [0.1] * 1536  # noqa: E731
    fake_match = {"name": "crm_search", "description": "Search CRM records by name or domain", "cosine": 0.9}

    tools = _make_task_tools(store, user_var, embed_fn=embed_fn)
    with patch.object(store, "search_skills_by_embedding", return_value=[fake_match]):
        result = _declare(tools, goal="Search CRM for accounts in Vancouver")

    assert len(result["suggested_skills"]) == 1
    assert result["suggested_skills"][0]["description"] == "Search CRM records by name or domain"


def test_declare_intent_includes_skill_suggestion_instruction_when_skills_present(store, user_var):
    """Response includes skill_suggestion_instruction when suggested_skills is non-empty."""
    embed_fn = lambda _: [0.1] * 1536  # noqa: E731
    fake_match = {"name": "crm_search", "description": "Search CRM records", "cosine": 0.9}

    tools = _make_task_tools(store, user_var, embed_fn=embed_fn)
    with patch.object(store, "search_skills_by_embedding", return_value=[fake_match]):
        result = _declare(tools, goal="Search CRM for accounts in Vancouver")

    assert "skill_suggestion_instruction" in result
    assert isinstance(result["skill_suggestion_instruction"], str)
    assert len(result["skill_suggestion_instruction"]) > 0


def test_declare_intent_no_skill_suggestion_instruction_when_no_skills(store, user_var):
    """skill_suggestion_instruction is absent when suggested_skills is empty."""
    tools = _make_task_tools(store, user_var)  # no embed_fn → empty suggestions
    result = _declare(tools)

    assert "skill_suggestion_instruction" not in result
