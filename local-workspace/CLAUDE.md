# Local Workspace

This is the employee R&D sandbox. Local AI agents operate here to experiment with MCP-connected data sources and codify successful workflows.

## Directory Layout

- **`tools/`** — Python scripts that perform data extraction, transformation, or analysis. Each file should be a self-contained module with a clearly defined `main()` or primary function.
- **`skills/`** — Markdown SOPs (Standard Operating Procedures) that teach agents when and how to use the corresponding tool. Named to match their tool (e.g., `tools/stripe_churn.py` pairs with `skills/evaluate_churn.md`).
- **`context/`** — Static reference material: brand guidelines, templates, glossaries, personas. Agents read these for domain knowledge.
- **`sessions/`** — Running, per-session notes capturing what the user is doing, their goals, key decisions, and which tools/skills are used.

## Session Notes

Session notes live in `sessions/` and are Markdown files maintained over the course of a working session.

- **Naming convention**: `YYYY-MM-DD-<short-topic>.md` (for example, `2026-03-12-churn-exploration.md`).
- **Audience**: Future agents and the centralized gateway, so they can semantically analyze how operations workflows are actually used.

Each session file should, at minimum, contain:

1. **Header** with date, participants (if known), and high-level goal.
2. **Running log** of major steps taken, including tools/skills invoked and any blockers or surprises.
3. **Outcomes** summarizing what was achieved in the session.
4. **Next steps / follow-ups** that future sessions or admins should consider.

These files are expected to be committed alongside tools and skills. The remote gateway can later ingest them for semantic usage analysis and to inform better configuration and tooling.

## Tool File Standards

Every Python tool in `tools/` must follow this structure:

```python
"""
<One-line summary of what this tool does.>

Business Context:
    <Why this tool exists — what business problem it solves.>

Usage:
    <How to invoke this tool, expected inputs/outputs.>
"""

def primary_function(param: str) -> dict:
    """Detailed docstring with args, returns, and raises."""
    ...

if __name__ == "__main__":
    primary_function()
```

Requirements:
- Type hints on all function signatures.
- Comprehensive docstrings (these become MCP tool descriptions upon migration).
- No hardcoded credentials — use `os.environ` for secrets.
- Default to read-only operations. No mutating calls (POST, DELETE, INSERT, DROP) without explicit approval.

## Skill File Standards

Every Markdown skill in `skills/` must include:

1. **Business Problem** — What question or workflow this addresses.
2. **When to Trigger** — The conditions under which an agent should invoke the paired tool.
3. **How to Interpret Output** — Guidance on reading and presenting results to users.
4. **Dependencies** — Which MCP tools or data sources are required.

### Bootstrap Skills

This workspace ships with a small set of **default skills** to help you standardize workflows and build new capabilities:

- **`skills/skill-creator/`** — The official Skill Creator skill from Anthropic’s skills library ([reference](https://github.com/anthropics/skills/tree/main/skills/skill-creator)). Use it to draft, test, benchmark, and iteratively refine other skills, including your own local SKILLs.

Local agents should prefer using this bootstrap skill whenever:

- A new recurring workflow appears that should be encoded as a skill.
- An existing skill needs evals, benchmarks, or trigger-description tuning.

## MCP Configuration

Local MCP servers are configured in `.mcp.json`. This file ships with a preconfigured connection to the **Remote Gateway** (`revops-gateway`), plus space for employee-added local servers (Stripe, Snowflake, CRM, etc.).

### Remote Gateway (Centralized Tools)

The `revops-gateway` entry in `.mcp.json` connects to the team's shared MCP server. Tool discovery is automatic — the MCP protocol's `tools/list` call returns every `@mcp.tool()` registered on the gateway. When the admin promotes a new tool, all connected agents see it on their next session without any local config changes.

Replace `<GATEWAY_URL>` in `.mcp.json` with the actual deployment URL provided by your admin.

### Skills as Context Layer

While the gateway advertises *what* tools exist, the Markdown skills in `skills/` teach agents *when* and *why* to use them. After `git pull`, new skill files appear and the agent gains business context for newly promoted gateway tools. Always check `skills/` for guidance before calling a gateway tool — a skill may specify preferred parameters, output interpretation, or sequencing with other tools.

### Local MCP Servers (R&D)

Employees can add raw MCP connections for experimentation. These are personal and not shared. Add entries to `mcpServers` in `.mcp.json`:

```json
{
  "mcpServers": {
    "revops-gateway": { "url": "<GATEWAY_URL>/sse" },
    "stripe": { "command": "npx", "args": ["-y", "@stripe/mcp", "--tools=all"] }
  }
}
```
