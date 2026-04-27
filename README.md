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
| `APOLLO_ACCESS_TOKEN` | Apollo OAuth access token (see [Apollo credentials](#apollo-credentials) below) |
| `APOLLO_REFRESH_TOKEN` | Apollo OAuth refresh token |
| `APOLLO_CLIENT_ID` | Apollo OAuth client ID |
| `EXA_API_KEY` | Exa API key |
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

### Apollo Credentials

The gateway proxies Apollo via `https://mcp.apollo.io/mcp` using OAuth tokens that originated from a **Claude Code local MCP connection**. Claude Code stores OAuth tokens for connected MCP servers in the macOS Keychain under `Claude Code-credentials`. The `extract_mcp_tokens.py` script at the repo root reads that keychain entry and formats the values for `.env`.

**Initial setup / token refresh:**

The `extract_mcp_tokens.py` script only works if you have previously connected Apollo to Claude Code via its MCP OAuth flow. That flow creates an `mcpOAuth` entry in the macOS Keychain that the script reads. If you run the script and see `No MCP OAuth tokens found`, you need to trigger that flow first:

1. In Claude Code → Settings → MCP Servers, add `https://mcp.apollo.io/mcp` as a new server.
2. Claude Code opens a browser for Apollo's OAuth consent — log in and approve. The tokens are stored in Keychain automatically.
3. Extract and paste into `.env`:
   ```bash
   python extract_mcp_tokens.py apollo --env
   ```
4. Restart the gateway.
5. Once confirmed working, remove the direct Apollo entry from Claude Code MCP settings — the gateway proxies it for all users from that point on.

**If the gateway shows `'apollo' failed to connect`:** the access token has expired. The gateway will attempt an automatic refresh using `APOLLO_REFRESH_TOKEN`, but if the refresh token has also expired you need to repeat steps 1–5 above.

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
