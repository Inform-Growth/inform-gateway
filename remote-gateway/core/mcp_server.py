"""
Agent Gateway — Central MCP Server

Hosts promoted, QA-approved tools as official MCP endpoints.
All tools are read-only by default unless explicitly granted write permission.

On startup, also proxies upstream MCP servers defined in mcp_connections.json,
re-exposing their tools under the naming convention ``<integration>__<tool_name>``.
Employees connect only to this gateway — no vendor credentials on their machines.

Run with:
    python remote-gateway/core/mcp_server.py
    # or via mcp CLI:
    mcp run remote-gateway/core/mcp_server.py
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import os
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Load .env from the remote-gateway directory if present (local dev)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from field_registry import registry  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.lowlevel.server import request_ctx as _request_ctx  # noqa: E402
from mcp_proxy import mount_all_proxies  # noqa: E402
from telemetry import telemetry as _telemetry  # noqa: E402


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Start upstream MCP proxy connections on startup; clean up on shutdown."""
    proxy_tasks = await mount_all_proxies(server)
    yield
    for task in proxy_tasks:
        task.cancel()
    if proxy_tasks:
        await asyncio.gather(*proxy_tasks, return_exceptions=True)


mcp = FastMCP(
    os.environ.get("MCP_SERVER_NAME", "inform-gateway"),
    lifespan=lifespan,
    host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
)


# ---------------------------------------------------------------------------
# Auth — Bearer token → user_id resolution via ASGI middleware.
#
# Each operator gets one API key (created by an admin via telemetry.add_api_key).
# They configure it in .mcp.json:
#   "headers": {"Authorization": "Bearer sk-<their-key>"}
#
# _AuthMiddleware extracts the key on every HTTP request, resolves the user_id
# from the telemetry DB, and stores it in _current_user for the duration of
# the request. The telemetry wrappers below read it automatically.
# ---------------------------------------------------------------------------

_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user", default=None
)


class _AuthMiddleware:
    """ASGI middleware: API key → user_id → ContextVar.

    Checks two locations in priority order:
    1. ``Authorization: Bearer <key>`` header  — Claude Code, API clients
    2. ``?api_key=<key>`` query parameter       — Claude Desktop/Web, OpenAI, Gemini
       (clients that set a URL but cannot add custom headers)
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            key = self._extract_key(scope)
            user_id = _telemetry.lookup_user(key) if key else None
            token = _current_user.set(user_id)
            try:
                await self._app(scope, receive, send)
            finally:
                _current_user.reset(token)
        else:
            await self._app(scope, receive, send)

    @staticmethod
    def _extract_key(scope: Any) -> str | None:
        """Return the API key from the Authorization header or api_key query param."""
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth: str = headers.get(b"authorization", b"").decode()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None

        # Fall back to query param — used by clients that can't set headers
        qs: str = scope.get("query_string", b"").decode()
        for part in qs.split("&"):
            if part.startswith("api_key="):
                return part[8:] or None
        return None


# ---------------------------------------------------------------------------
# Telemetry — patches mcp.tool() and mcp.add_tool() so every registered tool
# is tracked. mcp.tool() covers decorated built-in and promoted tools; mcp.add_tool()
# covers proxy tools (attio, exa, apollo, etc.) registered by mcp_proxy.py.
# Uses functools.wraps so FastMCP sees the original function signatures.
# ---------------------------------------------------------------------------


def _get_call_ids() -> tuple[str | None, str | None]:
    """Return (user_id, request_id) for the current request.

    user_id comes from _current_user, which _AuthMiddleware sets by resolving
    the caller's Bearer token. request_id comes from the MCP request context.
    Both are None outside of an active request (e.g. during tests).
    """
    user_id = _current_user.get()
    try:
        request_id = str(_request_ctx.get().request_id)
    except LookupError:
        request_id = None
    return user_id, request_id


_orig_mcp_tool = mcp.tool


def _tracked_mcp_tool(*args: Any, **kwargs: Any) -> Any:
    """Replacement for mcp.tool() that injects timing and error recording."""
    fastmcp_decorator = _orig_mcp_tool(*args, **kwargs)

    def wrapper(fn: Any) -> Any:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
                t0 = _time.monotonic()
                sid, rid = _get_call_ids()
                try:
                    result = await fn(*fn_args, **fn_kwargs)
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                        user_id=sid, request_id=rid,
                    )
                    return result
                except Exception as exc:
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                        type(exc).__name__, user_id=sid, request_id=rid,
                    )
                    raise

            return fastmcp_decorator(tracked_async)

        @functools.wraps(fn)
        def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            try:
                result = fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid,
                )
                return result
            except Exception as exc:
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                )
                raise

        return fastmcp_decorator(tracked)

    return wrapper


mcp.tool = _tracked_mcp_tool

_orig_add_tool = mcp.add_tool


def _tracked_add_tool(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Replacement for mcp.add_tool() that injects timing and error recording.

    Proxy tools (attio, exa, apollo, etc.) are registered via add_tool() rather
    than the @mcp.tool() decorator, so they bypass _tracked_mcp_tool. This patch
    ensures every tool — decorator or direct — is captured in telemetry.
    """
    tool_name: str = kwargs.get("name", fn.__name__)

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            try:
                result = await fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid,
                )
                return result
            except Exception as exc:
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                )
                raise

        return _orig_add_tool(tracked_async, *args, **kwargs)

    @functools.wraps(fn)
    def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
        t0 = _time.monotonic()
        sid, rid = _get_call_ids()
        try:
            result = fn(*fn_args, **fn_kwargs)
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), True,
                user_id=sid, request_id=rid,
            )
            return result
        except Exception as exc:
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                user_id=sid, request_id=rid,
            )
            raise

    return _orig_add_tool(tracked, *args, **kwargs)


