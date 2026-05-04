# Frontend Inline Documentation Design

**Date:** 2026-05-04  
**Status:** Approved

## Goal

Add persistent inline documentation to `admin_dashboard.html` so users understand what each tab does, what fields mean, how to drill down, and — specifically — what Tool Hints are and how they work. No new UI components; text lives directly in the existing layout.

## Approach

Tiered: simple tabs get a one-sentence section description; complex tabs (Tool Hints, Skills, Org Profile, Ops) get field-level helper text and examples. No tooltips, no collapsed callouts — always visible.

---

## Tab-by-Tab Spec

### Executive

Under the "Tool Health" section title, add:

> Click any column header to sort. High Error Rate flags tools with ≥5% errors over ≥10 calls. Click any row to open the full log drawer for that tool.

Under the "Tool Flow Patterns" chart title, add:

> Each band shows a tool-to-tool transition. Wider bands = more frequent sequences.

### Ops — Users

Under the "Users" section title, add:

> Each operator and agent gets its own API key. Copy the key immediately after creation — it won't be shown again.

### Ops — Permissions

Under the "Permissions" section title, add:

> Enable or disable individual tools for the selected user. Disabling a tool hides it from their `tools/list` and blocks calls at runtime.

### Tools

Under the "Registered Tools" section title, add:

> All tools registered to this gateway, including proxied integrations. Use the Global toggle to disable a tool for every user at once — no restart required.

### Logs

Under the "Raw Tool Logs" section title, add:

> Every tool call logged in real time. Click any row to inspect the full request and response. Use filters to isolate errors or activity from a specific user.

### Tasks

Under the "Tasks" section title, add:

> Tasks are declared by agents at session start via `declare_intent`. Each represents one user goal. Click a task to see every tool call made while working toward it.

### Org Profile

Replace bare placeholder text on form fields with richer examples:
- **ICP** placeholder: `B2B SaaS, 10–200 employees, US-based`
- **Tone** placeholder: `professional, concise`
- **Vocab Rules** placeholder: `Say 'prospect' not 'lead'. Use first name only in emails.`

Add field-level helper text below each label:
- **ICP**: *Ideal Customer Profile. Agents use this to filter and prioritize prospects.*
- **Tone**: *How agents should communicate in outputs and drafted messages.*
- **Vocab Rules**: *Terminology rules applied to all agent output.*

### Skills

Under the "Skills" section title, add:

> Skills are reusable prompt templates agents can invoke via `run_skill`. Use them for recurring workflows like morning briefings or prospect research.

In the skill modal, under the "Prompt Template" label, add:

> Use `{variable}` for runtime inputs. Example: `Research {company} and draft a 3-bullet outreach for {contact_name}.`

(This text already exists as a `<p>` tag — update wording to match the above.)

### Tool Hints (full treatment)

Replace the existing one-liner with a structured explainer block above the hints table:

**Title:** What are Tool Hints?

**Body:**
> When an agent calls a tool through the gateway, the response is automatically wrapped with a `meta` block containing your hint. The agent reads this on every call — like a sticky note attached to each tool response. Use hints to correct misinterpretations, enforce call discipline, and tag data sensitivity, without touching any code.

Add field-level descriptions inside the Add/Edit modal:

- **Interpretation Hint** helper text: *How should the agent read this data?*  
  Placeholder: `score > 80 = high priority. Ignore 'seniority' field — unreliable for VP-level titles.`

- **Usage Rules** helper text: *When and how should this tool be called?*  
  Placeholder: `Always pass company domain when searching by name. Never call more than once per person in a session.`

- **Data Sensitivity** helper text below the select:  
  `public` = can be shared freely · `internal` = do not surface in external-facing outputs · `confidential` = treat like PII; do not log or quote directly

---

## Visual Treatment

All helper text uses the existing `.text-muted` style (`color: var(--text-muted); font-size: 0.82rem`). No new CSS classes required. Field-level helper text sits between the label and the input, rendered as a `<p>` or `<small>` tag.

---

## Out of Scope

- No new tabs or nav changes
- No interactive tooltips or collapsible sections
- No changes to backend or API
