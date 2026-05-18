# Agent Gateway

> Distributed agent work. Governed through middleware. One source of truth.

The Agent Gateway is a centralized MCP server that bridges the gap between raw data sources (Apollo, Attio, Exa, etc.) and AI agents. It provides a unified, governed interface for all business data, ensuring that every agent in the organization has access to clean, pre-labeled, and documented fields.

## Core Mandates

1. **Shadow Note-taking**: Every session's value is automatically captured in a dedicated GitHub "Write Notes" repository. This serves as the institutional memory of the gateway's usage and performance.
2. **Proactive Maintenance**: Errors, auth failures, and "noisy" data are automatically logged as issues to be addressed by administrators.
3. **Context Efficiency**: By providing purposeful tools rather than raw API access, the gateway reduces token usage and improves response quality.

---

## Getting Started

### 1. Connect to the Gateway

Add the gateway's URL to your MCP client (Claude for Work, Claude Desktop, etc.):

```json
{
  "mcpServers": {
    "inform-gateway": {
      "url": "https://your-gateway.railway.app/sse",
      "headers": {
        "Authorization": "Bearer sk-your-api-key"
      }
    }
  }
}
```

### 2. Initialize your Session

At the start of every session, use the `/operator_init` slash command (or call the `operator_init` tool if your client does not support slash commands). This will:
- Initialize the **Gateway Operator** persona.
- Activate the **Shadow Note-taking** and **Issue Logging** rules.

---

## Features

### Prompt Discovery
The gateway provides several high-level prompts for common workflows. If your client supports slash commands, you can invoke these directly by typing `/`:
- `/operator_init`: Set up your session context.
- `/morning_briefing`: Get a summary of Attio deals and Apollo contacts.
- `/weekly_pipeline_review`: Cross-reference Attio deals with Apollo activity.
- `/research_prospect`: Deep research on a company using Exa, Attio, and Apollo.
- `/add_prospect`: Enrich a contact in Apollo and create records in Attio.

**If you don't see slash commands:** Use the `list_prompts` tool to see available templates and `get_prompt` to execute them.

### Shadow Note-taking
When you use the gateway, the agent acting on your behalf is instructed to "shadow" your work. After significant tasks, it calls `write_note` to record:
- What you were trying to do.
- Whether the gateway provided a "good job".
- Specific opportunities for improvement.

### Issue Logging
If a tool fails or returns suboptimal data, the agent automatically calls `write_issue`. This ensures that technical debt and API degradations are surfaced immediately to the gateway admins.

### Persistence
All notes and issues are stored in a dedicated GitHub repository, ensuring they survive gateway redeployments and are accessible across different client sessions.

---

## Local Development

### 1. Install dependencies

```bash
pip install -e .
pip install -e ".[dev]"   # adds pytest and ruff
```

### 2. Configure environment

Copy the example env file and fill in your keys:

```bash
cp remote-gateway/.env.example remote-gateway/.env
# Edit remote-gateway/.env — all vars listed below are required
```

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | PAT with Contents read+write on the notes repo |
| `GITHUB_REPO` | `owner/repo` for the notes repo (e.g. `Inform-Growth/inform-notes`) |
| `ATTIO_API_KEY` | Attio API key |
| `APOLLO_API_KEY` | Apollo API key (app.apollo.io → Settings → Integrations → API Keys) |
| `EXA_API_KEY` | Exa API key |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client ID (Cloud Console → APIs & Services → Credentials) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client secret |
| `USER_GOOGLE_EMAIL` | Google account the workspace MCP authenticates as |
| `WORKSPACE_MCP_CREDENTIALS_DIR` | Path to cached OAuth tokens (e.g. `/data/google-workspace-creds` on Railway) |
| `DATABASE_URL` | PostgreSQL connection string (e.g., `postgresql://user:password@host/dbname`). Railway injects this automatically when a Postgres plugin is added. |
| `ADMIN_TOKEN` | Admin dashboard token (optional — defaults to `inform-admin-2026` locally) |

### 3. Start the server

```bash
# Combined SSE + streamable-HTTP on port 8000 (recommended for local testing)
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py

# Stdio only (for Claude Code / mcp CLI, no browser dashboard)
python remote-gateway/core/mcp_server.py
```

### 4. Verify it's running

```bash
curl http://localhost:8000/health
# → {"status": "ok", "transport": "combined"}
```

### 5. Open the admin dashboard

```
http://localhost:8000/admin?token=inform-admin-2026
```

