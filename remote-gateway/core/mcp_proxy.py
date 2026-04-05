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
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

CONNECTIONS_FILE = Path(__file__).parent.parent / "mcp_connections.json"


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


def _access_token_env_var(config: dict) -> str | None:
    """Extract the env var name backing the Authorization Bearer token.

    Looks for a ``Bearer ${VAR_NAME}`` pattern in the headers config and
    returns ``VAR_NAME``, so callers can update ``os.environ`` after a refresh.

    Args:
        config: Connection config dict from mcp_connections.json.

    Returns:
        Env var name (e.g. ``"ATTIO_ACCESS_TOKEN"``), or None if not found.
    """
    auth_val = config.get("headers", {}).get("Authorization", "")
    if auth_val.startswith("Bearer ${") and auth_val.endswith("}"):
        return auth_val[len("Bearer ${"):-1]
    return None


def _refresh_token_env_var(config: dict) -> str | None:
    """Extract the env var name for the refresh token in the oauth config.

    Args:
        config: Connection config dict from mcp_connections.json.

    Returns:
        Env var name (e.g. ``"ATTIO_REFRESH_TOKEN"``), or None if not found.
    """
    refresh_val = config.get("oauth", {}).get("refresh_token", "")
    if refresh_val.startswith("${") and refresh_val.endswith("}"):
        return refresh_val[2:-1]
    return None


async def _get_current_token(config: dict) -> str:
    """Return a valid Bearer token for an HTTP proxy config.

    Reads the current ``Authorization`` header value. If the embedded JWT is
    near expiry and an ``oauth`` block is present, refreshes it first.

    Args:
        config: Connection config dict from mcp_connections.json.

    Returns:
        Valid access token string.
    """
    headers = resolve_headers(config.get("headers", {}))
    auth = headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()

    oauth_raw = config.get("oauth")
    if oauth_raw and _token_needs_refresh(token):
        oauth = resolve_headers(oauth_raw)
        oauth["_refresh_env_var"] = _refresh_token_env_var(config)
        print("  [proxy] OAuth token expiring soon — refreshing...")
        token = await _refresh_oauth_token(oauth)
        access_var = _access_token_env_var(config)
        if access_var:
            os.environ[access_var] = token
        print("  [proxy] Token refreshed.")

    return token


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
    env_overrides = resolve_env(config.get("env", {}))
    merged_env = {**os.environ, **env_overrides}

    server_params = StdioServerParameters(
        command=config["command"],
        args=config.get("args", []),
        env=merged_env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_response = await session.list_tools()

                for tool in tools_response.tools:
                    _register_proxy_tool(mcp_server, name, tool, session)

                count = len(tools_response.tools)
                print(f"  [proxy] '{name}' connected — {count} tool(s) available")
                ready.set()

                # Hold the connection open for the gateway's lifetime.
                await asyncio.Event().wait()

    except Exception as exc:  # noqa: BLE001
        print(f"  [proxy] '{name}' failed to connect: {exc}")
        ready.set()  # Unblock startup so the gateway still comes up


async def _run_http_proxy(
    name: str,
    config: dict,
    mcp_server: Any,
    ready: asyncio.Event,
) -> None:
    """Connect to one HTTP-based upstream MCP and keep it alive.

    Supports both streamable HTTP (``transport: "http"``) and SSE
    (``transport: "sse"``). Resolves ``Authorization`` headers from env vars
    and, if an ``oauth`` block is present, automatically refreshes the Bearer
    token before connecting or when the connection drops.

    Reconnects indefinitely on disconnect with a 30-second back-off.

    Args:
        name: Integration slug used as the tool name prefix (e.g., "attio").
        config: Connection config dict from mcp_connections.json.
        mcp_server: The FastMCP server instance to register tools on.
        ready: Event set once tools are registered on the first connection.
    """
    url: str = config["url"]
    transport: str = config.get("transport", "http")
    tools_registered = False
    auth_retries = 0
    max_auth_retries = 3

    while True:
        try:
            token = await _get_current_token(config)
            auth_headers = {"Authorization": f"Bearer {token}"}
            print(f"  [proxy] '{name}' connecting with token ...{token[-8:]}")

            if transport == "sse":
                client_cm = sse_client(url, headers=auth_headers)
            else:
                http_client = httpx.AsyncClient(headers=auth_headers)
                client_cm = streamable_http_client(url, http_client=http_client)

            async with client_cm as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    if not tools_registered:
                        tools_response = await session.list_tools()
                        for tool in tools_response.tools:
                            _register_proxy_tool(mcp_server, name, tool, session)
                        count = len(tools_response.tools)
                        print(f"  [proxy] '{name}' connected — {count} tool(s) available")
                        tools_registered = True
                        ready.set()

                    await asyncio.Event().wait()

        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            exc_text = repr(exc)
            is_auth_error = "401" in exc_text or "unauthorized" in exc_text.lower()
            if is_auth_error and config.get("oauth") and auth_retries < max_auth_retries:
                auth_retries += 1
                print(f"  [proxy] '{name}' got 401 — refreshing token (attempt {auth_retries}/{max_auth_retries})...")
                try:
                    oauth = resolve_headers(config["oauth"])
                    oauth["_refresh_env_var"] = _refresh_token_env_var(config)
                    new_token = await _refresh_oauth_token(oauth)
                    print(f"  [proxy] '{name}' got new token ...{new_token[-8:]}")
                    access_var = _access_token_env_var(config)
                    if access_var:
                        os.environ[access_var] = new_token
                    await asyncio.sleep(1)
                    continue
                except Exception as refresh_exc:  # noqa: BLE001
                    print(f"  [proxy] '{name}' token refresh failed: {refresh_exc}")
            if not tools_registered:
                if auth_retries >= max_auth_retries:
                    print(f"  [proxy] '{name}' giving up after {max_auth_retries} auth retries — check credentials.")
                else:
                    print(f"  [proxy] '{name}' failed to connect: {exc}")
                ready.set()
                return
            auth_retries = 0
            print(f"  [proxy] '{name}' disconnected ({exc}), reconnecting in 30s...")
            await asyncio.sleep(30)


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

    The gateway-side name is ``<integration>__<upstream_tool_name>`` so tools
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
        result = await session.call_tool(upstream_name, upstream_kwargs)
        if not result.content:
            return {}
        content = result.content[0]
        if hasattr(content, "text"):
            try:
                parsed = json.loads(content.text)
                # FastMCP cannot return a bare list — wrap it so the response
                # reaches the client rather than being silently dropped.
                return {"results": parsed} if isinstance(parsed, list) else parsed
            except (json.JSONDecodeError, ValueError):
                return {"result": content.text}
        return {}

    proxy_fn.__name__ = gateway_name
    proxy_fn.__doc__ = description
    mcp_server.add_tool(proxy_fn, name=gateway_name, description=description)


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
    # gateway starts accepting requests.
    if ready_events:
        await asyncio.gather(*(e.wait() for e in ready_events))

    return tasks
