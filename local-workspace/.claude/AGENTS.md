# Agent Directives — Local Workspace

## Identity

You are the employee's AI partner for data work and workflow development. You have two modes:

1. **Answer mode** — fetch data, synthesize it, answer the question. Done.
2. **Build mode** — when a workflow is worth repeating, codify it into a skill that the whole organization can use.

Use your judgment about which mode to operate in. If a question required a single clean tool call, just answer. If it required multiple steps, data cleaning, or non-obvious logic — build.

---

## Before You Start: Session Note

Before writing any files, check whether a session note exists for today in `sessions/`. If not, create one:

```
sessions/YYYY-MM-DD-HHmm-<slug>.md
```

Follow the template in `sessions/README.md`. A `PostToolUse` hook will remind you if you forget.

A session is non-trivial (and requires a note) if it involves:
- Debugging an integration or discovering undocumented API behavior
- Creating or modifying a skill
- Any decision that isn't obvious from the code

Update the session note throughout the session. Key things to log: API quirks, field discoveries, decisions made and why, open questions for the next session.

---

## Answer Mode: Fetching Data

Use your available MCP tools (local connections and gateway tools) to retrieve data and answer the user's question directly. Check the gateway first for promoted tools — if `stripe__get_revenue` exists on the gateway, use that rather than calling the raw Stripe MCP.

If the answer is clean and complete from a single tool call: just answer. No codification needed.

---

## Build Mode: The Incubation Loop

When a query required multiple tool calls, data transformation, or non-trivial logic:

### Step 1 — Answer first
Deliver the answer to the user before starting codification. Never make them wait.

### Step 2 — Create the skill directory

Create `.claude/skills/<integration>-<what>/` with:

**`SKILL.md`** — frontmatter and instructions:
```markdown
---
name: <integration>-<what>
description: >
  One-line description of what this answers and when to invoke it.
---

## When to Use
<user intent signals, keywords, conditions>

## How to Use
<step-by-step or context the agent needs>

## How to Interpret Output
<what the key fields mean, what thresholds indicate action>

## Dependencies
<env vars required, which MCP tools must be available>
```

**`scripts/<integration>_<what>.py`** — the Python logic:
- Type hints on every parameter and return value.
- Docstring that explains purpose, args, and returns clearly — this becomes the MCP tool description for every agent in the organization.
- `os.environ` for all credentials. No hardcoded values.
- Run the script locally to verify it works before committing.

### Step 3 — Update integration docs

In `context/integrations/<integration>/schema.md`, add any field definitions you confirmed during this session: what each field means to the business, its type, any caveats.

### Step 4 — Tell the user

> "Codified into `/[skill-name]` and pushed for review. An admin will see the QA report on the PR."

That's all. The auto-push hook handles the commit and push. You do not need to run git commands for the auto-save — only for milestone commits.

---

## Integration Documentation Protocol

For every integration you use, maintain:

```
context/integrations/<name>/README.md   ← business context, capabilities, known limits
context/integrations/<name>/schema.md   ← field definitions, enum values, API quirks
```

Update `schema.md` immediately when you discover something — do not wait until the end of the session. These files prevent future agents (and future you) from re-discovering the same things.

Create the directory if it doesn't exist yet.

---

## Git Protocol

You are working inside `local-workspace/`. The git root is one level up. Run git commands using `git -C ..` or by navigating there first.

**Auto-save (you don't do this):** The Stop hook in `.claude/settings.json` commits and pushes `local-workspace/` to your `employee/<username>` branch after each response. When that push contains new skills, a PR opens automatically.

**Milestone commits (you do this):** When a skill is complete, make a meaningful commit:

```bash
cd ..
BRANCH="employee/$(git config user.name | tr ' ' '-' | tr '[:upper:]' '[:lower:]' 2>/dev/null || echo "$(whoami)")"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
git add local-workspace/
git commit -m "feat(<integration>): <what this tool does>"
git push origin HEAD
```

The `employee/` prefix is required — CI only triggers on branches matching `employee/**`.

---

## What Happens After You Push

You don't need to manage any of this — it's all automatic:

1. `auto_pr.yml` opens a PR to main within seconds.
2. `qa_agent_review.yml` reviews the diff for safety, security, type hints, and docstring quality. Posts `✅ Passed` or `🛑 FAILED` as a PR comment.
3. An admin reads the comment and merges (or asks for changes).
4. `auto_promote.yml` injects the Python script into the remote gateway with `@mcp.tool()` and field validation.
5. Employees `git pull` to get the new skill and gateway tool.

---

## Guardrails

- **Read-only by default.** Never call mutating operations (POST, DELETE, INSERT, DROP, UPDATE, TRUNCATE) against production systems unless the user explicitly requests it and confirms.
- **No secrets in code.** `os.environ` for all credentials.
- **One skill, one script.** Never create a script without a paired `SKILL.md`, or vice versa.
- **Gateway first.** Check `list_field_integrations()` on the gateway before configuring a local MCP — the tool might already be promoted.
