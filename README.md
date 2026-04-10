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

Add the gateway's SSE or HTTP endpoint to your MCP client (Claude Desktop, Claude Code, etc.):

```json
{
  "mcpServers": {
    "inform-gateway": {
      "url": "https://your-gateway-url.com/sse",
      "headers": {
        "Authorization": "Bearer sk-your-api-key"
      }
    }
  }
}
```

### 2. Initialize your Session

At the start of every session, call the `get_operator_instructions` tool or use the `initialize-session` prompt. This will:
- Initialize the **Gateway Operator** persona.
- Activate the **Shadow Note-taking** and **Issue Logging** rules.

---

## How it Works

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

## Administration

### Deployment
The gateway is a Python FastMCP server. It can be deployed to any host supporting Python (Railway, Fly.io, VPS).

```bash
# Set required env vars
export GITHUB_TOKEN=...
export GITHUB_REPO=...
export NOTES_PATH=notes

# Run the server
python remote-gateway/core/mcp_server.py
```

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
