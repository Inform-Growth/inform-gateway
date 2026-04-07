"""
Tests for proxy_fn reliability:
- Fix 1: exceptions from session.call_tool() are caught and returned as error dicts
          (prevents FastMCP TaskGroup cancellation of sibling calls)
- Fix 3: MCP-level errors (result.isError=True) surface the error message

Run with:
    pytest remote-gateway/tests/test_proxy_reliability.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def _import_proxy():
    """Import mcp_proxy without triggering server startup or requiring mcp package."""
    import importlib.util

    for mod_name in (
        "mcp",
        "mcp.client",
        "mcp.client.sse",
        "mcp.client.stdio",
        "mcp.client.streamable_http",
    ):
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    mcp_stub = sys.modules["mcp"]
    for attr in ("ClientSession", "StdioServerParameters"):
        if not hasattr(mcp_stub, attr):
            setattr(mcp_stub, attr, MagicMock())

    for mod_name, func_names in [
        ("mcp.client.sse", ["sse_client"]),
        ("mcp.client.stdio", ["stdio_client"]),
        ("mcp.client.streamable_http", ["streamable_http_client"]),
    ]:
        mod = sys.modules[mod_name]
        for func_name in func_names:
            if not hasattr(mod, func_name):
                setattr(mod, func_name, MagicMock())

    path = Path(__file__).parent.parent / "core" / "mcp_proxy.py"
    spec = importlib.util.spec_from_file_location("mcp_proxy", path)
    mod = types.ModuleType("mcp_proxy")
    mod.__file__ = str(path)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_proxy = _import_proxy()


def _make_tool(name: str = "search_records") -> MagicMock:
    """Return a minimal mock MCP Tool object."""
    t = MagicMock()
    t.name = name
    t.description = f"A test tool: {name}"
    return t


# ---------------------------------------------------------------------------
# Fix 1 — exception handling in _register_proxy_tool (stdio/SSE)
# ---------------------------------------------------------------------------


def test_proxy_fn_returns_error_dict_on_exception():
    """session.call_tool() raising must not propagate — return error dict instead."""
    mock_server = MagicMock()
    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(side_effect=RuntimeError("connection refused"))

    _proxy._register_proxy_tool(
        mock_server, "apollo", _make_tool("mixed_people_api_search"), mock_session
    )

    proxy_fn = mock_server.add_tool.call_args.args[0]
    result = asyncio.run(proxy_fn())

    assert result.get("is_proxy_error") is True, "Expected is_proxy_error=True in result"
    assert "connection refused" in result.get("error", ""), "Expected error message in result"
    assert result.get("tool") == "mixed_people_api_search", "Expected tool name in result"


def test_proxy_fn_does_not_raise_on_exception():
    """proxy_fn must never raise — TaskGroup safety contract."""
    mock_server = MagicMock()
    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(side_effect=Exception("unexpected upstream failure"))

    _proxy._register_proxy_tool(mock_server, "apollo", _make_tool(), mock_session)

    proxy_fn = mock_server.add_tool.call_args.args[0]
    # Must not raise
    result = asyncio.run(proxy_fn())
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Fix 3 — isError surfacing in _register_proxy_tool (stdio/SSE)
# ---------------------------------------------------------------------------


def test_proxy_fn_surfaces_mcp_error_message():
    """result.isError=True must return error dict with is_mcp_error=True."""
    mock_server = MagicMock()

    mock_content = MagicMock()
    mock_content.text = "Required field missing: name"
    mock_result = MagicMock()
    mock_result.isError = True
    mock_result.content = [mock_content]

    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    _proxy._register_proxy_tool(mock_server, "attio", _make_tool("create_record"), mock_session)

    proxy_fn = mock_server.add_tool.call_args.args[0]
    result = asyncio.run(proxy_fn())

    assert result == {"error": "Required field missing: name", "is_mcp_error": True}


def test_proxy_fn_does_not_flag_successful_result_as_error():
    """A successful result with isError=False must be returned normally."""
    import json

    mock_server = MagicMock()

    mock_content = MagicMock()
    mock_content.text = json.dumps({"id": "rec-123", "name": "Acme"})
    mock_result = MagicMock()
    mock_result.isError = False
    mock_result.content = [mock_content]

    mock_session = MagicMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    _proxy._register_proxy_tool(mock_server, "attio", _make_tool("get_record"), mock_session)

    proxy_fn = mock_server.add_tool.call_args.args[0]
    result = asyncio.run(proxy_fn())

    assert result == {"id": "rec-123", "name": "Acme"}
    assert "is_mcp_error" not in result


# ---------------------------------------------------------------------------
# Fix 1 — exception handling in _register_streamable_http_proxy_tool (HTTP)
# ---------------------------------------------------------------------------


def test_streamable_http_proxy_fn_returns_error_dict_on_exception(monkeypatch):
    """Connection failure in streamable HTTP proxy_fn returns error dict, not raise."""
    mock_server = MagicMock()
    config = {
        "url": "https://mcp.exa.ai/mcp",
        "auth": {"type": "header", "headers": {"x-api-key": "test-key"}},
    }

    _proxy._register_streamable_http_proxy_tool(
        mock_server, "exa", _make_tool("web_search_exa"), "https://mcp.exa.ai/mcp", config
    )

    proxy_fn = mock_server.add_tool.call_args.args[0]

    # Simulate connection failure at the httpx.AsyncClient level
    import unittest.mock as mock
    with mock.patch.object(
        _proxy.httpx, "AsyncClient", side_effect=RuntimeError("no route to host")
    ):
        result = asyncio.run(proxy_fn())

    assert result.get("is_proxy_error") is True
    assert "no route to host" in result.get("error", "")
    assert result.get("tool") == "web_search_exa"


# ---------------------------------------------------------------------------
# Fix 3 — isError surfacing in _register_streamable_http_proxy_tool (HTTP)
# ---------------------------------------------------------------------------


def test_streamable_http_proxy_fn_surfaces_mcp_error():
    """isError=True in streamable HTTP proxy_fn must return is_mcp_error=True."""
    mock_server = MagicMock()
    # Use header auth (not OAuth) to avoid env-var lookups in resolve_auth_headers
    config = {
        "url": "https://mcp.apollo.io/mcp",
        "auth": {"type": "header", "headers": {"x-api-key": "test-key"}},
    }

    _proxy._register_streamable_http_proxy_tool(
        mock_server, "apollo", _make_tool("mixed_people_api_search"),
        "https://mcp.apollo.io/mcp", config
    )

    proxy_fn = mock_server.add_tool.call_args.args[0]

    mock_content = MagicMock()
    mock_content.text = "Rate limit exceeded"
    mock_result = MagicMock()
    mock_result.isError = True
    mock_result.content = [mock_content]

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.initialize = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_transport = MagicMock()
    mock_transport.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    mock_transport.__aexit__ = AsyncMock(return_value=False)

    mock_http_client = MagicMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    import unittest.mock as mock
    # Patch attributes on _proxy directly — they were imported by value at module load time
    with (
        mock.patch.object(_proxy.httpx, "AsyncClient", return_value=mock_http_client),
        mock.patch.object(_proxy, "streamable_http_client", return_value=mock_transport),
        mock.patch.object(_proxy, "ClientSession", return_value=mock_session),
    ):
        result = asyncio.run(proxy_fn())

    assert result == {"error": "Rate limit exceeded", "is_mcp_error": True}
