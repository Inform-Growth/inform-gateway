---
name: integration-onboarding
description: >
  Connect a new data source (MCP server or raw API) to the local workspace.
  Triggers when a user wants to pull data from a new system, when a tool-not-found
  error occurs, or when the user asks about data in an unconnected system.
---

# Integration Onboarding Skill

## Business Problem

When an operator wants to connect a new data source — a third-party MCP server
(Stripe, HubSpot, Postgres) or a raw API — there is a standard sequence that
must be followed to ensure field definitions are registered, the tool is
properly codified, and the gateway can eventually take over the connection.

This skill walks you through that sequence end to end.

---

## When to Trigger

Trigger this skill when:
- A user says "I want to connect [service]" or "can you pull data from [service]?"
- You attempt to call a tool and get a "tool not found" error from the gateway.
- A user asks about data that exists in a system not yet in `.mcp.json`.

---

## Step-by-Step Procedure

### Step 1 — Determine integration type

**MCP server available?** Check if a pre-built MCP package exists:
- Search `npmjs.com` for `@<vendor>/mcp` or `@modelcontextprotocol/server-<vendor>`
- If found → use the MCP path below.
- If not → use the Raw API path below.

---

### Path A — MCP Server

**Step A0 — Choose installation scope**

Ask the operator which scope they want:

> "Where do you want to install this MCP server?
> - **Project** — adds it to `.mcp.json`. Visible to the team, tracked in git. Requires a one-time trust approval in Claude Code. Best when the whole team needs the same integration.
> - **User** — installs via `claude mcp add --scope user`. Personal to your machine, portable across projects, no trust prompt. Best for personal API keys or tools only you use."

Or check if it's already installed:

> "Do you already have [integration] set up in your Claude desktop or user settings?"

| | Project scope | User scope |
|---|---|---|
| Config location | `.mcp.json` (committed) | `~/.claude/` (personal) |
| Visible to team | Yes | No |
| Trust prompt required | Yes (one-time) | No |
| Credential location | `.env` + `${VAR}` in JSON | Shell environment |
| Call logging | `sessions/tool-calls.log` | `sessions/tool-calls.log` |

> **Note**: Both scopes are logged. `sessions/tool-calls.log` records every tool call automatically via the PostToolUse hook in `settings.json`. This file is auto-saved with your session work.

If already installed at user scope: **skip A1 and A2** — verify in A3 and jump to Step 2. Record as `scope: user` in the registry (Step A4).

**Step A1 — Confirm credentials (project-scope only)**

Identify the required API key or token. Ask the user if they have it.
If not, direct them to the integration's developer portal to generate one.

Once they have it:
1. Ask them to add it to `local-workspace/.env`:
   ```
   STRIPE_API_KEY=sk_test_...
   ```
2. Add the variable name (no value) to `local-workspace/.env.example` under
   the integration's heading so the catalog stays accurate.

**Step A2 — Install the server**

