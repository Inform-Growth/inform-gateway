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
    from tools._core import profile_manager
    profile_manager.register(_MCP(), store, user_var)
    return collected


def test_profile_get_empty_initially(tools):
    result = tools["profile_get"]()
    assert result["org_id"] == "acme"
    assert result["profile"] == {}


def test_profile_update_sets_fields(tools):
    tools["profile_update"]({"tone": "direct", "icp": "SMB"})
    result = tools["profile_get"]()
    assert result["profile"]["tone"] == "direct"
    assert result["profile"]["icp"] == "SMB"


def test_profile_update_is_additive(tools):
    tools["profile_update"]({"tone": "direct"})
    tools["profile_update"]({"icp": "SMB"})
    result = tools["profile_get"]()
    assert result["profile"]["tone"] == "direct"
    assert result["profile"]["icp"] == "SMB"
