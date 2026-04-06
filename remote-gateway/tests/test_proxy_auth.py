"""
Unit tests for resolve_auth_headers and _should_register_tool.

Run with:
    pytest remote-gateway/tests/test_proxy_auth.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path


def _import_proxy():
    """Import mcp_proxy without triggering server startup or requiring mcp package."""
    import importlib.util
    import unittest.mock as mock

    # Stub out the MCP client modules imported at module level in mcp_proxy.py
    for mod_name in (
        "mcp",
        "mcp.client",
        "mcp.client.sse",
        "mcp.client.stdio",
        "mcp.client.streamable_http",
    ):
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    # Stub top-level classes in mcp
    mcp_stub = sys.modules["mcp"]
    for attr in ("ClientSession", "StdioServerParameters"):
        if not hasattr(mcp_stub, attr):
            setattr(mcp_stub, attr, mock.MagicMock())

    # Stub client functions
    for mod_name, func_names in [
        ("mcp.client.sse", ["sse_client"]),
        ("mcp.client.stdio", ["stdio_client"]),
        ("mcp.client.streamable_http", ["streamable_http_client"]),
    ]:
        mod = sys.modules[mod_name]
        for func_name in func_names:
            if not hasattr(mod, func_name):
                setattr(mod, func_name, mock.MagicMock())

    path = Path(__file__).parent.parent / "core" / "mcp_proxy.py"
    spec = importlib.util.spec_from_file_location("mcp_proxy", path)
    mod = types.ModuleType("mcp_proxy")
    mod.__file__ = str(path)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_proxy = _import_proxy()


# ---------------------------------------------------------------------------
# resolve_auth_headers
# ---------------------------------------------------------------------------


def test_resolve_auth_headers_header_type(monkeypatch):
    """auth.type='header' returns resolved header dict."""
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key-123")
    config = {
        "auth": {
            "type": "header",
            "headers": {"x-api-key": "${EXA_API_KEY}"},
        }
    }
    result = asyncio.run(_proxy.resolve_auth_headers(config))
    assert result == {"x-api-key": "test-exa-key-123"}


def test_resolve_auth_headers_none_type():
    """auth.type='none' returns empty dict."""
    config = {"auth": {"type": "none"}}
    result = asyncio.run(_proxy.resolve_auth_headers(config))
    assert result == {}


def test_resolve_auth_headers_missing_auth_block():
    """Missing auth block defaults to empty dict (no auth)."""
    config = {"transport": "http", "url": "https://example.com"}
    result = asyncio.run(_proxy.resolve_auth_headers(config))
    assert result == {}


def test_resolve_auth_headers_oauth_type_opaque_token(monkeypatch):
    """auth.type='oauth' with opaque token (non-JWT) returns Bearer header without refresh."""
    monkeypatch.setenv("TEST_ACCESS_TOKEN", "opaque-token-abc")
    config = {
        "auth": {
            "type": "oauth",
            "access_token": "${TEST_ACCESS_TOKEN}",
            "token_url": "https://example.com/token",
            "client_id": "test-client",
            "refresh_token": "test-refresh",
        }
    }
    result = asyncio.run(_proxy.resolve_auth_headers(config))
    assert result == {"Authorization": "Bearer opaque-token-abc"}


def test_resolve_auth_headers_header_multiple_headers(monkeypatch):
    """header type passes multiple headers through."""
    monkeypatch.setenv("API_KEY", "key-val")
    monkeypatch.setenv("TENANT_ID", "tenant-123")
    config = {
        "auth": {
            "type": "header",
            "headers": {
                "x-api-key": "${API_KEY}",
                "x-tenant-id": "${TENANT_ID}",
            },
        }
    }
    result = asyncio.run(_proxy.resolve_auth_headers(config))
    assert result == {"x-api-key": "key-val", "x-tenant-id": "tenant-123"}


# ---------------------------------------------------------------------------
# _should_register_tool
# ---------------------------------------------------------------------------


def test_should_register_tool_no_filter():
    """No tools config registers everything."""
    assert _proxy._should_register_tool("search_records", None) is True, (
        "Expected 'search_records' to be registered (no filter)"
    )
    assert _proxy._should_register_tool("delete_record", None) is True, (
        "Expected 'delete_record' to be registered (no filter)"
    )


def test_should_register_tool_allow_list():
    """Allow list only registers listed tools."""
    tools_config = {"allow": ["get_file_contents", "create_or_update_file"]}
    assert _proxy._should_register_tool("get_file_contents", tools_config) is True, (
        "Expected 'get_file_contents' to be registered (in allow list)"
    )
    assert _proxy._should_register_tool("create_or_update_file", tools_config) is True, (
        "Expected 'create_or_update_file' to be registered (in allow list)"
    )
    assert _proxy._should_register_tool("delete_repository", tools_config) is False, (
        "Expected 'delete_repository' to be blocked (not in allow list)"
    )


def test_should_register_tool_deny_list():
    """Deny list blocks listed tools and allows everything else."""
    tools_config = {"deny": ["delete_repository", "create_repository"]}
    assert _proxy._should_register_tool("get_file_contents", tools_config) is True, (
        "Expected 'get_file_contents' to be registered (not in deny list)"
    )
    assert _proxy._should_register_tool("delete_repository", tools_config) is False, (
        "Expected 'delete_repository' to be blocked (in deny list)"
    )
    assert _proxy._should_register_tool("create_repository", tools_config) is False, (
        "Expected 'create_repository' to be blocked (in deny list)"
    )


def test_should_register_tool_empty_allow_list():
    """Empty allow list registers nothing."""
    tools_config = {"allow": []}
    assert _proxy._should_register_tool("anything", tools_config) is False, (
        "Expected 'anything' to be blocked (empty allow list)"
    )


def test_should_register_tool_empty_deny_list():
    """Empty deny list registers everything."""
    tools_config = {"deny": []}
    assert _proxy._should_register_tool("anything", tools_config) is True, (
        "Expected 'anything' to be registered (empty deny list)"
    )
