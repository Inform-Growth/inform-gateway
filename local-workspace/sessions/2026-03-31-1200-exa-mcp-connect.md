# Session: exa-mcp-connect

**Date:** 2026-03-31
**Integration(s):** Exa
**Goal:** Connect the Exa MCP server so web search tools are available in the workspace.

## Discoveries

- Exa MCP is correctly configured in `.mcp.json` using `${EXA_API_KEY}` syntax — no credential exposure in config.
- `EXA_API_KEY` is present in `.env`, so the server has what it needs to authenticate.
- MCP servers are loaded once at session start. Adding or modifying `.mcp.json` mid-session does not activate new servers — a full session restart is required before Exa tools appear.
- `exa-mcp-server` v3.2.0 exists on npm and the `npx`-runner pattern should work on next session start.
- **Security note:** The `EXA_API_KEY` value was briefly visible in conversation output this session. User should consider rotating the key as a precaution.

## Decisions

- No skills created this session — Exa tools were not yet reachable, so there was nothing to codify. First real skill work deferred to next session once connectivity is confirmed.

## API Quirks

None confirmed yet — server never connected during this session. First live quirks expected next session.

## Open Questions

- Will Exa MCP connect successfully on the next session restart? This is the primary thing to verify at the top of the next session.
- If the key was rotated: is the new value in `.env` before restarting?
- Once connected, what is the tool surface? (`list_tools` or equivalent to document available Exa endpoints.)
- Should `context/integrations/exa/` schema.md be seeded with a stub now, or wait until first live tool responses return real field shapes?
