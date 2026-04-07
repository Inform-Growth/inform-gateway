# Gateway Reliability Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five confirmed gateway bugs: proxy exception propagation crashing FastMCP's TaskGroup, broken Attio npm tools, swallowed MCP error messages, `delete_note` SHA race condition, and sync-only telemetry wrapper.

**Architecture:** All changes are in `remote-gateway/`. Fixes 1+3 touch the same `proxy_fn` closures in `mcp_proxy.py`. Fix 2 adds `tools/attio.py` and a deny list in `mcp_connections.json`. Fix 4 adds one retry block to `tools/notes.py`. Fix 5 adds an async branch to the telemetry wrapper in `mcp_server.py`.

**Tech Stack:** Python 3.14, httpx, pytest, unittest.mock, FastMCP

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `remote-gateway/core/mcp_proxy.py` | Modify | Fixes 1+3: exception handling + isError check in both proxy_fn closures |
| `remote-gateway/tools/attio.py` | Create | Fix 2: direct REST tools for search_records and create_record |
| `remote-gateway/mcp_connections.json` | Modify | Fix 2: deny broken tools from attio npm proxy |
| `remote-gateway/core/mcp_server.py` | Modify | Fix 2: register attio tools; Fix 5: async branch in telemetry wrapper |
| `remote-gateway/tools/notes.py` | Modify | Fix 4: delete_note retry on 409/422 conflict |
| `remote-gateway/tests/test_proxy_reliability.py` | Create | Tests for Fixes 1+3 |
| `remote-gateway/tests/test_attio_tools.py` | Create | Tests for Fix 2 (tool logic) |
| `remote-gateway/tests/test_attio_config.py` | Modify | Tests for Fix 2 (deny list config) |
| `remote-gateway/tests/test_delete_note_retry.py` | Create | Tests for Fix 4 |
| `remote-gateway/tests/test_telemetry_async.py` | Create | Tests for Fix 5 |

---

### Task 1: Proxy reliability — exception handling and isError surfacing (Fixes 1 + 3)

**Files:**
- Create: `remote-gateway/tests/test_proxy_reliability.py`
- Modify: `remote-gateway/core/mcp_proxy.py`

- [ ] **Step 1.1: Write failing tests**

Create `remote-gateway/tests/test_proxy_reliability.py`:

```python
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

    _proxy._register_proxy_tool(mock_server, "apollo", _make_tool("mixed_people_api_search"), mock_session)

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
    with mock.patch.object(_proxy.httpx, "AsyncClient", side_effect=RuntimeError("no route to host")):
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
```

- [ ] **Step 1.2: Run tests — verify they fail**

```bash
pytest remote-gateway/tests/test_proxy_reliability.py -v
```

Expected: All tests FAIL — `test_proxy_fn_returns_error_dict_on_exception` raises `RuntimeError` instead of returning dict; `test_proxy_fn_surfaces_mcp_error_message` returns parsed JSON instead of error dict.

- [ ] **Step 1.3: Implement Fix 1 — exception handling in `_register_proxy_tool`**

In `remote-gateway/core/mcp_proxy.py`, find `_register_proxy_tool` (around line 525). Replace the `proxy_fn` body:

```python
    async def proxy_fn(**kwargs: Any) -> Any:
        """Forward the call to the upstream MCP server and return its response."""
        # FastMCP wraps tool args under a single "kwargs" key when the function
        # signature is **kwargs. Unwrap one level so upstream tools receive flat
        # params (e.g. {"domain": "gong.io"}) rather than {"kwargs": {"domain": ...}}.
        if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs["kwargs"], dict):
            upstream_kwargs = kwargs["kwargs"]
        else:
            upstream_kwargs = kwargs
        try:
            result = await session.call_tool(upstream_name, upstream_kwargs)
        except Exception as exc:
            return {"error": str(exc), "tool": upstream_name, "is_proxy_error": True}
        if not result.content:
            return {}
        content = result.content[0]
        if hasattr(content, "text"):
            if getattr(result, "isError", False):
                return {"error": content.text, "is_mcp_error": True}
            try:
                parsed = json.loads(content.text)
                # FastMCP cannot return a bare list — wrap it so the response
                # reaches the client rather than being silently dropped.
                return {"results": parsed} if isinstance(parsed, list) else parsed
            except (json.JSONDecodeError, ValueError):
                return {"result": content.text}
        return {}
```

