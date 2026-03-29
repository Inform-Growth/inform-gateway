# Agent Gateway

> Distributed agent work. Governed through middleware. One source of truth.

As AI agents proliferate across a business, three problems compound fast: agents waste tokens on raw, unrefined context; every team re-solves the same problems independently; and the same data fields get interpreted differently by different agents and teams.

Agent Gateway is a GitOps monorepo that addresses all of these. Operators explore data and workflows in personal sandboxes. Valuable work gets codified into tools and promoted to a shared gateway — a governed MCP server that accumulates the organization's business context: what tools exist, what each field means in your business, and how processes work. Every agent that connects to the gateway inherits that context instead of rebuilding it from scratch.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Four Pillars

### 1. Context efficiency through progressive codification

Early in an integration's life, agents spend tokens on exploration: raw API calls, large data payloads, reflection, planning. This is expected and necessary. The goal is to not stay there.

As an agent answers the same class of question repeatedly, it codifies the workflow: the API calls become a Python script that fetches and transforms data into a clean, purposeful shape. That script becomes a gateway tool. Future agents call the tool instead of the raw API — they receive exactly the fields they need, pre-labeled with business meaning, and nothing else.

Over time, the cost per task falls. Context gets smaller and more precise. The tokens that used to go toward wrestling with raw data go toward the actual work.

This is the core mechanic: **exploration → codification → refinement**. Every promoted tool is the organization learning something.

### 2. Distributed contribution across teams

Operators work independently in local sandboxes — no central bottleneck for exploration. Each operator's agent connects directly to the data sources they need and works freely. When a workflow proves valuable and repeatable, it flows upward through a pull request into the shared gateway, where it becomes available to every other agent in the org.

The result is a distributed contribution model: many agents explore in parallel, the best work rises to shared infrastructure, and no single team carries the burden of building everything.

> **Roadmap:** As teams and permission needs grow, access to gateway tools will be scopeable via per-team MCP keys. This is not implemented today but is a natural next step as the org grows.

### 3. Governance and safety through middleware

The gateway is not a direct API passthrough — it is middleware. Every promoted tool is QA-reviewed before merge, wrapped with a field validation layer on the gateway, and read-only by default. Mutating operations require explicit admin sign-off in the code review.

The single mandatory human gate is the merge decision. Everything else — PR creation, QA review, tool injection, field registry updates — is automated. The admin reads a QA comment and decides. That's it.

This model scales: a governance layer that requires no ongoing maintenance burden and applies uniformly to every tool, from every team, for every agent that connects.

### 4. Central source of truth for business data and processes

The gateway accumulates field definitions — the organization's semantic layer for every integration it touches. These definitions describe each data field not just technically (type, nullable) but semantically: what does `amount` mean in Stripe in your business? What does `stage` mean in your HubSpot pipeline? What does `arr` mean in your data warehouse, and how does your org calculate it?

These answers are written once, validated continuously, and shared with every agent that connects to the gateway. As more agents are layered onto the business — for analytics, operations, customer support, finance — they all inherit the same vocabulary. Nobody reinterprets the same field independently. Nobody builds on a stale definition.

The gateway becomes the place the business goes to understand what its data means.

---

## What the Operator Experiences

From the operator's perspective, this system is intentionally invisible. The workflow is:

```
Ask your agent a question about your data
        │
        ▼
Agent answers — using local tools, gateway tools, or both
        │
        ▼  (if the question was complex or likely to recur)
Agent says: "Codified into /stripe-revenue and pushed for review."
        │
        ▼
Nothing. Wait for the admin to merge.
        │
        ▼
git pull → new slash-command available, same answer costs far fewer tokens next time
```

That's the full operator experience. Everything between "pushed for review" and "git pull" happens automatically in the background.

---

## What Runs in the Background

| Trigger | What happens |
|---|---|
| Agent finishes a response | Hook commits and pushes `local-workspace/` to `operator/<username>` branch |
| Agent writes a file | Hook checks that a session note exists for today |
| Push to `operator/*` with new skills | `auto_pr.yml` opens a PR to main |
| PR opened or updated | `qa_agent_review.yml` runs QA review, posts structured comment on the PR |
| PR merged to main | `auto_promote.yml` injects tool into `remote-gateway/core/mcp_server.py` with `@mcp.tool()` and field validation wrapper; copies field definitions; commits back to main |

---

## What Requires Human Action

