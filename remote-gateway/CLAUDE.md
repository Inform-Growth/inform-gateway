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
| `MCP_SERVER_NAME` | No | Gateway display name (e.g., `inform-gateway`) |
| `MCP_TRANSPORT` | No | `sse` for remote deployment, omit for stdio |
| `MCP_SERVER_HOST` | No | SSE bind address (default: `0.0.0.0`) |
| `MCP_SERVER_PORT` | No | SSE port (default: `8000`) |
| `TELEMETRY_DB_PATH` | No | Path to SQLite telemetry file (default: `data/telemetry.db`) |
| `GITHUB_TOKEN` | Yes | PAT with Contents read+write on the notes repo |
| `GITHUB_REPO` | Yes | `owner/repo` slug for the notes repo |
| `GITHUB_BRANCH` | No | Branch for notes read/write (default: `main`) |
| `NOTES_PATH` | No | Folder inside `GITHUB_REPO` to store notes (default: `notes`) |
| `GMAIL_OAUTH_KEYS_JSON` | Gmail | Raw JSON of `gcp-oauth.keys.json` from GCP Console |
| `GMAIL_CREDENTIALS_JSON` | Gmail | Raw JSON of `~/.gmail-mcp/credentials.json` after local auth |
| `GMAIL_OAUTH_PATH` | Gmail | Override path to OAuth keys file (set automatically from `GMAIL_OAUTH_KEYS_JSON`) |
| `GMAIL_CREDENTIALS_PATH` | Gmail | Override path to credentials file (set automatically from `GMAIL_CREDENTIALS_JSON`) |

---

## Tool Telemetry

Every tool call is recorded automatically via the telemetry patch in `core/mcp_server.py`.

- **Querying stats**: Call `get_tool_stats()` from any connected agent.
- **High Error Rates**: The `summary.high_error_rate` list flags tools with ≥5% error rate—this is your primary signal for API degradation or auth failures.
- **Storage**: SQLite at `TELEMETRY_DB_PATH`. Mount a persistent volume at `/data` for production environments (Railway/Render) and set `TELEMETRY_DB_PATH=/data/telemetry.db`.

---

## Field Registry

Every tool should wrap its response with `validated("integration", result)`.
- **Validation**: Checks response against `context/fields/<integration>.yaml`.
- **Drift Detection**: Call `check_field_drift("integration", sample_data)` to identify schema changes.
- **Business Logic**: Definitions in YAML include `description` and `notes` to provide semantic context to agents.

---

## Proxying Upstream MCPs

The gateway can proxy upstream MCP servers (Apollo, Attio, etc.) at startup, re-exposing their tools as `<integration>__<tool_name>`.

Edit `mcp_connections.json`:
```json
{
  "connections": {
    "stripe": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@stripe/mcp", "--tools=all"],
      "env": { "STRIPE_API_KEY": "${STRIPE_API_KEY}" }
    }
  }
}
```

---

## Admin Guardrails

- **Read-only enforcement**: Tools should be read-only by default.
- **No hardcoded secrets**: Use `os.environ` exclusively.
- **Shadow Note-taking**: Monitor the "Write Notes" repository regularly to understand user goals and identify where the gateway is failing to provide a "good job."
- **Issue Backlog**: Audit the `issues/` folder in the notes repo to stay ahead of technical debt.