- [ ] **Step 1.4: Implement Fix 1+3 — exception handling in `_register_streamable_http_proxy_tool`**

In the same file, find `_register_streamable_http_proxy_tool` (around line 577). Replace the `proxy_fn` body:

```python
    async def proxy_fn(**kwargs: Any) -> Any:
        """Forward the call via a fresh connection to the upstream MCP server."""
        if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs["kwargs"], dict):
            upstream_kwargs = kwargs["kwargs"]
        else:
            upstream_kwargs = kwargs

        try:
            auth_headers = await resolve_auth_headers(config)
            async with (
                httpx.AsyncClient(headers=auth_headers) as http_client,
                streamable_http_client(url, http_client=http_client) as (read, write, *_),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(upstream_name, upstream_kwargs)
        except Exception as exc:
            return {"error": str(exc), "tool": upstream_name, "is_proxy_error": True}

        if not result.content:
            return {}
        content = result.content[0]
        if hasattr(content, "text"):
            if getattr(result, "isError", False):
                return {"error": content.text, "is_mcp_error": True}
            try:
                parsed = json.loads(content.text)
                return {"results": parsed} if isinstance(parsed, list) else parsed
            except (json.JSONDecodeError, ValueError):
                return {"result": content.text}
        return {}
```

- [ ] **Step 1.5: Run tests — verify they pass**

```bash
pytest remote-gateway/tests/test_proxy_reliability.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 1.6: Run full test suite — verify no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: All existing tests still PASS.

- [ ] **Step 1.7: Lint**

```bash
ruff check remote-gateway/core/mcp_proxy.py remote-gateway/tests/test_proxy_reliability.py
```

Expected: No errors.

- [ ] **Step 1.8: Commit**

```bash
git add remote-gateway/core/mcp_proxy.py remote-gateway/tests/test_proxy_reliability.py
git commit -m "fix(proxy): catch tool call exceptions and surface isError responses"
```

---

### Task 2: Attio tool overrides (Fix 2)

**Files:**
- Create: `remote-gateway/tools/attio.py`
- Create: `remote-gateway/tests/test_attio_tools.py`
- Modify: `remote-gateway/mcp_connections.json`
- Modify: `remote-gateway/tests/test_attio_config.py`
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 2.1: Write failing tests for attio tools**

Create `remote-gateway/tests/test_attio_tools.py`:

```python
"""
Unit tests for tools/attio.py — Python REST overrides for broken attio-mcp tools.

Run with:
    pytest remote-gateway/tests/test_attio_tools.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.attio import attio__create_record, attio__search_records


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Client response."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock()
    return m


def _mock_client(post_responses=None, get_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if post_responses is not None:
        mock.post.side_effect = post_responses
    if get_responses is not None:
        mock.get.side_effect = get_responses
    return mock


# ---------------------------------------------------------------------------
# attio__search_records
# ---------------------------------------------------------------------------


def test_search_records_returns_records(monkeypatch):
    """search_records returns count and records list from Attio query response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    records = [{"id": {"record_id": "rec-123"}, "values": {"name": [{"value": "Acme Corp"}]}}]
    mock_client = _mock_client(post_responses=[_mock_response({"data": records})])

    with patch("httpx.Client", return_value=mock_client):
        result = attio__search_records("companies", "Acme")

    assert result["count"] == 1
    assert result["records"] == records
    assert result["object_type"] == "companies"