| Step | Who | What |
|---|---|---|
| Initial repo setup | Admin | Deploy gateway, add `OPENROUTER_API_KEY` to GitHub Secrets |
| Operator onboarding | Operator | Sparse checkout, add credential to `.env`, add MCP to `.mcp.json` |
| Connecting a new local MCP | Operator | Add entry to `.mcp.json` with local API key |
| Merging a PR | Admin | Read QA comment, decide to approve and merge |
| Provisioning env vars after promotion | Admin | Set new env vars on the gateway server, redeploy |
| (Optional) Centralizing an integration | Admin | Add to `mcp_connections.json`, set server env vars, redeploy |

---

## Repository Structure

```
agent-gateway/
│
├── local-workspace/              ← operators sparse-checkout only this
│   ├── .mcp.json                 ← gateway URL + personal local MCPs
│   ├── .env.example              ← credential catalog (copy to .env, never commit .env)
│   └── .claude/
│       ├── CLAUDE.md             ← workspace instructions (loaded every session)
│       ├── AGENTS.md             ← agent directives: incubation loop, git protocol
│       ├── settings.json         ← permissions + hooks (session note check, auto-push)
│       └── skills/
│           ├── workspace-onboarding/     ← /workspace-onboarding slash-command
│           ├── process-capture/          ← /process-capture slash-command
│           ├── integration-onboarding/   ← /integration-onboarding slash-command
│           ├── skill-creator/            ← /skill-creator slash-command
│           └── <name>/                   ← skills created during R&D
│               ├── SKILL.md              ← frontmatter + instructions
│               └── scripts/
│                   └── <name>.py         ← Python tool (promoted to gateway on merge)
│
├── remote-gateway/               ← admin-managed, never pulled by operators
│   ├── core/
│   │   ├── mcp_server.py         ← FastMCP gateway server
│   │   ├── field_registry.py     ← field definition loader and drift detector
│   │   └── mcp_proxy.py          ← optional: proxies upstream MCPs server-side
│   ├── context/
│   │   └── fields/               ← per-integration field definition YAMLs (the source of truth)
│   ├── mcp_connections.json      ← optional: upstream MCPs to proxy through gateway
│   └── prompts/
│       └── qa_agent_instructions.md
│
├── .github/
│   ├── workflows/
│   │   ├── auto_pr.yml           ← opens PRs when operator/* branch gets new skills
│   │   ├── qa_agent_review.yml   ← QA agent reviews every tool PR
│   │   └── auto_promote.yml      ← promotes merged tools into the gateway
│   └── scripts/
│       └── promote_tools.py      ← AI-powered tool injection script
│
├── copier.yml                    ← template config (for copier users)
└── pyproject.toml
```

---

## Setup (Admin, One-Time)

### 1. Create your repo

**Option A — GitHub Template (quickest)**
Click **"Use this template"** at the top of this page.

**Option B — copier (best for agencies managing multiple clients)**
```bash
pip install copier
copier copy gh:your-org/agent-gateway ./my-gateway
```

Copier prompts for: `project_name`, `project_slug`, `gateway_url`, `github_org`.

### 2. Deploy the remote gateway

```bash
pip install -e .

# Set required env var
export MCP_SERVER_NAME=my-org-gateway

# Run locally for testing (stdio)
python remote-gateway/core/mcp_server.py

# Run for remote access (SSE — what operators connect to)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py
```

Deploy target: any Python host — Railway, Fly.io, VPS, Docker. The SSE endpoint is `https://your-domain.com/sse`.

### 3. Configure GitHub Secrets

In your repo settings → Secrets and variables → Actions, add:

| Secret | Used by |
|---|---|
| `OPENROUTER_API_KEY` | QA agent review + auto-promotion |

### 4. Set the gateway URL in the repo

Edit `local-workspace/.mcp.json` and replace `[[ gateway_url ]]` with your SSE endpoint.

---

## Operator Onboarding (Per Person)

Operators only pull `local-workspace/` — they never see gateway code or admin credentials.

### Sparse checkout

```bash
git clone --no-checkout https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO
git sparse-checkout init --cone
git sparse-checkout set local-workspace
git checkout main
```

### Add credentials for local R&D

```bash
cp local-workspace/.env.example local-workspace/.env
# Edit .env — add your API keys for the integrations you'll explore
```

### Connect local MCP servers

