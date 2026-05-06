"""
Tests for async support in the _tracked_mcp_tool telemetry wrapper (Fix 5).

The wrapper in mcp_server.py must detect async tool functions and await them
before recording telemetry — otherwise timing is 0ms and errors are invisible.

Run with:
    pytest remote-gateway/tests/test_telemetry_async.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _import_mcp_server():
    """Import mcp_server.py with all external dependencies stubbed.

    Returns (module, recorded_calls) where recorded_calls is a list that
    telemetry.record() appends to — inspect it to verify telemetry behavior.
    """
    # Stub mcp packages (FastMCP + lowlevel)
    import contextvars
    import importlib.util

    for mod_name in (
        "mcp", "mcp.server", "mcp.server.fastmcp",
        "mcp.server.lowlevel", "mcp.server.lowlevel.server",
    ):
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    # request_ctx: ContextVar with no value set — _get_call_ids() returns (None, None)
    sys.modules["mcp.server.lowlevel.server"].request_ctx = contextvars.ContextVar("request_ctx")
    # lifespan: stub as a no-op context manager factory (used for SSE transport setup)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _stub_lifespan(server):  # type: ignore[misc]
        yield

    sys.modules["mcp.server.lowlevel.server"].lifespan = _stub_lifespan

    # FastMCP: mcp.tool() decorator returns fn unchanged for test isolation
    mock_fastmcp_class = MagicMock()
    mock_mcp_instance = MagicMock()
    mock_mcp_instance.tool = MagicMock(side_effect=lambda *a, **kw: (lambda fn: fn))
    mock_fastmcp_class.return_value = mock_mcp_instance
    sys.modules["mcp.server.fastmcp"].FastMCP = mock_fastmcp_class

    # Stub field_registry
    if "field_registry" not in sys.modules:
        mod_fr = types.ModuleType("field_registry")
        mod_fr.registry = MagicMock()
        sys.modules["field_registry"] = mod_fr

    # Stub mcp_proxy
    if "mcp_proxy" not in sys.modules:
        mod_mp = types.ModuleType("mcp_proxy")
        mod_mp.mount_all_proxies = MagicMock(return_value=[])
        sys.modules["mcp_proxy"] = mod_mp
    # Ensure mount_all_proxies exists (may have been set by test_proxy_reliability.py)
    if not hasattr(sys.modules["mcp_proxy"], "mount_all_proxies"):
        sys.modules["mcp_proxy"].mount_all_proxies = MagicMock(return_value=[])

    # Stub telemetry — capture record() calls in a list we can inspect
    recorded: list[dict] = []
    mod_tel = types.ModuleType("telemetry")
    mock_tel = MagicMock()
    mock_tel.record = lambda name, duration_ms, success, exc_type=None, user_id=None, request_id=None, response_size=None, input_body=None, error_message=None, response_preview=None, task_id=None: recorded.append(  # noqa: E501
        {"name": name, "duration_ms": duration_ms, "success": success, "exc_type": exc_type,
         "user_id": user_id, "request_id": request_id, "error_message": error_message,
         "response_preview": response_preview}
    )
    mock_tel.lookup_user = MagicMock(return_value=None)
    mod_tel.telemetry = mock_tel
    sys.modules["telemetry"] = mod_tel

    # Stub tools sub-modules — only inject names that aren't already real packages
    _tools_stubs = (
        "tools", "tools.meta", "tools.notes", "tools.registry",
        "tools._core", "tools._core.onboarding",
        "tools._core.skill_manager", "tools._core.profile_manager",
        "tools._core.task_manager",
    )
    _pre_existing_tools = set(sys.modules.keys()) & set(_tools_stubs)
    for mod_name in _tools_stubs:
        if mod_name not in sys.modules:
            m = types.ModuleType(mod_name)
            m.register = MagicMock()  # type: ignore[attr-defined]
            sys.modules[mod_name] = m
        elif not hasattr(sys.modules[mod_name], "register"):
            sys.modules[mod_name].register = MagicMock()

    path = Path(__file__).parent.parent / "core" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("_mcp_server_for_test", path)
    module = types.ModuleType("_mcp_server_for_test")
    module.__file__ = str(path)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    # Clean up tools stubs so other tests can import the real tools package.
    for mod_name in _tools_stubs:
        if mod_name not in _pre_existing_tools:
            sys.modules.pop(mod_name, None)

    return module, recorded


_server, _recorded = _import_mcp_server()


def setup_function():
    """Clear telemetry records before each test."""
    _recorded.clear()


# ---------------------------------------------------------------------------
# Async branch
# ---------------------------------------------------------------------------


def test_async_tool_wrapper_is_coroutine_function():
    """Wrapping an async function must produce a coroutine function."""
    async def my_async_tool() -> dict:
        return {"ok": True}

    tracked = _server._tracked_mcp_tool()(my_async_tool)
    assert inspect.iscoroutinefunction(tracked), (
        "Wrapped async tool must remain a coroutine function"
    )


def test_async_tool_records_telemetry_after_await():
    """Telemetry must be recorded AFTER the coroutine completes, not before."""
    async def slow_tool() -> dict:
        await asyncio.sleep(0.02)
        return {"result": "ok"}

    tracked = _server._tracked_mcp_tool()(slow_tool)
    result = asyncio.run(tracked())

    assert result == {"result": "ok"}
    assert len(_recorded) == 1
    assert _recorded[0]["name"] == "slow_tool"
    assert _recorded[0]["success"] is True
    assert _recorded[0]["duration_ms"] >= 20, (
        f"Expected >= 20ms (sleep 0.02s), got {_recorded[0]['duration_ms']}ms"
    )


def test_async_tool_records_failure_on_exception():
    """Exceptions in async tools must be recorded and re-raised."""
    async def failing_tool() -> dict:
        raise ValueError("tool broke")

    tracked = _server._tracked_mcp_tool()(failing_tool)

    try:
        asyncio.run(tracked())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError to be re-raised")

    assert len(_recorded) == 1
    assert _recorded[0]["success"] is False
    assert _recorded[0]["exc_type"] == "ValueError"


def test_async_tool_preserves_function_name():
    """functools.wraps must preserve __name__ on the async tracked wrapper."""
    async def named_async_tool() -> dict:
        return {}

    tracked = _server._tracked_mcp_tool()(named_async_tool)
    assert tracked.__name__ == "named_async_tool"


# ---------------------------------------------------------------------------
# Sync branch — verify existing behavior unchanged
# ---------------------------------------------------------------------------


def test_sync_tool_still_works_after_async_branch_added():
    """Sync tools must still be wrapped correctly after the async branch is added."""
    def sync_tool() -> dict:
        return {"sync": True}

    tracked = _server._tracked_mcp_tool()(sync_tool)
    assert not inspect.iscoroutinefunction(tracked), "Sync tool must not become a coroutine"

    result = tracked()
    assert result == {"sync": True}
    assert len(_recorded) == 1
    assert _recorded[0]["name"] == "sync_tool"
    assert _recorded[0]["success"] is True


def test_error_message_captured_on_failure():
    """Telemetry wrapper must pass error_message=str(exc) when a tool raises."""
    async def broken_tool(x: int) -> str:
        raise ValueError("bad input: x must be positive")

    tracked = _server._tracked_mcp_tool()(broken_tool)

    try:
        asyncio.run(tracked(x=-1))
    except ValueError:
        pass

    assert len(_recorded) == 1
    call = _recorded[0]
    assert call["exc_type"] == "ValueError"
    assert call["error_message"] == "bad input: x must be positive"


def test_async_tool_captures_response_preview():
    """response_preview passed to record() must be str(result)[:400]."""
    long_response = "x" * 800

    async def big_tool() -> str:
        return long_response

    tracked = _server._tracked_mcp_tool()(big_tool)
    result = asyncio.run(tracked())

    assert result == long_response
    assert len(_recorded) == 1
    assert _recorded[0]["response_preview"] == "x" * 400
