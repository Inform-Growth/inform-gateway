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
import json
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


def _bootstrap_gmail_credentials() -> None:
    """Write Gmail OAuth credentials from env vars to temp files.

    Reads two env vars that hold the raw JSON content of the credential files:

    - ``GMAIL_OAUTH_KEYS_JSON``  → gcp-oauth.keys.json (GCP OAuth client secret)
    - ``GMAIL_CREDENTIALS_JSON`` → credentials.json (user access/refresh token)

    Writes each to a temp directory and sets ``GMAIL_OAUTH_PATH`` /
    ``GMAIL_CREDENTIALS_PATH`` so the Gmail MCP subprocess can find them.
    Skips silently if the var is absent (useful for local dev where the files
    already exist at their default locations).
    """
    import tempfile

    tmpdir: Path | None = None

    oauth_json = os.environ.get("GMAIL_OAUTH_KEYS_JSON")
    creds_json = os.environ.get("GMAIL_CREDENTIALS_JSON")

    if not (oauth_json or creds_json):
        return

    tmpdir = Path(tempfile.mkdtemp(prefix="gmail-mcp-"))

    if oauth_json and not os.environ.get("GMAIL_OAUTH_PATH"):
        p = tmpdir / "gcp-oauth.keys.json"
        p.write_text(oauth_json)
        os.environ["GMAIL_OAUTH_PATH"] = str(p)
        print(f"  [gmail] OAuth keys written to {p}")

    if creds_json and not os.environ.get("GMAIL_CREDENTIALS_PATH"):
        p = tmpdir / "credentials.json"
        p.write_text(creds_json)
        os.environ["GMAIL_CREDENTIALS_PATH"] = str(p)
        print(f"  [gmail] Credentials written to {p}")


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Start upstream MCP proxy connections on startup; clean up on shutdown."""
    _bootstrap_gmail_credentials()
    proxy_tasks = await mount_all_proxies(server)
    yield
    for task in proxy_tasks:
        task.cancel()
    if proxy_tasks:
        await asyncio.gather(*proxy_tasks, return_exceptions=True)


# Load instructions from init.md
_init_prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "init.md"
_instructions = _init_prompt_path.read_text() if _init_prompt_path.exists() else None

mcp = FastMCP(
    os.environ.get("MCP_SERVER_NAME", "inform-gateway"),
    instructions=_instructions,
    lifespan=lifespan,
    host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
    warn_on_duplicate_tools=False,
    warn_on_duplicate_prompts=False,
    warn_on_duplicate_resources=False,
)


@mcp.tool()
async def list_prompts() -> list[dict[str, Any]]:
    """Return a list of all available prompts and their arguments.
    
    Use this to discover templates for specific workflows like research or briefings.
    """
    prompts = await mcp.list_prompts()
    return [
        {
            "name": p.name,
            "description": p.description,
            "arguments": [
                {"name": arg.name, "description": arg.description, "required": arg.required}
                for arg in (p.arguments or [])
            ]
        }
        for p in prompts
    ]


@mcp.tool()
async def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Retrieve and render a specific prompt template by name.
    
    Args:
        name: The name of the prompt to retrieve.
        arguments: Dict of arguments to fill into the template.
    """
    return await mcp.get_prompt(name, arguments)


@mcp.prompt(description="Initialize gateway operator context")
def operator_init() -> str:
    """Initialize the Gateway Operator persona and shadow note-taking rules."""
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "init.md"
    if not prompt_path.exists():
        return "Error: init.md not found. Contact administrator."
    return prompt_path.read_text()


@mcp.prompt(description="Standard instructions for QA agents reviewing gateway tool usage")
def qa_agent_instructions() -> str:
    """Return instructions for QA agents reviewing gateway tool usage."""
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "qa_agent_instructions.md"
    if not prompt_path.exists():
        return "Error: qa_agent_instructions.md not found. Contact administrator."
    return prompt_path.read_text()


@mcp.prompt(description="Run a weekly pipeline review across Attio and Apollo")
def weekly_pipeline_review() -> str:
    """Analyze Attio deals and cross-reference with Apollo activity."""
    return """
Pull all open deals from Attio. For each:
- Check last activity date — flag anything with no contact in 14+ days
- Check Apollo for any recent email activity on the contact
Return a prioritized action list: who to follow up with and who to prospect.
"""


@mcp.prompt(description="Research a company and brief the outreach angle")
def research_prospect(company: str) -> str:
    """Research a company using Exa and check Attio/Apollo."""
    return f"""
Research {company} using Exa web search. Then check if they exist in Attio and Apollo.
Return a 1-page brief: what they do, company size, tech stack signals,
recent news, and the best outreach angle.
"""


@mcp.prompt(description="Morning RevOps briefing")
def morning_briefing() -> str:
    """Daily summary of Attio deals and new Apollo contacts."""
    return """
Give me my morning RevOps briefing:
1. Attio: any deals with activity today or overdue tasks
2. Apollo: new contacts added this week
3. Anything that needs immediate attention
Keep it tight — bullets only.
"""


@mcp.prompt(description="Add a new prospect to Attio and Apollo")
def add_prospect(name: str, company: str) -> str:
    """Enrich a contact in Apollo and create records in Attio."""
    return f"""
Add {name} from {company} as a new prospect:
1. Search Apollo for their contact record and enrich it
2. Create or update their record in Attio under People
3. Link them to the company in Attio
4. Confirm that it was created.
"""