mcp.add_tool = _tracked_add_tool


# ---------------------------------------------------------------------------
# Register internal tools from tools/ modules
# (imported here so .env is loaded and mcp.tool telemetry patch is active)
# ---------------------------------------------------------------------------

import sys as _sys  # noqa: E402

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import attio as _attio_tools  # noqa: E402
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
_attio_tools.register(mcp)  # must register after telemetry patch is applied


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------


def validated(integration: str, response: dict[str, Any]) -> dict[str, Any]:
    """Validate a tool response against the field registry and return it.

    Attaches a '_field_validation' key only when drift is detected, so
    callers can surface unknowns without blocking the response. In clean
    state the response passes through unchanged.

    Args:
        integration: Integration slug (e.g., "stripe").
        response: The raw dict returned by a promoted tool.

    Returns:
        The original response, with '_field_validation' appended if drift found.
    """
    result = registry.validate_response(integration, response)
    if not result.valid:
        response["_field_validation"] = result.summary()
    return response


# ---------------------------------------------------------------------------
# Promoted tools go below this line.
#
# Migration pattern:
#   1. Copy the function from local-workspace/tools/<script>.py
#   2. Decorate with @mcp.tool()
#   3. Wrap the return value with validated("<integration>", result) so the
#      field registry automatically checks the response on every call.
#   4. Ensure all credentials use os.environ (never hardcode)
#   5. Verify the docstring is clear — it becomes the MCP tool description
#
# Example:
#
#   @mcp.tool()
#   def get_churn_metrics(period: str = "30d") -> dict:
#       """Fetch customer churn metrics from Stripe for a given period.
#
#       Args:
#           period: Time window for churn calculation (e.g., "7d", "30d", "90d").
#
#       Returns:
#           Dict with churn_rate, churned_customers, and total_customers.
#       """
#       result = {...}  # fetch from Stripe
#       return validated("stripe", result)
#
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport in ("sse", "combined"):
        import uvicorn
        from starlette.applications import Starlette

        # Serve both SSE (legacy Claude Code / existing operators) and
        # streamable-http (Claude Desktop, newer clients) on the same port.
        # SSE: GET /sse + POST /messages
        # Streamable-HTTP: POST /mcp
        _sse = mcp.sse_app()
        _http = mcp.streamable_http_app()
        _combined = Starlette(routes=list(_sse.routes) + list(_http.routes))

        uvicorn.run(
            _AuthMiddleware(_combined),
            host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
        )
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