The dashboard shows live tool stats, registered users, per-user permissions, and a Sankey chart of tool call flows.

#### Working on the admin UI

The admin UI is a React + Vite + TypeScript + Tailwind 4 + shadcn (base-ui) app at `remote-gateway/admin-ui/`. For HMR-driven local development, use `./dev.sh` from the repo root — it runs the Python gateway on :8000 and the Vite dev server on :5173 in parallel:

```bash
./dev.sh
# Then open http://localhost:5173/admin
```

The Vite dev server proxies `/admin/api/*` to the Python gateway and injects `VITE_ADMIN_TOKEN` (from `remote-gateway/admin-ui/.env.local`) automatically. The legacy HTML dashboard remains available at `/admin/legacy?token=...` as a safety net during the React migration. See `remote-gateway/admin-ui/README.md` for build/test details.

### 6. Connect Claude Code

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "inform-gateway": {
      "url": "http://localhost:8000/sse",
      "headers": {
        "Authorization": "Bearer sk-your-api-key"
      }
    }
  }
}
```

Create an API key first via the admin dashboard → Users → Create, or run:

```bash
# Call the create_user tool via curl (no auth required for the first key in dev)
curl -X POST "http://localhost:8000/admin/api/users?token=inform-admin-2026" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "you@example.com"}'
```

### 7. Run tests

```bash
pytest
ruff check .
```

---

## Administration

### Deployment
The gateway is a Python FastMCP server. It can be deployed to any host supporting Python (Railway, Fly.io, VPS).

```bash
# Set required env vars (see local dev table above)
export GITHUB_TOKEN=...
export GITHUB_REPO=...
export MCP_TRANSPORT=combined

# Run the server
python remote-gateway/core/mcp_server.py
```

### Google Workspace OAuth (Gmail + Calendar + Drive/Docs)

The gateway proxies a unified Google Workspace MCP via `uvx workspace-mcp`. First-time auth is browser-based and only needs to happen **once per Google account**; the cached refresh token is then reused on the server.

1. **Create OAuth client in Google Cloud Console**: APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID. Application type: Desktop app (or Web with `http://localhost:8000/oauth2callback` as redirect URI). Enable Gmail API, Calendar API, Drive API on the same project. Save the client ID and secret.

2. **Run the OAuth flow locally to mint a refresh token**:
   ```bash
   export GOOGLE_OAUTH_CLIENT_ID=...
   export GOOGLE_OAUTH_CLIENT_SECRET=...
   export USER_GOOGLE_EMAIL=you@example.com
   export WORKSPACE_MCP_CREDENTIALS_DIR=$HOME/.google_workspace_mcp/credentials
   uvx workspace-mcp --tool-tier core
   ```
   Make any tool call (e.g. via Claude Code with `workspace-mcp` configured locally). The first call returns an authorization URL; open it, consent, and the server caches tokens to `WORKSPACE_MCP_CREDENTIALS_DIR`.

3. **Move the cached tokens onto the Railway volume**:
   - Mount your Railway volume at `/data` (already done if telemetry is persisting).
   - Copy the contents of your local `~/.google_workspace_mcp/credentials/` into `/data/google-workspace-creds/` on the volume (Railway CLI `railway run` or a one-off shell into the container).
   - Set `WORKSPACE_MCP_CREDENTIALS_DIR=/data/google-workspace-creds` in Railway env vars along with the same `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and `USER_GOOGLE_EMAIL`.

4. **Redeploy.** Look for `[proxy] 'google' connected — N tool(s) registered` in startup logs. Refresh tokens auto-rotate; you should not need to repeat step 2 unless the user revokes access in their Google account settings.

### Tool Promotion
New tools are added to `remote-gateway/tools/` and registered in `remote-gateway/core/mcp_server.py`. Each tool should wrap its response with `validated("integration", result)` to ensure field consistency.

---

## Repository Structure

```
inform-gateway/
├── remote-gateway/
│   ├── core/
│   │   ├── mcp_server.py         ← Central FastMCP server
│   │   ├── field_registry.py     ← Field definition loader
│   │   └── mcp_proxy.py          ← Upstream MCP proxy logic
│   ├── tools/
│   │   ├── attio.py              ← Attio-specific tools
│   │   ├── notes.py              ← GitHub-backed notes/issues tools
│   │   └── meta.py               ← Health check and init tools
│   └── prompts/
│       └── init.md               ← The "Gateway Operator" system prompt
├── .github/
│   └── workflows/                ← CI/CD and automated QA
└── README.md
```

## License

MIT
