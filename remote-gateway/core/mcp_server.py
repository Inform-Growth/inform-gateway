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
from mcp.server.lowlevel.server import lifespan as _noop_lifespan  # noqa: E402
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

_GATE_BYPASS: frozenset[str] = frozenset({
    "setup_start",
    "setup_save_profile",
    "setup_complete",
    "health_check",
    "skill_create",
    "skill_update",
    "skill_list",
    "run_skill",
    "profile_get",
    "profile_update",
    "create_user",
    "get_operator_instructions",
    "list_prompts",
    "get_prompt",
    "declare_intent",
    "complete_task",
    "get_tasks",
})


# _TASK_BYPASS must stay a superset of _GATE_BYPASS — any tool added to _GATE_BYPASS
# that should also bypass the task gate must be added here too.
_TASK_BYPASS: frozenset[str] = frozenset({
    "setup_start",
    "setup_save_profile",
    "setup_complete",
    "health_check",
    "skill_create",
    "skill_update",
    "skill_list",
    "run_skill",
    "profile_get",
    "profile_update",
    "create_user",
    "get_operator_instructions",
    "list_prompts",
    "get_prompt",
    "declare_intent",
    "complete_task",
    "get_tasks",
})


def _make_gate_task_redirect(tool_name: str) -> dict:
    return {
        "gateway_status": "no_active_task",
        "message": (
            "GATEWAY: No active task declared. "
            "AGENT INSTRUCTION: Call declare_intent with your goal and planned steps "
            "before using any tools."
        ),
        "blocked_tool": tool_name,
        "required_action": "declare_intent",
    }


def _inject_task_id_param(fn: Any) -> None:
    """Append optional task_id: str | None = None to fn's __signature__.

    FastMCP reads __signature__ to build the JSON schema advertised in tools/list.
    Setting it explicitly here overrides functools.wraps' __wrapped__ chain so
    every tool — built-in and proxied — exposes task_id as an optional parameter.
    The wrapper pops task_id from kwargs before calling the real function, so
    proxied tools never see a parameter they don't expect.
    """
    import inspect as _inspect
    sig = _inspect.signature(fn)
    if "task_id" in sig.parameters:
        return
    task_param = _inspect.Parameter(
        "task_id",
        _inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=str | None,
    )
    fn.__signature__ = sig.replace(
        parameters=list(sig.parameters.values()) + [task_param]
    )


def _get_org_id(user_id: str | None) -> str | None:
    """Return org_id for a user, or None for unauthenticated requests."""
    if user_id is None:
        return None
    return _telemetry.get_org_id(user_id)


def _make_gate_redirect(tool_name: str) -> dict[str, str]:
    return {
        "gateway_status": "not_initialized",
        "message": (
            "GATEWAY: This organization has not been set up yet. "
            "AGENT INSTRUCTION: Stop immediately and ask the user: "
            "'Your gateway needs to be initialized before any tools can be used. "
            "Would you like me to run setup now?' "
            "Only call setup_start if the user confirms."
        ),
        "blocked_tool": tool_name,
        "required_action": "setup_start",
    }


def _enrich_with_hint(result: Any, org_id: str, tool_name: str) -> Any:
    """Wrap result with tool hint meta if a hint exists for this org+tool.

    Returns the original result unchanged when no hint is configured.
    """
    if result is None:
        return result
    if not isinstance(org_id, str) or not org_id:
        return result
    hint = _telemetry.get_tool_hint(org_id, tool_name)
    if not hint or not isinstance(hint, dict):
        return result
    return {
        "data": result,
        "meta": {
            "interpretation_hint": hint.get("interpretation_hint"),
            "usage_rules": hint.get("usage_rules"),
            "data_sensitivity": hint.get("data_sensitivity"),
        },
    }


_PUBLIC_PATH_PREFIXES: tuple[str, ...] = ("/admin",)
_PUBLIC_EXACT_PATHS: frozenset[str] = frozenset({"/", "/health"})


