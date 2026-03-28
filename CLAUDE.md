# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

# Agent Gateway — Monorepo

Two isolated zones:

- **`local-workspace/`** — Employee R&D sandbox. Employees sparse-checkout only this folder. Local AI agents connect to raw data sources, explore workflows, and codify them as skills.
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

# Run the remote gateway (stdio — local dev)
python remote-gateway/core/mcp_server.py

# Run as SSE server (production — employees connect to this)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py
```

## Architecture

### Lifecycle: Local → Gateway

1. **Explore** — employee asks a question; agent uses local MCP connections (Stripe, HubSpot, Snowflake, etc.) to fetch data and answer.
2. **Codify** — if the workflow is worth repeating, the agent creates `.claude/skills/<name>/SKILL.md` (instructions, becomes a `/slash-command`) and `.claude/skills/<name>/scripts/<name>.py` (the Python logic).
3. **Auto-push** — Stop hook commits and pushes to `employee/<username>` branch automatically.
4. **Auto-PR** — `auto_pr.yml` opens a pull request to main.
5. **QA review** — `qa_agent_review.yml` runs a Claude agent (via OpenRouter) that reviews for safety, security, type hints, and docstring quality. Posts result as PR comment.
6. **Human merge** — admin reads QA comment, merges if approved. Only mandatory human gate.
7. **Auto-promote** — `auto_promote.yml` injects the script into `remote-gateway/core/mcp_server.py` with `@mcp.tool()`, copies field definitions, commits back to main.
8. **Admin redeploys** — provisions any new env vars on the gateway server, restarts.
9. **Fleet sync** — employees `git pull`; new skill is available as slash-command, new tool available on gateway.

### Skill/Script Pairing Rule

Every Python script in `.claude/skills/<name>/scripts/` must have a `SKILL.md` in the same skill directory. Enforced by the QA agent.

### MCP Server Transports

`remote-gateway/core/mcp_server.py` uses FastMCP and supports:
- **stdio** (default) — local dev and `mcp run`
- **SSE** — production; set `MCP_TRANSPORT=sse`

### Zone-Specific Instructions

- `local-workspace/.claude/CLAUDE.md` — skill structure, MCP config, background automation
- `local-workspace/.claude/AGENTS.md` — agent identity, incubation loop, git protocol, guardrails
- `remote-gateway/CLAUDE.md` — migration workflow, gateway management, field registry, admin guardrails

## Coding Standards

- Python 3.14+. Type hints and docstrings required on every function.
- Docstrings are MCP tool descriptions — write them for non-technical users.
- All credentials via `os.environ` — never hardcoded.
- Read-only by default. Mutating operations require explicit admin approval.
- `ruff` for linting, line length 100.
