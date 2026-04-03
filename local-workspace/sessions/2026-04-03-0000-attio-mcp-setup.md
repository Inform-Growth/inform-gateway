---
date: 2026-04-03
slug: attio-mcp-setup
status: active
---

# Attio MCP Setup

## Discoveries
- Attio provides a hosted MCP server at `https://mcp.attio.com/mcp`
- Added to `.mcp.json` with `Authorization: Bearer ${ATTIO_API_KEY}` header pattern

## Decisions
- Used `type: http` with Bearer token auth, matching Exa pattern in existing config
- `ATTIO_API_KEY` to be added to `.env`

## Open Questions
- What API key scopes are required for Attio MCP?
- Which Attio workflows are candidates for codification?
