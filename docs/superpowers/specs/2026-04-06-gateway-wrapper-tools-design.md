# Gateway Wrapper Tools — Design Spec

**Date:** 2026-04-06  
**Status:** Approved  
**Scope:** Promoted gateway tools wrapping Apollo, Attio, and Exa with opinionated interfaces that fix known API quirks and eliminate agent-side reasoning about failures.

---

## Problem

Raw proxied tools (`apollo__*`, `attio__*`, `exa__*`) are unreliable in practice:
- Apollo people search silently returns wrong results when wrong param name is used
- Apollo parallel calls consistently trigger TaskGroup errors
- Exa web fetch requires `urls` array but agents pass a single string
- Attio calls fail on missing required fields, surfacing errors to the agent to resolve
- Agents must rediscover these quirks each session

## Goal

Four promoted gateway tools that agents can call without knowing the quirks. Wrong params don't exist. Sequential enforcement is internal. Required fields are validated before any API call.

---

## Architecture

Raw proxied tools remain available on the gateway for admin/debugging. Non-technical users never see them — they interact exclusively through the promoted wrappers.

```
Agent
  └── apollo_enrich_company(domain)         → apollo__organization_enrich
  └── apollo_find_contacts(domain, titles)   → apollo__mixed_people_api_search (sequential)
  └── exa_fetch_pages(urls)                  → exa__web_fetch_exa
  └── attio_push_company(name, domain, list) → attio__create/update + attio__add_to_list
```

Session notes: unchanged. Agents call existing `write_note` / `read_note` / `list_notes` gateway tools at session end. GitHub-backed, admin-reviewable.

---

## Tool Interfaces

### `apollo_enrich_company(domain: str) -> dict`

Enriches a company by domain using Apollo's organization enrich endpoint.

**Returns:**
```json
{
  "name": "Acme Corp",
  "domain": "acme.com",
  "industry": "Software",
  "employee_count": 45,
  "estimated_revenue": "5M-10M",
  "hq_city": "San Francisco",
  "hq_country": "United States",
  "linkedin_url": "https://linkedin.com/company/acme",
  "funding_stage": "Seed",
  "total_funding_usd": 4300000
}
```

**Behavior:** Returns only the fields above — no raw Apollo noise. Missing fields return `null`. If Apollo returns an error, the tool returns `{"error": "<message>", "domain": "<domain>"}` without raising.

---

### `apollo_find_contacts(domain: str, titles: list[str], max_results: int = 5) -> dict`

Finds people at a company by domain and title keywords. Uses `q_organization_domains` (correct param name). Enforces sequential execution internally — safe to call in sequence, never in parallel.

**Returns:**
```json
{
  "domain": "acme.com",
  "contacts": [
    {
      "name": "Jane Smith",
      "title": "Head of Revenue Operations",
      "email": "jane@acme.com",
      "linkedin_url": "https://linkedin.com/in/janesmith",
      "seniority": "manager"
    }
  ],
  "count": 1
}
```

**Behavior:** If Apollo is unavailable (TaskGroup errors), returns `{"error": "apollo_unavailable", "domain": "<domain>", "contacts": []}`. Caller can continue without contacts rather than failing.

---

### `exa_fetch_pages(urls: list[str]) -> dict`

Fetches and extracts text content from a list of URLs.

**Returns:**
```json
{
  "pages": [
    {
      "url": "https://example.com/jobs/123",
      "title": "GTM Engineer at Acme",
      "text": "Full job description text...",
      "published_date": "2026-03-15",
      "warning": null
    }
  ]
}
```

**Behavior:** If a URL matches known client-side-rendered job board patterns (Ashby: `*.ashbyhq.com`, `jobs.ashbyhq.com`), sets `"warning": "Ashby pages are client-side rendered — content is likely empty. Use revopscareers.com or Welcome to the Jungle for full job descriptions."` Content is still returned as-is; the agent can decide how to handle it.

---

### `attio_push_company(name: str, domain: str, list_name: str, notes: str = "") -> dict`

Creates or updates a company in Attio and adds it to a named list. Validates required fields before any API call.

**Returns:**
```json
{
  "company_id": "abc123",
  "action": "created",
  "list_entry_id": "def456",
  "list_name": "RevOps AI Infra — Apr 2026"
}
```

**Behavior:**
- Validates `name` and `domain` are non-empty. Returns `{"error": "missing_required_fields", "missing": ["domain"]}` if not.
- Looks up list by name, not ID. Returns `{"error": "list_not_found", "list_name": "<name>"}` if the list doesn't exist.
- Create-or-update is idempotent — safe to call twice for the same domain.
- `notes` is written to the Attio company notes field if provided.

---

## Implementation Location

All four tools are promoted to `remote-gateway/core/mcp_server.py` following the standard promotion pattern. Each function lives in `remote-gateway/tools/` (one module per integration), registered via a `register(mcp)` call in `mcp_server.py`.

File layout:
```
remote-gateway/tools/
  apollo.py    ← apollo_enrich_company, apollo_find_contacts
  exa.py       ← exa_fetch_pages
  attio.py     ← attio_push_company
```

Each function is wrapped with `validated("<integration>", result)` for field registry tracking.

---

## Non-Technical User Workflow

1. Open Claude Desktop, connect to gateway SSE endpoint
2. Ask agent to research/prospect — agent uses wrapper tools
3. Agent writes session note via `write_note` at end of session
4. Admin reviews notes via `list_notes` + `read_note` from any connected agent, or directly in GitHub

No local workspace, no git, no `.mcp.json` setup required for end users.

---

## Out of Scope

- Orchestration tools (enrich + push as one call) — future iteration
- Gateway resources / workflow documentation — future iteration
- Per-user tool filtering / access control — future iteration
