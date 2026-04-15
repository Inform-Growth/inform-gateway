"""
MCP Proxy — Gateway upstream connection manager.

Reads remote-gateway/mcp_connections.json at startup. For each defined
connection, opens a persistent stdio (subprocess) or SSE connection to the
upstream MCP server, enumerates its tools, and registers them on the gateway
under the naming convention ``<integration>__<tool_name>``.

Employees connect only to the gateway URL — vendor credentials never leave
the server. Access to individual integrations can be revoked by removing the
entry from mcp_connections.json and redeploying.

Usage (called from mcp_server.py lifespan):
    from mcp_proxy import mount_all_proxies

    @asynccontextmanager
    async def lifespan(server: FastMCP):
        proxy_tasks = await mount_all_proxies(server)
        yield
        for task in proxy_tasks:
            task.cancel()
        await asyncio.gather(*proxy_tasks, return_exceptions=True)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

CONNECTIONS_FILE = Path(__file__).parent.parent / "mcp_connections.json"


# Common Node.js binary locations across environments.
# Used as a fallback when the command is not found via PATH alone.
_NODE_BIN_FALLBACKS: list[str] = [
    "/app/node_modules/.bin",                      # Railway standard install
    "node_modules/.bin",                           # Local standard install
    "/app/remote-gateway/vendor/node_modules/.bin", # Build-time vendoring on Railway
    "remote-gateway/vendor/node_modules/.bin",     # Local build-time vendoring
    "/npm-global/bin",                              # Railway/nixpacks custom prefix
    "/root/.nix-profile/bin",                       # nix (Railway, NixOS, devenv)
    "/nix/var/nix/profiles/default/bin",            # nix system profile
    "/usr/local/bin",                               # standard Linux / macOS
    "/usr/bin",                                     # standard Linux
    "/bin",                                         # standard Linux
    "/opt/homebrew/bin",                            # macOS Homebrew (Apple Silicon + Intel)
    str(Path.home() / ".volta/bin"),                # Volta version manager
    str(Path.home() / ".nvm/current/bin"),          # nvm (current symlink)
    str(Path.home() / ".npm-global/bin"),           # common npm global prefix
]


def _resolve_command(command: str, env: dict[str, str]) -> str:
    """Resolve a command name to its full path using the merged environment PATH.

    subprocess.Popen looks up bare command names using the *current process*
    PATH, not the ``env=`` parameter passed to it. When the binary lives in a
    directory that is only present in the child env (e.g. a nix profile or a
    custom npm prefix) the exec will raise ENOENT even though the binary
    exists. Pre-resolving with the merged env's PATH and passing an absolute
    path sidesteps that lookup entirely.

    Falls back to a list of common Node.js binary locations so that stdio
    MCP servers (npm packages) work out of the box on Railway, macOS, standard
    Linux, Volta, nvm, and nix environments without requiring PATH config.

    Args:
        command: Command name, relative path, or absolute path.
        env: Merged environment dict that will be modified in-place to include
            the resolved directory in its PATH.

    Returns:
        Absolute path to the command if found, otherwise the original command
        string (subprocess will raise a clear ENOENT if still not found).
    """
    def _inject_path(resolved_abs_path: str):
        """Prepend the binary's directory to the env's PATH if not already there."""
        parent_dir = str(Path(resolved_abs_path).parent)
        current_path = env.get("PATH", os.environ.get("PATH", ""))
        if parent_dir not in current_path.split(os.pathsep):
            env["PATH"] = (
                f"{parent_dir}{os.pathsep}{current_path}"
                if current_path else parent_dir
            )

    # If it's already an absolute path, just ensure its parent is in the PATH
    if os.path.isabs(command):
        if os.path.exists(command):
            _inject_path(command)
        return command

    # Primary: use the merged env's PATH (covers most cases when PATH is set).
    env_path = env.get("PATH", os.environ.get("PATH", ""))
    resolved = shutil.which(command, path=env_path)
    if resolved:
        _inject_path(os.path.abspath(resolved))
        return os.path.abspath(resolved)

    # Secondary: If the command is a relative path (e.g. "remote-gateway/vendor/..."),
    # try resolving it against the current working directory.
    if os.path.exists(command):
        abs_path = os.path.abspath(command)
        _inject_path(abs_path)
        return abs_path

    # Fallback: scan well-known Node.js locations not covered by PATH.
    for fallback in _NODE_BIN_FALLBACKS:
        resolved = shutil.which(command, path=fallback)
        if resolved:
            abs_path = os.path.abspath(resolved)
            _inject_path(abs_path)
            print(f"  [proxy] Resolved '{command}' to '{abs_path}' via fallback.")
            return abs_path

    return command


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_connections() -> dict[str, dict]:
    """Load upstream MCP connection definitions from mcp_connections.json.

    Returns:
        Dict mapping integration slug → connection config dict.
        Returns empty dict if mcp_connections.json does not exist.
    """
    if not CONNECTIONS_FILE.exists():
        return {}
    data = json.loads(CONNECTIONS_FILE.read_text())
    return data.get("connections", {})


def resolve_headers(headers_config: dict[str, str]) -> dict[str, str]:
    """Expand ``${VAR_NAME}`` references in header values to env var values.

    Handles both full-value references (``${VAR}``) and inline references
    (e.g. ``Bearer ${VAR}``).

    Args:
        headers_config: Dict of header name → value where values may contain ``${VAR}`` refs.

    Returns:
        Dict with all ``${VAR}`` references replaced by their runtime values.
    """
    def _substitute(val: str) -> str:
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), val)

    return {key: _substitute(str(val)) for key, val in headers_config.items()}


def resolve_env(env_config: dict[str, str]) -> dict[str, str]:
    """Expand ``${VAR_NAME}`` references to actual environment variable values.

    Args:
        env_config: Dict of key → value where values may contain ``${VAR}`` refs.

    Returns:
        Dict with all ``${VAR}`` references replaced by their runtime values.
    """
    def _substitute(val: str) -> str:
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), val)

    return {key: _substitute(str(val)) for key, val in env_config.items()}


# ---------------------------------------------------------------------------
# OAuth token refresh helpers
# ---------------------------------------------------------------------------


def _extract_env_var_name(ref: str) -> str | None:
    """Extract the variable name from a ``${VAR_NAME}`` reference string.

    Args:
        ref: A string like ``"${APOLLO_ACCESS_TOKEN}"``.

    Returns:
        The variable name (e.g. ``"APOLLO_ACCESS_TOKEN"``), or None if not a
        ``${...}`` reference.
    """
    if isinstance(ref, str) and ref.startswith("${") and ref.endswith("}"):
        return ref[2:-1]
    return None


def _jwt_exp(token: str) -> int | None:
    """Extract the ``exp`` claim from a JWT without verifying the signature.

    Args:
        token: Raw JWT string.

    Returns:
        Unix timestamp of expiry, or None if it cannot be decoded.
    """
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("exp")
    except Exception:  # noqa: BLE001
        return None


def _token_needs_refresh(token: str, buffer_seconds: int = 300) -> bool:
    """Return True if the token is expired or expires within ``buffer_seconds``.

    Args:
        token: Bearer token (JWT).
        buffer_seconds: Refresh this many seconds before actual expiry.

    Returns:
        True if a refresh is needed.
    """
    exp = _jwt_exp(token)
    if exp is None:
        return False  # Opaque token — can't determine expiry, use as-is and rely on 401 handling
    return time.time() >= (exp - buffer_seconds)


async def _refresh_oauth_token(oauth_config: dict) -> str:
    """Exchange a refresh token for a new access token.

    Calls the token endpoint with ``grant_type=refresh_token``. If the
    server returns a new refresh token, updates ``os.environ`` in place so
    subsequent refreshes during this process lifetime use the latest value.

    Args:
        oauth_config: Resolved dict with ``token_url``, ``client_id``, and
            ``refresh_token`` keys.

    Returns:
        New access token string.

    Raises:
        RuntimeError: If the token endpoint returns an error or no access_token.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            oauth_config["token_url"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": oauth_config["refresh_token"],
                "client_id": oauth_config["client_id"],
            },
        )
        response.raise_for_status()
        data = response.json()

    new_token = data.get("access_token")
    if not new_token:
        raise RuntimeError(f"No access_token in refresh response: {data}")

    # Persist rotated tokens back to os.environ so the next refresh uses them.
    new_refresh = data.get("refresh_token")
    if new_refresh and oauth_config.get("_refresh_env_var"):
        os.environ[oauth_config["_refresh_env_var"]] = new_refresh

    return new_token


