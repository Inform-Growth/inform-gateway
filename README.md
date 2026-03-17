# Agent Gateway

> An agentic GitOps monorepo template — bridge decentralized employee experimentation with centralized, governed AI infrastructure.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local AI agents connect to raw data sources (Stripe, Snowflake, CRM, etc.) for rapid R&D. When a workflow proves valuable, the agent automatically codifies it into a **Python Tool** and a **Markdown Skill**, then opens a pull request. A CI QA agent reviews the diff. Admins promote approved tools to a centralized **Remote Gateway** — a governed MCP server that every team member's AI agent connects to.

---

## How It Works

```
Employee asks a question
         │
         ▼
Local agent uses raw MCP tools (Stripe, Snowflake, CRM...)
         │
         ▼ (if multi-step or complex)
Codify → tools/<script>.py  +  skills/<name>.md
         │
         ▼
Auto-push to feature/<username>-<tool-name> branch
         │
         ▼
CI QA Agent reviews PR (safety · security · type hints · docstrings)
         │
         ▼
Admin promotes: copy function → remote-gateway/core/mcp_server.py + @mcp.tool()
         │
         ▼
git pull → entire team's agents learn the new centralized tool
```

---

## Getting Started

### Option 1 — GitHub Template (quickest)

Click **"Use this template"** at the top of this page. You get a clean copy with no git history.

After cloning your new repo:

1. Replace `[[ gateway_url ]]` in `local-workspace/.mcp.json` with your deployed gateway URL.
2. Copy `remote-gateway/.env.example` → `remote-gateway/.env` and fill in your keys.
3. Add `OPENAI_API_KEY` to your repo's GitHub Secrets (used by the CI QA agent).
4. Deploy the remote gateway (see below).

### Option 2 — copier (variable substitution + future sync)

Best for agencies or teams managing multiple independent deployments.

```bash
pip install copier
copier copy gh:your-org/agent-gateway ./my-agent-gateway
```

Copier will prompt you for:

| Variable | Description | Example |
|---|---|---|
| `project_name` | Human-readable name | `Acme Agent Gateway` |
| `project_slug` | Package/URL identifier | `acme-agent-gateway` |
| `gateway_url` | Where your remote gateway lives | `https://gateway.acme.com` |
| `github_org` | Your GitHub org or username | `acme-corp` |

To pull in upstream template improvements later:

```bash
cd my-agent-gateway
copier update
```

---

## Repository Structure

```
├── .github/
│   └── workflows/
│       └── qa_agent_review.yml     # CI: AI reviews every tool PR
│
├── local-workspace/                # Employees sparse-checkout only this folder
│   ├── .mcp.json                   # MCP server config (gateway URL + local MCPs)
│   ├── AGENTS.md                   # Agent directives: incubation loop, auto-push
│   ├── CLAUDE.md                   # Claude Code instructions for local agents
│   ├── tools/                      # Python tools created by local agents
│   ├── skills/                     # Markdown SOPs — when/why to use each tool
│   ├── context/                    # Brand guidelines, templates, reference docs
│   └── sessions/                   # Per-session notes (committed for analysis)
│
├── remote-gateway/                 # Admin-managed centralized gateway
│   ├── core/
│   │   └── mcp_server.py           # FastMCP server — promoted tools live here
│   ├── prompts/
│   │   └── qa_agent_instructions.md
│   └── skills/                     # Admin-facing skills for gateway management
│
├── copier.yml                      # Template config (for copier users)
└── pyproject.toml                  # Python package config
```

---

## Employee Onboarding (Sparse-Checkout)

Employees only pull `local-workspace/` — they never see gateway code or credentials:

```bash
# 1. Clone without checking out files
git clone --no-checkout https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO

# 2. Enable sparse-checkout
git sparse-checkout init --cone
git sparse-checkout set local-workspace

# 3. Pull the workspace
git checkout main
```

Then point their AI client (Claude Code, Cursor, etc.) at `local-workspace/.mcp.json` as the MCP config file.

---

## Deploying the Remote Gateway

```bash
# Install dependencies
pip install -e .

# Configure environment
cp remote-gateway/.env.example remote-gateway/.env
# Edit .env — add your API keys

# Run locally (stdio transport)
python remote-gateway/core/mcp_server.py

# Run for remote access (SSE transport)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py
```

The SSE endpoint is `https://your-domain.com/sse` — put that URL in `local-workspace/.mcp.json`.

**Deploy target:** Any Python host works — Railway, Fly.io, a VPS, Docker. The server is a standard ASGI app via FastAPI + uvicorn.

---

## Adding Local MCP Servers (R&D)

Employees can add personal MCP connections in `local-workspace/.mcp.json` for experimentation:

```json
{
  "mcpServers": {
    "my-gateway": { "url": "https://gateway.example.com/sse" },
    "stripe": { "command": "npx", "args": ["-y", "@stripe/mcp", "--tools=all"] },
    "postgres": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://..."] }
  }
}
```

These are personal and never committed (`.mcp.local.json` is gitignored for local overrides).

---

## The Tool → Gateway Lifecycle

### 1. Experiment
Local agent uses raw MCP connections to answer a business question.

### 2. Codify (Incubation Loop)
If the answer required multiple tool calls or data cleaning, the agent writes:
- `local-workspace/tools/<script>.py` — executable Python with type hints + docstring
- `local-workspace/skills/<name>.md` — Markdown SOP: business problem, when to trigger, how to interpret output

### 3. Auto-Push
Agent commits the tool+skill pair to `feature/<username>-<tool-name>` and pushes to GitHub.

### 4. CI QA Review
`.github/workflows/qa_agent_review.yml` triggers on the auto-created PR and checks:
- **Safety** — no mutating operations (POST, DELETE, INSERT, DROP)
- **Security** — no hardcoded secrets
- **Quality** — type hint coverage, docstring completeness
- **Skill pairing** — every tool has a matching skill

### 5. Auto-Promotion
On merge, `.github/workflows/auto_promote.yml` runs automatically:
- Calls Claude API to inject the tool function into `remote-gateway/core/mcp_server.py` with `@mcp.tool()` and field validation wrapper
- Copies field definition YAMLs to `remote-gateway/context/fields/`
- Commits back to main

The only remaining manual step: **admin provisions env vars and redeploys the gateway.**

### 6. Fleet Sync
Employees `git pull`. Their agents read the new skill and start routing requests to the centralized gateway tool instead of raw local MCPs.

---

## Coding Standards

- **Python 3.14+.** Type hints and docstrings required on every tool function.
- **Docstrings = MCP descriptions.** Write them to be clear and actionable.
- **No hardcoded credentials.** Use `os.environ` for all API keys.
- **Read-only by default.** Mutating operations require explicit admin approval.
- **Linting:** `ruff` with line length 100.

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

---

## For Agencies: Managing Multiple Client Deployments

If you're using this as a template for multiple clients:

```bash
# Generate a new client deployment
copier copy gh:your-org/agent-gateway ./client-acme

# Later — pull template improvements into an existing client repo
cd client-acme
copier update
```

Each client repo is independent. Improvements you make to the master template can be selectively merged into each client with `copier update`.

To backport a client discovery into the master template, open a PR against this repo.

---

## Contributing

Improvements welcome. Please:
1. Fork the repo and create a feature branch.
2. Follow the coding standards above (type hints, docstrings, `ruff` clean).
3. Open a PR — the CI QA agent will review it automatically.

---

## License

MIT — see [LICENSE](LICENSE).
