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

**Formatting:** Write each paragraph as a single continuous line of text with no line breaks within it. Only use a double newline (blank line) between paragraphs. Do not insert \n within a sentence or mid-paragraph. The email client handles word-wrapping.

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

Before sending, convert the draft to HTML to prevent Gmail's SMTP line-wrapping:

1. Call `normalize_email_body` with the raw draft body. It returns an HTML string in the `body` field — `<p>` tags per paragraph, no line breaks within paragraphs.
2. Call `gmail__send_email`:
   - **To:** Pass as an array: `["email@example.com"]`, not a plain string.
   - **Subject:** `"Follow up from ALL IN Talks West"` — default. Override with Jaron's direction if he specifies a different subject.
   - **Body:** the HTML string returned from `normalize_email_body` (the `body` field).

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