Edit `local-workspace/.mcp.json` to add the integrations you need locally:

```json
{
  "mcpServers": {
    "my-gateway": { "url": "https://gateway.example.com/sse" },
    "stripe": {
      "command": "npx",
      "args": ["-y", "@stripe/mcp", "--tools=all"],
      "env": { "STRIPE_API_KEY": "${STRIPE_API_KEY}" }
    }
  }
}
```

The `${STRIPE_API_KEY}` reference reads from your `.env` file. The gateway entry gives you access to all previously promoted tools.

> **Context note:** `--tools=all` is appropriate for early exploration — you don't yet know which tools you'll need. As integrations mature and workflows are codified into gateway tools, narrow or remove the local MCP connection. The goal over time is to replace broad raw-API access with targeted gateway tools that return clean, pre-labeled data.

### Open Claude Code

Open the `local-workspace/` directory in Claude Code. The skills, hooks, and MCP config load automatically.

### Run workspace onboarding

Type `/workspace-onboarding` in the chat. The skill will:
- Ask for your name and create your `operator/<name>` branch
- Inventory your connected integrations
- Ask about your role and goals
- Save everything to `context/operator-profile.md` so future sessions start with context loaded

This step is optional but recommended — it saves setup time every time you open the workspace.

---

## Day-to-Day Usage

### Asking questions

Just ask. The agent calls whatever MCP tools are available — local or gateway — and answers. If the question is simple, that's the end of it.

### When the agent codifies something

If a question required multiple steps, the agent creates a skill directory and tells you:

> "Codified into `/stripe-revenue` and pushed for review."

A PR will appear in the repo within seconds. You don't need to do anything.

### Connecting a new integration

Use `/integration-onboarding`. It walks through finding the MCP package, adding credentials to `.env`, adding the entry to `.mcp.json`, capturing a sample response, and creating the field definitions.

### Automating a multi-step business process

Use `/process-capture` when you have a full workflow to build out — not just a single question, but a sequence of steps across multiple systems. Describe your process in conversation or paste a runbook/SOP. The skill will:
- Map every step and clarify ambiguities with you
- Identify all the integrations involved and set up any that aren't connected
- Decompose the process into discrete, promotable skills
- Hand each one off to `/skill-creator` to build and test

Example: *"I want to pull leads from Apollo, push them to HubSpot, enrich them, look up their phone numbers, and generate a custom one-pager for each."* `/process-capture` turns that into a prioritized build queue.

### Checking what's available

- **Local MCPs:** `list_tools` from your MCP client shows everything connected.
- **Gateway tools:** Call `health_check()` and `list_field_integrations()` on the gateway.
- **Field definitions:** Call `lookup_field("stripe", "amount")` to see what a field means in your business context.
- **Your skills:** Type `/` in Claude Code to see all available slash-commands.

### After a PR is merged

```bash
git pull
```

New skills are immediately available as slash-commands. New promoted tools are available through the gateway.

---

## The Full Lifecycle

### Stage 1 — Local exploration

Operator works in `local-workspace/`. Agent uses local MCPs (direct API connections). This is the expensive phase: raw data in context, multiple tool calls, exploration of what fields and endpoints exist. Session notes capture discoveries. Nothing is shared yet — this is pure R&D.

**Operator action:** Configure `.mcp.json`, add credentials to `.env`.

### Stage 2 — Codification

When a workflow proves valuable and repeatable, the agent creates a skill directory in `.claude/skills/<name>/`:
- `SKILL.md` — when/why to use this, how to interpret output. Becomes a `/name` slash-command.
- `scripts/<name>.py` — the Python logic. The script fetches data and transforms it into a purposeful shape — returning only what downstream agents need, labeled with business meaning. Type hints and docstring are required (the docstring becomes the MCP tool description after promotion).

The agent also updates `context/integrations/<name>/schema.md` with field definitions discovered during exploration.

**Operator action:** None. The agent does this.

### Stage 3 — Auto-push

The Stop hook in `settings.json` automatically commits `local-workspace/` and pushes to the operator's `operator/<username>` branch after each response.

**Operator action:** None. The hook runs automatically.

### Stage 4 — Auto-PR

When the push lands on an `operator/*` branch with new skill files, `auto_pr.yml` opens a pull request to `main` within seconds.

**Operator action:** None. GitHub Actions creates the PR.

### Stage 5 — QA review

