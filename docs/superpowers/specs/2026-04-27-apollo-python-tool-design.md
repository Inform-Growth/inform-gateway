# Apollo Python Tool — Design Spec

**Date:** 2026-04-27
**Status:** Approved

## Problem

The gateway's Apollo integration used `https://mcp.apollo.io/mcp` as a proxied MCP server with OAuth. That OAuth flow no longer works reliably, and the tokens cannot be extracted from any local keychain (the claude.ai web connector stores tokens server-side at Anthropic; there is no local copy). The proxy connection fails on every gateway startup.

## Solution

Replace the broken proxy with a direct Python tool file (`tools/apollo.py`) that calls Apollo's REST API using a simple `APOLLO_API_KEY` header. Follows the same pattern as `tools/wiza.py`. The broken proxy entry is removed from `mcp_connections.json`.

Additionally, `tools/attio.py` gains an `attio__upsert_record` tool, which is missing from the current Attio toolset and required for the prospecting write flow.

---

## Primary Use Cases

**A (primary) — Prospecting:** Search Apollo for contacts/companies matching demographic criteria → human reviews → enrich selected records → upsert into Attio.

**B (secondary) — Gap-fill enrichment:** Identify Attio records missing data → look them up in Apollo → write enriched data back to Attio.

Both flows are human-in-the-loop. The tools are deliberately stateless and composable — the agent does not chain them automatically.

---

## Architecture

### New file: `tools/apollo.py`

Four registered tools plus two private helpers:

```
apollo__search_people(filters...)       → POST /v1/mixed_people/search
apollo__search_companies(filters...)    → POST /v1/mixed_companies/search
apollo__enrich_person(identifiers...)   → POST /v1/people/match
apollo__enrich_organization(domain)     → GET  /v1/organizations/enrich

_headers()                              → {"X-Api-Key": APOLLO_API_KEY}
_map_to_attio_values(person|org, type)  → Attio-ready write dict
```

Auth: `X-Api-Key: <APOLLO_API_KEY>` header on every request. No OAuth.

### Modified file: `tools/attio.py`

Adds `attio__upsert_record` alongside the existing `attio__search_records` and `attio__create_record`.

### Modified file: `mcp_connections.json`

Remove the `"apollo"` proxy entry. Gateway no longer attempts the OAuth MCP connection on startup.

---

## Tool Signatures

### `apollo__search_people`

```python
def apollo__search_people(
    person_titles: list[str] | None = None,
    person_seniorities: list[str] | None = None,
    # Valid: "owner", "founder", "c_suite", "partner", "vp",
    #        "head", "director", "manager", "senior", "entry", "intern"
    person_locations: list[str] | None = None,
    q_keywords: str | None = None,
    q_organization_name: str | None = None,
    organization_domains: list[str] | None = None,
    organization_num_employees_ranges: list[str] | None = None,
    # Format: ["1,10", "11,20", "21,50", "51,200", "201,500",
    #           "501,1000", "1001,5000", "5001,10000", "10001,"]
    organization_industry_tag_ids: list[str] | None = None,
    organization_keywords: list[str] | None = None,
    funding_stage: list[str] | None = None,
    # Valid: "seed", "series_a", "series_b", "series_c",
    #        "series_d", "series_e_plus", "ipo"
    organization_latest_funding_amount_min: int | None = None,
    organization_latest_funding_amount_max: int | None = None,
    contact_email_status: list[str] | None = None,
    # Valid: "verified", "guessed", "unavailable", "bounced", "pending_manual_fulfillment"
    page: int = 1,
    per_page: int = 25,   # max 100
) -> dict
```

### `apollo__search_companies`

```python
def apollo__search_companies(
    q_keywords: str | None = None,
    q_organization_name: str | None = None,
    organization_locations: list[str] | None = None,
    organization_num_employees_ranges: list[str] | None = None,
    organization_revenue_ranges: list[str] | None = None,
    # Format: ["1000000,10000000"] (USD)
    organization_industry_tag_ids: list[str] | None = None,
    organization_keywords: list[str] | None = None,
    funding_stage: list[str] | None = None,
    organization_latest_funding_amount_min: int | None = None,
    organization_latest_funding_amount_max: int | None = None,
    page: int = 1,
    per_page: int = 25,
) -> dict
```

### `apollo__enrich_person`

At least one of `id`, `email`, or `linkedin_url` must be provided. Raises `ValueError` before any HTTP call otherwise.

```python
def apollo__enrich_person(
    id: str | None = None,
    email: str | None = None,
    linkedin_url: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    organization_name: str | None = None,
    domain: str | None = None,
    reveal_personal_emails: bool = False,
    reveal_phone_number: bool = False,
) -> dict
```

### `apollo__enrich_organization`

```python
def apollo__enrich_organization(
    domain: str,   # required
) -> dict
```

### `attio__upsert_record` *(new, in `tools/attio.py`)*

```python
def attio__upsert_record(
    object_type: str,          # "people" or "companies"
    values: dict,              # same format as attio__create_record
    matching_attribute: str,   # "email_addresses" (people) or "domains" (companies)
) -> dict
```

Uses Attio's `POST /v2/objects/{object}/records` with `matching_attribute` in the request body, which causes Attio to upsert: update if a record matching that attribute exists, create otherwise.

---

## Response Shapes

### Search responses (both tools)

Null fields are stripped. Returns only populated values.

