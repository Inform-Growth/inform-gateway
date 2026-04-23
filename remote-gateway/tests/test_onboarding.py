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
    return TelemetryStore(db_path=tmp_path / "test.db")


@pytest.fixture()
def user_var():
    return contextvars.ContextVar("_current_user", default=None)


@pytest.fixture()
def mcp_stub(store, user_var):
    tools = {}
    class _MCP:
        def tool(self):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator
    stub = _MCP()
    from tools._core import onboarding
    onboarding.register(stub, store, user_var)
    return tools


def test_setup_start_returns_not_initialized(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    result = mcp_stub["setup_start"]()
    assert result["initialized"] is False
    assert result["org_id"] == "acme"


def test_setup_save_profile_persists(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    result = mcp_stub["setup_save_profile"]({"tone": "casual"})
    assert result["current_profile"]["tone"] == "casual"


def test_setup_complete_marks_initialized(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    mcp_stub["setup_complete"]()
    assert store.is_initialized("acme") is True


def test_setup_start_shows_initialized_after_complete(mcp_stub, store, user_var):
    store.add_api_key("alice@example.com", "sk-test", org_id="acme")
    user_var.set("alice@example.com")
    mcp_stub["setup_complete"]()
    result = mcp_stub["setup_start"]()
    assert result["initialized"] is True
