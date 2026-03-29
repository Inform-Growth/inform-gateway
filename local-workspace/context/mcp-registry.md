# MCP Registry

Source of truth for every MCP server operators are actively using across the workspace — regardless of whether it is installed at user scope (`~/.claude/settings.json`) or project scope (`.mcp.json`).

Admins read this file to know what the remote gateway needs to support and which env vars to provision on the gateway server.

---

## How to Update

When onboarding a new integration (Path A — MCP Server), add an entry below.
Run `@integration-onboarding` — it will fill this in automatically.

Fields:
- **scope**: `user` (installed via `claude mcp add --scope user`) or `project` (in `.mcp.json`)
- **install**: the command an operator would run to add it at project scope
- **env**: env var names required — no values, names only
- **skills**: skill directories that depend on this server

---

## Active Integrations

<!-- Add entries in alphabetical order -->

| Server | Package | Scope | Env Vars | Skills |
|--------|---------|-------|----------|--------|
| _(none yet)_ | | | | |

---

## Full Entry Format

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
- **Env vars**: `VAR_NAME` — description of what this key grants access to
- **Skills that use it**: `skill-dir-name`
- **Notes**: anything non-obvious about setup or retirement
```
