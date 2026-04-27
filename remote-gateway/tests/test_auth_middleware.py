"""
Tests for _AuthMiddleware._extract_key().

The method must extract the API key from:
  1. Authorization: Bearer <key> header
  2. ?api_key=<key> query parameter (fallback)

Run with:
    pytest remote-gateway/tests/test_auth_middleware.py -v
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_extract_key():
    """Extract _AuthMiddleware._extract_key without triggering server startup."""
    # Stub every heavy import mcp_server.py touches at module level.
    # Track which modules we inject so we can remove them afterwards and avoid
    # polluting sys.modules for other test files (e.g. test_delete_note_retry.py
    # imports the real tools.notes; leaving a stub would break it).
    stubs = [
        "mcp", "mcp.server", "mcp.server.fastmcp",
        "mcp.server.lowlevel", "mcp.server.lowlevel.server",
        "field_registry", "mcp_proxy", "telemetry",
        "tools", "tools.apollo", "tools.attio", "tools.email_tools",
        "tools.meta", "tools.notes", "tools.registry", "tools.wiza",
        "tools._core", "tools._core.onboarding", "tools._core.profile_manager",
        "tools._core.skill_manager", "tools._core.task_manager",
    ]
    _injected: list[str] = []
    for mod in stubs:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
            _injected.append(mod)

    sys.modules["telemetry"].telemetry = MagicMock()
    sys.modules["field_registry"].registry = MagicMock()
    sys.modules["mcp.server.lowlevel.server"].request_ctx = MagicMock()
    sys.modules["mcp.server.lowlevel.server"].lifespan = MagicMock()
    fastmcp_mock = MagicMock(return_value=MagicMock())
    sys.modules["mcp.server.fastmcp"].FastMCP = fastmcp_mock
    sys.modules["mcp_proxy"].mount_all_proxies = MagicMock()

    path = Path(__file__).parent.parent / "core" / "mcp_server.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("mcp_server_isolated", path)
    mod = types.ModuleType("mcp_server_isolated")
    mod.__file__ = str(path)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        pass  # startup side-effects may fail; we only need _AuthMiddleware

    extract_key = mod._AuthMiddleware._extract_key

    # Clean up injected stubs so later test files can import real modules.
    for mod_name in _injected:
        sys.modules.pop(mod_name, None)

    return extract_key


_extract_key = _load_extract_key()


def _scope(headers: list[tuple[bytes, bytes]], qs: str = "") -> dict:
    return {"type": "http", "headers": headers, "query_string": qs.encode()}


# ---------------------------------------------------------------------------
# Bearer token from Authorization header
# ---------------------------------------------------------------------------

def test_extract_key_from_bearer_header():
    assert _extract_key(_scope([(b"authorization", b"Bearer sk-abc123")])) == "sk-abc123"


def test_extract_key_bearer_case_insensitive():
    assert _extract_key(_scope([(b"authorization", b"BEARER sk-upper")])) == "sk-upper"


def test_extract_key_returns_none_for_non_bearer_auth():
    """Non-Bearer Authorization header must fall through to query param check."""
    assert _extract_key(_scope([(b"authorization", b"Basic dXNlcjpwYXNz")])) is None


def test_extract_key_returns_none_for_empty_bearer():
    assert _extract_key(_scope([(b"authorization", b"Bearer ")])) is None


# ---------------------------------------------------------------------------
# api_key query parameter fallback
# ---------------------------------------------------------------------------

def test_extract_key_from_query_param():
    assert _extract_key(_scope([], qs="api_key=sk-queryparam")) == "sk-queryparam"


def test_extract_key_query_param_among_others():
    assert _extract_key(_scope([], qs="foo=bar&api_key=sk-qp2&baz=qux")) == "sk-qp2"


def test_extract_key_returns_none_when_no_key():
    assert _extract_key(_scope([], qs="foo=bar")) is None


def test_extract_key_returns_none_for_empty_scope():
    assert _extract_key({"type": "http", "headers": [], "query_string": b""}) is None