def test_search_records_posts_correct_endpoint_and_filter(monkeypatch):
    """search_records POSTs to /records/query with a name $str_contains filter."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        attio__search_records("people", "Jane", limit=5)

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "people/records/query" in posted_url
    assert posted_body["filter"]["name"]["$str_contains"] == "Jane"
    assert posted_body["limit"] == 5


def test_search_records_uses_api_key_header(monkeypatch):
    """search_records sends ATTIO_API_KEY as Bearer token."""
    monkeypatch.setenv("ATTIO_API_KEY", "secret-key-xyz")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        attio__search_records("companies", "Test")

    posted_headers = mock_client.post.call_args.kwargs["headers"]
    assert posted_headers.get("Authorization") == "Bearer secret-key-xyz"


def test_search_records_empty_result(monkeypatch):
    """search_records with no matches returns count=0 and empty records list."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    mock_client = _mock_client(post_responses=[_mock_response({"data": []})])

    with patch("httpx.Client", return_value=mock_client):
        result = attio__search_records("companies", "NonexistentCo")

    assert result["count"] == 0
    assert result["records"] == []


# ---------------------------------------------------------------------------
# attio__create_record
# ---------------------------------------------------------------------------


def test_create_record_returns_record_id(monkeypatch):
    """create_record returns record_id from Attio create response."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(
        post_responses=[
            _mock_response({"data": {"id": {"record_id": "rec-new-456"}, "values": {}}})
        ]
    )
    values = {"name": [{"value": "New Corp"}], "domains": [{"domain": "newcorp.io"}]}

    with patch("httpx.Client", return_value=mock_client):
        result = attio__create_record("companies", values)

    assert result["record_id"] == "rec-new-456"
    assert result["object_type"] == "companies"
    assert result["data"]["id"]["record_id"] == "rec-new-456"


def test_create_record_posts_correct_payload(monkeypatch):
    """create_record wraps values in {"data": {"values": ...}} as Attio API requires."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key-abc")

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )
    values = {"name": [{"value": "Corp"}]}

    with patch("httpx.Client", return_value=mock_client):
        attio__create_record("companies", values)

    posted_url = mock_client.post.call_args.args[0]
    posted_body = mock_client.post.call_args.kwargs["json"]

    assert "companies/records" in posted_url
    assert "query" not in posted_url  # must be create endpoint, not search
    assert posted_body == {"data": {"values": values}}


def test_create_record_uses_api_key_header(monkeypatch):
    """create_record sends ATTIO_API_KEY as Bearer token."""
    monkeypatch.setenv("ATTIO_API_KEY", "create-key-999")

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )

    with patch("httpx.Client", return_value=mock_client):
        attio__create_record("companies", {"name": [{"value": "X"}]})

    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers.get("Authorization") == "Bearer create-key-999"
```

- [ ] **Step 2.2: Run tests — verify they fail with ImportError**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v
```

Expected: `ImportError: cannot import name 'attio__search_records' from 'tools.attio'` (file does not exist yet).

- [ ] **Step 2.3: Create `tools/attio.py`**

Create `remote-gateway/tools/attio.py`:

