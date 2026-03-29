---
name: process-capture
description: >
  Capture a multi-step business process and turn it into a set of buildable skills.
  Use when a user describes a workflow involving multiple tools or systems — whether
  spoken in conversation or provided as a document, runbook, or SOP. Identifies the
  integrations involved, sets up any that are missing, decomposes the process into
  discrete skill units, and queues them for building via /skill-creator.
  Trigger when someone says "here's my process", "I want to automate X end-to-end",
  "here's how we do Y", "help me build out this workflow", or pastes a multi-step
  workflow description or doc.
---

# Process Capture

Orchestration skill for turning a business process into a set of buildable skills.

This skill does not build anything itself. It interviews the user, maps the process,
discovers the integrations needed, connects any that are missing, decomposes the
process into discrete units, and hands each one off to `/skill-creator` to build,
test, and refine.

---

## Step 1 — Capture the Process

Accept input in either form:

**Conversational** — user describes the process in chat.
Walk through it with them:
> "Walk me through it step by step. What kicks it off? What happens at each stage?
> What does the finished result look like?"

**Artifact** — user shares a document, runbook, SOP, or pasted text.
Read it fully before responding. Extract the steps yourself, then confirm:
> "I've read through this. Here's how I understand your process: [summary with
> numbered steps]. Does that capture it, or did I miss anything?"

**After the initial capture, fill in gaps with targeted questions.** Don't ask all
of these at once — work through them conversationally, 1–2 at a time:

- What triggers this process? (manual, scheduled, an event like "new deal created"?)
- What does "done" look like? What's the final deliverable or end state?
- For any ambiguous step: what are the inputs? What comes out? Is there human
  judgment in the middle?
- Are there branch points? (e.g., "if score > 80, add to priority list; otherwise,
  drop into nurture sequence")
- What data moves between steps, and in what form?

Keep going until you have a clear, complete map of the process before moving to Step 2.

---

## Step 2 — Integration Inventory

Extract every system mentioned (tools, platforms, APIs, databases, SaaS products).

Check what's already connected:
- Read `local-workspace/.mcp.json` — project-scope MCPs
- Read `local-workspace/context/mcp-registry.md` — full registry including user-scope
- Call `list_field_integrations()` on the gateway (if available) — promoted tools

Build a status table and present it:

| System | Status |
|--------|--------|
| Apollo | not connected |
| HubSpot | connected (user scope) |
| Clearbit | not connected |
| Dialer (e.g., Aircall) | not connected |

> "Here are the systems your process touches. Before we build the skills, we'll need
> to connect the ones that aren't set up yet. Does this list look right? Anything
> I missed?"

---

## Step 3 — Set Up Missing Integrations

For each system listed as "not connected":
1. Ask if the user wants to connect it now.
2. If yes: delegate to `@integration-onboarding` for that system. Wait for it to
   finish before moving to the next — credential setup requires back-and-forth.
3. If no (or not yet): note it in the plan as an open dependency. The skills that
   require it will be built but can't run until it's connected.

Work through systems one at a time. Don't batch them.

---

## Step 4 — Decompose into Skills

Break the process into discrete, promotable units. A good skill unit:
- Does one thing well
- Has clear inputs and outputs
- Is reusable outside this specific process
- Maps to a single integration or transformation step

**Example — "Apollo → HubSpot → enrich → research → dial → one-pager":**

| Skill | What it does |
|-------|-------------|
| `apollo-lead-search` | Query Apollo for leads matching criteria, return structured list |
| `hubspot-contact-upsert` | Create or update contacts in HubSpot from a lead list |
| `lead-enrichment` | Call enrichment API to add company size, funding, tech stack |
| `lead-phone-lookup` | Find direct-dial numbers for a list of contacts |
| `lead-list-compile` | Assemble a prioritized dial list with all enriched data |
| `one-pager-generator` | Produce a custom one-pager document for a given contact |

Present the decomposition and get confirmation:
> "Here's how I'd break this down into skills: [table]. Does this feel right?
> Anything you'd split, combine, or rename?"

Revise based on their feedback before moving on. The user knows their process better
than you do — if they push back on a split, take it seriously.

---

## Step 5 — Build Queue

Once the decomposition is confirmed, help the user sequence and start building.

**Recommend a build order.** Start with foundational data-fetch skills (the ones
other skills depend on) before orchestration or output-generation skills. For the
example above: `apollo-lead-search` before `hubspot-contact-upsert` because the
upsert takes the search output as input.

Suggest the first skill to build:
> "I'd start with `apollo-lead-search` since most of the other steps depend on it.
> Want to kick that off now?"

For each skill the user is ready to build: invoke `/skill-creator`. Work through
them one at a time — `/skill-creator` runs its full build, test, and eval loop
before you come back here for the next one.

---

## After Each Skill Is Built

Update `context/operator-profile.md`:
- Add or confirm the integration in the integrations table
- Add the new skill to the "Active Workflows" section

This keeps the profile current for future sessions and gives the next operator (or
future-you) a clear picture of what's been built.

---

## Dependencies

- `@integration-onboarding` — Step 3, for any system that isn't yet connected
- `/skill-creator` — Step 5, for building and testing each skill unit
- `context/operator-profile.md` — updated throughout as integrations and skills land
