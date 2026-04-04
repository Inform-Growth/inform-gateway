---
date: 2026-04-04
slug: revops-prospecting-enrichment
status: complete
---

# Session: revops-prospecting-enrichment

**Date:** 2026-04-04
**Integration(s):** apollo, attio
**Goal:** Enrich 5 RevOps AI infra prospect companies, find decision-maker contacts, upload to Attio, and create call tasks with research notes.

---

## What We Did

### 1. Apollo — Org Enrichment (5 companies)
Called `apollo_organizations_enrich` on all 5 domains in parallel:
- **kubelt.com** → returned `{}` — domain not indexed in Apollo. No data available.
- **ivo.ai** → full enrichment: 80 employees, $83.2M total funding ($55M Series B Jan 2026), stack includes Salesforce, HubSpot, LeanData, Snowflake, Looker, dbt, Claude, OpenAI
- **hippocraticai.com** → full enrichment: 280 employees, $438M raised (Series C Nov 2025), $15.8M ARR, Salesforce Health Cloud, Gong, Snowflake, dbt
- **quorum.us** → full enrichment: 440 employees, $61.1M ARR, PE-backed (Serent Capital), LangChain + LlamaIndex in production tech stack
- **jupus.de** → full enrichment: 62 employees, €7.8M seed, HubSpot, Salesforce CRM Analytics

### 2. Apollo — People Search (title-filtered per company)
Called `apollo_mixed_people_api_search` with `q_organization_domains` + `person_titles` filters.

**Results:**
- Kubelt: 0 results (domain not indexed)
- Ivo: 3 contacts — Kostja M. (VP Revenue Strategy & Ops), Arie Jongejan (VP Sales), Phil Z. (Director RevOps)
- Hippocratic AI: 1 contact — Arvind Saran (VP International Sales). No dedicated RevOps leader found.
- Quorum: 6 candidates returned on broader search; narrowed to Edtience Tenbrook (Sr. Director Sales Ops). Ivan Luganskiy (Head of Sales) was a **false match** — that record belongs to a different "Quorum LLC" entity based in Moscow, Russia. Apollo matched on company name, not domain.
- JUPUS: 1 contact — Daniel Kaschta (Head of Sales)

### 3. Apollo — People Match/Enrichment
Called `apollo_people_match` with Apollo person IDs to get full names, verified emails, and employment history.

**Contacts confirmed (all email_status: verified):**
| Name | Company | Title | Email |
|---|---|---|---|
| Kostja M. | Ivo | VP Revenue Strategy & Operations | kostja@ivo.ai |
| Arie Jongejan | Ivo | VP of Sales | arie.jongejan@ivo.ai |
| Phil Z. | Ivo | Director of Revenue Operations | philz@ivo.ai |
| Edtience Tenbrook | Quorum | Sr. Director of Sales Operations | edtience@quorum.us |
| Arvind Saran | Hippocratic AI | VP International Sales | arvind@hippocraticai.com |
| Daniel Kaschta | JUPUS | Head of Sales | daniel.kaschta@jupus.de |

### 4. Notes file updated
Appended all enriched org data + contact table + outreach priority ranking to `notes/revops-ai-infra-prospects.md` in the remote-gateway notes repo. Committed via `write_note`.

### 5. Attio — Created list
User created "RevOps AI Infra — Apr 2026" list manually in Attio (API cannot create lists). API slug: `revops_ai_infra_apr_2026`.

### 6. Attio — Upserted 6 people records
All 6 contacts created/upserted in Attio with name, email, and job title.

### 7. Attio — Added all 6 to list
All 6 added to `revops_ai_infra_apr_2026` list.

### 8. Attio — Created call tasks with research
Created one task per contact linked to their person record, containing:
- Research findings (company context, funding, stack, contact background)
- 3 specific opening angles for the call

---

## Discoveries

- **Ivo is the hottest account**: 3 VP-level RevOps/Sales hires all joined between Jan 2025–Jan 2026 post-Series B. Kostja M. (VP RevOps) joined Jan 2026 specifically to build AI-first GTM. His xLinkedIn, xBain background + "AI-first GTM" self-identification makes him the #1 target in the batch.
- **Quorum is more advanced than expected**: They're already running LangChain and LlamaIndex in production alongside their Salesforce + SalesLoft + 6sense stack. They're hiring an "AI GTM Systems Manager" — they're building the AI infra layer right now.
- **Hippocratic AI has no visible RevOps leader in Apollo**: Only Arvind Saran (VP International Sales) surfaced. He's the entry point but the real RevOps buyer is likely unstaffed or not indexed. Worth asking Arvind who owns their GTM ops.
- **Kubelt is dark in Apollo**: Domain not indexed at all. Will need manual LinkedIn outreach to founders.
- **Apollo partially obfuscates last names** in people search results (e.g. "Za***s", "Mi***c"). Full names are resolved via `people_match` using the Apollo person ID.

