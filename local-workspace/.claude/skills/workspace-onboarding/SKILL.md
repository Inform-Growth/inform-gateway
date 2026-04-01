---
name: workspace-onboarding
description: >
  First-time setup and re-onboarding for the local workspace. Creates or updates
  context/operator-profile.md with name, branch, integrations, role, and goals.
  Trigger when a new operator is getting started, when no operator profile exists,
  or when the user says "set me up", "get me started", "I'm new here", "update my
  profile", or "onboard me". Also trigger proactively at session start if
  context/operator-profile.md does not exist.
---

# Workspace Onboarding

Interactive setup walkthrough. Collects operator identity, branch, connected
integrations, role, and goals — writes everything to `context/operator-profile.md`
so future sessions start with context already loaded.

**Rerunnable.** If a profile already exists, frame this as an update. Surface current
values as you go so the operator only needs to correct what's changed.

---

## Before You Start

Check for an existing profile:

```bash
cat local-workspace/context/operator-profile.md 2>/dev/null
```

If found: greet them by name and say you're updating their profile.
Carry their existing values forward — only ask them to confirm or change each one.

If not found: this is their first time. Explain what you're doing before asking anything:

> "Let me get your workspace set up. I'll ask a few questions, create your personal
> branch, and save a profile so future sessions start with context already loaded."

---

## Step 1 — Name and Branch

Ask:
> "What's your name?" (or "Is your name still [name]?" if updating)

From their answer:
1. Derive the branch slug: lowercase, hyphens for spaces
   (e.g., "Jane Smith" → `operator/jane-smith`)
2. Check if the branch exists:
   ```bash
   git -C .. branch --list "operator/<slug>"
   ```
3. If it doesn't exist, create and push it:
   ```bash
   git -C .. checkout -b "operator/<slug>"
   git -C .. push -u origin "operator/<slug>"
   ```
4. Confirm to the operator:
   > "Your branch is `operator/<slug>`. Work pushed from this workspace lands here
   > automatically."

---

## Step 2 — Role and Goals

Ask in a single conversational message:
1. "What's your role or team?"
2. "What are you here to accomplish? Any specific workflows or business questions
   you're starting with?"

A few sentences is enough. You're loading context, not writing a job description.

---

## Step 3 — Integration Inventory

**Gather what's already configured:**
- Read `local-workspace/.mcp.json` for project-scope entries
- Read `local-workspace/context/mcp-registry.md` for the full registry
- Call `list_field_integrations()` on the gateway (if available) to see promoted tools

**Ask about user-scope servers:**
> "Do you have any integrations already installed in your Claude desktop or user
> settings — things like Stripe, HubSpot, Notion, Postgres — that wouldn't show
> up in the project config?"

If yes: note them as `scope: user` in `mcp-registry.md`.

**Build an integration status table:**

| Server | Scope | Status |
|--------|-------|--------|
| stripe | user | connected |
| hubspot | project | connected |
| clearbit | — | not connected |

Present the table and ask:
> "Are there other systems you'll need that we should set up now?"

For any they want to connect: delegate to `@integration-onboarding`, one system at a
time. Return to this step after each one completes.

**Important — MCP trust prompt**: After adding a new project-scoped server to
`.mcp.json`, the operator must restart Claude Code. On first launch, Claude Code will
show a trust prompt for each project-scoped server — it must be approved or the server
silently won't load. If a server is missing after restart, see the Troubleshooting
section in `@integration-onboarding`.

---

## Step 4 — Write the Profile

Write (or overwrite) `local-workspace/context/operator-profile.md`:

```markdown
---
name: <Full Name>
branch: operator/<slug>
updated: <YYYY-MM-DD>
---

## Identity

- **Name**: <Full Name>
- **Branch**: `operator/<slug>`
- **Role**: <role or team>

## Goals

<What they're here to accomplish — their words, lightly edited>

## Integrations

| Server | Scope | Status |
|--------|-------|--------|
| <name> | project / user | connected / gateway |

## Active Workflows

<!-- Filled in as skills are created via /process-capture or /skill-creator -->
- (none yet)

## Notes

<!-- Free-form. Discoveries, decisions, preferences added over time. -->
```

---

## Step 5 — Session Note

Delegate to `@session-scribe` to ensure a session note exists for today.

---

## Step 6 — Closing Summary

> "You're all set. Here's what we've got:
> - **Branch**: `operator/<slug>`
> - **Integrations**: [list connected ones]
> - **Profile**: saved to `context/operator-profile.md`
>
> Ready when you are. If you have a workflow to automate, try `/process-capture`
> to walk through it end-to-end."

---

## On Future Sessions

Load `context/operator-profile.md` at session start if it exists. Use the name,
role, integrations, and goals to contextualize responses without asking again.
