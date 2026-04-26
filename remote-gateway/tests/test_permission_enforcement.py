"""
Tests for per-user tool permission enforcement in the telemetry patch.

The _tracked_mcp_tool wrapper must check _telemetry.has_permission(user_id, tool_name)
before calling the tool, and raise PermissionError if it returns False.

Run with:
    pytest remote-gateway/tests/test_permission_enforcement.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _import_server_with_permission_mock(has_permission_return: bool):
    """Import mcp_server with all deps stubbed and has_permission returning the given value."""
    import contextvars
    import importlib.util

    mod_name = f"_mcp_server_perm_{has_permission_return}"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    for dep in (
        "mcp", "mcp.server", "mcp.server.fastmcp",
        "mcp.server.lowlevel", "mcp.server.lowlevel.server",
    ):
        sys.modules.setdefault(dep, types.ModuleType(dep))

    sys.modules["mcp.server.lowlevel.server"].request_ctx = contextvars.ContextVar("request_ctx")

    mock_fastmcp_class = MagicMock()
    mock_mcp_instance = MagicMock()
    mock_mcp_instance.tool = MagicMock(side_effect=lambda *a, **kw: (lambda fn: fn))
    mock_fastmcp_class.return_value = mock_mcp_instance
    sys.modules["mcp.server.fastmcp"].FastMCP = mock_fastmcp_class

    if "field_registry" not in sys.modules:
        fr = types.ModuleType("field_registry")
        fr.registry = MagicMock()
        sys.modules["field_registry"] = fr

    # Remove cached mcp_proxy so it gets re-stubbed fresh each time
    sys.modules.pop("mcp_proxy", None)
    mp = types.ModuleType("mcp_proxy")
    mp.mount_all_proxies = MagicMock(return_value=[])
    sys.modules["mcp_proxy"] = mp

    mock_tel = MagicMock()
    mock_tel.record = MagicMock()
    mock_tel.lookup_user = MagicMock(return_value="alice")
    mock_tel.has_permission = MagicMock(return_value=has_permission_return)
    mock_tel.is_initialized = MagicMock(return_value=True)
    mock_tel.get_task = MagicMock(
        return_value={"task_id": "t1", "user_id": "alice", "status": "active"}
    )
    mod_tel = types.ModuleType("telemetry")
    mod_tel.telemetry = mock_tel
    sys.modules["telemetry"] = mod_tel

    for tool_mod in ("tools", "tools.meta", "tools.notes", "tools.registry", "tools.attio"):
        if tool_mod not in sys.modules:
            m = types.ModuleType(tool_mod)
            sys.modules[tool_mod] = m
        if not hasattr(sys.modules[tool_mod], "register"):
            sys.modules[tool_mod].register = MagicMock()

    path = Path(__file__).parent.parent / "core" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = types.ModuleType(mod_name)
    module.__file__ = str(path)
    spec.loader.exec_module(module)
    return module, mock_tel


def test_permission_denied_sync_raises_permission_error():
    """Sync tool must raise PermissionError when user has it disabled."""
    server, mock_tel = _import_server_with_permission_mock(has_permission_return=False)

    def my_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_tool)

    token = server._current_user.set("alice")
    try:
        try:
            tracked(task_id="t1")
        except PermissionError as exc:
            assert "my_tool" in str(exc)
        else:
            raise AssertionError("Expected PermissionError")
    finally:
        server._current_user.reset(token)


def test_permission_denied_async_raises_permission_error():
    """Async tool must raise PermissionError when user has it disabled."""
    server, mock_tel = _import_server_with_permission_mock(has_permission_return=False)

    async def my_async_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_async_tool)

    token = server._current_user.set("alice")
    try:
        try:
            asyncio.run(tracked(task_id="t1"))
        except PermissionError as exc:
            assert "my_async_tool" in str(exc)
        else:
            raise AssertionError("Expected PermissionError")
    finally:
        server._current_user.reset(token)


def test_permission_allowed_sync_calls_through():
    """Sync tool must execute normally when has_permission returns True."""
    server, _ = _import_server_with_permission_mock(has_permission_return=True)

    def my_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_tool)
    token = server._current_user.set("alice")
    try:
        result = tracked(task_id="t1")
        assert result == {"ok": True}
    finally:
        server._current_user.reset(token)


def test_unauthenticated_user_not_blocked():
    """When user_id is None (no API key), the permission check must be skipped."""
    server, mock_tel = _import_server_with_permission_mock(has_permission_return=False)

    def my_tool() -> dict:
        return {"ok": True}

    tracked = server._tracked_mcp_tool()(my_tool)
    # _current_user is None by default — no permission check should run
    result = tracked()
    assert result == {"ok": True}
    mock_tel.has_permission.assert_not_called()
