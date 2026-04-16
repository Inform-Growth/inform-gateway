# Attio Companies Field Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `attio-companies.yaml` with `writable`, `required_for_create`, and `write_format` on every field — the same pattern established for `attio-people.yaml` — so pre-flight validation in `attio__create_record` covers the companies object type.

**Architecture:** Pure data change. The pre-flight validation in `remote-gateway/tools/attio.py` already handles companies: it calls `registry.get_all("attio-companies")` and uses `v.get("writable", True)` as a fallback. Currently all 32 company fields lack the `writable` key, so the fallback treats every field (including `record_id`, `created_at`, etc.) as writable. This plan adds explicit `writable: false` to the 17 read-only fields, closing that gap without any code changes.

**Tech Stack:** YAML, Python (spot-check only)

---

## File Map

| File | Action | What changes |
|---|---|---|
| `remote-gateway/context/fields/attio-companies.yaml` | Modify | Add `writable`, `required_for_create`, `write_format` to all 32 fields |

---

## Field Classification

**Writable (15):** name, domains, description, team, categories, primary_location, angellist, facebook, instagram, linkedin, twitter, estimated_arr_usd, funding_raised_usd, foundation_date, employee_range

**Read-only (17):** record_id, logo_url, twitter_follower_count, first_calendar_interaction, last_calendar_interaction, next_calendar_interaction, first_email_interaction, last_email_interaction, first_interaction, last_interaction, next_interaction, strongest_connection_strength, strongest_connection_user, associated_deals, associated_workspaces, created_at, created_by

**Write format patterns used:**
| Field type | write_format |
|---|---|
| Simple string (name, description, etc.) | `[{"value": "..."}]` |
| Domain | `[{"domain": "acme.com"}]` |
| URL (social profiles) | `[{"value": "https://..."}]` |
| Record reference (team) | `[{"target_object": "people", "target_record_id": "<id>"}]` |
| Enum (categories, employee_range, estimated_arr_usd) | `[{"value": "<option>"}]` |
| Currency (funding_raised_usd) | `[{"currency_value": 1000000, "currency_code": "USD"}]` |
| Date (foundation_date) | `[{"value": "2020-01-01"}]` |
| Location | `[{"locality": "San Francisco", "region": "CA", "country_code": "US"}]` |

---

## Task 1: Enrich `attio-companies.yaml`

**Files:**
- Modify: `remote-gateway/context/fields/attio-companies.yaml`

- [ ] **Step 1.1: Replace the full file with the enriched version**