```python
"""
Direct Attio REST API tools — Python overrides for attio-mcp npm package bugs.

The attio-mcp npm package sends malformed payloads for search_records and
create_record. These Python implementations call the Attio v2 REST API
directly. The npm proxy is configured via mcp_connections.json to deny these
two tool names; these tools fill the gap.

Required env vars:
    ATTIO_API_KEY — Attio workspace API token (Bearer token)
"""
from __future__ import annotations

import os
from typing import Any

_ATTIO_BASE = "https://api.attio.com/v2"


def _headers() -> dict[str, str]:
    """Return Attio API request headers using ATTIO_API_KEY from env."""
    return {
        "Authorization": f"Bearer {os.environ.get('ATTIO_API_KEY', '')}",
        "Content-Type": "application/json",
    }


def attio__search_records(
    object_type: str,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Search Attio records by name.

    Searches companies or people by name using a contains filter against the
    Attio v2 records/query endpoint. Returns matching records with their IDs
    and attribute values.

    Args:
        object_type: Record type to search — "companies" or "people".
        query: Text to search for in the record name field (partial match).
        limit: Maximum number of records to return. Defaults to 20.

    Returns:
        Dict with 'records' list, 'count', and 'object_type'.
        Each record has 'id.record_id' and 'values'.
    """
    import httpx

    url = f"{_ATTIO_BASE}/objects/{object_type}/records/query"
    body: dict[str, Any] = {
        "filter": {"name": {"$str_contains": query}},
        "limit": limit,
    }

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    resp.raise_for_status()
    data = resp.json().get("data", [])
    return {"records": data, "count": len(data), "object_type": object_type}


def attio__create_record(
    object_type: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Create a new record in Attio.

    Creates a company or person record with the given attribute values using
    the Attio v2 records endpoint.

    Values format for companies:
        {"name": [{"value": "Acme Inc"}], "domains": [{"domain": "acme.io"}]}

    Values format for people — ALL THREE name subfields required:
        {"name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]}

    Company reference fields require target_object alongside target_record_id:
        {"company": [{"target_object": "companies", "target_record_id": "<id>"}]}

    Args:
        object_type: Record type to create — "companies" or "people".
        values: Attribute values in Attio REST API format (see docstring examples).

    Returns:
        Dict with 'record_id', 'object_type', and 'data' (the created record).
    """
    import httpx

    url = f"{_ATTIO_BASE}/objects/{object_type}/records"
    body: dict[str, Any] = {"data": {"values": values}}

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    record = result.get("data", {})
    record_id = record.get("id", {}).get("record_id", "")
    return {"record_id": record_id, "object_type": object_type, "data": record}


def register(mcp: Any) -> None:
    """Register Attio override tools on the FastMCP server.

    These tools replace the broken attio-mcp npm package implementations
    for search_records and create_record. The npm proxy is configured to
    deny these tool names in mcp_connections.json so only these Python
    versions are registered.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(attio__search_records)
    mcp.tool()(attio__create_record)
```

- [ ] **Step 2.4: Run tests — verify they pass**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 2.5: Write failing config test for deny list**

In `remote-gateway/tests/test_attio_config.py`, add these tests after the existing Apollo tests:

```python
# ---------------------------------------------------------------------------
# Attio deny list validation (Fix 2)
# ---------------------------------------------------------------------------


def test_attio_has_tools_deny_list():
    """attio entry must have a tools.deny list to suppress broken npm tools."""
    attio = _load_attio()
    tools = attio.get("tools", {})
    assert "deny" in tools, (
        "Expected 'tools.deny' in attio config — broken tools must be suppressed from npm proxy"
    )


def test_attio_deny_list_blocks_search_records():
    """search_records must be in the deny list (broken in attio-mcp npm package)."""
    attio = _load_attio()
    deny = attio.get("tools", {}).get("deny", [])
    assert "search_records" in deny, (
        f"Expected 'search_records' in deny list, got: {deny}"
    )


def test_attio_deny_list_blocks_create_record():
    """create_record must be in the deny list (broken in attio-mcp npm package)."""
    attio = _load_attio()
    deny = attio.get("tools", {}).get("deny", [])
    assert "create_record" in deny, (
        f"Expected 'create_record' in deny list, got: {deny}"
    )
```

- [ ] **Step 2.6: Run config tests — verify they fail**

```bash
pytest remote-gateway/tests/test_attio_config.py -v -k "deny"
```

Expected: 3 tests FAIL — `tools` key missing from attio entry.

- [ ] **Step 2.7: Add deny list to `mcp_connections.json`**

In `remote-gateway/mcp_connections.json`, add `"tools"` block to the `"attio"` entry:

```json
"attio": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "attio-mcp"],
  "env": {
    "ATTIO_API_KEY": "${ATTIO_API_KEY}"
  },
  "tools": {
    "deny": ["search_records", "create_record"]
  }
}
```

- [ ] **Step 2.8: Run config tests — verify they pass**

```bash
pytest remote-gateway/tests/test_attio_config.py -v
```

Expected: All tests PASS (including the 3 new deny list tests).

- [ ] **Step 2.9: Register attio tools in `mcp_server.py`**

In `remote-gateway/core/mcp_server.py`, add the attio import and register call alongside the existing tool registrations (around line 105):

