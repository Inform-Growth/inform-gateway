# Design: Pluggable MCP Connection Harness

**Date:** 2026-04-05
**Status:** Approved
**Author:** Jaron Sander

---

## Problem

The remote gateway's HTTP proxy hardcodes `Authorization: Bearer` as the only auth pattern. Any integration that uses a different auth scheme (e.g., Exa's `x-api-key` header) silently fails — the API key is never sent. There is also no way to filter which tools an integration exposes, and all internal tool code lives unsorted in `mcp_server.py` alongside server setup code.

## Solution

Introduce an explicit `auth` strategy block per HTTP connection in `mcp_connections.json`, refactor `mcp_proxy.py` to dispatch on auth type, add per-integration tool filtering, reorganize internal tools into a subfolder, and add Exa and GitHub as new connections.

This is Phase 1 of a two-phase design. Phase 2 (separate spec) will wire internal tools as facades over proxied tools and add pre/post processing hooks on tool calls.

## Architecture

```
[Operator agent]
      |
      v
[Gateway — FastMCP SSE]
  ├── Proxied tools:  exa__*, apollo__*, attio__*, github__*
  └── Internal tools: list_notes, read_note, get_tool_stats, ...
      |
      v
[mcp_proxy.py]
  ├── Auth dispatcher  (header | oauth | none)
  ├── Tool filter      (allow / deny list per integration)
  └── Transport layer  (stdio | http | sse)
      |
      v
[Upstream MCPs]
  ├── exa.ai/mcp          (HTTP, x-api-key header)
  ├── mcp.apollo.io/mcp   (HTTP, OAuth Bearer + refresh)
  ├── npx attio-mcp       (stdio, ATTIO_API_KEY env)
  └── npx @mcp/server-github (stdio, GITHUB_TOKEN env)
```

---

## Section 1: Connection Config Schema

`mcp_connections.json` gains an `auth` block on each HTTP connection. Stdio connections are unaffected — they use `env` and the subprocess handles auth.

### Auth types

| Type | When to use | Config keys |
|---|---|---|
| `header` | API key or custom header (e.g., Exa `x-api-key`) | `headers: { ... }` |
| `oauth` | Bearer token with refresh (e.g., Apollo) | `access_token`, `token_url`, `client_id`, `refresh_token` |
| `none` | Open MCP, no auth required | _(omit auth block or set type: none)_ |

### Tool filtering

Any connection (stdio or HTTP) can include an optional `tools` block:

```json
"tools": { "allow": ["tool_a", "tool_b"] }   // whitelist — only these are registered
"tools": { "deny":  ["delete_x", "drop_y"] }  // blacklist — all except these
```

`allow` and `deny` are mutually exclusive. Omitting `tools` registers all tools from the upstream (current default behavior).

### Full config after migration

```json
{
  "_comment": "...",
  "connections": {
    "exa": {
      "transport": "http",
      "url": "https://mcp.exa.ai/mcp",
      "auth": {
        "type": "header",
        "headers": { "x-api-key": "${EXA_API_KEY}" }
      }
    },
    "apollo": {
      "transport": "http",
      "url": "https://mcp.apollo.io/mcp",
      "auth": {
        "type": "oauth",
        "access_token": "${APOLLO_ACCESS_TOKEN}",
        "token_url": "https://mcp.apollo.io/api/v1/oauth/token",
        "client_id": "${APOLLO_CLIENT_ID}",
        "refresh_token": "${APOLLO_REFRESH_TOKEN}"
      }
    },
    "attio": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "attio-mcp"],
      "env": { "ATTIO_API_KEY": "${ATTIO_API_KEY}" }
    },
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" },
      "tools": {
        "allow": [
          "get_file_contents",
          "create_or_update_file",
          "list_files_in_repo",
          "search_repositories",
          "get_issue",
          "list_issues"
        ]
      }
    }
  }
}
```

---

## Section 2: `mcp_proxy.py` Refactor

### Auth dispatcher

New function `resolve_auth_headers(config)` replaces the hardcoded Bearer logic:

```python
async def resolve_auth_headers(config: dict) -> dict[str, str]:
    """Resolve the auth headers for an HTTP connection based on its auth strategy.

    Dispatches on config["auth"]["type"]:
    - "header": resolve and return all configured headers
    - "oauth":  get/refresh Bearer token and return Authorization header
    - "none" or missing: return empty dict
    """
    auth = config.get("auth", {})
    auth_type = auth.get("type", "none")

    if auth_type == "header":
        return resolve_headers(auth.get("headers", {}))

    if auth_type == "oauth":
        token = await _get_oauth_token(auth)
        return {"Authorization": f"Bearer {token}"}

    return {}
```

`_get_current_token` is renamed `_get_oauth_token` and updated to read from the `auth` block instead of the top-level config. OAuth refresh logic is otherwise unchanged.

`_run_http_proxy` calls `resolve_auth_headers(config)` instead of constructing Bearer headers directly. The 401 retry loop continues to work — it calls `resolve_auth_headers` again after refresh, which re-reads the updated env var.

### Tool filter enforcement

`_register_proxy_tool` receives the connection's `tools` config and skips registration for filtered tools:

```python
def _should_register_tool(tool_name: str, tools_config: dict | None) -> bool:
    """Return True if this tool should be registered given the filter config."""
    if not tools_config:
        return True
    if "allow" in tools_config:
        return tool_name in tools_config["allow"]
    if "deny" in tools_config:
        return tool_name not in tools_config["deny"]
    return True
```

---

## Section 3: Internal Tools Subfolder

Internal tool functions move from `mcp_server.py` into `remote-gateway/tools/`:

| File | Tools |
|---|---|
| `tools/notes.py` | `list_notes`, `read_note`, `write_note`, `delete_note` |
| `tools/registry.py` | `lookup_field`, `get_field_definitions`, `check_field_drift`, `list_field_integrations`, `discover_fields` |
| `tools/meta.py` | `get_tool_stats`, `health_check` |

`mcp_server.py` imports from these modules and registers them. No behavior changes — this is purely organizational. The subfolder structure prepares for Phase 2, where `tools/notes.py` will call proxied `github__*` tools instead of making raw API calls.

---

## Section 4: New Integrations

### Exa

HTTP connection with header auth. `EXA_API_KEY` added to `.env.example`. All tools exposed (no filter).

### GitHub

Stdio subprocess using `@modelcontextprotocol/server-github` (npm). `GITHUB_TOKEN` env var — same token the existing notes tools use, so no new credential needed. Allow list restricts to the 6 tools the notes facade will need in Phase 2, keeping the exposed surface area small.

**`GITHUB_TOKEN` and `GITHUB_REPO` env vars are already set on the gateway** (used by existing notes tools). No new Railway env var provisioning needed for GitHub.

`EXA_API_KEY` is new — must be added to Railway.

---

## What Doesn't Change

- `attio` connection — already on new stdio pattern, no migration needed
- Apollo OAuth refresh behavior — same logic, just reorganized
- Tool naming convention (`<integration>__<tool_name>`) — unchanged
- Existing notes tools behavior — same inputs/outputs, just moved to `tools/notes.py`

## Out of Scope (Phase 2)

- Notes tools calling proxied `github__*` tools internally
- Pre/post processing hooks on tool calls
- Workflow tools (multi-integration chains)
