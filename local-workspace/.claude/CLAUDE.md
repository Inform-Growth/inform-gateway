@AGENTS.md

# Local Workspace

R&D sandbox. Local AI agents connect to data sources, explore workflows, and codify them as skills that get promoted to the shared gateway.

---

## Directory Layout

```
local-workspace/
├── .mcp.json                        ← gateway URL + local MCP connections
├── .env                             ← your API keys (never committed)
├── .env.example                     ← catalog of variable names (committed)
└── .claude/
    ├── rules/                       ← loaded automatically by file type
    │   ├── guardrails.md            ← always: read-only, no hardcoded secrets
    │   ├── skill-standards.md       ← when in .claude/skills/**
    │   ├── python-quality.md        ← when in skills/**/scripts/**/*.py
    │   ├── integration-docs.md      ← when in context/integrations/**
    │   └── session-notes.md         ← when in sessions/**
    ├── agents/                      ← specialized subagents (@-mention or delegate)
    │   ├── qa-pre-check.md          ← reviews skills before push
    │   ├── field-enricher.md        ← enriches API field definitions (has memory)
    │   └── session-scribe.md        ← creates/updates session notes (has memory)
    ├── skills/                      ← slash-commands + promotable tools
    │   ├── workspace-onboarding/    ← /workspace-onboarding  (first-time setup + profile)
    │   ├── process-capture/         ← /process-capture        (workflow → skill decomposition)
    │   ├── integration-onboarding/  ← /integration-onboarding
    │   └── skill-creator/           ← /skill-creator
    ├── output-styles/
    │   └── analyst.md               ← data-focused response style
    └── settings.json                ← permissions + auto-save hook
```

Context and sessions live at the workspace level:
```
local-workspace/
├── context/integrations/<name>/     ← README.md + schema.md per integration
└── sessions/                        ← per-session notes (YYYY-MM-DD-HHmm-slug.md)
```

---

## MCP Configuration

`.mcp.json` is personal per-operator config and is **gitignored**. Copy `.mcp.json.example`
to `.mcp.json` to get started, then add your integrations.

`.mcp.json` has two kinds of entries — both present at the same time:

```json
{
  "mcpServers": {
    "my-gateway": {
      "url": "https://your-gateway.example.com/sse"
    },
    "stripe": {
      "command": "npx",
      "args": ["-y", "@stripe/mcp", "--tools=all"],
      "env": { "STRIPE_API_KEY": "${STRIPE_API_KEY}" }
    }
  }
}
```

**Gateway entry** — always present. All promoted tools live here.
**Local MCP entries** — added per integration during R&D. Remove once the integration is fully promoted and centralized on the gateway.

**Credentials**: always use `${VAR_NAME}` syntax in the `env` block — never paste a
key value directly. Some MCP setup guides (Perplexity, Linear, etc.) show inline keys;
do not follow that pattern. Real values go in `.env`.

**User-scope MCP servers**: if you've already installed a server via `claude mcp add
--scope user` or the Claude desktop app, you don't need a project-scope entry. The
agent will still track it in `context/mcp-registry.md` so admins know what the gateway needs.

**Tracking**: `context/mcp-registry.md` is the committed record of all MCP tools in
active use — regardless of scope. Admins use this to provision the gateway.

---

## Available Skills

Invoke with `/skill-name` or let the agent trigger them automatically.

| Skill | When to use |
|---|---|
| `/workspace-onboarding` | First time in this workspace, or to update your operator profile |
| `/process-capture` | Multi-step workflow to automate across multiple systems |
| `/integration-onboarding` | Connecting a single new data source (MCP or raw API) |
| `/skill-creator` | Building, improving, or testing a single skill |

---

## Available Agents

Use `@agent-name` to invoke directly, or delegate naturally in conversation.

| Agent | When to use |
|---|---|
| `@qa-pre-check` | Before pushing a skill — catches CI failures early |
| `@field-enricher` | After capturing a sample API response — writes business definitions |
| `@session-scribe` | At session start or to log a discovery mid-session |
