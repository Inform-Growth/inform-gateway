---
date: 2026-04-01
slug: exa-gateway-mcp-install
integrations: [exa, remote-gateway]
goal: Install Exa and the remote-gateway as local MCP connections so both are live and usable in the workspace.
---

# Session: exa-gateway-mcp-install

## Goal
Get Exa and remote-gateway working as project-scoped MCP servers in local-workspace.

## Discoveries

- Both servers are already correctly configured in `local-workspace/.mcp.json`
- `EXA_API_KEY` is set in `.env`
- `npx` / Node v22 available
- Remote-gateway SSE endpoint at `http://localhost:8000/sse` is live and responding
- `claude mcp list` only shows user-scoped servers — project-scoped ones from `.mcp.json` won't appear there even when working
- Root cause identified: project-scoped MCP trust prompt likely missed or denied on first launch

## Decisions

- Fix: run `claude mcp reset-project-choices`, restart Claude Code, approve the trust prompt for both servers

## Open Questions

- Do both servers appear as available tools after trust prompt approval?
- Is Exa's key still valid, or has it been rotated since last session?
- What tools does Exa expose? (document in `context/integrations/exa/schema.md` once connected)