```python
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402
from tools import attio as _attio_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
_attio_tools.register(mcp)
```

- [ ] **Step 2.10: Run full test suite — verify no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 2.11: Lint**

```bash
ruff check remote-gateway/tools/attio.py remote-gateway/tests/test_attio_tools.py remote-gateway/tests/test_attio_config.py remote-gateway/core/mcp_server.py
```

Expected: No errors.

- [ ] **Step 2.12: Commit**

```bash
git add remote-gateway/tools/attio.py remote-gateway/tests/test_attio_tools.py remote-gateway/tests/test_attio_config.py remote-gateway/mcp_connections.json remote-gateway/core/mcp_server.py
git commit -m "fix(attio): add Python REST overrides for broken search_records and create_record"
```

---

### Task 3: delete_note retry on SHA conflict (Fix 4)

**Files:**
- Create: `remote-gateway/tests/test_delete_note_retry.py`
- Modify: `remote-gateway/tools/notes.py`

- [ ] **Step 3.1: Write failing tests**

Create `remote-gateway/tests/test_delete_note_retry.py`:

```python
"""
Unit tests for delete_note SHA conflict retry (Fix 4).

The GitHub Contents API returns 409/422 when the SHA used in a DELETE
is stale (another write happened between the GET and DELETE). delete_note
must re-fetch the SHA and retry once.

Run with:
    pytest remote-gateway/tests/test_delete_note_retry.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.notes import delete_note


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx response with raise_for_status as a no-op by default."""
    m = MagicMock()
    m.status_code = status_code
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock()
    return m


def _mock_client(get_responses=None, request_responses=None) -> MagicMock:
    """Return a context-manager mock for httpx.Client."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if get_responses is not None:
        mock.get.side_effect = get_responses
    if request_responses is not None:
        mock.request.side_effect = request_responses
    return mock


def test_delete_note_retries_on_409(monkeypatch):
    """409 conflict triggers a re-fetch of the SHA and a second DELETE attempt."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-stale", "name": "_test.md"})
    second_get = _mock_response({"sha": "sha-fresh", "name": "_test.md"})

    conflict_resp = _mock_response({}, status_code=409)
    success_resp = _mock_response({
        "commit": {"sha": "commit-abc", "html_url": "https://github.com/org/repo/commit/abc"}
    })

    mock_client = _mock_client(
        get_responses=[first_get, second_get],
        request_responses=[conflict_resp, success_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "deleted"
    assert mock_client.request.call_count == 2, "Expected exactly 2 DELETE attempts"

    # Second DELETE must use the freshly fetched SHA
    second_call_body = mock_client.request.call_args_list[1].kwargs["json"]
    assert second_call_body["sha"] == "sha-fresh", (
        f"Expected sha-fresh in second DELETE, got: {second_call_body['sha']}"
    )


def test_delete_note_retries_on_422(monkeypatch):
    """422 conflict also triggers retry (GitHub uses both 409 and 422 for SHA mismatch)."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-old", "name": "_test.md"})
    second_get = _mock_response({"sha": "sha-new", "name": "_test.md"})

    conflict_resp = _mock_response({}, status_code=422)
    success_resp = _mock_response({
        "commit": {"sha": "commit-xyz", "html_url": "https://github.com/org/repo/commit/xyz"}
    })

    mock_client = _mock_client(
        get_responses=[first_get, second_get],
        request_responses=[conflict_resp, success_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "deleted"
    assert mock_client.request.call_count == 2


def test_delete_note_no_retry_on_success(monkeypatch):
    """When first DELETE succeeds (200), no retry is issued."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-ok", "name": "_test.md"})
    success_resp = _mock_response({
        "commit": {"sha": "commit-ok", "html_url": "https://github.com/org/repo/commit/ok"}
    })

    mock_client = _mock_client(
        get_responses=[first_get],
        request_responses=[success_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "deleted"
    assert mock_client.request.call_count == 1, "Expected exactly 1 DELETE attempt (no retry needed)"
    assert mock_client.get.call_count == 1, "Expected exactly 1 GET (no re-fetch needed)"


def test_delete_note_returns_not_found_when_file_gone_during_retry(monkeypatch):
    """If file disappears between first and retry GET, return not_found gracefully."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")

    first_get = _mock_response({"sha": "sha-stale", "name": "_test.md"})
    not_found_get = _mock_response({}, status_code=404)

    conflict_resp = _mock_response({}, status_code=409)

    mock_client = _mock_client(
        get_responses=[first_get, not_found_get],
        request_responses=[conflict_resp],
    )

    with patch("httpx.Client", return_value=mock_client):
        result = delete_note("_test")

    assert result["status"] == "not_found"
```

