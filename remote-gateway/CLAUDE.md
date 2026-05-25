# Remote Gateway — Admin Reference

The Remote Gateway is the organization's central MCP server. It hosts promoted, QA-approved tools and acts as a governed interface for all business data. It also serves as the orchestrator for the **"Gateway First"** architecture, ensuring every agent session is documented and improved through shadow note-taking.

---

## Core Infrastructure

### Gateway Operator Persona
The gateway includes a mandatory initialization step for all connecting agents.
- **Initialization Tool**: `get_operator_instructions`
- **Initialization Prompt**: `initialize-session`

These instructions (defined in `prompts/init.md`) force the agent to adopt a "Gateway Operator" persona, which includes:
- **Shadow Note-taking** — call `write_note` after every significant task
- **Issue Filing** — when hitting friction, tell the user and ask for consent before calling `report_issue`. Issues are GitHub Issues on `ISSUE_DEPLOYMENT_REPO`.

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
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string. Railway injects this automatically when a Postgres plugin is added to the service. |
| `NOTES_ADAPTER` | No | Notes storage backend (default: `github-issues`). |
| `NOTES_REPO` | Yes (when adapter=github-issues) | `owner/repo` for notes (e.g. `Inform-Growth/inform-notes`). |
| `NOTES_GITHUB_TOKEN` | Yes (when adapter=github-issues) | Fine-grained PAT with `Issues: read+write` on `NOTES_REPO`. |
| `ISSUE_DEPLOYMENT_REPO` | Yes | `owner/repo` for friction issues (bugs about the gateway). |
| `ISSUE_DEPLOYMENT_GITHUB_TOKEN` | Yes | Fine-grained PAT with `Issues: read+write` on the gateway repo. |
| `ISSUE_REPORT_DISABLED` | No | Kill switch — set to `"true"` to disable `report_issue` without removing the tool |
| `BOOTSTRAP_ADMIN_USER_IDS` | No | Comma-separated user_ids to promote to role='admin' on every startup. Idempotent; never demotes. Unknown user_ids are logged and skipped. |
| `GOOGLE_OAUTH_CLIENT_ID` | Google | OAuth client ID from Google Cloud Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google | OAuth client secret |
| `USER_GOOGLE_EMAIL` | Google | Account the workspace MCP authenticates as |
| `WORKSPACE_MCP_CREDENTIALS_DIR` | Google | Persistent directory for cached OAuth tokens (e.g. `/data/google-workspace-creds`) |

---

## Tool Telemetry

Every tool call is recorded automatically via the telemetry patch in `core/mcp_server.py`.

- **Querying stats**: Call `get_tool_stats()` from any connected agent.
- **High Error Rates**: The `summary.high_error_rate` list flags tools with ≥5% error rate—this is your primary signal for API degradation or auth failures.
- **Storage**: PostgreSQL at `DATABASE_URL`. Railway injects the DSN automatically when a Postgres plugin is added to the service.

---

## Field Registry

Every tool should wrap its response with `validated("integration", result)`.
- **Validation**: Checks response against `context/fields/<integration>.yaml`.
- **Drift Detection**: Call `check_field_drift("integration", sample_data)` to identify schema changes.
- **Business Logic**: Definitions in YAML include `description` and `notes` to provide semantic context to agents.

---

## Admin Dashboard

The admin UI is a React + Vite + TypeScript + Tailwind 4 + shadcn (base-ui) app at `admin-ui/`. Production builds are served by Starlette from `/admin/`. For local development run `./dev.sh` from the repo root (Python on :8000, Vite on :5173 with HMR).

See `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md` (design) and `docs/superpowers/plans/2026-05-05-admin-ui-phase-0-scaffolding.md` (phase 0 plan).

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
- **Notes & Issue Backlog**: Monitor two repos — `NOTES_REPO` for `type:note` session notes (via the configured notes adapter), and `ISSUE_DEPLOYMENT_REPO` for `source:report_issue` friction signals. Review both regularly to understand user goals and stay ahead of integration failures.

### Admin role

A new `api_keys.role` column distinguishes `'admin'` from `'user'`. Five tools are admin-gated (require `role='admin'` on the caller): `create_user`, `list_users`, `set_user_role`, `set_tool_permission`, `set_skill_permission`. Seed admins on startup via the `BOOTSTRAP_ADMIN_USER_IDS` env var. The UI exposes a role-select cell on the Operators page, backed by `PUT /api/users/{user_id}/role`.

Custom roles and role→permission-set lookups are out of scope here — tracked separately.
