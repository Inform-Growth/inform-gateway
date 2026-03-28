@AGENTS.md

# Local Workspace

This is your R&D sandbox. You have direct access to data sources via local MCP connections and to all promoted tools via the shared gateway. Work freely here — nothing reaches the shared gateway until a PR is reviewed and merged by an admin.

---

## Directory Layout

```
local-workspace/
├── .mcp.json                      ← gateway URL + your local MCP connections
├── .env                           ← your local API keys (never committed)
├── .env.example                   ← catalog of variable names (committed, no values)
├── .claude/
│   ├── settings.json              ← auto-save hook, permissions
│   ├── skills/                    ← all skills live here
│   │   ├── integration-onboarding/  ← /integration-onboarding slash-command
│   │   ├── skill-creator/           ← /skill-creator slash-command
│   │   └── <name>/                  ← skills you create during R&D
│   │       ├── SKILL.md             ← frontmatter + instructions
│   │       └── scripts/
│   │           └── <name>.py        ← Python tool (promoted to gateway on merge)
├── context/
│   └── integrations/
│       └── <name>/
│           ├── README.md           ← business context, capabilities, known limits
│           └── schema.md           ← field definitions, enum values, API quirks
└── sessions/
    └── YYYY-MM-DD-HHmm-slug.md    ← per-session notes (see sessions/README.md)
```

---

## Skill Standards

Every skill in `.claude/skills/<name>/` follows this structure:

```
.claude/skills/<name>/
├── SKILL.md           ← required: frontmatter + instructions
├── scripts/           ← Python or Bash scripts the skill uses
├── references/        ← docs, schemas loaded into context as needed
└── assets/            ← templates, icons, other static files
```

**`SKILL.md` frontmatter** (required):
```yaml
---
name: skill-name        # becomes /skill-name slash-command
description: >
  One-line description. Used by Claude to decide when to auto-invoke this skill.
---
```

**Script requirements** — enforced by the CI QA agent before promotion:
- Type hints on every function parameter and return value.
- Comprehensive docstring covering purpose, args, returns. This becomes the MCP tool description on promotion — write it for a non-technical user.
- Credentials via `os.environ` only. Never hardcode keys.
- Read-only by default. No mutating calls (POST, DELETE, INSERT, DROP) without explicit approval.
- Reference scripts from `SKILL.md` using `${CLAUDE_SKILL_DIR}/scripts/<file>.py`.

---

## MCP Configuration

`.mcp.json` has two kinds of entries:

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

- **Gateway entry** — always present. Gives you access to all promoted tools.
- **Local MCP entries** — add as needed for R&D. These are your direct connections to raw data sources. Once an integration is promoted and centralized on the gateway, you can remove its local entry.

Credentials in `env` blocks use `${VAR_NAME}` syntax, which reads from your `.env` file.

---

## Background Automation

Two hooks run automatically — you don't trigger them manually:

**After every file write (`PostToolUse`):** Checks whether a session note exists for today. If not, prints a reminder. Session notes are the institutional memory of your R&D.

**After every response (`Stop`):** Commits all changes in `local-workspace/` and pushes to your `employee/<username>` branch. When new skills are pushed, a PR to main opens automatically and the QA agent reviews it.

You will see the message "Codified and pushed for review" when a skill is ready and has been pushed. After that, nothing more is required from you until the admin merges the PR.