async def _get_oauth_token(auth: dict) -> str:
    """Return a valid Bearer token for an OAuth auth config block.

    Resolves ``${VAR}`` references in the auth block, checks expiry,
    and refreshes the token if needed.

    Args:
        auth: The ``auth`` block from a connection config (type must be ``"oauth"``).

    Returns:
        Valid access token string.
    """
    token = os.environ.get(_extract_env_var_name(auth.get("access_token", "")) or "", "")

    if _token_needs_refresh(token):
        def _resolve(val: str) -> str:
            return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), val)

        refresh_config = {
            "token_url": _resolve(auth.get("token_url", "")),
            "client_id": _resolve(auth.get("client_id", "")),
            "refresh_token": _resolve(auth.get("refresh_token", "")),
            "_refresh_env_var": _extract_env_var_name(auth.get("refresh_token", "")),
        }
        print("  [proxy] OAuth token expiring soon — refreshing...")
        token = await _refresh_oauth_token(refresh_config)
        access_var = _extract_env_var_name(auth.get("access_token", ""))
        if access_var:
            os.environ[access_var] = token
        print("  [proxy] Token refreshed.")

    return token


async def resolve_auth_headers(config: dict) -> dict[str, str]:
    """Resolve the auth headers for an HTTP connection based on its auth strategy.

    Dispatches on ``config["auth"]["type"]``:
    - ``"header"``: resolve and return all configured headers as-is
    - ``"oauth"``: get/refresh Bearer token, return Authorization header
    - ``"none"`` or missing: return empty dict (no auth)

    Args:
        config: Full connection config dict from mcp_connections.json.

    Returns:
        Dict of resolved HTTP headers to send with upstream requests.
    """
    auth = config.get("auth", {})
    auth_type = auth.get("type", "none")

    if auth_type == "header":
        return resolve_headers(auth.get("headers", {}))

    if auth_type == "oauth":
        token = await _get_oauth_token(auth)
        return {"Authorization": f"Bearer {token}"}

    if auth_type not in ("none", "header", "oauth", ""):
        print(f"  [proxy] unknown auth type '{auth_type}' — sending no auth headers")
    return {}


