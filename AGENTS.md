# AGENTS.md

Wayfinding for agents working with this gateway. Two distinct audiences:

1. **Operators** — agents *calling* the gateway via MCP to do work for an end user.
2. **Extenders** — agents *modifying* the gateway: adding a new integration, a new Python tool, a new prompt, a new system skill.

If you don't know which one you are, you're an operator. Skip to the operator section.

---

## For operators (calling the gateway)

You connect via MCP with a Bearer token. Your job is to help the user accomplish their goal using the tools the gateway exposes.

### Initialize every session

Call `operator_init` (or run the `/operator_init` slash command) at the start. It loads the Gateway Operator persona, which activates the Shadow Note-taking and Issue Logging mandates.

### Mandates

- **Shadow notes.** After every significant task, call `write_note` to record the user's goal, the outcome, and whether the gateway served them well. Notes persist to a GitHub repo across sessions and redeploys.
- **Issue logging.** When you hit auth failures, 4xx/5xx errors, or "noisy/raw" data the user has to clean up themselves, call `write_issue`. Surfaces tech debt to gateway admins.
- **Task gate.** Most tools require a task_id. Call `declare_intent` before doing work; pass the returned `task_id` on subsequent tool calls; call `complete_task` when done. If you lose the task_id mid-session, call `get_tasks` to recover it.

### Discovery

- `list_prompts` / `get_prompt` — discover and render registered prompt templates.
- `skill_list` / `run_skill` — discover and execute SQLite-backed reusable workflows. Skills are prompt templates; `run_skill` returns the rendered prompt for you to act on.
- `get_tool_stats` — see what's been called recently and which tools are erroring.
- `health_check` — verify the gateway is up.

### When the operator wants a new repeatable workflow

Don't write code or files. Use the seeded `skill-creator` system skill:

```
run_skill("skill-creator", {"goal": "<one-sentence description>", "variables": "<comma-separated placeholder names>"})
```

`skill-creator` walks you through designing the skill, gets the operator's approval, then calls `skill_create` to persist it. The new skill is immediately discoverable via `skill_list` — hot-reload, no redeploy.

If the workflow needs *new tools* (not just a new prompt template), that's an extender task — see below.

---

## For extenders (modifying the gateway)

Code/connector changes ship via PRs to this repo. Pick the recipe that matches what you need:

### Add an integration (proxy a third-party MCP server)

Per-transport recipes:

- **stdio** (local Node/Python CLI MCP server, e.g. HubSpot, GitHub): [remote-gateway/docs/integrations/stdio.md](remote-gateway/docs/integrations/stdio.md)
- **SSE pass-through** (older long-lived remote MCPs): [remote-gateway/docs/integrations/sse-passthrough.md](remote-gateway/docs/integrations/sse-passthrough.md)
- **Streamable-HTTP** (modern remote MCPs): [remote-gateway/docs/integrations/streamable-http.md](remote-gateway/docs/integrations/streamable-http.md)

`remote-gateway/mcp_connections.example.json` has one entry per transport — copy the relevant block into `mcp_connections.json` and fill in env vars.

### Add a Python tool

When no upstream MCP exists, write a Python tool: [remote-gateway/docs/custom-tools.md](remote-gateway/docs/custom-tools.md).

Pattern: module under `remote-gateway/tools/`, `register(mcp)` function, wired from `core/mcp_server.py`. Telemetry, gates, and task-id wrapping are auto-applied — don't reimplement them.

### Add a prompt or skill

Two paths, [remote-gateway/docs/custom-prompts.md](remote-gateway/docs/custom-prompts.md) covers both:

- **Static prompt** (`@mcp.prompt()` in `core/mcp_server.py`) — for prompts that need to read repo files, or that should be identical for every org. Requires a redeploy.
- **System skill** (entry in `remote-gateway/system_skills.json`) — for default-for-every-org workflow templates. Seeder upserts on every boot with `is_system=1`. Cannot be edited or deleted from the operator surface.
- **Org-scoped skill** (operator calls `skill_create` at runtime) — for workflows specific to one operator's org. Hot-reload, no redeploy.

For most workflow templates, prefer skills over static prompts.

### Skill creation surfaces

Two equivalent paths:

- **`skill_create` MCP tool** — `tools/_core/skill_manager.py`. What operators and the `skill-creator` skill use.
- **`POST /admin/api/skills`** — `core/admin_api.py`. What automation outside MCP uses.

Both write to the same SQLite `skills` table.

---

## House style

- **Read-only by default.** Tools that mutate external state (create a CRM record, send a message) need a docstring callout and an explicit per-user write permission via `tool_permissions`. The admin dashboard's Users tab gates writes.
- **No hardcoded credentials.** Use `os.environ`. `mcp_connections.json` references env vars via `${VAR_NAME}`.
- **Field registry.** Wrap structured tool responses with `validated("integration", result)` if a YAML schema exists in `remote-gateway/context/fields/`. Drift surfaces automatically when vendors change schemas.
- **Tests.** Mirror the patterns in `remote-gateway/tests/`. Mock external HTTP — never hit real APIs in CI.
- **Ruff target is `py314`** — match the existing style. `ruff check .` runs in CI.

---

## Hand-off rule

If you find yourself wanting to write a SKILL.md file, modify the repo's tool source, or add a connector while operating in the operator role: stop. Either:

- Use `skill-creator` to register the workflow as a runtime skill (no code change), or
- Open a PR to this repo with the change, framed as an extender task using the recipes above.

The operator surface and the extender surface don't blend. Skills are the bridge — they're the only way operators meaningfully extend behavior at runtime.