- [ ] **Step 3.2: Run tests — verify they fail**

```bash
pytest remote-gateway/tests/test_delete_note_retry.py -v
```

Expected: `test_delete_note_retries_on_409`, `test_delete_note_retries_on_422`, and `test_delete_note_returns_not_found_when_file_gone_during_retry` FAIL. `test_delete_note_no_retry_on_success` PASS (existing behavior).

- [ ] **Step 3.3: Implement the retry in `delete_note`**

In `remote-gateway/tools/notes.py`, replace the `delete_note` function body (inside the `with httpx.Client() as client:` block) with:

```python
def delete_note(filename: str, commit_message: str = "") -> dict:
    """Delete a markdown note from the gateway's notes folder.

    Args:
        filename: Note filename, with or without .md extension.
        commit_message: Optional git commit message. Defaults to "chore: delete <filename>".

    Returns:
        Dict confirming deletion with 'filename' and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)
    base_name = os.path.basename(path)

    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 404:
            return {"status": "not_found", "filename": base_name}
        check.raise_for_status()
        sha = check.json()["sha"]

        body = {
            "message": commit_message or f"chore: delete {base_name}",
            "sha": sha,
            "branch": branch,
        }
        resp = client.request("DELETE", url, headers=_github_headers(), json=body)

        if resp.status_code in (409, 422):
            # SHA is stale — a concurrent write changed the file between our GET and DELETE.
            # Re-fetch the current SHA and retry once.
            recheck = client.get(url, headers=_github_headers(), params={"ref": branch})
            if recheck.status_code == 404:
                return {"status": "not_found", "filename": base_name}
            recheck.raise_for_status()
            body["sha"] = recheck.json()["sha"]
            resp = client.request("DELETE", url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "deleted",
        "filename": base_name,
        "commit_url": commit.get("html_url", ""),
    }
```

- [ ] **Step 3.4: Run tests — verify they pass**

