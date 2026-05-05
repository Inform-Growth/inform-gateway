# Adding a custom prompt

The gateway exposes prompts (also known as "slash commands" in clients that support them) two ways:

1. **Static prompts in code** — registered via `@mcp.prompt()` in `core/mcp_server.py`. Built into the gateway image; require a redeploy to change.
2. **SQLite-backed skills** — registered at runtime via the `skill_create` MCP tool or the seeder in `system_skills.json`. Hot-reload; no redeploy.

For most workflow templates, **use a skill, not a static prompt.** Skills are easier to iterate on, scoped per-org, and don't require a redeploy. Static prompts are for things that need to read repo files at render time (e.g. `operator_init` reads `prompts/init.md`) or that should be identical for every org and every operator.

---

## Option A: SQLite-backed skill (recommended for workflows)

A skill is `(name, description, prompt_template)` stored in the gateway's SQLite skills table. Agents discover skills via `skill_list` and execute them via `run_skill(name, variables=...)`, which renders the prompt_template with caller-supplied variables and returns the rendered string.

### Two ways to add one

**At runtime (org-scoped, hot-reload):** call the seeded `skill-creator` system skill — it walks an agent through the design and registration flow:

```
run_skill("skill-creator", {"goal": "send a weekly stand-up reminder", "variables": "team_name"})
```

The agent designs the skill, shows it to the operator for approval, then calls `skill_create(...)`. The new skill is immediately discoverable in `skill_list`.

**At deploy time (default for every org, immutable from the operator surface):** add an entry to `remote-gateway/system_skills.json`:

```json
{
  "skills": [
    {
      "name": "weekly_pipeline_review",
      "description": "Review the pipeline for the week. Inputs: week_of (date string).",
      "prompt_template": "Generate a weekly pipeline review for week_of={week_of}. ..."
    }
  ]
}
```

The seeder in `core/system_skills.py` upserts each entry into SQLite with `is_system=1` on every gateway boot. System skills cannot be edited or deleted via the operator surface (`skill_update` and `skill_delete` refuse to touch `is_system=1` rows).

### Template syntax

Templates render via Python `str.format()`. Wrap each variable name in single curly braces. Any literal curly brace inside the template body that is NOT a placeholder must be doubled in the source — write two opening braces in a row to produce one literal opening brace, and the same for closing braces. If a placeholder is misnamed or escaping is wrong, `run_skill` raises `KeyError` at render time.

---

## Option B: Static prompt in code

For prompts that need to read repo files or that should never differ across orgs.

### Pattern

In `core/mcp_server.py`, add a function decorated with `@mcp.prompt(...)`:

```python
@mcp.prompt(description="Daily ops briefing — pre-canned aggregator")
def daily_briefing() -> str:
    """Return a daily briefing prompt for the operator."""
    return """
# Daily Briefing

Pull the last 24h of telemetry events:
1. Call `get_tool_stats()`
2. Surface anything in `summary.high_error_rate`
3. Cross-reference with the issues backlog (`list_issues`)
4. Write a one-paragraph summary as a note via `write_note`
"""
```

The `description` is shown in clients that surface prompts as slash commands. The function name becomes the command (`/daily_briefing`).

For prompts that read a file:

```python
@mcp.prompt(description="Operator init")
def operator_init() -> str:
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "init.md"
    if not prompt_path.exists():
        return "Error: init.md not found. Contact administrator."
    return prompt_path.read_text()
```

Add the corresponding markdown file to `remote-gateway/prompts/`.

### Where to register

Static prompts live alongside `operator_init`, `qa_agent_instructions`, and `how_to_use_prompts` in `core/mcp_server.py`. Keep them grouped — there shouldn't be many.

---

## Discovery

Both options surface in the same two places:

- **Slash menus** in clients that support MCP prompts (Claude for Work, Claude Desktop newer builds).
- **`list_prompts` and `get_prompt` MCP tools** for clients that don't render slash menus. Agents can list prompts, render one with arguments, and execute the resulting string.

Skills additionally surface in the admin dashboard's Skills tab and via `skill_list` / `run_skill` for the SQLite-backed flow.
