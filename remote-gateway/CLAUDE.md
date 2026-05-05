# Remote Gateway — Admin Reference

The Remote Gateway is the organization's central MCP server. It hosts promoted, QA-approved tools and acts as a governed interface for all business data. It also serves as the orchestrator for the **"Gateway First"** architecture, ensuring every agent session is documented and improved through shadow note-taking.

---

## Core Infrastructure

### Gateway Operator Persona
The gateway includes a mandatory initialization step for all connecting agents.
- **Initialization Tool**: `get_operator_instructions`
- **Initialization Prompt**: `initialize-session`

These instructions (defined in `prompts/init.md`) force the agent to adopt a "Gateway Operator" persona, which includes background **Shadow Note-taking** and **Issue Logging** to a dedicated GitHub repository.

---

## Running the Gateway

```bash
pip install -e .

# Stdio (local testing)
python remote-gateway/core/mcp_server.py

# SSE (production — operators connect to this)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MCP_SERVER_NAME` | No | Gateway display name (e.g., `agent-gateway`) |
| `MCP_TRANSPORT` | No | `combined`, `sse`, `streamable-http`, or omit for stdio |
| `MCP_SERVER_HOST` | No | SSE bind address (default: `0.0.0.0`) |
| `MCP_SERVER_PORT` | No | SSE port (default: `8000`) |
| `TELEMETRY_DB_PATH` | No | Path to SQLite telemetry file (default: `data/telemetry.db`) |
| `ADMIN_TOKEN` | Production: yes | Admin dashboard token. Default in `core/admin_api.py` is a loud sentinel; set to a real secret in production. |
| `GITHUB_TOKEN` | For notes tools | PAT with Contents read+write on the notes repo |
| `GITHUB_REPO` | For notes tools | `owner/repo` slug for the notes repo |
| `GITHUB_BRANCH` | No | Branch for notes read/write (default: `main`) |
| `NOTES_PATH` | No | Folder inside `GITHUB_REPO` to store notes (default: `notes`) |

Per-integration env vars (e.g. `HUBSPOT_PRIVATE_APP_ACCESS_TOKEN`) are referenced from `mcp_connections.json` via `${VAR_NAME}` substitution. See `mcp_connections.example.json` and `docs/integrations/`.

---

## Tool Telemetry

Every tool call is recorded automatically via the telemetry patch in `core/mcp_server.py`.

- **Querying stats**: Call `get_tool_stats()` from any connected agent.
- **High Error Rates**: The `summary.high_error_rate` list flags tools with ≥5% error rate—this is your primary signal for API degradation or auth failures.
- **Storage**: SQLite at `TELEMETRY_DB_PATH`. Mount a persistent volume at `/data` for production environments (Railway/Render) and set `TELEMETRY_DB_PATH=/data/telemetry.db`.

---

## Field Registry

Wrap structured tool responses with `validated("integration", result)` if a YAML schema exists.
- **Validation**: Checks response against `context/fields/<integration>.yaml`. None ship by default; add per integration as needed.
- **Drift Detection**: Call `check_field_drift("integration", sample_data)` to identify schema changes.
- **Business Logic**: Definitions in YAML include `description` and `notes` to provide semantic context to agents.

---

## Proxying Upstream MCPs

The gateway proxies upstream MCP servers at startup, re-exposing their tools as `<integration>__<tool_name>`. Three transports supported (stdio, sse, http).

For the recipe per transport, see [docs/integrations/stdio.md](docs/integrations/stdio.md), [docs/integrations/sse-passthrough.md](docs/integrations/sse-passthrough.md), and [docs/integrations/streamable-http.md](docs/integrations/streamable-http.md). One example per transport ships in `mcp_connections.example.json`.

To add a new Python tool (no upstream MCP available), see [docs/custom-tools.md](docs/custom-tools.md). To add a prompt or skill, see [docs/custom-prompts.md](docs/custom-prompts.md).

---

## Admin Guardrails

- **Read-only enforcement**: Tools should be read-only by default.
- **No hardcoded secrets**: Use `os.environ` exclusively.
- **Shadow Note-taking**: Monitor the "Write Notes" repository regularly to understand user goals and identify where the gateway is failing to provide a "good job."
- **Issue Backlog**: Audit the `issues/` folder in the notes repo to stay ahead of technical debt.