**Project-scope**: Add to `.mcp.json` (copy `.mcp.json.example` if it doesn't exist yet):

```json
{
  "mcpServers": {
    "existing-gateway": { "url": "..." },
    "<integration>": {
      "command": "npx",
      "args": ["-y", "@<vendor>/mcp", "--tools=all"],
      "env": { "<API_KEY_VAR>": "${<API_KEY_VAR>}" }
    }
  }
}
```

**Critical**: Use `${VAR_NAME}` syntax — never paste a credential value directly.
Some MCP server setup guides (Perplexity, Linear, others) show the key inline.
Do not follow that pattern. If the user pastes a config with an inline key, flag it
per the "No Credentials in Config" guardrail and fix it before proceeding.

Restart Claude Code. On first launch with a new project-scoped server, Claude Code
shows a **trust prompt** — approve it or the server silently won't load. If it doesn't
appear after restart, see the Troubleshooting section.

**User-scope**: Run in terminal (credential must already be exported in your shell):

```bash
# For SSE/HTTP servers:
claude mcp add <name> --transport sse <url> --scope user

# For stdio/npx servers:
claude mcp add <name> --scope user -- npx -y @<vendor>/mcp --tools=all
```

Then set the credential in your shell profile (e.g. `~/.zshrc`) so it's available at
launch — `.env` files are not read for user-scope servers:

```bash
export <API_KEY_VAR>=your-key-here
```

> `--tools=all` is appropriate for initial exploration — you don't yet know which tools you'll need. As workflows are codified into gateway tools, the local MCP connection becomes redundant and should be retired (see "After Promotion" below).

**Step A4 — Register in mcp-registry.md**

Add or update an entry in `local-workspace/context/mcp-registry.md`. This is what
admins read to know what the gateway needs to support — it must be kept current.

```markdown
### <server-name>

- **Package**: `@vendor/mcp-package`
- **Scope**: user | project
- **Install (project scope)**:
  ```json
  "<server-name>": {
    "command": "npx",
    "args": ["-y", "@vendor/mcp-package", "--tools=all"],
    "env": { "VAR_NAME": "${VAR_NAME}" }
  }
  ```
- **Env vars**: `VAR_NAME` — what this key grants access to
- **Skills that use it**: _(fill in after Step 4)_
```

Also add a row to the summary table at the top of the file.

**Step A3 — Verify connection**

Call any tool from the new MCP server to confirm it connects and returns data.
Capture the raw response — you need it for Step 3.

---

### Path B — Raw API (no MCP package)

**Step B1 — Confirm credentials**

Ask the user for the API key and base URL. Then:
1. Ask them to add credentials to `local-workspace/.env`:
   ```
   INTERNAL_API_KEY=...
   INTERNAL_API_BASE_URL=https://api.example.com
   ```
2. Add the variable names (no values) to `local-workspace/.env.example`.
3. Reference them in your tool script via `os.environ` — never hardcode.

**Step B2 — Write a probe call**

Write a minimal Python snippet in `tools/` that authenticates and fetches one
representative record. Run it via terminal to confirm connectivity and capture
a sample response.

---

### Step 2 — Capture a sample response

You need a real response object — a dict with all the fields the integration
returns — before proceeding. If you have not already, make a test call now and
save the raw output.

---

### Step 3 — Generate field definitions

Invoke `@field-enricher` with the integration name and sample response. It will:
- Fetch the vendor's API documentation for accurate definitions
- Write business-meaningful descriptions to `context/integrations/<integration>/schema.md`
- Create `context/fields/<integration>.yaml` for the gateway field registry

If you prefer to write definitions manually, use the template at `remote-gateway/context/fields/_template.yaml`. Every field needs a real `description` — no TODOs before committing.

---

### Step 4 — Create the skill directory

Once the skill directory name is known, go back to `mcp-registry.md` and fill in the
`Skills that use it` field for the integration you just registered.

Create `.claude/skills/<integration>-<what>/` with two files:

**`SKILL.md`** — frontmatter + instructions:
```markdown
---
name: <integration>-<what>
description: >
  One-line description of what this does and when Claude should invoke it.
---

## Business Problem
<what business question this answers>

## When to Trigger
<conditions, keywords, or user intent signals>

## How to Interpret Output
<which fields matter, what thresholds mean>

## Dependencies
- MCP or env vars required: `<VAR_NAME>`
```

**`scripts/<integration>_<what>.py`** — the Python tool:
- Type hints on all functions.
- Comprehensive docstring (becomes the MCP tool description on promotion).
- Credentials via `os.environ` only.
- Read-only by default.
- Transform the output — return only the fields downstream agents need, with business-meaningful keys. The script should replace the raw API in context, not replicate it.

---

### Step 5 — Test and pre-check

Run the script directly:

```bash
python .claude/skills/<integration>-<what>/scripts/<integration>_<what>.py
```

Verify the output matches expectations and the field definitions are complete.

Then invoke `@qa-pre-check` on the skill directory. Fix anything it flags before committing — it's faster than getting a 🛑 from CI after the PR is open.

---

### Step 6 — Commit and push

Stage the skill directory and field definitions, then push to your operator branch:

```bash
BRANCH="operator/$(git config user.name | tr ' ' '-' | tr '[:upper:]' '[:lower:]')"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"

git add local-workspace/.claude/skills/<integration>-<what>/
git add local-workspace/context/fields/<integration>.yaml

git commit -m "feat(integration): onboard <integration> — <what> tool"
git push origin "$BRANCH"
```

The pipeline takes it from here:
1. A PR to main is opened automatically.
2. The QA agent reviews for safety, security, and quality.
3. On merge, the tool is promoted into the remote gateway and field definitions
   are copied to `remote-gateway/context/fields/`.
4. All agents get the new tool on `git pull`.

**Do not tell the user about the git/PR/merge process unless they ask.**
Just confirm that their question was answered and the workflow has been codified.

---

## How to Interpret Field Discovery Output

After writing the field YAML, verify:
- Every field in your sample response has an entry.
- No `description` reads "TODO" — fill them all before committing.
- `type` is semantically correct, not just the Python type
  (`currency_usd` not `number` for dollar amounts; `timestamp` not `string` for dates).

---

## After Promotion — Retiring the Local Integration

Once the tool has been promoted to the remote gateway (PR merged, gateway redeployed),
the local connection is no longer needed. Retire it:

1. **Project-scope** (entry in `.mcp.json`): remove the entry. The gateway now handles
   the integration — keeping the local entry would cause duplicate tool names.

2. **User-scope** (installed via `claude mcp add --scope user` or desktop app): ask
   the operator to remove the server from their user settings. They can run:
   ```bash
   claude mcp remove <server-name> --scope user
   ```

3. **Update `mcp-registry.md`**: add a note to the entry indicating it has been
   promoted and the local connection retired:
   ```
   - **Status**: promoted — use gateway tool `<tool_name>` instead
   ```

4. **Inform the user:**
   > "[Integration] is now available through the shared gateway. Remove the local
   > connection so you don't get duplicate tool names."

5. **The local `.env` entry can stay** — it does no harm and may be useful for
   direct testing. Do not delete it.

The agent checks for retirement candidates automatically at session start by calling
`list_field_integrations()` on the gateway and comparing against local `.mcp.json`
entries and `mcp-registry.md`.

---

## Troubleshooting — MCP Server Not Appearing After Restart

**Symptom**: You've added a server to `.mcp.json`, restarted Claude Code, but the
server's tools are not available and `/mcp` doesn't show it.

**Root cause**: Claude Code requires explicit trust approval for project-scoped MCP
servers from `.mcp.json`. If the trust prompt was dismissed (or never shown), the
server silently skips loading.

**Fix 1 — Re-trigger the trust prompt** (preferred):
```bash
claude mcp reset-project-choices
```
Then quit and reopen Claude Code in the workspace directory. It will re-prompt you
to approve each server in `.mcp.json`.

**Fix 2 — Add at user scope instead**:
```bash
# For SSE/HTTP servers (like the remote gateway):
claude mcp add <name> --transport sse <url> --scope user

# For stdio servers (like exa, stripe, etc.):
claude mcp add <name> --scope user -- npx -y <package-name>
```
User-scope servers load without a trust prompt. The credential must be in your
shell environment (not just `.env`) when using this path.

**Diagnosis**: `claude mcp list` only shows user-scope servers. If your project-scope
servers are absent from that list, it means they haven't been approved. If you added
them at user scope, they should appear there.

---

## Dependencies

- Write access to the operator's git branch (automatic via Claude Code).
- MCP server package (if MCP path) or API credentials (if raw API path).
- `ANTHROPIC_API_KEY` set on the gateway server (for the auto-promote CI step).
- `OPENAI_API_KEY` set in GitHub Secrets (for the QA agent CI step).
