# CLAUDE.md: Agent Gateway

This file is for Claude Code working in this repository as a developer (extending the gateway, fixing bugs, running tests). For agent-facing wayfinding (operators calling the gateway, extenders adding integrations) see [AGENTS.md](AGENTS.md).

# System Overview

A centralized MCP server template that hosts curated tools and proxies upstream MCP servers behind one authenticated endpoint. Operators connect once with an API key; the gateway resolves auth, enforces per-user and global permissions, records telemetry, and surfaces shadow notes + issue logs to a GitHub repo. Operates under a **"Gateway First"** architecture where all agent interactions are governed, documented, and shadowed for proactive improvement.

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
  - `core/` — FastMCP server (`mcp_server.py`), proxy (`mcp_proxy.py`), admin API (`admin_api.py`), telemetry, field registry, and the system-skill seeder (`system_skills.py`).
  - `tools/` — Built-in Python tools: Notes (GitHub-backed), Meta (health/stats/auth), Registry (field-registry queries), and `_core/` (onboarding, profile, skills, tasks).
  - `docs/` — Author-facing recipes: per-transport integration guides under `integrations/`, plus `custom-tools.md` and `custom-prompts.md`.
  - `prompts/` — `init.md` (Gateway Operator persona) and `qa_agent_instructions.md`.
  - `context/fields/` — YAML field schemas for field registry validation. None ship by default; add per integration as needed.
  - `tests/` — Pytest test suite.
  - `mcp_connections.json` — Active proxy definitions. Empty by default.
  - `mcp_connections.example.json` — One reference entry per transport (stdio, sse, http).
  - `system_skills.json` — Seed file for is_system=1 skills; reconciled into SQLite on every gateway boot.
- **`data/`** — SQLite telemetry DB (gitignored in prod; mount as a persistent volume).
- **`AGENTS.md`** — Agent-facing wayfinding (operators + extenders).
- **`copier.yml`** — Template scaffolding config for `copier copy`.

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
| `list_prompts` / `get_prompt` | Discover and render prompt templates |
| `write_note` / `read_note` / `list_notes` / `delete_note` | GitHub-backed markdown notes |
| `write_issue` / `list_issues` | Issue tracking in notes repo |
| `skill_list` / `skill_create` / `skill_update` / `skill_delete` / `run_skill` | SQLite-backed reusable prompt templates |
| `setup_start` / `setup_save_profile` / `setup_complete` | Org onboarding flow |
| `profile_get` / `profile_update` | Org profile CRUD |
| `declare_intent` / `complete_task` / `get_tasks` | Task gate — agents declare intent before tool use |
| `check_field_drift` / `discover_fields` / `get_field_definitions` / `lookup_field` / `list_field_integrations` | Field registry queries |

### Proxied integrations (from `mcp_connections.json`)
Tools appear as `<integration>__<tool_name>`.

No integrations configured by default — add entries to `mcp_connections.json`.

## Available Prompts

| Prompt | Description |
|---|---|
| `operator_init` | Initialize Gateway Operator persona |
| `qa_agent_instructions` | Instructions for QA agents reviewing tool usage |
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
- **Field Registry.** Wrap structured tool responses with `validated("<integration>", result)` if a YAML schema exists in `context/fields/`. None ship by default; add per integration.

## Admin Guardrails

- All proxied integrations (defined in `mcp_connections.json`) are subject to per-user tool permissions via the `tool_permissions` table.
- Tool allow/deny lists are enforced at tool invocation time and reflected in `tools/list` responses.
- Admin approval is required before adding new built-in tools; follow code review guidelines in Coding Standards.

### Global Tool Toggle

Disable a proxied or built-in tool for **all users** at runtime — no restart required:

```
PUT /admin/api/permissions/*/<tool_name>
Body: {"enabled": false}
```

The sentinel `user_id = "*"` in `tool_permissions` applies to every user. Globally disabled tools are hidden from `tools/list` and blocked at call time. Re-enable with `{"enabled": true}`.

View all global toggles:
```
GET /admin/api/permissions/*
```

Use this when replacing a proxied MCP tool with a Python tool — disable the old route globally, register the new Python tool via `@mcp.tool()`, and the transition is live immediately.
