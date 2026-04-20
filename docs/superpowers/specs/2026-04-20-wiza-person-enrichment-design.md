# Wiza Person Enrichment — Design Spec

**Date:** 2026-04-20  
**Status:** Approved

---

## Overview

Add a `wiza__enrich_person` tool to the Agent Gateway that takes a LinkedIn profile URL and returns a person's work email, mobile phone, and LinkedIn profile data in a single blocking call. Uses Wiza's Individual Reveals API with `enrichment_level: "full"`.

---

## Architecture

### Implementation pattern

Follows the existing `attio.py` pattern: a standalone Python module at `remote-gateway/tools/wiza.py` with one exported function registered directly on the FastMCP server. No entry in `mcp_connections.json` — Wiza has no MCP server, so this is a direct REST integration.

### Files changed

| File | Change |
|---|---|
| `remote-gateway/tools/wiza.py` | New file — tool implementation |
| `remote-gateway/context/fields/wiza.yaml` | New file — field registry schema |
| `remote-gateway/core/mcp_server.py` | Import wiza module + register tool |

### Authentication

`WIZA_API_KEY` environment variable. Bearer token, same pattern as `ATTIO_API_KEY`. Raises `ValueError` at call time if unset.

---

## Tool

### Signature

```python
def wiza__enrich_person(linkedin_url: str) -> dict:
    """Enrich a person by LinkedIn URL using Wiza.

    Looks up email, mobile phone number, and LinkedIn profile data for a
    person identified by their LinkedIn profile URL. Uses enrichment_level
    'full' — credits are only deducted if data is found (up to 2 for email,
    5 for phone, 1 for LinkedIn match).

    Args:
        linkedin_url: The person's LinkedIn profile URL
            (e.g. https://www.linkedin.com/in/username).

    Returns:
        Dict with name, title, linkedin_profile_url, email, email_status,
        mobile_phone, company_name, and credits_used breakdown.
    """
```

### Behavior

1. POST `https://wiza.co/api/individual_reveals` with:
   ```json
   {
     "individual_reveal": {
       "profile_url": "<linkedin_url>",
       "enrichment_level": "full"
     }
   }
   ```
2. Extract `data.id` and `data.status` from the 200 response.
3. Poll `GET https://wiza.co/api/individual_reveals/{id}` every 3 seconds, up to 10 attempts (30s total).
4. On `status: "finished"` — extract and return the filtered response.
5. On `status: "failed"` — raise `RuntimeError` with the status message.
6. On timeout (10 polls exhausted) — raise `TimeoutError` with the reveal ID so the caller can note it.

### Return shape

```json
{
  "name": "Jane Smith",
  "title": "VP of Engineering",
  "linkedin_profile_url": "https://www.linkedin.com/in/janesmith",
  "email": "jane@example.com",
  "email_status": "valid",
  "mobile_phone": "+14155551234",
  "company_name": "Acme Corp",
  "credits_used": {
    "email": 2,
    "phone": 5,
    "api": 1
  }
}
```

Fields absent from the Wiza response are omitted (not null-padded). The full raw response is not returned — only the MVP fields above.

---

## Field Registry

`remote-gateway/context/fields/wiza.yaml` covers the fields in the return shape:

| Field | Type | Notes |
|---|---|---|
| `name` | string | Full name |
| `title` | string | Current job title |
| `linkedin_profile_url` | string | Canonical LinkedIn URL |
| `email` | string | Primary work email |
| `email_status` | string | `valid`, `catch_all`, `invalid`, or `unknown` |
| `mobile_phone` | string | E.164 format mobile number |
| `company_name` | string | Current employer name |
| `credits_used` | object | Breakdown of credits deducted |

---

## Error Handling

| Condition | Behavior |
|---|---|
| `WIZA_API_KEY` not set | `ValueError` at call time |
| 400 from Wiza (bad input) | Re-raise with Wiza's error message |
| 401 from Wiza | `PermissionError("WIZA_API_KEY is invalid or disabled")` |
| 429 from Wiza (queue full) | `RuntimeError("Wiza queue full — try again later")` |
| Reveal status `"failed"` | `RuntimeError` with status |
| 30s polling timeout | `TimeoutError` with reveal ID |

---

## Out of Scope (MVP)

- Webhook support (polling only)
- Name+company input (LinkedIn URL only)
- Targeted enrichment levels (always `"full"`)
- Bulk enrichment (single person per call)
- Company enrichment endpoint
- Prospect search
