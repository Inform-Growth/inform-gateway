# SSE pass-through integration recipe

For remote MCP servers that expose Server-Sent Events transport (the older remote-MCP standard). The gateway maintains a persistent SSE session and re-exposes upstream tools.

## When to use

- The vendor hosts an MCP server at a URL ending in `/sse`.
- The connection is long-lived — server pushes events to the client (your gateway).
- Less common today; most modern remote MCPs use streamable-HTTP. See [streamable-http.md](streamable-http.md) first.

## Config shape

In `remote-gateway/mcp_connections.json`:

```json
{
  "connections": {
    "example_sse": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "auth": {
        "type": "header",
        "headers": {
          "Authorization": "Bearer ${EXAMPLE_SSE_TOKEN}"
        }
      }
    }
  }
}
```

The top-level key (`example_sse`) becomes the tool prefix — upstream tools appear as `example_sse__<tool_name>`.

## Auth strategies

The `auth.type` field controls how headers are resolved:

- **`none`** (or omit `auth`): no headers sent.
- **`header`**: pass arbitrary headers, with `${VAR}` substitution from `.env`. Most common — Bearer token via `Authorization`.
- **`oauth`**: gateway-managed OAuth refresh. Use when the vendor requires OAuth and provides client/refresh credentials. Config shape:
  ```json
  "auth": {
    "type": "oauth",
    "client_id": "${VENDOR_CLIENT_ID}",
    "client_secret": "${VENDOR_CLIENT_SECRET}",
    "refresh_token": "${VENDOR_REFRESH_TOKEN}",
    "token_url": "https://vendor.example.com/oauth/token"
  }
  ```
  The gateway will refresh the access token on 401 and retry up to 3 times.

## Reconnect behavior

SSE proxies maintain a persistent session. On disconnect, the gateway reconnects with a 30-second back-off. Tools registered on the first successful connection stay registered across reconnects — agents see no interruption.

## Verify

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

Boot log shows `[proxy] 'example_sse' connecting...` then `[proxy] 'example_sse' connected — registered N tools`. Failed auth shows up as `[proxy] 'example_sse' auth failed (401)`.

## Tool allow/deny

Same shape as stdio — see [stdio.md § Optional: tool allow/deny lists](stdio.md#optional-tool-allowdeny-lists).

## Troubleshooting

- **`unknown auth type 'X'`**: `auth.type` must be `header`, `oauth`, or `none`. Typo in the config.
- **Repeated 401s after token refresh**: the OAuth refresh token is stale or revoked. Regenerate at the vendor and update `.env`.
- **`tools/list` empty after connect**: the upstream's `list_tools` raised. Check the gateway boot log for the unwrapped exception message.
