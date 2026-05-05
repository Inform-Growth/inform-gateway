# stdio integration recipe

For MCP servers distributed as a local CLI (Node, Python, or any executable that speaks MCP over stdin/stdout). The gateway spawns them as subprocesses and proxies their tools.

## When to use

- The vendor ships an MCP server as `npx` / `pip install` / a shipped binary.
- Examples: `@hubspot/mcp-server`, `@modelcontextprotocol/server-github`, `attio-mcp`.

## Worked example: HubSpot

### 1. Add an entry to `remote-gateway/mcp_connections.json`

```json
{
  "connections": {
    "hubspot": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@hubspot/mcp-server"],
      "env": {
        "PRIVATE_APP_ACCESS_TOKEN": "${HUBSPOT_PRIVATE_APP_ACCESS_TOKEN}"
      }
    }
  }
}
```

The top-level key (`hubspot`) becomes the tool prefix — every upstream tool is exposed as `hubspot__<tool_name>` on the gateway.

`env` values support `${VAR_NAME}` substitution from the gateway's environment. Don't put secrets in `mcp_connections.json` directly — declare them in `.env` and reference them.

### 2. Set the env var

In `remote-gateway/.env`:

```
HUBSPOT_PRIVATE_APP_ACCESS_TOKEN=pat-na1-...
```

For HubSpot specifically: create the token at HubSpot → Settings → Integrations → Private Apps → Create a private app. Recommended scopes: `crm.objects.contacts.read/write`, `crm.objects.companies.read/write`, `crm.objects.deals.read/write`, `crm.schemas.{contacts,companies,deals}.read`, `tickets.read/write`.

### 3. Restart the gateway

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

The boot log will show `[proxy] 'hubspot' connected — registered N tools`.

### 4. Verify

```bash
curl -s -H "Authorization: Bearer sk-your-key" http://localhost:8000/sse | head -5
```

Or, from any MCP client, call `tools/list` and grep for `hubspot__`.

## Optional: tool allow/deny lists

To register only a subset of upstream tools:

```json
"hubspot": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@hubspot/mcp-server"],
  "env": { "PRIVATE_APP_ACCESS_TOKEN": "${HUBSPOT_PRIVATE_APP_ACCESS_TOKEN}" },
  "tools": {
    "allow": ["search_contacts", "create_contact", "list_companies"]
  }
}
```

Or to register everything *except* a few:

```json
"tools": { "deny": ["dangerous_bulk_delete"] }
```

`allow` and `deny` are mutually exclusive — pick one. Both lists use the upstream tool's bare name (without the `hubspot__` prefix).

## Troubleshooting

- **`[proxy] WARNING: 'hubspot' env var X is not set`**: the `${VAR_NAME}` reference in `env` didn't resolve — check `.env` is loaded and the var name matches.
- **Subprocess fails to spawn**: most often Node isn't on PATH. The gateway's Dockerfile installs Node 20; if running locally without Node, install it first or pick a Python-based stdio server instead.
- **Tools missing from `tools/list`**: the upstream's `list_tools` failed. Check the boot log for the actual error from the subprocess (the gateway prints it via `mcp_proxy._unwrap_exception_group`).
