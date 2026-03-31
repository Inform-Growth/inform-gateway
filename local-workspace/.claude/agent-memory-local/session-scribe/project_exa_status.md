---
name: Exa MCP connection status
description: Exa MCP was configured 2026-03-31 but never connected — open question is whether it works on next restart
type: project
---

Exa MCP server is configured in `.mcp.json` with correct `${EXA_API_KEY}` syntax and key is present in `.env`. Server was not reachable mid-session because MCP servers only load at startup.

**Why:** Session ended before a restart could confirm connectivity. Key may also need rotation after brief exposure in conversation output.

**How to apply:** At the start of the next session, surface this: "Last time Exa was configured but not yet verified — check if Exa tools are showing up now that the session restarted."