# ---------------------------------------------------------------------------
# Tool registration helpers
# ---------------------------------------------------------------------------


def _should_register_tool(tool_name: str, tools_config: dict | None) -> bool:
    """Return True if this tool should be registered given the filter config.

    Supports two mutually exclusive filter modes:
    - ``allow``: whitelist — only listed tools are registered
    - ``deny``: blacklist — all tools except listed ones are registered
    Omitting ``tools_config`` (or passing None) registers everything.

    Args:
        tool_name: Upstream tool name to check.
        tools_config: The ``tools`` block from a connection config, or None.

    Returns:
        True if the tool should be registered on the gateway.
    """
    if not tools_config:
        return True
    if "allow" in tools_config:
        return tool_name in tools_config["allow"]
    if "deny" in tools_config:
        return tool_name not in tools_config["deny"]
    return True


# ---------------------------------------------------------------------------
# Per-integration proxy runner
# ---------------------------------------------------------------------------


async def _run_stdio_proxy(
    name: str,
    config: dict,
    mcp_server: Any,
    ready: asyncio.Event,
) -> None:
    """Connect to one stdio-based upstream MCP and keep it alive.

    Enumerates the upstream server's tools on connect, registers each as a
    proxied tool on the gateway, then blocks indefinitely to maintain the
    subprocess connection.

    Args:
        name: Integration slug used as the tool name prefix (e.g., "stripe").
        config: Connection config dict from mcp_connections.json.
        mcp_server: The FastMCP server instance to register tools on.
        ready: Event set once tools are registered (or on failure).
    """
    raw_env = config.get("env", {})
    env_overrides = resolve_env(raw_env)
    for key, raw_val in raw_env.items():
        if re.search(r"\$\{([^}]+)\}", str(raw_val)) and not env_overrides.get(key):
            var_name = re.search(r"\$\{([^}]+)\}", str(raw_val))
            print(
                f"  [proxy] WARNING: '{name}' env var "
                f"{var_name.group(1) if var_name else key} is not set — "
                f"tools will fail at call time"
            )
    # Silence Node.js deprecation warnings (e.g. punycode) from stdio subprocesses.
    merged_env = {**os.environ, **env_overrides, "NODE_NO_WARNINGS": "1"}

    server_params = StdioServerParameters(
        command=_resolve_command(config["command"], merged_env),
        args=config.get("args", []),
        env=merged_env,
    )

    _errlog = open(os.devnull, "w")  # noqa: WPS515
    try:
        async with contextlib.AsyncExitStack() as _stack:
            read, write = await _stack.enter_async_context(
                stdio_client(server_params, errlog=_errlog)
            )
            session = await _stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            try:
                tools_response = await session.list_tools()
            except Exception:
                from mcp.types import ListToolsResult
                tools_response = ListToolsResult(tools=[])

            try:
                prompts_response = await session.list_prompts()
            except Exception:
                from mcp.types import ListPromptsResult
                prompts_response = ListPromptsResult(prompts=[])

            tools_config = config.get("tools")
            registered_tools = 0
            for tool in tools_response.tools:
                if _should_register_tool(tool.name, tools_config):
                    _register_proxy_tool(mcp_server, name, tool, session)
                    registered_tools += 1

            registered_prompts = 0
            for prompt in prompts_response.prompts:
                _register_proxy_prompt(mcp_server, name, prompt, session)
                registered_prompts += 1

            total_tools = len(tools_response.tools)
            suffix = (
                f" ({total_tools - registered_tools} filtered)"
                if registered_tools != total_tools else ""
            )
            prompt_suffix = f", {registered_prompts} prompt(s)" if registered_prompts else ""
            print(
                f"  [proxy] '{name}' connected — "
                f"{registered_tools} tool(s){prompt_suffix} registered{suffix}"
            )
            ready.set()

            # Hold the connection open for the gateway's lifetime.
            await asyncio.Event().wait()

    except Exception as exc:  # noqa: BLE001
        # Unwrap ExceptionGroup (raised by asyncio.TaskGroup / stdio_client) to
        # surface the real sub-exception rather than the generic outer message.
        if isinstance(exc, BaseExceptionGroup):
            causes = "; ".join(repr(e) for e in exc.exceptions)
            print(f"  [proxy] '{name}' failed to connect: {causes}")
        else:
            print(f"  [proxy] '{name}' failed to connect: {exc}")
        ready.set()  # Unblock startup so the gateway still comes up
    finally:
        _errlog.close()


