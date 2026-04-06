# Design: Attio MCP Gateway Integration via stdio

**Date:** 2026-04-04  
**Status:** Approved  
**Author:** Jaron Sander

---

## Problem

The current Attio integration at `remote-gateway/mcp_connections.json` connects to Attio's hosted MCP server (`https://mcp.attio.com/mcp`) using OAuth tokens extracted from the macOS Keychain (`Claude Code-credentials`). This approach has two compounding failures:

1. **Setup fragility** — initial token acquisition requires manually extracting tokens from the Keychain after completing Claude Code's OAuth flow. This is a manual, error-prone step that must be repeated on every new deployment or token expiry.
2. **Auth instability** — the tokens belong to Claude Code's OAuth client (Anthropic's), not to Inform's. The refresh flow in `mcp_proxy.py` sends only `client_id` + `refresh_token`, no `client_secret`, because it's a public/PKCE client. Inform has no control over that OAuth app; if Attio rotates or revokes it, the integration breaks with no recourse.

## Solution

Replace the Attio connection with [`attio-mcp`](https://github.com/kesslerio/attio-mcp-server) (npm: `attio-mcp`), a community-maintained stdio MCP server that authenticates using a plain Attio workspace API key. API keys are long-lived, org-controlled, and require no refresh logic. The gateway's existing stdio proxy path handles this with zero changes to `mcp_proxy.py`.

## Architecture

```
Operator agent
    │
    ▼
Remote gateway (FastMCP, SSE)
    │
    ▼
mcp_proxy.py stdio path
    │  spawns subprocess at startup
    ▼
npx attio-mcp (Node.js subprocess)
    │  ATTIO_API_KEY env var
    ▼
Attio REST API
```

Tools are exposed to operators as `attio__<tool_name>` — same naming convention as the current integration.

## Changes Required

### 1. `nixpacks.toml`

Add a `[phases.setup]` block to include Node.js 20 in the Railway build:

```toml
[phases.setup]
nixPkgs = ["nodejs_20"]

[phases.install]
cmds = ["pip install -e ."]

[start]
cmd = "MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py"
```

Node.js is required for `npx attio-mcp`. Without it, the subprocess fails to spawn and the gateway starts with no Attio tools.

### 2. `remote-gateway/mcp_connections.json`

Replace the `attio` entry:

```json
"attio": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "attio-mcp"],
  "env": {
    "ATTIO_API_KEY": "${ATTIO_API_KEY}"
  }
}
```

Remove: `url`, `headers`, `oauth` keys.

### 3. `remote-gateway/.env.example`

Replace the Attio block:

```
# Attio CRM (proxied via gateway — operators need no local credentials)
# Get from: Attio workspace settings → API Keys → Create API key
# ATTIO_API_KEY=your_api_key_here
```

Remove: `ATTIO_ACCESS_TOKEN`, `ATTIO_REFRESH_TOKEN`, `ATTIO_CLIENT_ID`.

### 4. Railway environment variables

After deploying:
- **Add:** `ATTIO_API_KEY`
- **Remove:** `ATTIO_ACCESS_TOKEN`, `ATTIO_REFRESH_TOKEN`, `ATTIO_CLIENT_ID`

## What Doesn't Change

- `remote-gateway/core/mcp_proxy.py` — no modifications needed; stdio transport is fully implemented
- Apollo connection — untouched
- Tool naming convention (`attio__<tool_name>`) — same prefix, tool names will differ from the old hosted MCP set (clean break is acceptable)

## Trade-offs

| | Attio hosted MCP + OAuth app | attio-mcp stdio (this design) |
|---|---|---|
| Auth | OAuth access+refresh tokens | API key (never expires) |
| Maintenance | Official Attio | Community (60 stars, TypeScript, updated Mar 2026) |
| Tool set | Attio-maintained | 14 universal tools |
| Setup complexity | Auth code flow + env vars | Single env var |
| Gateway code changes | `mcp_proxy.py` + config | Config only |
| Node.js required | No | Yes (added via nixpacks) |

The community-maintenance risk is accepted: the package is actively developed, has a real npm release, and the auth simplicity eliminates the entire class of failure we're solving for.

## Startup Behavior

On first deploy after this change, `npx -y attio-mcp` will download the package at gateway startup (a few seconds). Subsequent deploys will re-download unless `npm install -g attio-mcp` is added to the nixpacks install phase. This is acceptable for the current deploy frequency.
