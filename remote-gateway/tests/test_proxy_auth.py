"""
Unit tests for resolve_auth_headers and _should_register_tool.

Run with:
    pytest remote-gateway/tests/test_proxy_auth.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import types

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def _import_proxy():
    """Import mcp_proxy without triggering server startup."""
    import importlib.util

    path = Path(__file__).parent.parent / "core" / "mcp_proxy.py"
    spec = importlib.util.spec_from_file_location("mcp_proxy", path)
    mod = types.ModuleType("mcp_proxy")
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# resolve_auth_headers
# ---------------------------------------------------------------------------


def test_resolve_auth_headers_header_type(monkeypatch):
    """auth.type='header' returns resolved header dict."""
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key-123")
    proxy = _import_proxy()
    config = {
        "auth": {
            "type": "header",
            "headers": {"x-api-key": "${EXA_API_KEY}"},
        }
    }
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {"x-api-key": "test-exa-key-123"}


def test_resolve_auth_headers_none_type():
    """auth.type='none' returns empty dict."""
    proxy = _import_proxy()
    config = {"auth": {"type": "none"}}
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {}


def test_resolve_auth_headers_missing_auth_block():
    """Missing auth block defaults to empty dict (no auth)."""
    proxy = _import_proxy()
    config = {"transport": "http", "url": "https://example.com"}
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {}


def test_resolve_auth_headers_oauth_type_opaque_token(monkeypatch):
    """auth.type='oauth' with opaque token (non-JWT) returns Bearer header without refresh."""
    monkeypatch.setenv("TEST_ACCESS_TOKEN", "opaque-token-abc")
    proxy = _import_proxy()
    config = {
        "auth": {
            "type": "oauth",
            "access_token": "${TEST_ACCESS_TOKEN}",
            "token_url": "https://example.com/token",
            "client_id": "test-client",
            "refresh_token": "test-refresh",
        }
    }
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {"Authorization": "Bearer opaque-token-abc"}


def test_resolve_auth_headers_header_multiple_headers(monkeypatch):
    """header type passes multiple headers through."""
    monkeypatch.setenv("API_KEY", "key-val")
    monkeypatch.setenv("TENANT_ID", "tenant-123")
    proxy = _import_proxy()
    config = {
        "auth": {
            "type": "header",
            "headers": {
                "x-api-key": "${API_KEY}",
                "x-tenant-id": "${TENANT_ID}",
            },
        }
    }
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {"x-api-key": "key-val", "x-tenant-id": "tenant-123"}


# ---------------------------------------------------------------------------
# _should_register_tool
# ---------------------------------------------------------------------------


def test_should_register_tool_no_filter():
    """No tools config registers everything."""
    proxy = _import_proxy()
    assert proxy._should_register_tool("search_records", None) is True
    assert proxy._should_register_tool("delete_record", None) is True


def test_should_register_tool_allow_list():
    """Allow list only registers listed tools."""
    proxy = _import_proxy()
    tools_config = {"allow": ["get_file_contents", "create_or_update_file"]}
    assert proxy._should_register_tool("get_file_contents", tools_config) is True
    assert proxy._should_register_tool("create_or_update_file", tools_config) is True
    assert proxy._should_register_tool("delete_repository", tools_config) is False


def test_should_register_tool_deny_list():
    """Deny list blocks listed tools and allows everything else."""
    proxy = _import_proxy()
    tools_config = {"deny": ["delete_repository", "create_repository"]}
    assert proxy._should_register_tool("get_file_contents", tools_config) is True
    assert proxy._should_register_tool("delete_repository", tools_config) is False
    assert proxy._should_register_tool("create_repository", tools_config) is False


def test_should_register_tool_empty_allow_list():
    """Empty allow list registers nothing."""
    proxy = _import_proxy()
    tools_config = {"allow": []}
    assert proxy._should_register_tool("anything", tools_config) is False


def test_should_register_tool_empty_deny_list():
    """Empty deny list registers everything."""
    proxy = _import_proxy()
    tools_config = {"deny": []}
    assert proxy._should_register_tool("anything", tools_config) is True
