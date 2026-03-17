# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# RevOps Agent Gateway — Monorepo

Agentic GitOps monorepo with two isolated zones:

- **`local-workspace/`** — Employee R&D sandbox. Employees sparse-checkout only this folder. Local AI agents create Python tools and Markdown skills here.
- **`remote-gateway/`** — Centralized MCP gateway. Admin-managed. Hosts promoted, QA-approved tools as official MCP endpoints. Never pulled by employees.

## Commands

```bash
# Install (from repo root)
pip install -e .
pip install -e ".[dev]"   # includes pytest and ruff

# Lint
ruff check .

# Test
pytest

# Run the remote gateway (stdio transport, default)
python remote-gateway/core/mcp_server.py

# Run as SSE server (for remote deployment)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py

# Run via mcp CLI
mcp run remote-gateway/core/mcp_server.py
```

## Coding Standards

- Python 3.14+. All functions must have type hints and comprehensive docstrings.
- Docstrings serve double duty: they become MCP tool descriptions when migrated to the gateway.
- All credentials via `os.environ` — never hardcoded.
- All data-fetching tools default to **read-only** unless explicit write-permission is granted by an admin.
- `ruff` for linting, line length 100.

## Architecture

### Lifecycle: Local → Gateway

1. **Local agent fetches data** using raw MCP connections (Stripe, Snowflake, CRM, etc.) configured in `local-workspace/.mcp.json`.
2. **Incubation Loop** — if the answer required multi-step logic, the agent codifies it: writes a Python tool to `local-workspace/tools/` and a paired Markdown skill to `local-workspace/skills/`.
3. **Auto-push** — agent commits the tool+skill pair to a `feature/<username>-<tool-name>` branch and pushes.
4. **CI QA review** — `.github/workflows/qa_agent_review.yml` triggers on PRs touching `local-workspace/tools/**` or `local-workspace/skills/**`. A GPT-4o agent (using `remote-gateway/prompts/qa_agent_instructions.md`) reviews for safety (no mutations), security (no hardcoded secrets), type hint coverage, and docstring quality, then posts a structured comment.
5. **Admin migration** — approved tools are copy-pasted into `remote-gateway/core/mcp_server.py` and decorated with `@mcp.tool()`. The existing docstring becomes the MCP tool description automatically.
6. **Fleet update** — merged skills propagate via `git pull`, teaching all local agents to use the new centralized tool.

### Tool/Skill Pairing Rule

Every Python tool in `local-workspace/tools/` must have a corresponding Markdown skill in `local-workspace/skills/`. Skills explain *when* and *why* to invoke the tool; tools are the executable code. This is enforced by the QA agent.

### MCP Server Transports

`remote-gateway/core/mcp_server.py` uses FastMCP and supports two transports:
- **stdio** (default) — local dev and `mcp run`
- **SSE** — remote deployment via `MCP_TRANSPORT=sse`; local agents connect via `<GATEWAY_URL>/sse` in `local-workspace/.mcp.json`

### Session Notes

Local agents maintain per-session notes in `local-workspace/sessions/` using the naming convention `YYYY-MM-DD-<short-topic>.md`. See `local-workspace/CLAUDE.md` for the required structure.

### Zone-Specific Instructions

- `local-workspace/CLAUDE.md` — tool file standards, skill file standards, MCP config details
- `local-workspace/AGENTS.md` — agent identity, tool resolution order, incubation loop, auto-push git protocol, guardrails
- `remote-gateway/CLAUDE.md` — migration workflow, server configuration, admin guardrails
