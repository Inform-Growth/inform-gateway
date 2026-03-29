# Remote Gateway — Admin Reference

The remote gateway is the organization's shared MCP server. It hosts promoted, QA-approved tools that every operator's AI agent can call. It also accumulates field definitions — the organization's source of truth for what each integration's data actually means.

Employees never see this directory. They sparse-checkout only `local-workspace/`.

---

## How Tools Get Here

Tool promotion is fully automated once a PR is merged. You do not manually copy code.

1. **Employee R&D** — operator works locally, agent codifies a skill in `local-workspace/.claude/skills/<name>/`.
2. **Auto-PR** — push to `operator/*` branch triggers `auto_pr.yml`, which opens a PR to main.
3. **QA review** — `qa_agent_review.yml` posts a `✅ Passed` or `🛑 FAILED` comment. Read this before merging.
4. **Merge** — you review the QA comment and merge.
5. **Auto-promotion** — `auto_promote.yml` runs:
   - Calls Claude (via OpenRouter) to inject the Python function into `core/mcp_server.py` with `@mcp.tool()` and `validated()` wrapper.
   - Copies `context/fields/*.yaml` files from `local-workspace` to `remote-gateway/context/fields/`.
   - Commits and pushes back to main.
   - Prints a list of env vars the new tool needs.

**Your actions after auto-promotion:**
1. Read the workflow output — find the listed env vars.
2. Add them to the gateway deployment environment.
3. Redeploy (pull updated main, restart server).

---

## Running the Gateway

```bash
pip install -e .

# Stdio (local testing)
python remote-gateway/core/mcp_server.py

# SSE (production — operators connect to this)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py
```

Environment variables:

| Variable | Required | Description |
|---|---|---|
| `MCP_SERVER_NAME` | No | Gateway display name (default: `[[ project_slug ]]`) |
| `MCP_TRANSPORT` | No | `sse` for remote deployment, omit for stdio |
| `MCP_SERVER_HOST` | No | SSE bind address (default: `0.0.0.0`) |
| `MCP_SERVER_PORT` | No | SSE port (default: `8000`) |
| `TELEMETRY_DB_PATH` | No | Path to SQLite telemetry file (default: `data/telemetry.db`) |
| *(tool-specific vars)* | Yes | Set after each promotion — printed by `auto_promote.yml` |

Deploy target: any Python host — Railway, Fly.io, VPS, Docker. The server is a standard ASGI app.

---

## Tool Telemetry

Every tool call is recorded automatically — no per-tool changes needed. The telemetry
patch in `core/mcp_server.py` wraps the `@mcp.tool()` decorator at startup, so
all built-in and promoted tools are tracked from the moment they register.

**Querying stats** — call `get_tool_stats()` from any connected agent:
```
get_tool_stats()           # all tools
get_tool_stats("stripe_revenue")   # one tool
```

Returns per-tool: call count, error count, error rate, last called timestamp,
avg and max duration. The `summary.high_error_rate` list flags tools with ≥5%
error rate across ≥10 calls — the primary signal for API degradation.

**Storage** — SQLite at `TELEMETRY_DB_PATH` (default: `remote-gateway/data/telemetry.db`).
The `data/` directory is gitignored. Zero external dependencies.

**Persistent storage on Railway / Render:**
1. Add a persistent volume to the service (Railway: Settings → Volumes; Render: Settings → Disks)
2. Mount it at `/data`
3. Set env var: `TELEMETRY_DB_PATH=/data/telemetry.db`

Without a persistent volume, stats reset on each redeploy. The gateway continues
to function normally — telemetry is never load-bearing.

---

## Field Registry

Every promoted tool wraps its response with `validated("integration", result)`. The field registry:
- Checks the response against stored field definitions.
- Flags unknown or changed fields in `_field_validation` without blocking the call.
- Provides `lookup_field()`, `get_field_definitions()`, and `check_field_drift()` as gateway tools operators can call.

Field definitions live in `context/fields/<integration>.yaml`. They're copied there automatically on PR merge. You enrich them by filling in `description` and `notes` for each field — the auto-generated entries have `TODO` placeholders.

**Drift detection** — run periodically or after vendor API updates:
```python
# Via MCP call to the gateway:
check_field_drift("stripe", fresh_sample_dict)
# → returns new_fields, removed_fields, unchanged_fields
```

Update the YAML and redeploy to bring the registry back in sync.

---

## Optional: Proxying Integrations Through the Gateway

For integrations that are mature and org-wide, you can move their credentials server-side so operators no longer need local API keys. The gateway connects to the upstream MCP at startup and re-exposes its tools as `<integration>__<tool_name>`.

Edit `mcp_connections.json`:

```json
{
  "connections": {
    "stripe": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@stripe/mcp", "--tools=all"],
      "env": {
        "STRIPE_API_KEY": "${STRIPE_API_KEY}"
      }
    }
  }
}
```

Set `STRIPE_API_KEY` on the gateway server, redeploy. Employees can then remove `stripe` from their `.mcp.json` — the gateway handles it.

**To revoke access:** remove the entry from `mcp_connections.json` and redeploy. Access is removed for all users immediately.

This is optional per integration. Local MCP connections remain the development path — centralization is a graduation step, not a requirement.

---

## Optional: Access Policy

For organizations that need governance over which MCPs operators can configure, Claude Code supports [`managed-mcp.json`](https://code.claude.com/docs/en/mcp#managed-mcp-configuration) deployed at the OS level on operator machines. Using Option 2 (allowlist/denylist), you can permit specific vendors while blocking others. This is an IT governance decision — not required for the gateway to function.

---

## Guardrails

- **Read-only enforcement.** Promoted tools must be read-only unless you explicitly grant write permission during the merge review.
- **No hardcoded secrets.** All credentials via `os.environ`. The QA agent rejects PRs that violate this.
- **Review AI-generated promotions.** `auto_promote.yml` uses an LLM to inject code — spot-check that the `@mcp.tool()` decorator, function signature, and `validated()` call are correct after each promotion.
- **Docstrings are user-facing.** They appear as tool descriptions in every connected AI agent. If a docstring is unclear, fix it before redeploying.