---

## Decisions

- **Skipped Ivan Luganskiy (Quorum)**: Apollo returned him as "Head of Sales" at Quorum, but enrichment showed he's based in Moscow and linked to "Quorum LLC" — a different entity from quorum.us (Washington DC). False match due to company name collision. Always verify location + domain alignment when enriching Quorum-type names.
- **Skipped `company` field on Attio upsert**: The `company` attribute on `people` is a record-reference to the `companies` object — it requires an Attio company record ID, not a string. Would need to first upsert each company record and capture its ID. Skipped for this session; job title carries the context.
- **List creation is manual**: Attio API does not support creating lists. User must create in UI, then agent can populate.

---

## API Quirks

### Apollo

| Tool | Quirk | Fix |
|---|---|---|
| `apollo_organizations_enrich` | Returns `{}` (empty dict, no error) when domain is not indexed | Check for empty response before processing |
| `apollo_mixed_people_api_search` | Last names are obfuscated (e.g. "Za***s") in search results | Always follow up with `apollo_people_match` using the person ID to get full name + email |
| `apollo_people_match` | Payload: `{"id": "<apollo_person_id>", "reveal_personal_emails": false}` | `reveal_personal_emails: false` avoids extra credit usage; work email is returned by default |
| `apollo_mixed_people_api_search` | Company name collisions: searching `q_organization_domains` doesn't guarantee the returned person actually works at that domain — Apollo can match on company name. | After enrichment, cross-check `city`, `country`, and org `primary_domain` in the match result to confirm you have the right entity |

### Attio

| Tool | Quirk | Fix |
|---|---|---|
| `upsert-record` | Top-level params are `object` and `values` — NOT `object_type` and `attributes` | Use `{"object": "people", "matching_attribute": "...", "values": {...}}` |
| `upsert-record` — `name` field | Requires `full_name` (string) at minimum. `first_name` / `last_name` alone throw "Required: full_name" error | Always include `full_name` alongside `first_name` / `last_name` |
| `upsert-record` — `company` field | Is a `record-reference` type pointing to the `companies` object — cannot be set as a plain string | Must upsert company record first, capture its `record_id`, then reference it |
| `add-record-to-list` | Params are `list` (slug or ID), `parent_object`, `parent_record_id` — NOT `list_id` and `record_id` | Use `{"list": "api_slug", "parent_object": "people", "parent_record_id": "..."}` |
| `create-task` | Linking param is `linked_record_object` — NOT `linked_object` | Use `{"linked_record_object": "people", "linked_record_id": "..."}` |
| `list-lists` | Returns `api_slug` — this can be used directly as the `list` value in `add-record-to-list` instead of the UUID | Prefer slug over ID for readability |

---

## Toward a Skill: `prospect-and-load`

This session laid out a repeatable workflow worth codifying. Rough shape:

```
Input: list of {company_name, domain, why_warm}
Steps:
  1. apollo_organizations_enrich(domain) → org context, stack, funding, headcount
  2. apollo_mixed_people_api_search(domain, target_titles) → candidate people IDs
  3. apollo_people_match(id) → full name, verified email, employment history
  4. Filter false matches (verify org domain alignment)
  5. attio__upsert-record(people) → create/update person record
  6. attio__add-record-to-list → add to campaign list
  7. attio__create-task → call task with research + angles
Output: Attio list populated, tasks created, notes file updated
```

**Known edge cases to handle:**
- Domain not in Apollo → log and skip enrichment, flag for manual outreach
- Company name collision in people search → validate with `primary_domain` check post-match
- `company` field on Attio people → requires separate company upsert pass
- List must pre-exist in Attio → either require as input param or document as prerequisite

---

## Open Questions

- Can we find Kubelt decision-makers via LinkedIn scraping or Exa search?
- Who owns RevOps at Hippocratic AI? Arvind is the entry point but not the buyer.
- Should the skill auto-create the Attio list (not possible via API) or accept list slug as input?
- Should we enrich Ivo's companies object in Attio to enable the `company` record-reference linkage?