def _is_public_path(path: str) -> bool:
    """Return True for routes that don't require an authenticated user.

    Admin routes have their own ``ADMIN_TOKEN`` query-param auth; ``/`` and
    ``/health`` are uptime probes. Everything else (MCP transport routes:
    ``/mcp``, ``/sse``, ``/messages/``, etc.) requires a Bearer token that
    resolves to a real user.
    """
    if path in _PUBLIC_EXACT_PATHS:
        return True
    return any(path == p or path.startswith(p + "/") for p in _PUBLIC_PATH_PREFIXES)


_UNAUTHORIZED_BODY: bytes = (
    b'{"error":"unauthorized",'
    b'"message":"Missing or invalid API key. '
    b'Set Authorization: Bearer sk-<key> or pass ?api_key=sk-<key>."}'
)


async def _send_http_unauthorized(send: Any) -> None:
    """Emit a 401 JSON response — never invokes the inner ASGI app."""
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="inform-gateway"'),
                (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})


async def _close_websocket_unauthorized(send: Any) -> None:
    """Close an unauthenticated websocket with policy-violation code 1008."""
    await send({"type": "websocket.close", "code": 1008, "reason": "missing or invalid api key"})


class _AuthMiddleware:
    """ASGI middleware: API key → user_id → ContextVar; reject anonymous MCP.

    Checks two locations in priority order:
    1. ``Authorization: Bearer <key>`` header  — Claude Code, API clients
    2. ``?api_key=<key>`` query parameter       — Claude Desktop/Web, OpenAI, Gemini
       (clients that set a URL but cannot add custom headers)

    Requests to non-public paths (anything other than ``/``, ``/health``, or
    ``/admin/...``) without a valid key are rejected with 401 (HTTP) or close
    code 1008 (WebSocket); the inner ASGI app is never invoked. Stdio
    transport is unaffected — this middleware only runs in HTTP / WS modes.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        scope_type = scope["type"]
        if scope_type not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        key = self._extract_key(scope)
        user_id = _telemetry.lookup_user(key) if key else None

        if user_id is None and not _is_public_path(scope.get("path", "")):
            if scope_type == "http":
                await _send_http_unauthorized(send)
            else:
                await _close_websocket_unauthorized(send)
            return

        token = _current_user.set(user_id)
        try:
            await self._app(scope, receive, send)
        finally:
            _current_user.reset(token)

    @staticmethod
    def _extract_key(scope: Any) -> str | None:
        """Return the API key from the Authorization header or api_key query param.

        Scans headers directly — no dict allocation on the hot request path.
        """
        for key, val in scope.get("headers", []):
            if key.lower() == b"authorization":
                auth: str = val.decode()
                if auth.lower().startswith("bearer "):
                    return auth[7:].strip() or None

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


def _resolve_user_from_request_ctx() -> str | None:
    """Return user_id by reading the current Starlette request, or None.

    MCP's streamable-http and SSE transports attach the active Starlette
    ``Request`` to each JSON-RPC message via ``ServerMessageMetadata``; the
    low-level server exposes it as ``request_ctx.get().request`` inside the
    same task that dispatches the tool. Reading auth here — instead of from
    a ContextVar set in ASGI middleware — sidesteps the long-lived
    ``run_server`` task created by ``StreamableHTTPSessionManager``, which
    snapshots its ContextVars at session creation time and therefore never
    sees per-request auth on follow-up calls.
    """
    try:
        ctx = _request_ctx.get()
    except LookupError:
        return None

    request = getattr(ctx, "request", None)
    if request is None:
        return None

    key: str | None = None
    auth = request.headers.get("authorization") if hasattr(request, "headers") else None
    if auth and auth.lower().startswith("bearer "):
        key = auth[7:].strip() or None

    if key is None and hasattr(request, "query_params"):
        key = request.query_params.get("api_key") or None

    if not key:
        return None
    return _telemetry.lookup_user(key)


def _get_call_ids() -> tuple[str | None, str | None]:
    """Return (user_id, request_id) for the current request.

    user_id is resolved per-call from the live Starlette ``Request`` exposed
    on ``request_ctx``; this is the source of truth for HTTP transports.
    Falls back to the ``_current_user`` ContextVar (set by ``_AuthMiddleware``)
    for stdio and any transport that does not attach the request to message
    metadata. request_id comes from the MCP request context. Both are None
    outside of an active request (e.g. during tests).
    """
    user_id = _resolve_user_from_request_ctx()
    if user_id is None:
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


def _get_response_preview(result: Any) -> str | None:
    """Return the first 400 chars of str(result), or None if result is None."""
    if result is None:
        return None
    try:
        return str(result)[:400]
    except Exception:
        return None


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
                task_id = fn_kwargs.pop("task_id", None)
                input_body = json.dumps(fn_kwargs, default=str)
                if fn.__name__ not in _GATE_BYPASS:
                    _org = _get_org_id(sid)
                    if _org and not _telemetry.is_initialized(_org):
                        return _make_gate_redirect(fn.__name__)
                if fn.__name__ not in _TASK_BYPASS and sid:
                    if task_id is not None:
                        task_row = _telemetry.get_task(task_id)
                        if task_row is None or task_row["user_id"] != sid or task_row["status"] != "active":
                            task_id = None
                    active = _telemetry.list_active_tasks(sid)
                    if not active and task_id is None:
                        return _make_gate_task_redirect(fn.__name__)
                    if task_id is None and active:
                        task_id = active[0]["task_id"]
                if sid and not _telemetry.has_permission(sid, fn.__name__):
                    _perm_msg = f"Tool '{fn.__name__}' is disabled for your account."
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                        "PermissionError", user_id=sid, request_id=rid,
                        input_body=input_body,
                        error_message=_perm_msg,
                        task_id=task_id,
                    )
                    raise PermissionError(_perm_msg)
                try:
                    result = await fn(*fn_args, **fn_kwargs)
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                        user_id=sid, request_id=rid,
                        response_size=_calculate_response_size(result),
                        input_body=input_body,
                        response_preview=_get_response_preview(result),
                        task_id=task_id,
                    )
                    _org = _get_org_id(sid)
                    if _org:
                        result = _enrich_with_hint(result, _org, fn.__name__)
                    return result
                except Exception as exc:
                    _telemetry.record(
                        fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                        type(exc).__name__, user_id=sid, request_id=rid,
                        input_body=input_body,
                        error_message=str(exc),
                        task_id=task_id,
                    )
                    raise

            _inject_task_id_param(tracked_async)
            return fastmcp_decorator(tracked_async)

        @functools.wraps(fn)
        def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            task_id = fn_kwargs.pop("task_id", None)
            input_body = json.dumps(fn_kwargs, default=str)
            if fn.__name__ not in _GATE_BYPASS:
                _org = _get_org_id(sid)
                if _org and not _telemetry.is_initialized(_org):
                    return _make_gate_redirect(fn.__name__)
            if fn.__name__ not in _TASK_BYPASS and sid:
                if task_id is not None:
                    task_row = _telemetry.get_task(task_id)
                    if task_row is None or task_row["user_id"] != sid or task_row["status"] != "active":
                        task_id = None
                active = _telemetry.list_active_tasks(sid)
                if not active and task_id is None:
                    return _make_gate_task_redirect(fn.__name__)
                if task_id is None and active:
                    task_id = active[0]["task_id"]
            if sid and not _telemetry.has_permission(sid, fn.__name__):
                _perm_msg = f"Tool '{fn.__name__}' is disabled for your account."
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False,
                    "PermissionError", user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=_perm_msg,
                    task_id=task_id,
                )
                raise PermissionError(_perm_msg)
            try:
                result = fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid,
                    response_size=_calculate_response_size(result),
                    input_body=input_body,
                    response_preview=_get_response_preview(result),
                    task_id=task_id,
                )
                _org = _get_org_id(sid)
                if _org:
                    result = _enrich_with_hint(result, _org, fn.__name__)
                return result
            except Exception as exc:
                _telemetry.record(
                    fn.__name__, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=str(exc),
                    task_id=task_id,
                )
                raise

        _inject_task_id_param(tracked)
        return fastmcp_decorator(tracked)

    return wrapper


mcp.tool = _tracked_mcp_tool

_orig_add_tool = mcp.add_tool


def _tracked_add_tool(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Replacement for mcp.add_tool() that injects timing and error recording.

    Proxy tools (attio, exa, apollo, etc.) are registered via add_tool() rather
    than the @mcp.tool() decorator, so they bypass _tracked_mcp_tool. This patch
    ensures every tool — decorator or direct — is captured in telemetry.

    Note: FastMCP's ``@mcp.tool()`` decorator internally calls
    ``self.add_tool(fn, name=None, ...)`` when the caller did not supply a
    name, so ``kwargs.get("name", fn.__name__)`` can't be relied on — it will
    return ``None`` whenever ``name`` is present but falsy. Normalize here
    against ``fn.__name__`` so gate, permission, and telemetry paths always
    see a real tool name.
    """
    tool_name: str = kwargs.get("name") or getattr(fn, "__name__", "unknown")

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def tracked_async(*fn_args: Any, **fn_kwargs: Any) -> Any:
            t0 = _time.monotonic()
            sid, rid = _get_call_ids()
            task_id = fn_kwargs.pop("task_id", None)
            input_body = json.dumps(fn_kwargs, default=str)
            if tool_name not in _GATE_BYPASS:
                _org = _get_org_id(sid)
                if _org and not _telemetry.is_initialized(_org):
                    return _make_gate_redirect(tool_name)
            if tool_name not in _TASK_BYPASS and sid:
                if task_id is not None:
                    task_row = _telemetry.get_task(task_id)
                    if task_row is None or task_row["user_id"] != sid or task_row["status"] != "active":
                        task_id = None
                active = _telemetry.list_active_tasks(sid)
                if not active and task_id is None:
                    return _make_gate_task_redirect(tool_name)
                if task_id is None and active:
                    task_id = active[0]["task_id"]
            if sid and not _telemetry.has_permission(sid, tool_name):
                _perm_msg = f"Tool '{tool_name}' is disabled for your account."
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), False,
                    "PermissionError", user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=_perm_msg,
                    task_id=task_id,
                )
                raise PermissionError(_perm_msg)
            try:
                result = await fn(*fn_args, **fn_kwargs)
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), True,
                    user_id=sid, request_id=rid,
                    response_size=_calculate_response_size(result),
                    input_body=input_body,
                    response_preview=_get_response_preview(result),
                    task_id=task_id,
                )
                _org = _get_org_id(sid)
                if _org:
                    result = _enrich_with_hint(result, _org, tool_name)
                return result
            except Exception as exc:
                _telemetry.record(
                    tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                    user_id=sid, request_id=rid,
                    input_body=input_body,
                    error_message=str(exc),
                    task_id=task_id,
                )
                raise

        _inject_task_id_param(tracked_async)
        return _orig_add_tool(tracked_async, *args, **kwargs)

    @functools.wraps(fn)
    def tracked(*fn_args: Any, **fn_kwargs: Any) -> Any:
        t0 = _time.monotonic()
        sid, rid = _get_call_ids()
        task_id = fn_kwargs.pop("task_id", None)
        input_body = json.dumps(fn_kwargs, default=str)
        if tool_name not in _GATE_BYPASS:
            _org = _get_org_id(sid)
            if _org and not _telemetry.is_initialized(_org):
                return _make_gate_redirect(tool_name)
        if tool_name not in _TASK_BYPASS and sid:
            if task_id is not None:
                task_row = _telemetry.get_task(task_id)
                if task_row is None or task_row["user_id"] != sid or task_row["status"] != "active":
                    task_id = None
            active = _telemetry.list_active_tasks(sid)
            if not active and task_id is None:
                return _make_gate_task_redirect(tool_name)
            if task_id is None and active:
                task_id = active[0]["task_id"]
        if sid and not _telemetry.has_permission(sid, tool_name):
            _perm_msg = f"Tool '{tool_name}' is disabled for your account."
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), False,
                "PermissionError", user_id=sid, request_id=rid,
                input_body=input_body,
                error_message=_perm_msg,
                task_id=task_id,
            )
            raise PermissionError(_perm_msg)
        try:
            result = fn(*fn_args, **fn_kwargs)
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), True,
                user_id=sid, request_id=rid,
                response_size=_calculate_response_size(result),
                input_body=input_body,
                response_preview=_get_response_preview(result),
                task_id=task_id,
            )
            _org = _get_org_id(sid)
            if _org:
                result = _enrich_with_hint(result, _org, tool_name)
            return result
        except Exception as exc:
            _telemetry.record(
                tool_name, int((_time.monotonic() - t0) * 1000), False, type(exc).__name__,
                user_id=sid, request_id=rid,
                input_body=input_body,
                error_message=str(exc),
                task_id=task_id,
            )
            raise

    _inject_task_id_param(tracked)
    return _orig_add_tool(tracked, *args, **kwargs)