@mcp.prompt(description="How to use these prompts in your client")
def how_to_use_prompts() -> str:
    """Return a guide on how to invoke these workflows in Claude."""
    return """
# How to use Gateway Workflows

## 1. Slash Commands (Preferred)
In your chat box, simply type `/` followed by a command name. For example:
- `/operator_init`
- `/morning_briefing`

## 2. Prompts as Tools
If you do not see a slash menu (common in some desktop versions), you can ask Claude to
"list available prompts" or "run the morning briefing prompt".

Claude will use the `list_prompts` and `get_prompt` tools to find and execute
these templates for you automatically.
"""


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


def _calculate_response_size(result: Any) -> int:
    """Return the approximate size of the result in characters."""
    try:
        return len(str(result))
    except Exception:
        return 0


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
                input_body = json.dumps(fn_kwargs, default=str)
                if sid and not _telemetry.has_permission(sid, fn.__name__):
                    _perm_msg = f"Tool '{fn.__name__}' is disabled for your account."
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                        "PermissionError", user_id=sid, request_id=rid,
                        input_body=input_body,
                        error_message=_perm_msg,
                    )
                    raise PermissionError(_perm_msg)
                try:
                    result = await fn(*fn_args, **fn_kwargs)
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                        user_id=sid, request_id=rid,
                        response_size=_calculate_response_size(result),
                        input_body=input_body,
                    )
                    return result
                except Exception as exc:
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                        type(exc).__name__, user_id=sid, request_id=rid,
                        input_body=input_body,
                        error_message=str(exc),
                    )
                    raise

            return fastmcp_decorator(tracked_async)

        @functools.wraps(fn)
        def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            input_body = json.dumps(fn_kwargs, default=str)
            if sid and not _telemetry.has_permission(sid, fn.__name__):
                _perm_msg = f"Tool '{fn.__name__}' is disabled for your account."
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                    "PermissionError", user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=_perm_msg,
                )
                raise PermissionError(_perm_msg)
            try:
                result = fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid,
                    response_size=_calculate_response_size(result),
                    input_body=input_body,
                )
                return result
            except Exception as exc:
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=str(exc),
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
            input_body = json.dumps(fn_kwargs, default=str)
            if sid and not _telemetry.has_permission(sid, tool_name):
                _perm_msg = f"Tool '{tool_name}' is disabled for your account."
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), False,
                    "PermissionError", user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=_perm_msg,
                )
                raise PermissionError(_perm_msg)
            try:
                result = await fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid,
                    response_size=_calculate_response_size(result),
                    input_body=input_body,
                )
                return result
            except Exception as exc:
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=str(exc),
                )
                raise

        return _orig_add_tool(tracked_async, *args, **kwargs)

    @functools.wraps(fn)
    def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
        t0 = _time.monotonic()
        sid, rid = _get_call_ids()
        input_body = json.dumps(fn_kwargs, default=str)
        if sid and not _telemetry.has_permission(sid, tool_name):
            _perm_msg = f"Tool '{tool_name}' is disabled for your account."
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), False,
                "PermissionError", user_id=sid, request_id=rid,
                input_body=input_body,
                error_message=_perm_msg,
            )
            raise PermissionError(_perm_msg)
        try:
            result = fn(*fn_args, **fn_kwargs)
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), True,
                user_id=sid, request_id=rid,
                response_size=_calculate_response_size(result),
                input_body=input_body,
            )
            return result
        except Exception as exc:
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                user_id=sid, request_id=rid,
                input_body=input_body,
                error_message=str(exc),
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
# Main Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport in ("sse", "combined"):
        import uvicorn
        from starlette.applications import Starlette

        # Serve both SSE (legacy Claude Code / existing operators) and
        # streamable-http (Claude Desktop, newer clients) on the same port.
        _sse = mcp.sse_app()
        _http = mcp.streamable_http_app()
        
        from admin_api import create_admin_app as _create_admin_app
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route

        async def health_check_handler(_request):
            return JSONResponse({"status": "ok", "transport": transport})

        @asynccontextmanager
        async def combined_lifespan(_app):
            # 1. Start upstream MCP proxy connections using our defined lifespan logic.
            # This registers tools/prompts on the 'mcp' (FastMCP) instance.
            async with lifespan(mcp):
                # 2. Re-setup handlers to ensure Prompts/Tools capabilities are updated
                # in the MCP server instance based on what was just mounted.
                mcp._setup_handlers()
                
                # 3. Start the FastMCP session manager which handles the underlying 
                # JSON-RPC protocol state for both SSE and HTTP transports.
                async with mcp.session_manager.run():
                    yield

        # Mount SSE and streamable-http routes directly at the root.
        _combined = Starlette(
            routes=[
                Mount("/admin", app=_create_admin_app(_telemetry, list_tools_fn=mcp.list_tools)),
                *_sse.routes,
                *_http.routes,
                Route("/health", health_check_handler),
                Route("/", health_check_handler),
            ],
            lifespan=combined_lifespan,
        )

        uvicorn.run(
            _AuthMiddleware(_combined),
            host=os.environ.get("MCP_SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_SERVER_PORT", "8000")),
        )
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
