# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# System Overview

The Agent Gateway is a centralized MCP server that hosts promoted tools for business integrations (Attio, Apollo, Exa, GitHub, etc.) and provides a unified interface for AI agents. It operates under a **"Gateway First"** architecture where all agent interactions are governed, documented, and shadowed for proactive improvement.

This branch (`template/clean-gateway`) is the **Copier template** consumed via `copier copy` / `copier update` (see `copier.yml`). When editing files that downstream consumers will render, remember the non-standard Jinja delimiters: `[[ var ]]` for variables and `[% block %]` for blocks (chosen to avoid colliding with GitHub Actions `${{ }}`).

## Core Commands

```bash
# Install (from repo root)
pip install -e .
pip install -e ".[dev]"   # includes pytest and ruff

# Lint & Test
ruff check .
pytest                                 # full suite
pytest remote-gateway/tests/test_init_gate.py        # single file
pytest -k "test_declare_intent" -xvs                 # single test, fail fast

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

## Admin Dashboard

The admin dashboard is a React + Vite + TypeScript + Tailwind 4 + shadcn (base-ui) app at
`remote-gateway/admin-ui/`. It is built into `dist/` at Docker build time and served by
Starlette from `/admin/` (same port as the MCP gateway).

### Local development

```bash
./dev.sh
# Python gateway on :8000, Vite dev server on :5173 (HMR)
# Open http://localhost:5173/admin
```

The Vite dev server proxies `/admin/api/*` to the Python gateway and injects
`VITE_ADMIN_TOKEN` (from `remote-gateway/admin-ui/.env.local`) automatically.

### Building once locally

```bash
npm run build:ui
python remote-gateway/core/mcp_server.py
# Open http://localhost:8000/admin?token=<ADMIN_TOKEN>
```

### Legacy HTML dashboard

The pre-React HTML dashboard remains at `/admin/legacy?token=<ADMIN_TOKEN>` through Phase 8
of the migration as a safety net.

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
  - `core/` — FastMCP server (`mcp_server.py`), proxy logic (`mcp_proxy.py`), telemetry (`telemetry.py`), field registry, admin API and dashboard HTML.
  - `tools/` — Built-in tool modules registered by `mcp_server.py`:
    - `meta.py` — health, stats, auth, operator instructions.
    - `notes.py` — GitHub-backed notes & issues.
    - `registry.py` — field registry tools.
    - `_core/` — onboarding (`setup_*`), profile manager (`profile_get/update`), task manager (`declare_intent`/`complete_task`/`get_tasks` — the **init gate**), skill manager (`skill_*`, `run_skill`).
  - `prompts/` — `init.md` (Gateway Operator persona) and `qa_agent_instructions.md`.
  - `context/fields/` — YAML field schemas (`_template.yaml` ships with the template; consumers add `apollo.yaml`, `attio-*.yaml`, etc.).
  - `skills/` — Claude Code skill definitions bundled with the template (`gateway-health-check`, `mcp-builder`).
  - `tests/` — Pytest test suite.
  - `mcp_connections.json` — Upstream proxy definitions; **empty by default in the template** (`{"connections": {}}`). Consumers add integrations here.
- **`.github/workflows/`** — `auto_pr.yml`, `auto_promote.yml`, `qa_agent_review.yml` drive the tool promotion pipeline.
- **`copier.yml`** — Copier template config (questions: `project_name`, `project_slug`, `gateway_url`, `github_org`).
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
| `setup_start` / `setup_save_profile` / `setup_complete` | Onboarding flow — **bypasses the init gate** |
| `profile_get` / `profile_update` | Org profile (free-form JSON; bypasses init gate) |
| `declare_intent` / `complete_task` / `get_tasks` | Task lifecycle — `declare_intent` opens the **init gate** for an org/user |
| `skill_create` / `skill_update` / `skill_delete` / `skill_list` / `run_skill` | Dynamic prompt-based skills (templates with `{var}` placeholders rendered at call time) |

### The init gate
`mcp_server.py` enforces an **init gate**: most tool calls fail until the org has been onboarded (`setup_complete`) and the calling agent has called `declare_intent` to open a task. A small allowlist (`setup_*`, `profile_*`, `declare_intent`, `health_check`, `get_operator_instructions`) bypasses the gate. When adding a tool, decide explicitly whether it should be gated; the default is **gated**.

### Proxied integrations (from `mcp_connections.json`)
Tools appear as `<integration>__<tool_name>`.

The template ships with `{"connections": {}}` — **no integrations are configured by default**. Add entries (see `remote-gateway/CLAUDE.md` for the schema) to enable Apollo/Attio/Exa/etc. proxying.

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

- **Python ≥3.11** (`pyproject.toml`); ruff targets `py314` with rules `E,F,I,N,UP,B,SIM` and 100-char lines. Strict type hints and comprehensive docstrings required.
- **Docstrings are MCP descriptions.** Write them clearly for end-users.
- **No Hardcoded Credentials.** Use `os.environ` exclusively.
- **Read-Only by Default.** Mutating operations require explicit admin approval in code review.
- **Field Registry.** Wrap all tool responses with `validated("<integration>", result)` to ensure field consistency and drift detection. YAML schemas live in `context/fields/`.

## Admin Guardrails

- All proxied integrations (exa, apollo, attio, github) are subject to per-user tool permissions via `tool_permissions` table.
- Tool allow/deny lists are enforced at tool invocation time and reflected in `tools/list` responses.
- Admin approval is required before adding new built-in tools; follow code review guidelines in Coding Standards.

### Global Tool Toggle

Disable a proxied or built-in tool for **all users** at runtime — no restart required:

```
PUT /api/permissions/*/attio__search_records
Body: {"enabled": false}
```

The sentinel `user_id = "*"` in `tool_permissions` applies to every user. Globally disabled tools are hidden from `tools/list` and blocked at call time. Re-enable with `{"enabled": true}`.

View all global toggles:
```
GET /api/permissions/*
```

Use this when replacing a proxied MCP tool with a Python tool — disable the old route globally, register the new Python tool via `@mcp.tool()`, and the transition is live immediately.