mcp.add_tool = _tracked_add_tool

_orig_list_tools = mcp.list_tools


async def _filtered_list_tools() -> list[Any]:
    """list_tools override that hides tools disabled for the current user.

    Reads _disabled_cache from telemetry — no DB query at list time.
    Fails open: returns the full tool list if telemetry is unavailable.
    Global disables (user_id='*') apply to unauthenticated requests too.

    Patched onto mcp.list_tools so every tools/list RPC goes through this.
    If FastMCP's tools/list RPC handler calls an internal method rather than
    mcp.list_tools, the patch target may need to be mcp._tool_manager.list_tools
    instead — verify by confirming that filtering applies during a live session.
    """
    tools = await _orig_list_tools()
    user_id = _resolve_user_from_request_ctx() or _current_user.get()
    if not _telemetry._enabled:
        return tools
    visible = _telemetry.filter_visible_tools(user_id, [t.name for t in tools])
    return [t for t in tools if t.name in visible]


mcp.list_tools = _filtered_list_tools


# ---------------------------------------------------------------------------
# Register internal tools from tools/ modules
# (imported here so .env is loaded and mcp.tool telemetry patch is active)
# ---------------------------------------------------------------------------

import sys as _sys  # noqa: E402

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import attio as _attio_tools  # noqa: E402
from tools import email_tools as _email_tools  # noqa: E402
from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402
from tools import wiza as _wiza_tools  # noqa: E402
from tools._core import onboarding as _onboarding_tools  # noqa: E402
from tools._core import skill_manager as _skill_manager_tools  # noqa: E402
from tools._core import profile_manager as _profile_manager_tools  # noqa: E402
from tools._core import task_manager as _task_manager_tools  # noqa: E402

