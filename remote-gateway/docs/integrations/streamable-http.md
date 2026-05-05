# Streamable-HTTP integration recipe

For modern remote MCP servers that use the streamable-HTTP transport (the MCP default for HTTP-based servers). Each request opens an SSE-streamed response that closes after the response cycle, so the gateway connects per-call rather than maintaining a persistent session.

## When to use

- The vendor hosts an MCP server at a URL ending in `/mcp` (or similar non-SSE path).
- This is the default for most newer hosted MCPs.

## Config shape

In `remote-gateway/mcp_connections.json`:

```json
{
  "connections": {
    "example_http": {
      "transport": "http",
      "url": "https://mcp.example.com/mcp",
      "auth": {
        "type": "header",
        "headers": {
          "Authorization": "Bearer ${EXAMPLE_HTTP_TOKEN}"
        }
      }
    }
  }
}
```

The top-level key (`example_http`) becomes the tool prefix — upstream tools appear as `example_http__<tool_name>`.

Note: `transport: "http"` is the streamable-HTTP transport. Don't confuse with `"sse"` (which is the older long-lived SSE transport — see [sse-passthrough.md](sse-passthrough.md)).

## How it differs from SSE

The gateway connects **once at startup** to enumerate tools, then connects **fresh on every tool call** at runtime. The session is not reused — each call is a self-contained HTTP request that returns a streamed response.

Practical implications:
- No reconnect loop. If the vendor is down at startup, the gateway logs the failure and skips that integration; it doesn't retry until restart.
- Higher per-call latency than persistent connections, but simpler failure modes — a single failed call doesn't tear down anything.
- Auth headers are resolved fresh on every call, so OAuth token refresh works transparently.

## Auth

Same dispatch as SSE:
- **`header`**: arbitrary headers with `${VAR}` substitution. Most vendors.
- **`oauth`**: gateway-managed OAuth — see [sse-passthrough.md § Auth strategies](sse-passthrough.md#auth-strategies) for the config shape.
- **`none`**: no auth.

## Verify

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

Boot log shows `[proxy] 'example_http' connected — registered N tools` on success. Connection failure unwraps the inner exception (e.g. DNS failure, 401, malformed URL) — no opaque `BaseExceptionGroup` wrappers.

## Tool allow/deny

Same shape as stdio — see [stdio.md § Optional: tool allow/deny lists](stdio.md#optional-tool-allowdeny-lists).

## Troubleshooting

- **Tools registered at boot but failing at runtime**: most often a credential rotation. The startup connection used a fresh token; runtime calls hit a stale cache. Restart the gateway.
- **`[proxy] '<name>' failed to connect: <inner exception>`**: the unwrapped error is the upstream's actual response — typically 401 (auth), 404 (URL wrong), or DNS resolution failure. Fix the corresponding piece of config.
- **Tools missing from `tools/list` after a successful connect**: the upstream returned an empty `list_tools` response. Some vendors gate tools behind scopes — verify your token has the access you expect.
