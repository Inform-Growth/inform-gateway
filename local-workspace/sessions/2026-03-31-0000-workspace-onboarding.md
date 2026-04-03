# Session: workspace-onboarding

**Date:** 2026-03-31
**Integration(s):** Exa
**Goal:** First-time workspace onboarding for Jaron (owner/founder) — establish operator branch and configure initial MCP integrations.

## Discoveries

- Exa MCP server available via `npx exa-mcp-server`. Configured in `.mcp.json` with `EXA_API_KEY` env var using `${EXA_API_KEY}` syntax. Entry added to `mcp-registry.md`.
- `.env.example` updated to catalog `EXA_API_KEY` as a required variable for Exa activation.
- `operator/jaron` branch created as Jaron's personal operator branch — this is where auto-save commits will land and PRs will originate.

## Decisions

- Exa chosen as the first local MCP integration. Rationale: web search capability is broadly useful for research-heavy workflows before more domain-specific integrations (Stripe, HubSpot, etc.) are added.
- Used `npx exa-mcp-server` (package-runner pattern) rather than a global install, consistent with how other MCP servers are configured in this workspace.

## API Quirks

None yet — Exa not yet activated (API key pending).

## Open Questions

- What is Jaron's primary use case for Exa? Web research for specific domains, competitive intel, general lookup? This will shape whether a skill gets built around it.
- Has Jaron received / added the EXA_API_KEY to `.env`? Exa MCP server will not connect until this is done.
- Are there other integrations to onboard in early sessions (Stripe, HubSpot, Snowflake, Linear, etc.)? Worth prioritizing based on what workflows Jaron wants to automate first.
- Should a `context/integrations/exa/` directory be created proactively (README + schema stub) or wait until first live tool calls return data to document?