```python
{
  "people": [          # or "companies"
    {
      "id": "abc123",
      "name": "Jane Doe",
      "first_name": "Jane",
      "last_name": "Doe",
      "title": "VP of Sales",
      "email": "jane@acme.com",
      "email_status": "verified",
      "linkedin_url": "https://linkedin.com/in/janedoe",
      "city": "San Francisco",
      "state": "California",
      "country": "United States",
      "organization_name": "Acme Inc",
      "organization_id": "org456",
      "funding_stage": "series_b",
      "estimated_num_employees": 250
    },
    ...
  ],
  "pagination": {
    "total": 1432,
    "page": 1,
    "per_page": 25,
    "has_more": True,
    "summary": "Showing 25 of 1,432 matches — refine filters or increment page to continue."
  },
  "agent_hint": "Review results above. To enrich a person and get Attio-ready values, call apollo__enrich_person with their id. To search again with refined filters, call apollo__search_people with updated parameters."
}
```

### Enrich person response

```python
{
  "person": {
    # Full Apollo person payload, nulls stripped
    "id": "...",
    "name": "Jane Doe",
    "email": "jane@acme.com",
    "phone_numbers": [{"raw_number": "+1-555-0100", "type": "work"}],
    "employment_history": [...],
    # ...all other non-null Apollo fields
  },
  "attio_values": {
    # Pre-mapped, ready to pass directly to attio__upsert_record
    "name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}],
    "email_addresses": [{"email_address": "jane@acme.com"}],
    "job_title": [{"value": "VP of Sales"}],
    "linkedin": [{"value": "https://linkedin.com/in/janedoe"}],
    "phone_numbers": [{"phone_number": "+1-555-0100"}]
    # organization_name is omitted — Attio's company field is a relationship
    # requiring a record ID; agent must resolve separately if linking is needed.
    # Only fields with data are included.
  },
  "agent_hint": "attio_values is pre-mapped for attio__upsert_record. Call attio__upsert_record(object_type='people', values=attio_values, matching_attribute='email_addresses') to write to Attio."
}
```

### Enrich organization response

```python
{
  "organization": {
    # Full Apollo org payload, nulls stripped
    "id": "...",
    "name": "Acme Inc",
    "domain": "acme.com",
    "industry": "Software",
    "num_employees": 250,
    "estimated_annual_revenue": "10M-50M",
    "funding_stage": "series_b",
    "latest_funding_amount": 25000000,
    "latest_funding_date": "2024-03-15",
    # ...all other non-null Apollo fields
  },
  "attio_values": {
    "name": [{"value": "Acme Inc"}],
    "domains": [{"domain": "acme.com"}],
    "primary_location": [{"value": "San Francisco, CA"}]
    # Only fields with data are included
  },
  "agent_hint": "attio_values is pre-mapped for attio__upsert_record. Call attio__upsert_record(object_type='companies', values=attio_values, matching_attribute='domains') to write to Attio."
}
```

### Attio upsert response

```python
{
  "record_id": "...",
  "object_type": "people",
  "upserted": True,   # True = updated existing, False = created new
  "data": { ...full Attio record... }
}
```

---

## `_map_to_attio_values` — Field Mapping

Private helper called by both enrich tools. Translates Apollo field shapes to Attio write format. Omits any field where the Apollo value is None or empty.

| Apollo field | Attio field | Attio write format |
|---|---|---|
| `first_name` + `last_name` | `name` | `[{"first_name": ..., "last_name": ..., "full_name": ...}]` |
| `email` | `email_addresses` | `[{"email_address": ...}]` |
| `title` | `job_title` | `[{"value": ...}]` |
| `linkedin_url` | `linkedin` | `[{"value": ...}]` |
| `phone_numbers[0].raw_number` | `phone_numbers` | `[{"phone_number": ...}]` |
| `organization_name` (person) | *(omitted)* | Attio's `company` field is a relationship requiring a record ID — cannot map from a name string. Agent must resolve the Attio company record separately if linking is needed. |
| `name` (org) | `name` | `[{"value": ...}]` |
| `domain` | `domains` | `[{"domain": ...}]` |
| `city` + `state` + `country` | `primary_location` | `[{"value": "City, State"}]` |

---

## Error Handling

| Condition | Behaviour |
|---|---|
| `APOLLO_API_KEY` not set | `ValueError` raised before any HTTP call |
| Apollo 401 | `PermissionError("APOLLO_API_KEY is invalid or expired")` |
| Apollo 422 (bad params) | Returns `{"error": ..., "detail": <Apollo message>}` |
| Apollo 429 | `RuntimeError("Apollo rate limit — retry after Xs")` using `Retry-After` header |
| `enrich_person` with no identifiers | `ValueError("Provide at least one of: id, email, linkedin_url")` |
| `upsert_record` invalid `matching_attribute` | `ValueError` listing valid options |
| Attio API error | Returns `{"error": "Attio API error {status}: {body}"}` |

---

## Files Changed

| File | Change |
|---|---|
| `remote-gateway/tools/apollo.py` | **Create** |
| `remote-gateway/tools/attio.py` | Add `attio__upsert_record`, register it |
| `remote-gateway/core/mcp_server.py` | Import and register `_apollo_tools` |
| `remote-gateway/mcp_connections.json` | Remove `"apollo"` proxy entry |
| `remote-gateway/context/fields/apollo.yaml` | Replace TODO stubs with real descriptions |
| `remote-gateway/.env.example` | Replace `APOLLO_ACCESS_TOKEN` / `REFRESH` / `CLIENT_ID` with `APOLLO_API_KEY` |
| `remote-gateway/tests/test_apollo_tools.py` | **Create** — unit tests for all four tools and the mapper |

---

## Out of Scope

- Bulk export / CSV download from Apollo
- Apollo sequences or email sending
- Attio list management (covered by existing proxied attio-mcp tools)
- Automatic agent chaining (human-in-the-loop is intentional)