```yaml
integration: "attio"
object: "companies"
source_url: "https://developers.attio.com/reference/get_v2-objects-companies-attributes"
discovered_at: "2026-04-03"
last_drift_check: "2026-04-16"

fields:
  record_id:
    display_name: "Record ID"
    description: "Unique identifier for this company record in Attio."
    type: "id"
    notes: "System-generated. Read-only."
    nullable: false
    writable: false
    required_for_create: false
    write_format: null

  name:
    display_name: "Name"
    description: "The company's display name."
    type: "string"
    notes: "Writable. Not unique — Attio deduplicates on domain instead."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "Acme Inc"}]'

  domains:
    display_name: "Domains"
    description: "Web domains associated with this company (e.g. acme.com)."
    type: "string"
    notes: "Multiselect. Unique across workspace — primary deduplication key. Omit the 'https://' prefix."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"domain": "acme.com"}]'

  description:
    display_name: "Description"
    description: "Free-text description or notes about this company."
    type: "string"
    notes: "Writable."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "Short description of the company."}]'

  team:
    display_name: "Team"
    description: "People at this company who are linked as team members."
    type: "id"
    notes: "Multiselect record reference → people. Requires existing Attio people record_ids."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"target_object": "people", "target_record_id": "<person_record_id>"}]'

  categories:
    display_name: "Categories"
    description: "Industry or sector categories this company belongs to."
    type: "string"
    notes: "Multiselect enum. Options include: SAAS, Health Care, Telecommunications, etc."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "SAAS"}]'

  primary_location:
    display_name: "Primary Location"
    description: "Geographic headquarters location of this company."
    type: "string"
    notes: "Attio location type — includes city, state, country. All subfields are optional."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"locality": "San Francisco", "region": "CA", "country_code": "US"}]'

  logo_url:
    display_name: "Logo URL"
    description: "URL of the company's logo, auto-populated by Attio enrichment."
    type: "string"
    notes: "Read-only. Set by enrichment."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  angellist:
    display_name: "AngelList"
    description: "AngelList company profile URL."
    type: "string"
    notes: "Writable. Free-text URL."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://angel.co/company/acme"}]'

  facebook:
    display_name: "Facebook"
    description: "Facebook page URL for this company."
    type: "string"
    notes: "Writable. Free-text URL."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://facebook.com/acme"}]'

  instagram:
    display_name: "Instagram"
    description: "Instagram profile URL for this company."
    type: "string"
    notes: "Writable. Free-text URL."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://instagram.com/acme"}]'

  linkedin:
    display_name: "LinkedIn"
    description: "LinkedIn company page URL."
    type: "string"
    notes: "Writable. Often auto-populated by enrichment."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://linkedin.com/company/acme"}]'

  twitter:
    display_name: "Twitter"
    description: "Twitter/X handle or profile URL for this company."
    type: "string"
    notes: "Writable. Free-text."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://twitter.com/acme"}]'

  twitter_follower_count:
    display_name: "Twitter Follower Count"
    description: "Number of Twitter/X followers this company's account has."
    type: "number"
    notes: "Read-only. Auto-populated by enrichment."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  estimated_arr_usd:
    display_name: "Estimated ARR"
    description: "Estimated annual recurring revenue band for this company."
    type: "string"
    notes: "Enum: $0-$1M, $1M-$10M, $10M-$50M, $50M-$100M, $100M-$250M, $250M-$500M, $500M-$1B, $1B-$10B, $10B+. Writable."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "$1M-$10M"}]'

  funding_raised_usd:
    display_name: "Funding Raised"
    description: "Total funding raised by this company in USD."
    type: "currency_usd"
    notes: "Writable. Currency field in USD."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"currency_value": 1000000, "currency_code": "USD"}]'

  foundation_date:
    display_name: "Foundation Date"
    description: "Date this company was founded."
    type: "timestamp"
    notes: "Writable. Date only (no time component). Use ISO 8601 format: YYYY-MM-DD."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "2020-01-15"}]'

  employee_range:
    display_name: "Employee Range"
    description: "Approximate headcount band for this company."
    type: "string"
    notes: "Enum: 1-10, 11-50, 51-250, 251-1K, 1K-5K, 5K-10K, 10K-50K, 50K-100K, 100K+. Writable."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "11-50"}]'

  first_calendar_interaction:
    display_name: "First Calendar Interaction"
    description: "Date of the first calendar event with anyone at this company."
    type: "timestamp"
    notes: "Read-only. Computed from connected calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  last_calendar_interaction:
    display_name: "Last Calendar Interaction"
    description: "Date of the most recent calendar event with anyone at this company."
    type: "timestamp"
    notes: "Read-only. Computed from connected calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  next_calendar_interaction:
    display_name: "Next Calendar Interaction"
    description: "Date of the next upcoming calendar event with anyone at this company."
    type: "timestamp"
    notes: "Read-only."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  first_email_interaction:
    display_name: "First Email Interaction"
    description: "Date of the first email exchange with anyone at this company."
    type: "timestamp"
    notes: "Read-only. Computed from connected email."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  last_email_interaction:
    display_name: "Last Email Interaction"
    description: "Date of the most recent email exchange with anyone at this company."
    type: "timestamp"
    notes: "Read-only."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  first_interaction:
    display_name: "First Interaction"
    description: "Date of the first interaction with this company across all channels."
    type: "timestamp"
    notes: "Read-only. Aggregated across email and calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  last_interaction:
    display_name: "Last Interaction"
    description: "Date of the most recent interaction with this company across all channels."
    type: "timestamp"
    notes: "Read-only. Useful for relationship health monitoring."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  next_interaction:
    display_name: "Next Interaction"
    description: "Date of the next scheduled interaction with this company."
    type: "timestamp"
    notes: "Read-only."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  strongest_connection_strength:
    display_name: "Connection Strength"
    description: "How strong the team's relationship with this company is, based on interaction history."
    type: "string"
    notes: "Read-only enum: Very weak, Weak, Good, Strong, Very strong."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  strongest_connection_user:
    display_name: "Strongest Connection"
    description: "The workspace member with the strongest relationship with this company."
    type: "id"
    notes: "Read-only. Actor reference."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  associated_deals:
    display_name: "Associated Deals"
    description: "Deals linked to this company."
    type: "id"
    notes: "Multiselect record reference → deals. Read-only on create; managed via deal records."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  associated_workspaces:
    display_name: "Associated Workspaces"
    description: "Product workspace records linked to this company."
    type: "id"
    notes: "Multiselect record reference → workspaces object. Read-only on create."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  created_at:
    display_name: "Created At"
    description: "Timestamp when this company record was created in Attio."
    type: "timestamp"
    notes: "Read-only. UTC."
    nullable: false
    writable: false
    required_for_create: false
    write_format: null

  created_by:
    display_name: "Created By"
    description: "The workspace member or system that created this company record."
    type: "id"
    notes: "Read-only. Actor reference."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null
```

- [ ] **Step 1.2: Spot-check the YAML parses correctly**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
python3 -c "
import sys
sys.path.insert(0, 'remote-gateway')
from core.field_registry import FieldRegistry
from pathlib import Path
r = FieldRegistry(fields_dir=Path('remote-gateway/context/fields'))
defs = r.get_all('attio-companies')
writable = [k for k, v in defs.items() if v.get('writable')]
readonly = [k for k, v in defs.items() if not v.get('writable')]
print(f'Total fields: {len(defs)}')
print(f'Writable ({len(writable)}): {sorted(writable)}')
print(f'Read-only ({len(readonly)}): {sorted(readonly)}')
"
```

Expected:
- Total fields: 32
- Writable (15): angellist, categories, description, domains, employee_range, estimated_arr_usd, facebook, foundation_date, funding_raised_usd, instagram, linkedin, name, primary_location, team, twitter
- Read-only (17): associated_deals, associated_workspaces, created_at, created_by, first_calendar_interaction, first_email_interaction, first_interaction, last_calendar_interaction, last_email_interaction, last_interaction, logo_url, next_calendar_interaction, next_email_interaction (if present), next_interaction, record_id, strongest_connection_strength, strongest_connection_user, twitter_follower_count

- [ ] **Step 1.3: Run the full test suite to confirm no regressions**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v --tb=short -q
```

Expected: 11 passed. The pre-flight validation tests use a temp YAML fixture and are unaffected by this file change. The three retrofitted existing create_record tests use an empty registry (no YAML files), so they are also unaffected.

- [ ] **Step 1.4: Commit**

```bash
git add remote-gateway/context/fields/attio-companies.yaml
git commit -m "docs: enrich attio-companies.yaml with writable/required_for_create/write_format

Closes the pre-flight validation gap for the companies object type.
Previously all 32 fields lacked writable metadata, so read-only fields
(record_id, created_at, etc.) were silently allowed through validation
due to the writable=True default fallback.

15 writable fields, 17 read-only. No code changes required."
```