class _RequestAwareUser:
    """ContextVar-compatible shim whose ``.get()`` resolves the caller per-request.

    Tool modules read ``current_user_var.get()`` inside tool functions. The real
    ``_current_user`` ContextVar is stale across the streamable-http session's
    ``run_server`` task boundary, so delegate to the same resolver used by the
    telemetry wrappers (reads the live Starlette request attached by MCP to
    each JSON-RPC message, falls back to the ASGI-middleware ContextVar).
    """

    def get(self, *default: Any) -> str | None:
        user_id = _resolve_user_from_request_ctx()
        if user_id is not None:
            return user_id
        if default:
            return _current_user.get(default[0])
        return _current_user.get()

    def set(self, value: str | None) -> Any:
        return _current_user.set(value)

    def reset(self, token: Any) -> None:
        _current_user.reset(token)


_user_view = _RequestAwareUser()

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
_attio_tools.register(mcp)  # must register after telemetry patch is applied
_email_tools.register(mcp)
_wiza_tools.register(mcp)
_onboarding_tools.register(mcp, _telemetry, _user_view)
_skill_manager_tools.register(mcp, _telemetry, _user_view)
_profile_manager_tools.register(mcp, _telemetry, _user_view)
_task_manager_tools.register(mcp, _telemetry, _user_view)


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

                # 3. Prevent per-SSE-connection re-initialization: FastMCP's low-level
                # Server.run() calls self.lifespan() on every SSE client connection,
                # which would re-run mount_all_proxies for each client. Swap it out
                # for the built-in no-op now that startup is complete.
                mcp._mcp_server.lifespan = _noop_lifespan

                # 4. Start the FastMCP session manager which handles the underlying
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
