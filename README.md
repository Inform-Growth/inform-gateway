# << project_name >>

> Distributed agent work. Governed through middleware. One source of truth.

A centralized MCP server that hosts curated tools and proxies upstream MCP servers behind one authenticated endpoint. Operators connect once with an API key; the gateway resolves auth, enforces per-user and global permissions, records every tool call to SQLite telemetry, and surfaces shadow notes + issue logs to a dedicated GitHub repo.

This repo is a template. Scaffold a deployment with [Copier](https://copier.readthedocs.io/), wire your integrations into `mcp_connections.json`, and ship.

## Why this template

- **One credential surface.** Operators hold one Bearer token; vendor credentials stay server-side.
- **Per-user + global permissions.** Disable a tool for one operator or for everyone — runtime, no restart.
- **Telemetry by default.** Every tool call is timed, attributed, and stored in SQLite.
- **Field registry.** YAML schemas under `remote-gateway/context/fields/` document every integration's response shape and surface drift when vendors change schemas.
- **Hot-reloaded skills.** Reusable prompt templates live in SQLite; agents create new ones at runtime via the seeded `skill-creator` skill.

## Core mandates

1. **Shadow note-taking.** Every operator session is shadow-recorded to a GitHub notes repo via `write_note`. Institutional memory of what agents did and how well the gateway served them.
2. **Proactive maintenance.** Errors, auth failures, and noisy data get logged as issues via `write_issue`.
3. **Context efficiency.** Purposeful tools beat raw API access — fewer tokens, better responses.

---

## Quickstart

### Scaffold the template

```bash
pip install copier
copier copy gh:<< github_org >>/<< project_slug >> ./my-gateway
cd my-gateway
```

### Install + configure

```bash
pip install -e ".[dev]"
cp remote-gateway/.env.example remote-gateway/.env
# Edit remote-gateway/.env — see "Environment variables" below
```

### Run

```bash
# Combined SSE + streamable-HTTP on port 8000 (recommended for local testing)
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

### Verify

```bash
curl http://localhost:8000/health
# → {"status": "ok", "transport": "combined"}
```

### Open the admin dashboard

```
http://localhost:8000/admin?token=$ADMIN_TOKEN
```

Live tool stats, registered users, per-user permissions, telemetry charts.

### Connect a client

Copy `.mcp.json.example` → `.mcp.json` and replace `${GATEWAY_USER_API_KEY}` with a real key. Create the first key via the admin dashboard's Users tab, or:

```bash
curl -X POST "http://localhost:8000/admin/api/users?token=$ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "you@example.com"}'
```

### Run tests

```bash
pytest
ruff check .
```

---

## Environment variables

Configured in `remote-gateway/.env`. The gateway reads all of these via `os.environ`; nothing is hardcoded.

| Variable | Required | Purpose |
|---|---|---|
| `MCP_SERVER_NAME` | No | Display name for the gateway. Defaults to `agent-gateway`. |
| `MCP_SERVER_HOST` | No | SSE bind address. Defaults to `0.0.0.0`. |
| `MCP_SERVER_PORT` | No | SSE port. Defaults to `8000`. |
| `MCP_TRANSPORT` | No | `combined`, `sse`, `streamable-http`, or omit for stdio. |
| `TELEMETRY_DB_PATH` | No | SQLite path. Defaults to `data/telemetry.db`. Mount `/data` as a persistent volume on Railway/Render. |
| `ADMIN_TOKEN` | **Production: yes** | Admin dashboard token. The `_DEFAULT_TOKEN` placeholder in `core/admin_api.py` is a loud sentinel — set this to a real secret in production. |
| `GITHUB_TOKEN` | For notes tools | Fine-grained PAT with Contents read+write on the notes repo. |
| `GITHUB_REPO` | For notes tools | `owner/repo` slug (e.g. `<< github_org >>/agent-notes`). |
| `GITHUB_BRANCH` | No | Branch for notes read/write. Defaults to `main`. |
| `NOTES_PATH` | No | Folder inside `GITHUB_REPO`. Defaults to `notes`. |

Per-integration env vars (e.g. `HUBSPOT_PRIVATE_APP_ACCESS_TOKEN`) are referenced from `mcp_connections.json` via `${VAR_NAME}` substitution. See `mcp_connections.example.json` and the integration recipes below.

---

## Built-in capabilities

Available via MCP tools and (where applicable) admin HTTP routes.

| Tool | Description |
|---|---|
| `health_check` | Verify server is running. |
| `get_tool_stats` | Per-tool call counts, error rates, latency. |
| `get_session_usage` | Tool call sequences, per-user breakdown. |
| `create_user` | Admin — issue an API key for a new operator. |
| `get_operator_instructions` | Load the Gateway Operator persona. |
| `list_prompts` / `get_prompt` | Discover and render prompt templates. |
| `write_note` / `read_note` / `list_notes` / `delete_note` | GitHub-backed markdown notes. |
| `write_issue` / `list_issues` | Issue tracking in the same repo. |
| `skill_list` / `skill_create` / `skill_update` / `skill_delete` / `run_skill` | SQLite-backed reusable prompt templates. |
| `setup_start` / `setup_save_profile` / `setup_complete` | Org onboarding flow. |
| `profile_get` / `profile_update` | Org profile CRUD. |
| `declare_intent` / `complete_task` / `get_tasks` | Task gate — agents declare intent before tool use; calls are attributed to a task. |
| `check_field_drift` / `discover_fields` / `get_field_definitions` / `lookup_field` / `list_field_integrations` | Field registry queries. |

### Available prompts

| Prompt | Description |
|---|---|
| `operator_init` | Initialize the Gateway Operator persona. |
| `qa_agent_instructions` | Instructions for QA agents reviewing tool usage. |
| `how_to_use_prompts` | Guide for invoking prompts in your client. |

For workflow-style prompts (weekly reviews, daily briefings, etc.), use SQLite-backed skills — see [Adding a custom prompt](remote-gateway/docs/custom-prompts.md). The seeded `skill-creator` skill walks an agent through designing and registering a new one.

---

## Adding integrations

Pick the recipe that matches your transport:

- **stdio** (local Node/Python CLI MCP servers): [remote-gateway/docs/integrations/stdio.md](remote-gateway/docs/integrations/stdio.md). Worked example: HubSpot.
- **SSE pass-through** (older long-lived remote MCPs): [remote-gateway/docs/integrations/sse-passthrough.md](remote-gateway/docs/integrations/sse-passthrough.md).
- **Streamable-HTTP** (modern remote MCPs): [remote-gateway/docs/integrations/streamable-http.md](remote-gateway/docs/integrations/streamable-http.md).

`remote-gateway/mcp_connections.example.json` ships one example per transport. Copy entries into `mcp_connections.json` to enable.

## Adding tools and prompts

- **Custom Python tool**: [remote-gateway/docs/custom-tools.md](remote-gateway/docs/custom-tools.md). Module under `remote-gateway/tools/`, `register(mcp)` function, wired from `core/mcp_server.py`. Telemetry, gates, and task-id wrapping are auto-applied via `_tracked_mcp_tool`.
- **Custom prompt or skill**: [remote-gateway/docs/custom-prompts.md](remote-gateway/docs/custom-prompts.md). Static prompts via `@mcp.prompt()`; skills via `skill_create` (runtime) or `system_skills.json` (deploy-time seed).

---

## Permissions

### Per-user

Per-user tool permissions live in the `tool_permissions` SQLite table. The admin dashboard's Users tab toggles them at runtime; the gateway's `_AuthMiddleware` enforces them on every call and reflects them in `tools/list`.

### Global toggle

Disable a tool for *all* users at runtime — no restart:

```
PUT /admin/api/permissions/*/<tool_name>
Body: {"enabled": false}
```

`user_id = "*"` is the global sentinel. Globally disabled tools are hidden from `tools/list` and blocked at call time. View all toggles via `GET /admin/api/permissions/*`.

Use this when replacing a proxied MCP tool with a Python tool: disable the proxy route globally, register the Python replacement via `@mcp.tool()`, and the swap is live.

---

## Deployment

The gateway is a Python FastMCP server. It runs on any host that supports Python 3.11+ — Railway, Fly.io, Render, a VPS. The shipped Dockerfile is a self-contained image with Node 20 (for stdio MCP subprocesses) and the gateway code.

```bash
docker build -t << project_slug >> .
docker run -p 8000:8000 \
  -e ADMIN_TOKEN=... \
  -e GITHUB_TOKEN=... \
  -e GITHUB_REPO=... \
  -v /opt/data:/app/data \
  << project_slug >>
```

Mount a persistent volume for `data/telemetry.db` so telemetry and skills survive redeploys.

---

## Repository structure

```
<< project_slug >>/
├── remote-gateway/
│   ├── core/
│   │   ├── mcp_server.py         ← FastMCP server entrypoint
│   │   ├── mcp_proxy.py          ← Upstream MCP proxy (stdio / sse / http)
│   │   ├── admin_api.py          ← Admin HTTP routes
│   │   ├── system_skills.py      ← System skill seeder
│   │   ├── telemetry.py          ← SQLite store
│   │   └── field_registry.py     ← YAML field schema loader
│   ├── tools/
│   │   ├── meta.py               ← health_check, stats, user mgmt
│   │   ├── notes.py              ← GitHub-backed notes/issues
│   │   ├── registry.py           ← Field registry query tools
│   │   └── _core/                ← Onboarding, profile, skills, tasks
│   ├── docs/
│   │   ├── integrations/         ← Per-transport recipes
│   │   ├── custom-tools.md
│   │   └── custom-prompts.md
│   ├── prompts/
│   │   ├── init.md               ← Gateway Operator persona
│   │   └── qa_agent_instructions.md
│   ├── context/fields/           ← YAML field schemas (none ship by default)
│   ├── tests/                    ← pytest suite
│   ├── mcp_connections.json      ← Active proxy configs (empty by default)
│   ├── mcp_connections.example.json  ← One example per transport
│   ├── system_skills.json        ← Seed file for is_system=1 skills
│   └── .env.example
├── AGENTS.md                     ← Top-level guide for agents
├── CLAUDE.md                     ← Claude Code dev guidance
├── .mcp.json.example             ← Client connection template
├── copier.yml                    ← Template scaffolding config
├── Dockerfile
└── pyproject.toml
```

## License

MIT