async def _run_http_proxy(
    name: str,
    config: dict,
    mcp_server: Any,
    ready: asyncio.Event,
) -> None:
    """Connect to one HTTP-based upstream MCP and register its tools.

    Handles two transports differently:

    - ``transport: "http"`` (streamable HTTP): Connects once at startup to
      enumerate tools, then registers each tool with a per-call connection
      factory. The SSE response stream closes after each request-response
      cycle, so a persistent session cannot be reused. No reconnect loop.

    - ``transport: "sse"`` (server-sent events): Maintains a persistent
      session where the server pushes events. Reconnects with 30s back-off
      on disconnect.

    Args:
        name: Integration slug used as the tool name prefix (e.g., "attio").
        config: Connection config dict from mcp_connections.json.
        mcp_server: The FastMCP server instance to register tools on.
        ready: Event set once tools are registered on the first connection.
    """
    url: str = config["url"]
    transport: str = config.get("transport", "http")

    if transport == "http":
        await _run_streamable_http_proxy(name, config, url, mcp_server, ready)
        return

    # SSE: persistent session with reconnect loop.
    tools_registered = False
    auth_retries = 0
    max_auth_retries = 3

    while True:
        try:
            auth_headers = await resolve_auth_headers(config)
            print(f"  [proxy] '{name}' connecting...")

            async with (
                sse_client(url, headers=auth_headers) as (read, write, *_),
                ClientSession(read, write) as session,
            ):
                await session.initialize()

                if not tools_registered:
                    try:
                        tools_response = await session.list_tools()
                    except Exception:
                        from mcp.types import ListToolsResult
                        tools_response = ListToolsResult(tools=[])

                    try:
                        prompts_response = await session.list_prompts()
                    except Exception:
                        from mcp.types import ListPromptsResult
                        prompts_response = ListPromptsResult(prompts=[])

                    tools_config = config.get("tools")
                    registered_tools = 0
                    for tool in tools_response.tools:
                        if _should_register_tool(tool.name, tools_config):
                            _register_proxy_tool(mcp_server, name, tool, session)
                            registered_tools += 1
                    
                    registered_prompts = 0
                    for prompt in prompts_response.prompts:
                        _register_proxy_prompt(mcp_server, name, prompt, session)
                        registered_prompts += 1

                    total_tools = len(tools_response.tools)
                    suffix = (
                        f" ({total_tools - registered_tools} filtered)"
                        if registered_tools != total_tools
                        else ""
                    )
                    prompt_suffix = (
                        f", {registered_prompts} prompt(s)" if registered_prompts else ""
                    )
                    print(
                        f"  [proxy] '{name}' connected — "
                        f"{registered_tools} tool(s){prompt_suffix} registered{suffix}"
                    )
                    tools_registered = True
                    ready.set()

                await asyncio.Event().wait()

        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            exc_text = repr(exc)
            is_auth_error = "401" in exc_text or "unauthorized" in exc_text.lower()
            auth = config.get("auth", {})
            if is_auth_error and auth.get("type") == "oauth" and auth_retries < max_auth_retries:
                auth_retries += 1
                print(
                    f"  [proxy] '{name}' got 401 — refreshing token "
                    f"(attempt {auth_retries}/{max_auth_retries})..."
                )
                try:
                    resolved = resolve_headers(auth)
                    refresh_config = {
                        "token_url": resolved.get("token_url", ""),
                        "client_id": resolved.get("client_id", ""),
                        "refresh_token": resolved.get("refresh_token", ""),
                        "_refresh_env_var": _extract_env_var_name(auth.get("refresh_token", "")),
                    }
                    new_token = await _refresh_oauth_token(refresh_config)
                    print(f"  [proxy] '{name}' token refreshed.")
                    access_var = _extract_env_var_name(auth.get("access_token", ""))
                    if access_var:
                        os.environ[access_var] = new_token
                    await asyncio.sleep(1)
                    continue
                except Exception as refresh_exc:  # noqa: BLE001
                    print(f"  [proxy] '{name}' token refresh failed: {refresh_exc}")
            if not tools_registered:
                if auth_retries >= max_auth_retries:
                    print(
                        f"  [proxy] '{name}' giving up after {max_auth_retries} "
                        f"auth retries — check credentials."
                    )
                else:
                    print(f"  [proxy] '{name}' failed to connect: {exc}")
                ready.set()
                return
            auth_retries = 0
            print(f"  [proxy] '{name}' disconnected ({exc}), reconnecting in 30s...")
            await asyncio.sleep(30)


