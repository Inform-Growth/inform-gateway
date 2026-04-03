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

---

# Session: workspace-test + ai-governance-research

**Date:** 2026-04-01
**Integration(s):** exa
**Goal:** Confirm the local workspace (hooks, rules, skills) is functioning, then research AI governance — how organizations approach internal AI policies and how agencies manage AI use in client environments.

## Discoveries

### Workspace Status

- Exa MCP confirmed connected and functional
- Session note rule triggered correctly (PostToolUse hook working)
- Hooks, rules, and skills infrastructure verified operational

### Internal AI Governance — Landscape

- >50% of workers using GenAI at work without formal employer approval (Salesforce 2025 survey)
- Major enterprise AI use policy publications in mid-2025 through early 2026: Salesforce, GitHub, IBM, Ivanti
- Core policy components across these orgs: approved tool lists, data classification rules, output review requirements, mandatory training obligations

### Shadow AI — Compliance Risk

- A B2B contractor was fined €50,000 (Germany/France) for using personal LLM accounts in client work
- **United States v. Heppner** (Feb 13, 2026, SDNY, Judge Rakoff): court ruled AI conversations are NOT legally privileged; executive had used a free AI tool to assess legal exposure — that conversation was discoverable
- Salesforce survey finding: employees pasting customer data into personal LLM accounts without awareness of the data exposure risk
- MeshAI (Mar 2026): "Shadow AI agents" identified as a distinct emerging risk category — unauthorized agents operating inside org systems, not just unauthorized chat tools

### Agency-Side AI Governance

- LinkedIn webinar (Emily Hatton, Mar 2026): "Your team is already using AI in client work. You just don't have control over it." — shadow AI in agencies is pervasive
- BattleBridge (Mar 2026): agencies restructuring delivery models around agentic AI — one person managing 5–8 clients with AI agents
- "Agentic-first agency" model: 60–80% margins vs. 15–25% traditional; 75% claimed workload reduction per client
- No widely adopted standard yet for disclosing AI use to clients; contractual AI clauses are nascent and inconsistent

### Contractual / Regulatory Pressure

- GSA proposed AI procurement clause (March 2026): federal contractors must disclose AI use in deliverables and how data is handled; public comment closed March 20, 2026
- EU AI Act enforcement deadline: August 2, 2026 — organizations must audit their "AI agent estate" before this date

### Agentic AI / MCP-Specific Governance

- TrueFoundry (Mar 2026): "Zero Trust for Agentic AI" — MCP security framework for enterprise; treats each agent action as an untrusted call requiring scoped authorization
- WorkOS Pipes MCP (Mar 2026): session-scoped authorization for AI agents (vs. long-lived OAuth tokens) — directly addresses the problem of AI agents holding persistent broad access to client systems (Snowflake, Salesforce, Google Drive)
- UC Today (Jan 2026): Claude MCP apps require identity, permissions, and audit trails before enterprise adoption is viable
- MCP Manager (Feb 2026): complete guide to MCP permission scoping published

## Decisions

- This research is directionally relevant to inform-gateway's governance design — the MCP-specific findings (session-scoped auth, audit trails, zero-trust agent access) should be revisited when designing gateway permission controls

## Open Questions

- How are non-government agencies contractually handling AI disclosure to clients today? No clear industry standard found — this is a gap worth monitoring
- What do client-side procurement teams actually require vs. what agencies proactively volunteer? The Heppner ruling may accelerate client demands for disclosure
- WorkOS Pipes session-scoped auth model — worth evaluating as a pattern for how the remote gateway issues access to operator agents
