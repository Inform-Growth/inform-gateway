# CLAUDE.md: Agent Gateway

This file provides guidance to Claude Code when working in the **inform-gateway** repository.

# System Overview

The Agent Gateway is a centralized MCP server that hosts promoted tools for business integrations (Attio, Apollo, Exa, GitHub, etc.) and provides a unified interface for AI agents. It operates under a **"Gateway First"** architecture where all agent interactions are governed, documented, and shadowed for proactive improvement.

## Core Commands

```bash
# Install (from repo root)
pip install -e .
pip install -e ".[dev]"   # includes pytest and ruff

# Lint & Test
ruff check .
pytest

# Run the Remote Gateway
# Local dev (stdio)
python remote-gateway/core/mcp_server.py

# Production — SSE + streamable-http on same port (preferred)
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py

# SSE only (legacy clients)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py

# Streamable-HTTP only (newer clients)
MCP_TRANSPORT=streamable-http python remote-gateway/core/mcp_server.py
```

## Primary Mandate: Gateway Operator

When acting as an agent in this environment, you MUST initialize your session by calling `get_operator_instructions` or using the `initialize-session` prompt. This activates your **Shadow Note-taking** and **Issue Logging** duties.

### Shadow Note-taking
- **Trigger**: After every significant task or discovery.
- **Action**: Call `write_note` to record the user's goal, the outcome, and whether the gateway did a "good job."
- **Persistence**: Notes are written to the dedicated "Write Notes" GitHub repository.

### Issue Logging
- **Trigger**: Auth failures, tool errors (4xx/5xx), or "noisy/raw" data.
- **Action**: Call `write_issue` to surface the problem to gateway administrators.

## Repository Structure

- **`remote-gateway/`** — The core infrastructure.
  - `core/` — FastMCP server (`mcp_server.py`), proxy logic, telemetry, and field registry.
  - `tools/` — Internal tools: Attio, Notes (GitHub-backed), Meta (health/stats/auth), Registry.
  - `prompts/` — `init.md` (Gateway Operator persona) and `qa_agent_instructions.md`.
  - `context/fields/` — YAML field schemas for field registry validation (apollo, attio-companies, attio-deals, attio-people, exa).
  - `official_tools/` — Promoted tool packages (`gateway-health-check`, `mcp-builder`).
  - `skills/` — Claude Code skill definitions used by gateway operators.
  - `vendor/` — Vendored JS dependencies (node_modules).
  - `tests/` — Pytest test suite.
  - `mcp_connections.json` — Upstream proxy definitions (exa, apollo, attio, github).
- **`data/`** — SQLite telemetry DB (gitignored in prod; use a mounted volume).
- **`debug_mcp.py`**, **`extract_mcp_tokens.py`** — Root-level dev utilities.

## Authentication

Operators authenticate via API key, created by an admin using the `create_user` tool. The key is passed on every MCP connection in one of two ways:

```json
// .mcp.json — Claude Code / API clients
"headers": { "Authorization": "Bearer sk-<key>" }

// URL query param — Claude Desktop / Web / clients that can't set headers
"url": "https://<host>:8000/mcp?api_key=sk-<key>"
```

The `_AuthMiddleware` ASGI layer resolves the key to a `user_id` on every request. All telemetry is tagged with this `user_id` automatically.

## Tool Inventory

### Built-in tools (registered at startup)
| Tool | Description |
|---|---|
| `health_check` | Verify server is running |
| `get_tool_stats` | Per-tool call counts, error rates, latency |
| `get_session_usage` | Tool call sequences and per-user breakdown |
| `create_user` | Admin — create an API key for a new operator |
| `get_operator_instructions` | Load Gateway Operator persona and shadow note rules |
| `list_prompts` | Discover available prompt templates |
| `get_prompt` | Render a specific prompt template |
| `write_note` / `read_note` / `list_notes` / `delete_note` | GitHub-backed markdown notes |
| `write_issue` / `list_issues` | Issue tracking in notes repo |
| `check_field_drift` / `discover_fields` / `get_field_definitions` / `lookup_field` / `list_field_integrations` | Field registry |

### Proxied integrations (from `mcp_connections.json`)
Tools appear as `<integration>__<tool_name>`.

| Integration | Transport | Notes |
|---|---|---|
| `exa` | HTTP | Rate-limited: 20 rpm, 2 concurrent |
| `apollo` | HTTP (OAuth) | Rate-limited: 10 rpm, 1 concurrent |
| `attio` | stdio | Tool deny list: `search_records`, `create_record` |
| `github` | stdio | Tool allow list: get/create files, list/search repos and issues |

## Available Prompts

| Prompt | Description |
|---|---|
| `operator_init` | Initialize Gateway Operator persona |
| `qa_agent_instructions` | Instructions for QA agents reviewing tool usage |
| `weekly_pipeline_review` | Analyze Attio deals + Apollo activity |
| `research_prospect` | Research a company and draft an outreach brief |
| `morning_briefing` | Daily RevOps summary (Attio + Apollo) |
| `add_prospect` | Enrich a contact in Apollo and create in Attio |
| `how_to_use_prompts` | Guide for invoking gateway workflows |

## Telemetry

Every tool call is recorded automatically (timing, success/failure, `user_id`, `request_id`, response size).

- **SQLite DB**: `TELEMETRY_DB_PATH` (default: `data/telemetry.db`). Mount `/data` as a persistent volume on Railway/Render.
- **Stats**: Call `get_tool_stats()` for per-tool metrics. `summary.high_error_rate` flags tools with ≥5% error rate over ≥10 calls.
- **Session analysis**: Call `get_session_usage()` for call sequences grouped by user.

## Coding Standards

- **Python ≥3.11**; ruff targets `py314`. Strict type hints and comprehensive docstrings required.
- **Docstrings are MCP descriptions.** Write them clearly for end-users.
- **No Hardcoded Credentials.** Use `os.environ` exclusively.
- **Read-Only by Default.** Mutating operations require explicit admin approval in code review.
- **Field Registry.** Wrap all tool responses with `validated("<integration>", result)` to ensure field consistency and drift detection. YAML schemas live in `context/fields/`.
