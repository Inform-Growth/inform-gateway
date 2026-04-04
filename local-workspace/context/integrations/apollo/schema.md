# Apollo Integration — Field & Payload Notes

**Source:** Apollo.io API via remote gateway MCP tools
**Last updated:** 2026-04-04

---

## Tool Payload Reference

### `apollo_organizations_enrich`
Enriches a single company by domain.

```json
{ "domain": "example.com" }
```

**Quirks:**
- Returns `{}` (empty dict, no error) when the domain is not indexed in Apollo. Always check `if not result or not result.get("organization")` before processing.
- Credits are consumed per call regardless of whether data is returned.

**Key response fields:**
| Field | Notes |
|---|---|
| `organization.estimated_num_employees` | Headcount estimate — Apollo's own, not LinkedIn |
| `organization.total_funding` | Total funding in USD cents (integer) |
| `organization.latest_funding_stage` | e.g. "Series B", "Seed", "Merger / Acquisition" |
| `organization.latest_funding_round_date` | ISO 8601 timestamp |
| `organization.technology_names` | Flat list of tech stack tool names |
| `organization.current_technologies` | Array of `{uid, name, category}` — more structured than `technology_names` |
| `organization.departmental_head_count` | Headcount by department (sales, engineering, marketing, etc.) |
| `organization.organization_headcount_six_month_growth` | Decimal growth rate, e.g. `0.5` = 50% growth |
| `organization.organization_headcount_twenty_four_month_growth` | Same, 24-month window |
| `organization.short_description` | 2-paragraph company summary |
| `organization.primary_domain` | Canonical domain — use this to verify org identity |

---

### `apollo_mixed_people_api_search`
Finds people by org domain + title filters. Does NOT return emails or full last names.

```json
{
  "q_organization_domains": "example.com",
  "person_titles": ["VP Sales", "Director of Revenue Operations", "CRO"]
}
```

**Quirks:**
- **Last names are obfuscated** in search results: e.g. `"last_name_obfuscated": "Za***s"`. Always follow up with `apollo_people_match` to get the full name and email.
- **Company name collisions**: Apollo can return people from a different org that shares the same company name. A search for `q_organization_domains: "quorum.us"` returned a person linked to "Quorum LLC" (Moscow, Russia). **Always verify `city`, `country`, and org `primary_domain` in the `apollo_people_match` result.**
- Returns `total_entries` and `people[]`. If `total_entries: 0`, the person does not exist in Apollo for that domain/title combo — not necessarily that they don't exist at the company.

**Key response fields per person:**
| Field | Notes |
|---|---|
| `id` | Apollo person ID — use this for `apollo_people_match` |
| `first_name` | Full first name (not obfuscated) |
| `last_name_obfuscated` | Partial last name — must call `people_match` for full |
| `title` | Current job title |
| `has_email` | Boolean — if false, `people_match` may still return an email via extrapolation |
| `has_direct_phone` | "Yes", "Maybe: please request via bulk_match", or absent |
| `last_refreshed_at` | When Apollo last updated this record |

---

### `apollo_people_match`
Resolves a full person record from an Apollo person ID. Returns full name, verified email, employment history.

```json
{
  "id": "<apollo_person_id>",
  "reveal_personal_emails": false
}
```

**Quirks:**
- `reveal_personal_emails: false` keeps credit usage lower. Work email is returned by default when available.
- `email_status: "verified"` means Apollo has confirmed deliverability. Other values: `"likely_valid"`, `"unavailable"`.
- `email_domain_catchall: true` means the domain accepts all email — verified status may be less reliable.
- `employment_history` is an array of past roles with `start_date`, `end_date`, `current: true/false`. Use to infer tenure and how recently someone joined a role.
- Last name may still be a single letter (e.g. `"last_name": "Z"`) if Apollo only has partial data.

**Key response fields:**
| Field | Notes |
|---|---|
| `email` | Work email address |
| `email_status` | "verified", "likely_valid", "unavailable" |
| `email_domain_catchall` | If true, treat email as less reliable even if "verified" |
| `employment_history[]` | Full career history with dates and org IDs |
| `headline` | LinkedIn headline — useful for understanding self-positioning |
| `seniority` | "vp", "director", "head", "manager", etc. |
| `departments` | Top-level dept buckets: "master_sales", "master_operations", etc. |
| `subdepartments` | More specific: "revenue_operations", "sales_operations", etc. |
| `organization.primary_domain` | Use to confirm you have the right org (vs. name collision) |

---

## Workflow Pattern: Prospect Enrichment

```
1. apollo_organizations_enrich(domain)
   → Check result is not empty
   → Extract: headcount, funding, stack, growth rate

2. apollo_mixed_people_api_search(domain, titles)
   → Collect person IDs
   → Note: last names are obfuscated at this stage

3. apollo_people_match(id) for each person
   → Verify org primary_domain matches target domain (guards against name collisions)
   → Extract: full name, email, email_status, employment history

4. Filter: skip if email_status == "unavailable", or if org domain doesn't match
```

---

## Credit Usage Notes
- `apollo_organizations_enrich`: consumes credits per call
- `apollo_people_match`: consumes credits per call
- `apollo_mixed_people_api_search`: does NOT consume enrichment credits (prospecting only)
- `reveal_personal_emails: false` avoids personal email credit charge on `people_match`
