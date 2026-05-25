# Conference Contact Skill — Design Spec

**Date:** 2026-04-15
**Status:** Approved

## Goal

Test the `conference-contact` Claude Code skill end-to-end, fix known issues, then deploy it as a skill in `remote-gateway/skills/conference-contact/SKILL.md` so it is available on all gateway clients including mobile.

## Approach

1. Apply fixes to the `conference-contact.md` note in the notes repo
2. Run a live end-to-end test from this repo
3. If passing, copy the validated skill to `remote-gateway/skills/conference-contact/SKILL.md` and commit

## Skill Fixes (applied before testing)

| # | Fix | Detail |
|---|-----|--------|
| 1 | Calendly link | Replace `[CALENDLY_LINK]` with `https://calendly.com/jaron-informgrowth/30min` |
| 2 | Event name | Replace `All Intalks West 2026` with `ALL IN Talks West 2026` |
| 3 | Attio search tool | Replace `attio__search_records` with `attio__search` (type: "people") — old tool throws 400 on people |
| 4 | Attio name fields | Require all three: `first_name`, `last_name`, `full_name` — `full_name` alone silently saves empty |
| 5 | Attio dedup | Add search-before-create step for person record to prevent duplicates |
| 6 | Apollo conditional | Only run Apollo enrichment if email not already provided by Jaron |
| 7 | Attio task tool | No dedicated task tool exposed — replace with `attio__create_note` with a "FOLLOW UP" flag and due date |

## Revised Workflow

```
Input: name (required), company (required), email (optional), LinkedIn URL (optional), notes (optional)

Step 1: Research (Exa)
  - web_search: "[name] [company] [role]"
  - web_fetch: LinkedIn URL if provided
  - Extract: title, company description, news, public content

Step 2: Enrichment (conditional)
  - IF email provided by Jaron → skip Apollo
  - IF no email → run apollo__apollo_people_match → get email, phone, title

Step 3: Dedup check
  - attio__search (type: "people", query: full name)
  - IF exists → surface to Jaron, ask whether to update or skip create
  - IF not exists → proceed to create

Step 4: Create Attio contact
  - attio__create_record (people)
  - Required: first_name, last_name, full_name (all three), company, email, LinkedIn
  - attio__create_note: event context + Exa research summary

Step 5: Follow-up note
  - attio__create_note with body:
    "FOLLOW UP — met at ALL IN Talks West 2026. Due: [2 business days from today]"

Step 6: Draft email
  - Under 100 words, Jaron's voice (direct, no fluff, grade-6 level, no em dashes)
  - Line 1: specific reference from conversation or research
  - Line 2-3: what Inform Growth does, framed to their context
  - CTA: https://calendly.com/jaron-informgrowth/30min
  - Email formatting: plain prose, no extra line breaks between sentences, single blank line between paragraphs only
  - Show draft to Jaron → "Good to send?"

Step 7: Send (only after Jaron confirms)
  - gmail__send_email
  - To: contact email
  - Subject: default "Follow up from ALL IN Talks West" — override with Jaron's direction if provided
```

## Error Handling

| Failure | Action |
|---------|--------|
| Exa returns thin results | Note the gap, proceed with Apollo/manual data |
| Apollo returns no match | Tell Jaron, ask if he has email. If yes proceed, if no skip email |
| Attio dedup finds existing record | Surface to Jaron — update or skip |
| Attio create fails | Surface error, do not proceed to email |
| Jaron rejects email draft | Save draft as note on Attio contact |

## Test Plan

Run against a real person + company so Exa and Apollo return meaningful data. Test email destination: jar.sand.on@gmail.com

| Step | Tool | Pass condition |
|------|------|----------------|
| Research | `exa__web_search_exa` | Returns title, company info |
| Enrich (if no email) | `apollo__apollo_people_match` | Returns work email |
| Dedup | `attio__search` | No 400, returns empty or match |
| Create contact | `attio__create_record` | Record in Attio, name fields not blank |
| Attach note | `attio__create_note` | Note visible on contact |
| Follow-up note | `attio__create_note` | FOLLOW UP note on contact |
| Email draft | — | Draft reviewed and approved by Jaron |
| Send | `gmail__send_email` | Arrives at jar.sand.on@gmail.com |

## Deployment

Once testing passes:
- Write validated skill to `remote-gateway/skills/conference-contact/SKILL.md`
- Commit and push to main
- Skill available via `Skill` tool on all gateway clients (including mobile)
- Lives alongside `mcp-builder/` and `gateway-health-check/` in the skills directory