async def _run_streamable_http_proxy(
    name: str,
    config: dict,
    url: str,
    mcp_server: Any,
    ready: asyncio.Event,
) -> None:
    """Enumerate tools from a streamable HTTP MCP and register per-call connections.

    Streamable HTTP (the MCP default HTTP transport) closes its SSE response
    stream after each request-response cycle. A session established at startup
    is dead by the time tool calls arrive, so we cannot reuse it. Instead:

    1. Connect once to enumerate tools.
    2. Register each tool with a closure that opens a fresh connection per call.
    3. Hold open forever — no reconnect loop needed since each call is
       self-connecting.

    Args:
        name: Integration slug (e.g., "exa").
        config: Full connection config dict from mcp_connections.json.
        url: Upstream MCP endpoint URL.
        mcp_server: FastMCP server to register tools on.
        ready: Event set once tools are registered (or on failure).
    """
    print(f"  [proxy] '{name}' connecting...")
    try:
        auth_headers = await resolve_auth_headers(config)
        async with (
            httpx.AsyncClient(headers=auth_headers) as http_client,
            streamable_http_client(url, http_client=http_client) as (read, write, *_),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            try:
                tools_response = await session.list_tools()
            except Exception:
                from mcp.types import ListToolsResult
                tools_response = ListToolsResult(tools=[])

            try:
                prompts_response = await session.list_prompts()
            except Exception:
                from mcp.types import ListPromptsResult
                prompts_response = ListPromptsResult(prompts=[])

        tools_config = config.get("tools")
        registered_tools = 0
        for tool in tools_response.tools:
            if _should_register_tool(tool.name, tools_config):
                _register_streamable_http_proxy_tool(mcp_server, name, tool, url, config)
                registered_tools += 1

        registered_prompts = 0
        for prompt in prompts_response.prompts:
            _register_streamable_http_proxy_prompt(mcp_server, name, prompt, url, config)
            registered_prompts += 1

        total_tools = len(tools_response.tools)
        suffix = (
            f" ({total_tools - registered_tools} filtered)"
            if registered_tools != total_tools else ""
        )
        prompt_suffix = f", {registered_prompts} prompt(s)" if registered_prompts else ""
        print(
            f"  [proxy] '{name}' connected — "
            f"{registered_tools} tool(s){prompt_suffix} registered{suffix}"
        )
        ready.set()

    except Exception as exc:  # noqa: BLE001
        print(f"  [proxy] '{name}' failed to connect: {exc}")
        ready.set()
        return

    # Hold the task open for the gateway's lifetime.
    # Tool calls are self-connecting, so no reconnect loop is needed.
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# Throttling & Reliability
# ---------------------------------------------------------------------------


class Throttler:
    """Manages concurrency and rate limits for an integration.

    Uses an asyncio.Semaphore for concurrency and tracks request timestamps
    to enforce a requests-per-minute (RPM) limit.
    """

    def __init__(self, name: str, rpm: int = 0, concurrency: int = 2) -> None:
        self.name = name
        self.rpm = rpm
        self.semaphore = asyncio.Semaphore(concurrency)
        self._history: list[float] = []

    async def acquire(self) -> None:
        """Wait for a permit to execute a request."""
        await self.semaphore.acquire()

        if self.rpm > 0:
            now = time.time()
            # Purge history older than 60s
            self._history = [t for t in self._history if now - t < 60]
            if len(self._history) >= self.rpm:
                # Wait until the oldest request is > 60s old
                wait_time = 60 - (now - self._history[0])
                if wait_time > 0:
                    print(f"  [proxy] '{self.name}' rate limit reached — waiting {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
            self._history.append(time.time())

    def release(self) -> None:
        """Release the concurrency permit."""
        self.semaphore.release()


_THROTTLERS: dict[str, Throttler] = {}


def get_throttler(name: str, config: dict) -> Throttler:
    """Return or create a throttler for an integration based on its config."""
    if name not in _THROTTLERS:
        limit_cfg = config.get("rate_limit", {})
        rpm = limit_cfg.get("rpm", 0)
        concurrency = limit_cfg.get("concurrency", 2)
        _THROTTLERS[name] = Throttler(name, rpm, concurrency)
    return _THROTTLERS[name]


def _is_rate_limit_error(result: Any) -> bool:
    """Return True if the result or error message indicates a rate limit."""
    if not isinstance(result, dict):
        return False

    # Check for explicit flags
    if result.get("is_rate_limit") or result.get("is_throttled"):
        return True

    # Check for 429 status or common strings in error messages
    error_msg = str(result.get("error", "")).lower()
    return any(s in error_msg for s in ("429", "rate limit", "too many requests", "throttled"))


async def _call_with_retry(
    integration: str,
    tool_name: str,
    call_fn: Any,
    max_retries: int = 3,
) -> Any:
    """Execute a tool call with throttling and exponential backoff on rate limits."""
    # We use a global registry so limits are shared across all tools of one integration
    config = load_connections().get(integration, {})
    throttler = get_throttler(integration, config)

    for attempt in range(max_retries + 1):
        await throttler.acquire()
        try:
            result = await call_fn()
            if _is_rate_limit_error(result) and attempt < max_retries:
                backoff = (2**attempt) + (time.time() % 1)  # 1s, 2s, 4s + jitter
                print(
                    f"  [proxy] '{integration}__{tool_name}' rate limited — "
                    f"retry {attempt + 1}/{max_retries} in {backoff:.1f}s"
                )
                await asyncio.sleep(backoff)
                continue
            return result
        finally:
            throttler.release()

    return {
        "error": f"Maximum retries exceeded for '{integration}__{tool_name}' (rate limited)",
        "is_proxy_error": True,
        "is_rate_limit": True,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def _register_proxy_tool(
    mcp_server: Any,
    integration: str,
    tool: Any,
    session: ClientSession,
) -> None:
    """Register a single upstream tool as a callable on the gateway.

    The gateway-side name is ``<integration>__<tool_name>`` so tools
    from different integrations never collide and the source is always clear.

    Args:
        mcp_server: FastMCP server to register the tool on.
        integration: Integration slug (e.g., "stripe").
        tool: MCP Tool object from list_tools() response.
        session: Live ClientSession used to forward calls.
    """
    upstream_name: str = tool.name
    gateway_name: str = f"{integration}__{upstream_name}"
    description: str = (
        (tool.description or upstream_name)
        + f"\n\n[Proxied from the '{integration}' integration. Managed by gateway admin.]"
    )

    async def proxy_fn(**kwargs: Any) -> Any:
        """Forward the call to the upstream MCP server and return its response."""
        # FastMCP wraps tool args under a single "kwargs" key when the function
        # signature is **kwargs. Unwrap one level so upstream tools receive flat
        # params (e.g. {"domain": "gong.io"}) rather than {"kwargs": {"domain": ...}}.
        if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs["kwargs"], dict):
            upstream_kwargs = kwargs["kwargs"]
        else:
            upstream_kwargs = kwargs

        async def _execute():
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

        return await _call_with_retry(integration, upstream_name, _execute)

    proxy_fn.__name__ = gateway_name
    proxy_fn.__doc__ = description
    mcp_server.add_tool(proxy_fn, name=gateway_name, description=description)


def _register_proxy_prompt(
    mcp_server: Any,
    integration: str,
    prompt: Any,
    session: ClientSession,
) -> None:
    """Register a single upstream prompt as a callable on the gateway.

    Args:
        mcp_server: FastMCP server to register the prompt on.
        integration: Integration slug (e.g., "stripe").
        prompt: MCP Prompt object from list_prompts() response.
        session: Live ClientSession used to forward calls.
    """
    upstream_name: str = prompt.name
    gateway_name: str = f"{integration}__{upstream_name}"
    description: str = (
        (prompt.description or upstream_name)
        + f"\n\n[Proxied from the '{integration}' integration. Managed by gateway admin.]"
    )

    async def proxy_fn(arguments: dict[str, Any] | None = None) -> str:
        """Forward the prompt request to the upstream MCP server."""
        try:
            result = await session.get_prompt(upstream_name, arguments)
            # Prompts return a list of messages (text/image/resource).
            # FastMCP expects the function to return a single string or a Prompt object.
            # We join text components for simplicity if returning a string.
            texts = []
            for msg in result.messages:
                if msg.content.type == "text":
                    texts.append(msg.content.text)
            return "\n\n".join(texts)
        except Exception as exc:
            return f"Error fetching proxied prompt '{gateway_name}': {exc}"

    proxy_fn.__name__ = gateway_name
    proxy_fn.__doc__ = description
    from mcp.server.fastmcp.prompts import Prompt as _Prompt
    mcp_server.add_prompt(
        _Prompt.from_function(proxy_fn, name=gateway_name, description=description)
    )


def _register_streamable_http_proxy_tool(
    mcp_server: Any,
    integration: str,
    tool: Any,
    url: str,
    config: dict,
) -> None:
    """Register a streamable HTTP tool that opens a fresh connection per call.

    Unlike ``_register_proxy_tool``, this does not capture a session. Instead,
    the closure reconnects to the upstream server on every invocation. This is
    required for streamable HTTP because the server's SSE response stream closes
    after each request-response cycle — a session established at startup is dead
    by the time the first tool call arrives.

    Args:
        mcp_server: FastMCP server to register the tool on.
        integration: Integration slug (e.g., "exa").
        tool: MCP Tool object from list_tools() response.
        url: Upstream MCP endpoint URL.
        config: Full connection config dict (used to resolve auth headers per call).
    """
    upstream_name: str = tool.name
    gateway_name: str = f"{integration}__{upstream_name}"
    description: str = (
        (tool.description or upstream_name)
        + f"\n\n[Proxied from the '{integration}' integration. Managed by gateway admin.]"
    )

    async def proxy_fn(**kwargs: Any) -> Any:
        """Forward the call via a fresh connection to the upstream MCP server."""
        if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs["kwargs"], dict):
            upstream_kwargs = kwargs["kwargs"]
        else:
            upstream_kwargs = kwargs

        async def _execute():
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

        return await _call_with_retry(integration, upstream_name, _execute)

    proxy_fn.__name__ = gateway_name
    proxy_fn.__doc__ = description
    mcp_server.add_tool(proxy_fn, name=gateway_name, description=description)


def _register_streamable_http_proxy_prompt(
    mcp_server: Any,
    integration: str,
    prompt: Any,
    url: str,
    config: dict,
) -> None:
    """Register a streamable HTTP prompt that opens a fresh connection per call.

    Args:
        mcp_server: FastMCP server to register the prompt on.
        integration: Integration slug (e.g., "exa").
        prompt: MCP Prompt object from list_prompts() response.
        url: Upstream MCP endpoint URL.
        config: Full connection config.
    """
    upstream_name: str = prompt.name
    gateway_name: str = f"{integration}__{upstream_name}"
    description: str = (
        (prompt.description or upstream_name)
        + f"\n\n[Proxied from the '{integration}' integration. Managed by gateway admin.]"
    )

    async def proxy_fn(arguments: dict[str, Any] | None = None) -> str:
        """Forward the call via a fresh connection to the upstream MCP server."""
        try:
            auth_headers = await resolve_auth_headers(config)
            async with (
                httpx.AsyncClient(headers=auth_headers) as http_client,
                streamable_http_client(url, http_client=http_client) as (read, write, *_),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.get_prompt(upstream_name, arguments)
                texts = []
                for msg in result.messages:
                    if msg.content.type == "text":
                        texts.append(msg.content.text)
                return "\n\n".join(texts)
        except Exception as exc:
            return f"Error fetching proxied prompt '{gateway_name}': {exc}"

    proxy_fn.__name__ = gateway_name
    proxy_fn.__doc__ = description
    from mcp.server.fastmcp.prompts import Prompt as _Prompt
    mcp_server.add_prompt(
        _Prompt.from_function(proxy_fn, name=gateway_name, description=description)
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def mount_all_proxies(mcp_server: Any) -> list[asyncio.Task]:
    """Mount all upstream MCPs defined in mcp_connections.json.

    Called from the gateway's lifespan context at startup. Waits for every
    connection to either succeed or fail before returning, so the gateway
    never starts serving with missing tools.

    Args:
        mcp_server: The FastMCP server instance.

    Returns:
        List of running asyncio Tasks (one per connection). Cancel these
        in the lifespan shutdown path to cleanly close upstream processes.
    """
    connections = load_connections()
    if not connections:
        print("  [proxy] No upstream MCP connections configured.")
        return []

    tasks: list[asyncio.Task] = []
    ready_events: list[asyncio.Event] = []

    for name, config in connections.items():
        transport = config.get("transport", "stdio")

        if transport == "stdio":
            runner = _run_stdio_proxy
        elif transport in ("http", "sse"):
            runner = _run_http_proxy
        else:
            print(f"  [proxy] '{name}' skipped — transport '{transport}' not supported.")
            continue

        ready = asyncio.Event()
        ready_events.append(ready)
        task = asyncio.create_task(
            runner(name, config, mcp_server, ready),
            name=f"proxy:{name}",
        )
        tasks.append(task)

    # Wait until all proxies have either connected or failed before the
    # gateway starts accepting requests. Cap at 30s so a slow/hanging
    # subprocess (e.g. npx download) doesn't block the server indefinitely.
    if ready_events:
        try:
            await asyncio.wait_for(
                asyncio.gather(*(e.wait() for e in ready_events)),
                timeout=30,
            )
        except TimeoutError:
            timed_out = [
                name
                for name, ev in zip(connections, ready_events, strict=False)
                if not ev.is_set()
            ]
            print(
                f"  [proxy] Startup timeout — still waiting for: {timed_out}. "
                f"Proceeding anyway."
            )

    return tasks
