---
date: 2026-04-01
slug: mcp-config-debugging
status: active
---

# Session: MCP Config Debugging

## Goal
Fix MCP server connection errors surfaced by `/doctor`.

## Issues Found

### 1. Schema error: `"type": "http"` in `.mcp.json`
- `remote-gateway` and `exa` entries had `"type": "http"` which is not a valid MCP server config type
- Claude Code was sending POST requests (streamable HTTP transport) to `/sse`, but the gateway server only handles GET on that endpoint (SSE transport)
- Server returned `405 Method Not Allowed`, causing `BrokenResourceError` in the receive loop

**Fix**: Removed `"type": "http"` from both entries in `.mcp.json`. URL-based entries default to SSE transport.

### 2. Missing `EXA_API_KEY`
- Exa MCP server warns about missing env var
- Action: add `EXA_API_KEY=...` to `.env`

## Open
- Restart Claude Code to pick up `.mcp.json` changes
- Verify remote-gateway connects cleanly after restart
