# Conference Contact Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix known issues in the conference-contact skill, validate it end-to-end via live API calls, then deploy it to `remote-gateway/skills/conference-contact/SKILL.md`.

**Architecture:** Update the skill note in the GitHub notes repo with all fixes, run a live test against real APIs (Exa → Apollo conditional → Attio → Gmail), fix any remaining failures, then copy the validated skill into the gateway's skills directory.

**Tech Stack:** Gateway MCP tools — `exa__web_search_exa`, `exa__web_fetch_exa`, `apollo__apollo_people_match`, `attio__search`, `attio__create_record`, `attio__create_note`, `gmail__send_email`. Gateway notes tools — `write_note`, `read_note`.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `notes/conference-contact.md` (notes repo) | Modify via `write_note` | Fixed skill definition used for testing |
| `remote-gateway/skills/conference-contact/SKILL.md` | Create | Final deployed skill for gateway clients |

---

### Task 1: Write the fixed skill to the notes repo

**Files:**
- Modify: `notes/conference-contact.md` via `write_note` tool

- [ ] **Step 1: Call `write_note` with the full corrected skill content**

Use the `write_note` tool with filename `conference-contact.md` and the following content exactly:

```markdown
---
name: conference-contact
description: Use this skill when Jaron has just met someone at a conference or networking event and wants to follow up. Triggers when he provides a person's name, company, and/or notes from a conversation. Runs a full enrichment and outreach workflow: web research via Exa, optional Apollo enrichment if no email provided, contact creation in Attio with dedup check, and a personalized follow-up email via Gmail with a Calendly booking CTA.
---

# Conference Contact Skill

## What This Does

Takes raw notes from a conference conversation and runs a full follow-up workflow:

1. **Research** the person via Exa
2. **Enrich** via Apollo — only if no email was provided by Jaron
3. **Dedup check** in Attio before creating
4. **Create** contact in Attio with enriched data
5. **Attach** event note to the Attio contact
6. **Create** a follow-up note in Attio
7. **Draft** a personalized email
8. **Confirm** with Jaron before sending
9. **Send** via Gmail

---

## Input

Jaron provides:
- Name (required)
- Company (required)
- Email (optional — if provided, skip Apollo entirely)
- LinkedIn URL (optional)
- Notes from conversation (optional)

---

## Step-by-Step Workflow

### Step 1: Research (Exa)

Run up to 2 searches:
- `exa__web_search_exa`: query `"[Full Name] [Company] [role if known]"`
- If LinkedIn URL was provided: `exa__web_fetch_exa` on the URL

Extract: current title, company description, recent news or launches, any public content they've written or been quoted in.

If Exa returns thin results, note it and proceed with whatever is available.

### Step 2: Enrichment (conditional)

**If Jaron provided an email:** skip this step entirely.

**If no email was provided:** call `apollo__apollo_people_match` with name + company.
- Extract: work email, phone (if available), LinkedIn URL, job title confirmation
- If Apollo returns no match: tell Jaron, ask if he has the email. If yes, continue. If no, create the Attio record and follow-up note anyway, then skip the email steps.

### Step 3: Dedup check

Call `attio__search` with `type: "people"` and query set to the contact's full name.

Do NOT use `attio__search_records` — it throws a 400 on people lookups.

- If a matching record is found: surface it to Jaron. Ask whether to update the existing record or skip create. Do not create a duplicate.
- If no match: proceed to Step 4.

### Step 4: Create Attio contact

Call `attio__create_record` with object type `"people"`.

REQUIRED: pass all three name subfields. Passing only `full_name` silently saves with empty name fields.

```json
"name": [{"first_name": "[First]", "last_name": "[Last]", "full_name": "[First Last]"}]
```

Also include: company, email, LinkedIn URL, job title.

### Step 5: Attach event note

Call `attio__create_note` on the newly created record. Body:

```
[Event]: ALL IN Talks West 2026
[Met]: [today's date]
[Notes]: [Jaron's raw conversation notes]
[Research]:
- [key finding from Exa #1]
- [key finding from Exa #2]
- [key finding from Exa #3]
```

### Step 6: Follow-up note

Call `attio__create_note` on the same record. Body:

```
FOLLOW UP — met at ALL IN Talks West 2026. Due: [2 business days from today]
```

### Step 7: Draft email

Write a short email in Jaron's voice:
- Direct, no fluff, grade-6 reading level
- No em dashes
- Short sentences
- Plain prose — no extra line breaks between sentences, single blank line between paragraphs only
- Under 100 words total
- No "I hope this email finds you well" or sign-off fluff beyond Jaron's name

Structure:
- Line 1: reference something specific from the conversation OR a real detail from Exa research. Not generic.
- Line 2-3: one sentence on what Inform Growth does, framed to their context
- CTA: https://calendly.com/jaron-informgrowth/30min
- Sign-off: Jaron

Example:

```
Hey Sarah,

Loved the point you made about RevOps tooling sprawl. That's exactly the problem we solve at Inform Growth.

Worth 20 minutes to compare notes? Grab a time here: https://calendly.com/jaron-informgrowth/30min

Jaron
```

Show the draft to Jaron and ask: "Good to send?"

### Step 8: Send

Only after Jaron confirms. Call `gmail__send_email`:
- **To:** contact email
- **Subject:** `"Follow up from ALL IN Talks West"` — default. Override with Jaron's direction if he specifies a different subject.
- **Body:** the confirmed draft

---

## Error Handling

| Failure | Action |
|---------|--------|
| Exa returns thin results | Note the gap, proceed with Apollo/manual data |
| Apollo returns no match | Ask Jaron for email. If he has one, proceed. If not, create Attio record + note, skip email. |
| Attio dedup finds existing record | Ask Jaron: update existing or skip create? |
| Attio create fails | Surface the error. Do not proceed to email until the record exists. |
| Jaron rejects email draft | Save draft as a note on the Attio contact for later. |

---

## Summary Output

After completing the workflow:

```
Done.

Research:    [Name] — [Title] at [Company]. [1 sentence insight]
Attio:       Contact created + follow-up note set for [date]
Email:       Sent to [email] — Subject: "Follow up from ALL IN Talks West"
```

Flag any failures clearly with what to do next.
```

- [ ] **Step 2: Verify the note saved correctly**

Call `read_note` with filename `conference-contact.md`. Confirm:
- Calendly link appears as `https://calendly.com/jaron-informgrowth/30min`
- Event name appears as `ALL IN Talks West 2026`
- Step 3 uses `attio__search`, not `attio__search_records`
- Step 4 shows all three name subfields (`first_name`, `last_name`, `full_name`)
- Step 2 is conditional on email being absent

- [ ] **Step 3: Commit checkpoint**

Note saved. Move to live testing.

---

### Task 2: Get test contact from Jaron

- [ ] **Step 1: Ask Jaron for test contact details**

Ask: "Ready to test. Give me the person's name, company, and anything else you have (email, LinkedIn, notes). I'll run the full flow."

Wait for input before proceeding to Task 3.

---

### Task 3: Live test — Research (Exa)

**Files:** No file changes. This is a live API validation step.

- [ ] **Step 1: Run Exa web search**

Call `exa__web_search_exa` with query: `"[Full Name] [Company]"`.

Pass criteria:
- Tool returns without error
- Results contain name, company, or role references
- At least one usable signal (title, company description, news item, or public content)

Fail criteria: 5xx error or completely empty results.

- [ ] **Step 2: Fetch LinkedIn if URL provided**

If Jaron gave a LinkedIn URL, call `exa__web_fetch_exa` with that URL.

Pass criteria: profile page content returned with title and company visible.

- [ ] **Step 3: Extract research summary**

Write down:
- Confirmed title
- Company description (1-2 sentences)
- Any recent news or notable content

This feeds into the Attio note and email draft later.

---

### Task 4: Live test — Apollo enrichment (conditional)

- [ ] **Step 1: Check if email was provided**

If Jaron gave an email → skip this task entirely. Note: "Email provided, skipping Apollo."

If no email → proceed.

- [ ] **Step 2: Call `apollo__apollo_people_match`**

Parameters: `name: "[Full Name]"`, `organization_name: "[Company]"`.

Pass criteria:
- Returns a record with `email` field populated
- Title matches what Exa found (or is a reasonable variation)

Fail criteria: no match returned.

- [ ] **Step 3: Handle no-match**

If Apollo returns no match: tell Jaron. Ask for email. If Jaron provides one, proceed to Task 5 using that email. If not, note "email unavailable — will skip send step."

---

### Task 5: Live test — Attio dedup check

- [ ] **Step 1: Call `attio__search`**

Parameters: `type: "people"`, `query: "[Full Name]"`.

Pass criteria:
- Tool returns without error (especially without a 400)
- Returns either empty results or a list of matching records

Fail criteria: 400 or 5xx error.

- [ ] **Step 2: Handle dedup result**

If a matching record is found: show it to Jaron. Ask: "This person already exists in Attio. Update the record, or skip create?" Follow Jaron's direction.

If no match: proceed to Task 6.

---

### Task 6: Live test — Create Attio contact

- [ ] **Step 1: Call `attio__create_record`**

Object type: `"people"`. Include:

```json
{
  "name": [{"first_name": "[First]", "last_name": "[Last]", "full_name": "[First Last]"}],
  "email_addresses": [{"email_address": "[email]"}],
  "job_title": "[title from research]"
}
```

Pass criteria:
- Tool returns a record ID
- No error response

Fail criteria: error response, or missing record ID in response.

- [ ] **Step 2: Verify name fields are not blank**

From the create response, confirm:
- `first_name` is not empty
- `last_name` is not empty
- `full_name` is not empty

If any name field is blank: this is the known bug. The fix is already in the skill (all three subfields required). Surface to Jaron and check whether the payload was sent correctly.

- [ ] **Step 3: Store the record ID**

Note the `record_id` from the response. Needed for the two `create_note` calls in Tasks 7 and 8.

---

### Task 7: Live test — Event note

- [ ] **Step 1: Call `attio__create_note` (event note)**

Attach to the record ID from Task 6. Body:

```
[Event]: ALL IN Talks West 2026
[Met]: [today's date]
[Notes]: [Jaron's conversation notes, or "none provided" if absent]
[Research]:
- [Exa finding 1]
- [Exa finding 2]
- [Exa finding 3]
```

Pass criteria: note visible on the Attio contact. No error.

---

### Task 8: Live test — Follow-up note

- [ ] **Step 1: Call `attio__create_note` (follow-up note)**

Same record ID. Body:

```
FOLLOW UP — met at ALL IN Talks West 2026. Due: [date 2 business days from today]
```

Pass criteria: second note visible on the Attio contact. No error.

---

### Task 9: Live test — Email draft and send

- [ ] **Step 1: Write the email draft**

Use the research from Task 3 to write a specific opening line. Apply the voice rules:
- Under 100 words
- No em dashes
- Short sentences
- Plain prose, no extra line breaks between sentences
- Single blank line between paragraphs only
- Specific opening (not "great to meet you")
- CTA: https://calendly.com/jaron-informgrowth/30min
- Sign-off: Jaron

- [ ] **Step 2: Show draft to Jaron**

Display the draft. Ask: "Good to send?"

Wait for confirmation. Do not send until Jaron explicitly approves.

- [ ] **Step 3: Send via Gmail on approval**

Call `gmail__send_email`:
- To: contact email
- Subject: `"Follow up from ALL IN Talks West"` (or Jaron's override if given)
- Body: approved draft

- [ ] **Step 4: Verify delivery**

Confirm tool returns success. Note: "Sent to [email] — Subject: [subject]."

Test destination for this test run: jar.sand.on@gmail.com (override the real contact email for testing — confirm with Jaron before sending).

---

### Task 10: Fix any failures from testing

- [ ] **Step 1: Document what broke**

For each step that failed in Tasks 3-9, note:
- Which tool failed
- The exact error
- What the fix is

- [ ] **Step 2: Update the note if skill content needs changing**

If any workflow instructions were wrong (wrong tool name, wrong parameters, missing step), update `conference-contact.md` via `write_note` with corrected content.

- [ ] **Step 3: Re-run the failing step**

Re-run only the step that failed with the fix applied. Confirm it passes before moving to Task 11.

---

### Task 11: Deploy skill to gateway

**Files:**
- Create: `remote-gateway/skills/conference-contact/SKILL.md`

- [ ] **Step 1: Read the validated note**

Call `read_note` with filename `conference-contact.md`. Copy the full content.

- [ ] **Step 2: Write to gateway skills directory**

Create `remote-gateway/skills/conference-contact/SKILL.md` with the content from the note.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/skills/conference-contact/SKILL.md
git commit -m "feat: add conference-contact skill to gateway"
```

- [ ] **Step 4: Verify skill is discoverable**

Confirm the file exists at `remote-gateway/skills/conference-contact/SKILL.md` and the frontmatter `name` and `description` fields are correct.

---

## Self-Review

**Spec coverage:**
- [x] All 7 fixes from the spec are in Task 1 skill content
- [x] Apollo conditional logic (Task 4)
- [x] Attio dedup check (Task 5)
- [x] All three name subfields required (Task 6)
- [x] `attio__search` not `attio__search_records` (Task 5)
- [x] Follow-up note replaces missing task tool (Task 8)
- [x] Email format — plain prose, no extra line breaks (Task 9)
- [x] Subject line default + override (Task 9)
- [x] Deploy to `remote-gateway/skills/conference-contact/SKILL.md` (Task 11)
- [x] Test email: jar.sand.on@gmail.com (Task 9, Step 4)

**No placeholders:** All steps have concrete tool names, parameters, and pass/fail criteria.

**Type consistency:** `attio__search`, `attio__create_record`, `attio__create_note`, `gmail__send_email`, `write_note`, `read_note` used consistently throughout.