`qa_agent_review.yml` runs a Claude agent (via OpenRouter) that reviews the PR diff for:
- **Safety** — no mutating operations (POST, DELETE, INSERT, DROP, PUT, PATCH)
- **Security** — no hardcoded API keys or credentials
- **Quality** — type hints present, docstring complete and clear
- **Output design** — script transforms data rather than passing through raw API responses
- **Pairing** — every script has a `SKILL.md` in the same directory

The agent posts a structured comment: either `🛑 QA FAILED` with the exact violation, or `✅ Passed Automated QA` with a migration summary for the admin.

**Operator action:** None. The review is automatic.

### Stage 6 — Human merge decision

An admin reads the QA comment and decides whether to merge. This is the only mandatory human gate in the pipeline.

**Admin action:** Review and merge (or request changes).

### Stage 7 — Auto-promotion

On merge from an `operator/*` branch, `auto_promote.yml`:
1. Calls Claude (via OpenRouter) to inject the Python function into `remote-gateway/core/mcp_server.py` with `@mcp.tool()` decorator and field validation wrapper.
2. Copies `context/fields/*.yaml` files to `remote-gateway/context/fields/`.
3. Commits and pushes the updated gateway back to `main`.
4. Prints a list of env vars the new tool requires (for admin to provision).

**Admin action:** Provision the listed env vars on the gateway server and redeploy.

### Stage 8 — Fleet sync

Operators run `git pull`. The new `SKILL.md` is pulled into their workspace — the `/tool-name` slash-command is immediately available. Their agent can now route queries to the centralized gateway tool instead of the local MCP.

**Operator action:** `git pull`.

### Stage 9 — Retire local connection

Once the gateway carries a promoted tool for an integration, the local MCP connection becomes redundant for that workflow. The operator removes that entry from `.mcp.json`. The gateway version uses server-side credentials and returns clean, transformed data.

Over time, this is how context gets smaller: each promoted tool replaces a broad local connection with a targeted, purposeful one.

**Operator action:** Clean up `.mcp.json`.

---

## The Field Registry

Every promoted tool wraps its response with `validated("integration", result)`. Field definitions live in `context/fields/<integration>.yaml`. The registry tools are available to any connected agent:

```python
lookup_field("stripe", "amount")           # → definition, type, business notes
get_field_definitions("hubspot")           # → full schema for the integration
check_field_drift("stripe", fresh_sample)  # → new_fields, removed_fields, unchanged
```

Drift detection keeps definitions current as vendor APIs evolve. Run it periodically or after a vendor update.

---

## Optional: Centralizing an Integration on the Gateway

Once an integration is mature and used org-wide, an admin can move its credentials server-side so operators no longer need local API keys for it.

Edit `remote-gateway/mcp_connections.json`:

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

Set `STRIPE_API_KEY` on the gateway server, redeploy. The gateway now proxies all of Stripe's tools as `stripe__<tool_name>`. Operators remove their local Stripe MCP entry — the gateway handles it.

> Centralizing the raw MCP is useful before custom tools exist. As integrations mature, purpose-built gateway tools should replace raw proxy access.

---

## Optional: Access Policy

For organizations that need governance over which MCP servers operators can configure, Claude Code supports a policy-based allowlist/denylist via [`managed-mcp.json`](https://code.claude.com/docs/en/mcp#managed-mcp-configuration) deployed at the OS level. This is an IT decision and is not required for the gateway to function.

---

## Coding Standards

- **Python 3.14+.** Type hints on every function parameter and return value.
- **Docstrings are MCP descriptions.** Write them to be clear to non-technical users — they appear as tool descriptions in every AI agent connected to the gateway.
- **No hardcoded credentials.** `os.environ` only.
- **Read-only by default.** Mutating operations (POST, DELETE, INSERT, DROP) require explicit admin approval in the QA review.
- **Transform, don't pass through.** Scripts should return purposeful data shapes, not raw API responses. Remove fields agents don't need. Add business labels. The test: can the output go directly into agent context without noise?
- **Linting:** `ruff` with line length 100.

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

---

## For Agencies: Managing Multiple Client Deployments

```bash
# New client
copier copy gh:your-org/agent-gateway ./client-acme

# Pull upstream improvements into an existing client repo
cd client-acme && copier update
```

Each client repo is independent. Improvements to the master template can be selectively pulled into each client with `copier update`.

---

## License

MIT — see [LICENSE](LICENSE).