```bash
pytest remote-gateway/tests/test_delete_note_retry.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 3.5: Run full test suite — verify no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3.6: Lint**

```bash
ruff check remote-gateway/tools/notes.py remote-gateway/tests/test_delete_note_retry.py
```

Expected: No errors.

- [ ] **Step 3.7: Commit**

```bash
git add remote-gateway/tools/notes.py remote-gateway/tests/test_delete_note_retry.py
git commit -m "fix(notes): retry delete_note once on SHA conflict (409/422)"
```

---

### Task 4: Telemetry async support (Fix 5)

**Files:**
- Create: `remote-gateway/tests/test_telemetry_async.py`
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 4.1: Write failing tests**

Create `remote-gateway/tests/test_telemetry_async.py`:

```python
"""
Tests for async support in the _tracked_mcp_tool telemetry wrapper (Fix 5).

The wrapper in mcp_server.py must detect async tool functions and await them
before recording telemetry — otherwise timing is 0ms and errors are invisible.

Run with:
    pytest remote-gateway/tests/test_telemetry_async.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _import_mcp_server():
    """Import mcp_server.py with all external dependencies stubbed.

    Returns (module, recorded_calls) where recorded_calls is a list that
    telemetry.record() appends to — inspect it to verify telemetry behavior.
    """
    import importlib.util

    # Stub mcp packages (FastMCP)
    for mod_name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

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
    mock_tel.record = lambda name, duration_ms, success, exc_type=None: recorded.append(
        {"name": name, "duration_ms": duration_ms, "success": success, "exc_type": exc_type}
    )
    mod_tel.telemetry = mock_tel
    sys.modules["telemetry"] = mod_tel

    # Stub tools sub-modules
    for mod_name in ("tools", "tools.meta", "tools.notes", "tools.registry", "tools.attio"):
        if mod_name not in sys.modules:
            m = types.ModuleType(mod_name)
            sys.modules[mod_name] = m
        if not hasattr(sys.modules[mod_name], "register"):
            sys.modules[mod_name].register = MagicMock()

    path = Path(__file__).parent.parent / "core" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("_mcp_server_for_test", path)
    module = types.ModuleType("_mcp_server_for_test")
    module.__file__ = str(path)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
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
    assert asyncio.iscoroutinefunction(tracked), (
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
    assert not asyncio.iscoroutinefunction(tracked), "Sync tool must not become a coroutine"

    result = tracked()
    assert result == {"sync": True}
    assert len(_recorded) == 1
    assert _recorded[0]["name"] == "sync_tool"
    assert _recorded[0]["success"] is True
```

- [ ] **Step 4.2: Run tests — verify they fail**

```bash
pytest remote-gateway/tests/test_telemetry_async.py -v
```

Expected: `test_async_tool_wrapper_is_coroutine_function` FAIL (returns sync function); `test_async_tool_records_telemetry_after_await` FAIL (duration near 0ms). Sync tests PASS.

- [ ] **Step 4.3: Implement the async branch in `_tracked_mcp_tool`**

In `remote-gateway/core/mcp_server.py`, replace `_tracked_mcp_tool` (starting around line 70):

```python
def _tracked_mcp_tool(*args: Any, **kwargs: Any) -> Any:
    """Replacement for mcp.tool() that injects timing and error recording."""
    fastmcp_decorator = _orig_mcp_tool(*args, **kwargs)

    def wrapper(fn: Any) -> Any:
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
                t0 = _time.monotonic()
                try:
                    result = await fn(*fn_args, **fn_kwargs)
                    _telemetry.record(fn.__name__, int((_time.monotonic() - t0) * 1000), True)
                    return result
                except Exception as exc:
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__
                    )
                    raise

            return fastmcp_decorator(tracked_async)

        @functools.wraps(fn)
        def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            try:
                result = fn(*fn_args, **fn_kwargs)
                _telemetry.record(fn.__name__, int((_time.monotonic() - t0) * 1000), True)
                return result
            except Exception as exc:
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__
                )
                raise

        return fastmcp_decorator(tracked)

    return wrapper
```

Note: `asyncio` is already imported at the top of `mcp_server.py` (line 19). No new import needed.

- [ ] **Step 4.4: Run tests — verify they pass**

```bash
pytest remote-gateway/tests/test_telemetry_async.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 4.5: Run full test suite — verify no regressions**

```bash
pytest remote-gateway/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 4.6: Lint**

```bash
ruff check remote-gateway/core/mcp_server.py remote-gateway/tests/test_telemetry_async.py
```

Expected: No errors.

- [ ] **Step 4.7: Commit**

```bash
git add remote-gateway/core/mcp_server.py remote-gateway/tests/test_telemetry_async.py
git commit -m "fix(telemetry): support async tools in _tracked_mcp_tool wrapper"
```

---

## Final Verification

- [ ] **Run full test suite one last time**

```bash
pytest remote-gateway/tests/ -v
```

Expected output: All tests pass. Confirm test count includes tests from:
- `test_proxy_auth.py` (11 tests, existing)
- `test_attio_config.py` (11 tests — 8 existing + 3 new deny list tests)
- `test_attio_tools.py` (8 tests, new)
- `test_proxy_reliability.py` (7 tests, new)
- `test_delete_note_retry.py` (4 tests, new)
- `test_telemetry_async.py` (5 tests, new)

- [ ] **Lint all changed files**

```bash
ruff check remote-gateway/core/mcp_proxy.py remote-gateway/core/mcp_server.py remote-gateway/tools/attio.py remote-gateway/tools/notes.py
```

Expected: No errors.
